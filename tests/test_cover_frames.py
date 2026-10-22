"""Candidatos de capa: quadros nítidos e espalhados do vídeo, ou foto enviada."""
import colorsys
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

import cover_frames
from cover_frames import CoverError

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "cover_frames.py"

W, H, FPS = 640, 480, 10
STRIP_Y = int(H * 0.94)  # faixa colorida fora da região central usada na nitidez


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def _color(sec: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(sec / 12, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def _between(seconds) -> str:
    return "+".join(f"gte(t,{s})*lt(t,{s + 1})" for s in sorted(seconds)) or "0"


def make_marked_video(out: Path, duration: int = 12, blurry=(), black=(), rotation=None) -> Path:
    """Vídeo `testsrc2` (cheio de detalhe fino) em que o segundo S tem uma faixa
    inferior de cor própria (`_color(S)`), fica borrado se S está em `blurry` e
    preto se S está em `black`. A faixa fica abaixo da região usada na nitidez."""
    vf = []
    if blurry:
        vf.append(f"boxblur=luma_radius=14:luma_power=2:chroma_radius=14:chroma_power=2:"
                  f"enable='{_between(blurry)}'")
    for s in range(duration):
        r, g, b = _color(s)
        vf.append(f"drawbox=x=0:y=ih*0.88:w=iw:h=ih*0.12:color=0x{r:02x}{g:02x}{b:02x}:"
                  f"t=fill:enable='between(t,{s},{s + 1})'")
    if black:
        vf.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='{_between(black)}'")
    src = out if rotation is None else out.with_name(out.stem + "-land.mp4")
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration={duration}",
            "-vf", ",".join(vf), "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", src)
    if rotation is not None:
        _ffmpeg("-display_rotation", str(rotation), "-i", src, "-c", "copy", out)
        src.unlink()
    return out


def second_of(png: Path) -> int:
    """Lê de volta o segundo do vídeo pela cor da faixa inferior."""
    img = Image.open(png).convert("RGB")
    px = img.getpixel((img.width // 2, int(img.height * 0.94)))
    return min(range(12), key=lambda s: sum((a - b) ** 2 for a, b in zip(px, _color(s))))


def thumb_diff(a: Path, b: Path) -> float:
    ta = Image.open(a).convert("RGB").resize((64, 64))
    tb = Image.open(b).convert("RGB").resize((64, 64))
    return sum(ImageStat.Stat(ImageChops.difference(ta, tb)).mean) / 3


def frame_at(video: Path, t: float, out: Path) -> Path:
    _ffmpeg("-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", out)
    return out


def leftovers(d: Path) -> list[str]:
    return sorted(p.name for p in d.rglob("*") if ".tmp" in p.name or p.name.startswith("."))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def sharp_video(tmp_path_factory):
    return make_marked_video(tmp_path_factory.mktemp("sharp") / "v.mp4")


# --------------------------------------------------------------- vídeo

def test_returns_n_distinct_frames(sharp_video, tmp_path):
    out = tmp_path / "capa"
    paths = cover_frames.candidates(sharp_video, out, n=3)
    assert [p.name for p in paths] == ["candidato-1.png", "candidato-2.png", "candidato-3.png"]
    assert sorted(p.name for p in out.iterdir()) == [p.name for p in paths]
    for p in paths:
        assert p.parent == out
        with Image.open(p) as im:
            assert im.format == "PNG"
            assert im.size == (W, H)
    for i in range(3):
        for j in range(i + 1, 3):
            assert thumb_diff(paths[i], paths[j]) > 3
    # ordenados no tempo, um por terço (0,6-4,2 s | 4,2-7,8 s | 7,8-11,4 s: sem 5 % das pontas)
    secs = [second_of(p) for p in paths]
    assert secs == sorted(secs) and len(set(secs)) == 3
    assert 0 <= secs[0] <= 4 and 4 <= secs[1] <= 7 and 7 <= secs[2] <= 11
    assert leftovers(out) == []


def test_default_n_is_three(sharp_video, tmp_path):
    assert len(cover_frames.candidates(sharp_video, tmp_path / "c")) == 3


def test_skips_blurry_frames(tmp_path):
    sharp = {1, 5, 10}
    blurry = [s for s in range(12) if s not in sharp]
    video = make_marked_video(tmp_path / "v.mp4", blurry=blurry)
    paths = cover_frames.candidates(video, tmp_path / "capa", n=3)
    assert len(paths) == 3
    assert [second_of(p) for p in paths] == [1, 5, 10]
    # a nitidez de cada escolhido é >= 3x a de um quadro borrado do mesmo vídeo
    base = cover_frames.sharpness(Image.open(frame_at(video, 3.5, tmp_path / "blur.png")))
    for p in paths:
        assert cover_frames.sharpness(Image.open(p)) >= 3 * base


def test_dark_frames_are_rejected_and_replaced(tmp_path):
    video = make_marked_video(tmp_path / "v.mp4", black=range(0, 4))  # 1o terço todo preto
    paths = cover_frames.candidates(video, tmp_path / "capa", n=3)
    assert len(paths) == 3
    for p in paths:
        with Image.open(p) as im:
            assert ImageStat.Stat(im.convert("L")).mean[0] > 25
    for i in range(3):
        for j in range(i + 1, 3):
            assert thumb_diff(paths[i], paths[j]) > 3


def test_all_black_video_is_an_error(tmp_path):
    video = make_marked_video(tmp_path / "v.mp4", duration=6, black=range(6))
    with pytest.raises(CoverError, match="utilizável"):
        cover_frames.candidates(video, tmp_path / "capa", n=3)
    assert leftovers(tmp_path) == []


def test_rotated_phone_video_comes_out_upright(tmp_path):
    video = make_marked_video(tmp_path / "rot.mp4", duration=6, rotation=90)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream_side_data=rotation", "-of", "json", str(video)],
        check=True, capture_output=True, text=True).stdout
    assert "rotation" in probe  # a fixture carrega a matriz de rotação
    paths = cover_frames.candidates(video, tmp_path / "capa", n=2)
    assert len(paths) == 2
    for p in paths:
        with Image.open(p) as im:
            assert im.size == (H, W)  # 480x640: em pé, como o telefone mostra


def test_short_video_reduces_n_with_warning(tmp_path, capsys):
    video = make_marked_video(tmp_path / "v.mp4", duration=2)
    paths = cover_frames.candidates(video, tmp_path / "capa", n=3)
    assert len(paths) == 2  # cabe 1 candidato por segundo de vídeo
    err = capsys.readouterr().err
    assert "aviso" in err and "2" in err


def test_sub_second_video_gives_one_frame(tmp_path):
    video = tmp_path / "v.mp4"
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", video)
    paths = cover_frames.candidates(video, tmp_path / "capa", n=3)
    assert [p.name for p in paths] == ["candidato-1.png"]


def test_n_larger_than_video_allows(tmp_path):
    video = make_marked_video(tmp_path / "v.mp4", duration=5)
    paths = cover_frames.candidates(video, tmp_path / "capa", n=10)
    assert len(paths) == 5
    secs = [second_of(p) for p in paths]
    assert secs == sorted(secs)


@pytest.mark.parametrize("n", [0, -1])
def test_n_must_be_positive(sharp_video, tmp_path, n):
    with pytest.raises(CoverError, match="n"):
        cover_frames.candidates(sharp_video, tmp_path / "capa", n=n)
    assert not (tmp_path / "capa").exists()


def test_audio_only_file_has_no_video(tmp_path):
    audio = tmp_path / "a.m4a"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "aac", audio)
    with pytest.raises(CoverError, match="o arquivo não tem vídeo"):
        cover_frames.candidates(audio, tmp_path / "capa")
    assert not (tmp_path / "capa").exists()


def test_missing_and_garbage_input(tmp_path):
    with pytest.raises(CoverError):
        cover_frames.candidates(tmp_path / "nao-existe.mp4", tmp_path / "capa")
    junk = tmp_path / "x.mp4"
    junk.write_bytes(b"isto nao e um video" * 50)
    with pytest.raises(CoverError):
        cover_frames.candidates(junk, tmp_path / "capa")
    with pytest.raises(CoverError):
        cover_frames.candidates(tmp_path, tmp_path / "capa")  # pasta, não arquivo
    assert not (tmp_path / "capa").exists()


def test_out_dir_created_original_untouched_no_leftovers(sharp_video, tmp_path):
    before = sha(sharp_video)
    out = tmp_path / "a" / "b" / "capa"
    assert not out.exists()
    paths = cover_frames.candidates(sharp_video, out, n=3)
    assert out.is_dir() and len(paths) == 3
    assert sha(sharp_video) == before
    assert leftovers(out) == []


def test_out_dir_that_is_a_file_is_an_error(sharp_video, tmp_path):
    blocker = tmp_path / "capa"
    blocker.write_text("x")
    with pytest.raises(CoverError):
        cover_frames.candidates(sharp_video, blocker)


def test_rerun_with_smaller_n_removes_stale_candidates(sharp_video, tmp_path):
    out = tmp_path / "capa"
    cover_frames.candidates(sharp_video, out, n=3)
    cover_frames.candidates(sharp_video, out, n=2)
    assert sorted(p.name for p in out.iterdir()) == ["candidato-1.png", "candidato-2.png"]


def test_ffmpeg_failure_midway_leaves_nothing(sharp_video, tmp_path, monkeypatch):
    real = cover_frames._ffmpeg
    calls = {"full": 0}

    def flaky(args):
        if "-frames:v" in args and "fps=" not in " ".join(map(str, args)):
            calls["full"] += 1
            if calls["full"] == 2:
                raise CoverError("ffmpeg falhou (simulado)")
        return real(args)

    monkeypatch.setattr(cover_frames, "_ffmpeg", flaky)
    out = tmp_path / "capa"
    out.mkdir()
    with pytest.raises(CoverError, match="simulado"):
        cover_frames.candidates(sharp_video, out, n=3)
    assert calls["full"] == 2
    assert list(out.iterdir()) == []  # nem candidato parcial, nem .tmp, nem pasta de trabalho


def test_ffmpeg_failure_while_sampling_leaves_nothing(sharp_video, tmp_path, monkeypatch):
    def broken(args):
        raise CoverError("ffmpeg falhou (simulado)")

    monkeypatch.setattr(cover_frames, "_ffmpeg", broken)
    out = tmp_path / "capa"
    out.mkdir()
    with pytest.raises(CoverError, match="simulado"):
        cover_frames.candidates(sharp_video, out, n=3)
    assert list(out.iterdir()) == []


# --------------------------------------------------------------- foto

def _exif(orientation: int) -> Image.Exif:
    ex = Image.Exif()
    ex[0x0112] = orientation
    return ex


@pytest.mark.parametrize("ext", ["png", "jpg"])
def test_accepts_uploaded_photo(tmp_path, ext):
    # guardada deitada (1000x700) com marca vermelha no canto superior esquerdo e
    # EXIF 6: o telefone mostra girada 90 graus horário, em pé (700x1000), marca
    # no canto superior direito
    img = Image.new("RGB", (1000, 700), (30, 60, 90))
    img.paste((255, 0, 0), (0, 0, 100, 100))
    src = tmp_path / f"retrato.{ext}"
    img.save(src, exif=_exif(6))
    before = sha(src)
    out = cover_frames.from_photo(src, tmp_path / "capa")
    assert out == tmp_path / "capa" / "foto.png"
    with Image.open(out) as im:
        assert im.format == "PNG" and im.mode == "RGB"
        assert im.size == (700, 1000)
        r, g, b = im.getpixel((im.width - 50, 50))
        assert r > 200 and g < 60 and b < 60
        assert im.getpixel((50, 50))[0] < 100  # o canto esquerdo não é mais vermelho
    assert sha(src) == before
    assert leftovers(tmp_path / "capa") == []


def test_photo_without_exif_keeps_orientation(tmp_path):
    src = tmp_path / "f.jpg"
    Image.new("RGB", (900, 1200), (10, 20, 30)).save(src)
    with Image.open(cover_frames.from_photo(src, tmp_path / "capa")) as im:
        assert im.size == (900, 1200)


def test_photo_rgba_becomes_rgb_on_white(tmp_path):
    src = tmp_path / "f.png"
    img = Image.new("RGBA", (800, 800), (0, 0, 0, 0))  # tudo transparente
    img.paste((10, 100, 200, 255), (300, 300, 500, 500))
    img.save(src)
    with Image.open(cover_frames.from_photo(src, tmp_path / "capa")) as im:
        assert im.mode == "RGB"
        assert im.getpixel((10, 10)) == (255, 255, 255)  # transparente vira branco, não preto
        assert im.getpixel((400, 400)) == (10, 100, 200)


def test_photo_palette_with_transparency(tmp_path):
    src = tmp_path / "f.png"
    Image.new("RGBA", (800, 800), (0, 0, 0, 0)).convert("P").save(src, transparency=0)
    with Image.open(cover_frames.from_photo(src, tmp_path / "capa")) as im:
        assert im.mode == "RGB" and im.getpixel((5, 5)) == (255, 255, 255)


def test_photo_too_small(tmp_path):
    src = tmp_path / "f.jpg"
    Image.new("RGB", (1200, 599), (1, 2, 3)).save(src)
    with pytest.raises(CoverError, match="foto pequena demais"):
        cover_frames.from_photo(src, tmp_path / "capa")
    assert not (tmp_path / "capa").exists()
    ok = tmp_path / "ok.jpg"
    Image.new("RGB", (1200, 600), (1, 2, 3)).save(ok)
    assert cover_frames.from_photo(ok, tmp_path / "capa").is_file()  # 600 passa


def test_photo_small_check_uses_upright_size(tmp_path):
    # 2000x500 com EXIF 6 vira 500x2000: lado curto 500, continua pequena
    src = tmp_path / "f.jpg"
    Image.new("RGB", (2000, 500)).save(src, exif=_exif(6))
    with pytest.raises(CoverError, match="foto pequena demais"):
        cover_frames.from_photo(src, tmp_path / "capa")


def test_photo_not_an_image_or_missing(tmp_path):
    txt = tmp_path / "f.jpg"
    txt.write_text("isto não é uma imagem")
    with pytest.raises(CoverError, match="imagem"):
        cover_frames.from_photo(txt, tmp_path / "capa")
    with pytest.raises(CoverError):
        cover_frames.from_photo(tmp_path / "nao-existe.png", tmp_path / "capa")
    with pytest.raises(CoverError):
        cover_frames.from_photo(tmp_path, tmp_path / "capa")
    assert not (tmp_path / "capa").exists()


def test_photo_overwrites_previous_and_leaves_no_tmp(tmp_path):
    out = tmp_path / "capa"
    a = tmp_path / "a.png"
    Image.new("RGB", (700, 700), (255, 0, 0)).save(a)
    b = tmp_path / "b.png"
    Image.new("RGB", (700, 700), (0, 255, 0)).save(b)
    cover_frames.from_photo(a, out)
    cover_frames.from_photo(b, out)
    with Image.open(out / "foto.png") as im:
        assert im.getpixel((5, 5)) == (0, 255, 0)
    assert leftovers(out) == []


# --------------------------------------------------------------- CLI

def _cli(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def test_cli_video_prints_one_path_per_line(sharp_video, tmp_path):
    out = tmp_path / "capa"
    r = _cli("video", sharp_video, out, "--n", "2")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines == [str(out / "candidato-1.png"), str(out / "candidato-2.png")]
    assert all(Path(line).is_file() for line in lines)


def test_cli_photo(tmp_path):
    src = tmp_path / "f.jpg"
    Image.new("RGB", (800, 900), (9, 9, 9)).save(src)
    r = _cli("photo", src, tmp_path / "capa")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [str(tmp_path / "capa" / "foto.png")]


def test_cli_errors_are_clear_not_tracebacks(tmp_path):
    r = _cli("video", tmp_path / "nao-existe.mp4", tmp_path / "capa")
    assert r.returncode == 1 and r.stderr.startswith("erro:") and "Traceback" not in r.stderr
    small = tmp_path / "s.png"
    Image.new("RGB", (100, 100)).save(small)
    r = _cli("photo", small, tmp_path / "capa")
    assert r.returncode == 1 and "foto pequena demais" in r.stderr
    assert "Traceback" not in r.stderr and r.stdout == ""


# --------------------------------------------------------------- docs e insumos

def test_skill_readme_and_assets_mention_cover_step():
    skill = (REPO / ".claude" / "skills" / "editor-reel" / "SKILL.md").read_text("utf-8")
    assert "scripts/cover_frames.py video" in skill and "scripts/cover_frames.py photo" in skill
    assert "qual quadro mostra o sorriso" in skill
    # a composição deixou de ser "o próximo passo": agora é o passo 10
    assert "próximo passo" not in skill
    assert "scripts/cover_compose.py" in skill and "brand.py set-handles" in skill
    assert "cover_frames" in (REPO / "README.md").read_text("utf-8")
    capa = (REPO / "references" / "capa.md").read_text("utf-8")
    assert "assets/logo.webp" in capa and "candidato-N.png" in capa and "foto.png" in capa
    with Image.open(REPO / "assets" / "logo.webp") as logo:
        assert logo.mode == "RGBA" and logo.size == (1908, 1045)


# ---- onda final, item 12: sorriso em tripe nao e "quase duplicado"; foto 16 bits ----
def make_tripod_video(out: Path, tmp_path: Path) -> Path:
    """Tripé: o quadro inteiro parado (testsrc2 congelado), só a "boca" muda
    (neutra, sorriso, sorriso aberto) a cada 3 s. Diferença do quadro inteiro < 1,0 de 255.""" 
    base = tmp_path / "base.png"
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=1:duration=1", "-frames:v", "1", base)
    frames = []
    for k, color in enumerate([(150, 90, 80), (245, 245, 240), (40, 10, 10)]):
        im = Image.open(base).convert("RGB")
        im.paste(color, (W // 2 - 36, int(H * 0.45), W // 2 + 36, int(H * 0.45) + 24))
        p = tmp_path / f"boca-{k}.png"
        im.save(p)
        frames.append(p)
    args = []
    for p in frames:
        args += ["-loop", "1", "-t", "3", "-framerate", str(FPS), "-i", p]
    _ffmpeg(*args, "-filter_complex", "concat=n=3:v=1:a=0", "-c:v", "libx264", "-crf", "12",
            "-pix_fmt", "yuv420p", out)
    return out


def test_tripod_smile_frames_are_kept(tmp_path):
    video = make_tripod_video(tmp_path / "tripe.mp4", tmp_path)
    paths = cover_frames.candidates(video, tmp_path / "capa", n=3)
    assert len(paths) == 3
    a, b, c = (Image.open(p).convert("RGB") for p in paths)
    mouth = (W // 2, int(H * 0.45) + 12)
    assert len({a.getpixel(mouth)[0] // 40, b.getpixel(mouth)[0] // 40, c.getpixel(mouth)[0] // 40}) == 3
    assert thumb_diff(paths[0], paths[1]) < 1.0  # o quadro inteiro quase nao muda


def test_static_video_still_dedups(tmp_path):
    video = tmp_path / "parado.mp4"
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=1:duration=1", "-frames:v", "1",
            tmp_path / "p.png")
    _ffmpeg("-loop", "1", "-t", "6", "-framerate", str(FPS), "-i", tmp_path / "p.png", "-c:v", "libx264",
            "-crf", "12", "-pix_fmt", "yuv420p", video)
    paths = cover_frames.candidates(video, tmp_path / "capa", n=3)
    assert len(paths) == 1  # tudo igual: um candidato so


@pytest.mark.parametrize("mode,value,ext", [("I;16", 32768, "png"), ("I", 32768, "tif"),
                                            ("I;16", 1000, "png")])
def test_16_bit_grayscale_photo_is_not_white(tmp_path, mode, value, ext):
    src = tmp_path / f"g16.{ext}"
    img = Image.new(mode, (800, 800), value)
    img.paste(65535 if value > 5000 else 4000, (0, 0, 400, 800))  # metade clara
    img.save(src)
    out = cover_frames.load_photo(src)
    assert out.mode == "RGB"
    left, right = out.getpixel((100, 400)), out.getpixel((700, 400))
    assert left != right and right[0] < 250  # nao vira tudo branco
    assert left[0] > right[0]
