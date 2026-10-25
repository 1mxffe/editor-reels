import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops

import brand
import captions
import cut
import render

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "render.py"

CLEAN_WORDS = [
    # frase 1 (antes do corte 2.6-3.4)
    ("O", 0.50, 0.70), ("prazo", 0.70, 1.10), ("para", 1.10, 1.30), ("recorrer", 1.30, 1.70),
    ("conta", 1.70, 1.95), ("dias", 1.95, 2.15), ("úteis.", 2.15, 2.40),
    # frase 2 (depois do corte)
    ("Leia", 3.80, 4.10), ("a", 4.10, 4.20), ("intimação", 4.20, 4.70), ("com", 4.70, 4.90),
    ("calma.", 4.90, 5.30),
]
CUTS = [{"id": "c0", "start": 2.6, "end": 3.4, "kind": "silence"}]


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def _make_project(root: Path, video: Path, words, cuts=CUTS, name="reel") -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / f"entrada{video.suffix}").write_bytes(video.read_bytes())
    transcript = {"duration": 6.0,
                  "words": [{"w": w, "start": s, "end": e} for w, s, e in words]}
    (proj / "transcricao.json").write_text(json.dumps(transcript, ensure_ascii=False), "utf-8")
    (proj / "cortes.json").write_text(json.dumps({"cuts": cuts}), "utf-8")
    return proj


def _probe_streams(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height,duration", "-of", "json", str(video)],
        check=True, capture_output=True, text=True).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


def _size(video: Path) -> tuple[int, int]:
    v = _probe_streams(video)["video"]
    return int(v["width"]), int(v["height"])


def _frame(video: Path, t: float, out: Path) -> Image.Image:
    _ffmpeg("-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", out)
    return Image.open(out).convert("RGB")


def _tmp_leftovers(proj: Path) -> list[str]:
    saida = proj / "saida"
    if not saida.exists():
        return []
    return [p.name for p in saida.iterdir() if ".tmp" in p.name]


@pytest.fixture
def clean_project(tmp_path, make_sample):
    return _make_project(tmp_path, make_sample, CLEAN_WORDS)


@pytest.fixture
def static_sample(tmp_path):
    """Video vertical de cor solida: fora das frases a faixa de legenda fica uniforme."""
    out = tmp_path / "static.mp4"
    _ffmpeg("-f", "lavfi", "-i", "color=c=0x808080:size=1080x1920:rate=30:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out)
    return out


def test_preview_resolution_540x960(clean_project):
    out = render.render(clean_project, "preview")
    assert out == clean_project / "saida" / "preview.mp4"
    assert _size(out) == (540, 960)
    assert _tmp_leftovers(clean_project) == []


def test_final_resolution_1080x1920(clean_project):
    out = render.render(clean_project, "final")
    assert out == clean_project / "saida" / "final.mp4"
    assert _size(out) == (1080, 1920)
    assert _tmp_leftovers(clean_project) == []


def test_missing_brand_asks_interview(clean_project, tmp_path):
    with pytest.raises(brand.BrandMissing):
        render.render(clean_project, "preview", brand_path=tmp_path / "nao-existe.json")
    assert not (clean_project / "saida").exists()


def test_incomplete_brand_names_missing_keys(clean_project, tmp_path):
    bad = tmp_path / "brand.json"
    bad.write_text(json.dumps({"accent": "#a8c8f0"}), "utf-8")
    with pytest.raises(brand.BrandMissing, match="fg"):
        render.render(clean_project, "preview", brand_path=bad)
    assert not (clean_project / "saida").exists()


@pytest.mark.parametrize("variant", ["landscape", "display_rotation_90"])
def test_rotated_input_still_vertical(tmp_path, variant):
    land = tmp_path / "land.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", land)
    src = land
    if variant == "display_rotation_90":
        src = tmp_path / "rot.mp4"
        _ffmpeg("-display_rotation", "90", "-i", land, "-c", "copy", src)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream_side_data=rotation", "-of", "json", str(src)],
            check=True, capture_output=True, text=True).stdout
        assert "rotation" in probe  # fixture realmente carrega a matriz de rotacao
    proj = _make_project(tmp_path, src, CLEAN_WORDS)
    out = render.render(proj, "preview")
    assert _size(out) == (540, 960)
    streams = _probe_streams(out)
    assert abs(float(streams["video"]["duration"]) - float(streams["audio"]["duration"])) <= 0.1


def test_audio_in_sync(clean_project):
    out = render.render(clean_project, "preview")
    streams = _probe_streams(out)
    v, a = float(streams["video"]["duration"]), float(streams["audio"]["duration"])
    assert abs(v - a) <= 0.1
    # 6 s menos o corte de 0.8 s
    assert abs(v - 5.2) <= 0.15


def test_captions_are_burned_in(tmp_path, static_sample):
    proj = _make_project(tmp_path, static_sample, CLEAN_WORDS)
    out = render.render(proj, "preview")
    words = json.loads((proj / "transcricao.json").read_text("utf-8"))["words"]
    keep = cut.keep_segments(6.0, CUTS)
    ph = captions.phrases(captions.remap(words, keep))
    first = ph[0]
    mid = (first["start"] + first["end"]) / 2
    outside = first["start"] / 2  # antes da primeira frase
    a = _frame(out, mid, tmp_path / "mid.png")
    b = _frame(out, outside, tmp_path / "out.png")
    w, h = a.size
    band = (0, h * 2 // 3, w, h)
    diff = ImageChops.difference(a.crop(band), b.crop(band))
    assert diff.getbbox() is not None
    assert max(hi for _, hi in diff.getextrema()) > 60


def test_original_entrada_untouched(clean_project):
    entrada = clean_project / "entrada.mp4"
    before = entrada.read_bytes()
    render.render(clean_project, "preview")
    assert entrada.read_bytes() == before


def test_ffmpeg_failure_leaves_no_tmp(clean_project, monkeypatch):
    monkeypatch.setattr(render, "_encode_args",
                        lambda quality: ["-c:v", "codec_que_nao_existe"])
    with pytest.raises(SystemExit):
        render.render(clean_project, "final")
    saida = clean_project / "saida"
    assert not (saida / "final.mp4").exists()
    assert _tmp_leftovers(clean_project) == []


def test_project_path_with_special_chars(tmp_path, make_sample):
    proj = _make_project(tmp_path, make_sample, CLEAN_WORDS, name="reel: o'teste, [1]; x")
    out = render.render(proj, "preview")
    assert _size(out) == (540, 960)


def _cli(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def test_cli_ok_exit_0(clean_project):
    proc = _cli(clean_project, "preview")
    assert proc.returncode == 0, proc.stderr
    assert (clean_project / "saida" / "preview.mp4").is_file()


def test_cli_missing_brand_asks_interview(clean_project, tmp_path):
    proc = _cli(clean_project, "preview", "--brand", tmp_path / "nada.json")
    assert proc.returncode == 1
    assert "entrevista de marca" in proc.stderr
    assert not (clean_project / "saida").exists()


# --- Task 3b (sem ffmpeg real: falham antes do encode ou usam stubs) -----------


def _proj_words(tmp_path, words, cuts=CUTS, name="reel"):
    """Projeto com entrada falsa: serve para os caminhos que param antes do ffmpeg."""
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "entrada.mp4").write_bytes(b"nao e video")
    (proj / "transcricao.json").write_text(json.dumps({"duration": 6.0, "words": words}), "utf-8")
    (proj / "cortes.json").write_text(json.dumps({"cuts": cuts}), "utf-8")
    return proj


def _w(items):
    return [{"w": w, "start": s, "end": e} for w, s, e in items]


def test_no_words_fails_nenhuma_fala(tmp_path):
    proj = _proj_words(tmp_path, [])
    with pytest.raises(render.ProjectError, match="nenhuma fala detectada"):
        render.render(proj, "preview")
    proc = _cli(proj, "preview")
    assert proc.returncode == 1 and "nenhuma fala detectada" in proc.stderr
    assert not (proj / "saida").exists()


@pytest.mark.parametrize("word", [
    {"start": 0.0, "end": 0.5},
    {"w": 3, "start": 0.0, "end": 0.5},
    {"w": "oi", "start": "0", "end": 0.5},
    {"w": "oi", "start": 0.0},
    {"w": "oi", "start": 0.0, "end": True},
    "oi",
])
def test_bad_word_entry_fails_clearly(tmp_path, word):
    proj = _proj_words(tmp_path, [word])
    with pytest.raises(render.ProjectError, match="palavra 0"):
        render.render(proj, "preview")
    assert not (proj / "saida").exists()


def test_bad_cut_entry_fails_clearly(tmp_path):
    proj = _proj_words(tmp_path, _w(CLEAN_WORDS), cuts=[{"id": "c0", "start": 1.0}])
    with pytest.raises(render.ProjectError, match="corte 0"):
        render.render(proj, "preview")


def test_cli_invalid_brand_value_asks_interview(tmp_path):
    proj = _proj_words(tmp_path, _w(CLEAN_WORDS))
    bad = tmp_path / "brand.json"
    bad.write_text(json.dumps({**brand.seed_from_guide(), "fg": "branco"}), "utf-8")
    proc = _cli(proj, "preview", "--brand", bad)
    assert proc.returncode == 1
    assert "valor inválido" in proc.stderr and "fg" in proc.stderr
    assert "inválida" in proc.stderr and "entrevista de marca" in proc.stderr
    assert not (proj / "saida").exists()


@pytest.fixture
def stub_ffmpeg(monkeypatch):
    """Troca cut.apply e common.run por stubs que so criam os arquivos de saida."""
    calls = []

    def fake_apply(video, cuts, out):
        Path(out).write_bytes(b"corte")

    def fake_run(cmd):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"mp4")
        return ""

    monkeypatch.setattr(cut, "apply", fake_apply)
    monkeypatch.setattr(render, "_has_audio", lambda video: True)
    monkeypatch.setattr(render.common, "run", fake_run)
    return calls


def test_encode_has_no_redundant_r_and_unique_tmp(tmp_path, stub_ffmpeg):
    proj = _proj_words(tmp_path, _w(CLEAN_WORDS))
    saida = proj / "saida"
    saida.mkdir()
    stale = saida / "preview.tmp.mp4"  # de outro render em andamento: nao e nosso
    stale.write_bytes(b"de outro processo")
    out = render.render(proj, "preview")
    assert out.read_bytes() == b"mp4"
    [cmd] = stub_ffmpeg
    assert "-r" not in cmd
    assert "fps=30" in cmd[cmd.index("-vf") + 1]
    assert Path(cmd[-1]).name != "preview.tmp.mp4"
    assert stale.read_bytes() == b"de outro processo"
    assert sorted(p.name for p in saida.iterdir()) == ["preview.mp4", "preview.tmp.mp4"]


def test_mkstemp_failure_leaves_no_tmp(tmp_path, stub_ffmpeg, monkeypatch):
    import tempfile
    real = tempfile.mkstemp
    n = {"calls": 0}

    def flaky(*a, **k):
        n["calls"] += 1
        if n["calls"] == 2:
            raise OSError("sem inodes")
        return real(*a, **k)

    monkeypatch.setattr(render.tempfile, "mkstemp", flaky)
    proj = _proj_words(tmp_path, _w(CLEAN_WORDS))
    with pytest.raises(OSError):
        render.render(proj, "preview")
    assert list((proj / "saida").iterdir()) == []


# ---- Task 11: estilo.json ----
import hashlib  # noqa: E402

ASS_HEAD = {  # hash do .ass que o render gerava antes do estilo.json (commit aca4b43)
    "preview": "7f5e40f1f51553a5c8a44a82231a8dc4af016d760b8684152cfb2f4f23c009bc",
    "final": "6895616cf7f36b51cf1a0ead8206eab13532c1de58a0d6572bfc0c7427776fe7",
}


@pytest.fixture
def ass_spy(monkeypatch):
    """Stub do ffmpeg que guarda o .ass que o render deixou para o filtro subtitles."""
    got = []

    def fake_run(cmd):
        saida = Path(cmd[-1]).parent
        got.extend(p.read_text("utf-8") for p in saida.glob(".legendas-*.tmp.ass"))
        Path(cmd[-1]).write_bytes(b"mp4")
        return ""

    monkeypatch.setattr(cut, "apply", lambda v, c, o: Path(o).write_bytes(b"x"))
    monkeypatch.setattr(render, "_has_audio", lambda v: True)
    monkeypatch.setattr(render, "has_libass", lambda: True)
    monkeypatch.setattr(render.common, "run", fake_run)
    return got


def _style(ass):
    line = next(l for l in ass.splitlines() if l.startswith("Style:"))
    fmt = next(l for l in ass.splitlines() if l.startswith("Format:") and "Fontname" in l)
    keys = [k.strip() for k in fmt[len("Format:"):].split(",")]
    return dict(zip(keys, (v.strip() for v in line[len("Style:"):].split(","))))


@pytest.mark.parametrize("quality", ["preview", "final"])
def test_render_without_estilo_unchanged(tmp_path, ass_spy, quality):
    proj = _proj_words(tmp_path, _w(CLEAN_WORDS))
    render.render(proj, quality)
    [ass] = ass_spy
    assert hashlib.sha256(ass.encode("utf-8")).hexdigest() == ASS_HEAD[quality]


def test_render_with_estilo_uses_palette_font(tmp_path, ass_spy, monkeypatch):
    import banco
    import graphics
    proj = _proj_words(tmp_path, _w(CLEAN_WORDS))
    (proj / "estilo.json").write_text(json.dumps({
        "paleta": "grafite", "fonte": "Poppins",
        "legenda": {"estilo": "pilula-escura", "posicao": "meio", "tamanho": "G"},
        "cards": {"estilo": "vidro"}}), "utf-8")
    brand_antes = render.DEFAULT_BRAND.read_bytes()
    marcas = []
    card = {"id": "g1", "title": "Prazo", "body": "15 dias úteis", "at": 0.5, "dur": 1.5}
    monkeypatch.setattr(render, "load_cards", lambda p: [dict(card)])
    monkeypatch.setattr(graphics, "renderer_status", lambda: None)

    def fake_clip(c, b, out, size):
        marcas.append(b)
        Path(out).write_bytes(b"webm")
        return Path(out)
    monkeypatch.setattr(graphics, "render_clip", fake_clip)
    render.render(proj, "final")
    [ass] = ass_spy
    pal = banco.carregar().item("paleta", "grafite")["dados"]
    st = _style(ass)
    assert st["Fontname"] == "Poppins"
    assert st["PrimaryColour"] == captions._ass_color(pal["texto"])
    assert st["BackColour"] == captions._ass_color(pal["fundo"], alpha=0x26)
    assert st["Alignment"] == "5" and int(st["Fontsize"]) > 64
    [b] = marcas
    assert (b["bg"], b["fg"], b["accent"], b["muted"]) == (
        pal["fundo"], pal["texto"], pal["destaque"], pal["apoio"])
    assert b["font_title"] == b["font_body"] == "Poppins"
    assert render.DEFAULT_BRAND.read_bytes() == brand_antes


def test_render_invalid_estilo_fails_clearly(tmp_path, ass_spy):
    proj = _proj_words(tmp_path, _w(CLEAN_WORDS))
    (proj / "estilo.json").write_text('{"paleta": "arco-iris"}', "utf-8")
    proc = _cli(proj, "preview")
    assert proc.returncode == 1
    assert "estilo.json" in proc.stderr and "arco-iris" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_render_estilo_invalido_antes_de_nenhuma_fala(tmp_path):
    import estilo as estilomod
    proj = _proj_words(tmp_path, [])
    (proj / "estilo.json").write_text("[" * 16000, "utf-8")
    with pytest.raises(estilomod.EstiloError):
        render.render(proj, "preview")
    proc = _cli(proj, "preview")
    assert proc.returncode == 1 and "estilo.json" in proc.stderr and "Traceback" not in proc.stderr
