"""Composição da capa do Reel (1080x1920) por Chromium headless.

Fotos sintéticas (degradê + "rosto" elíptico + corpo escuro, feitas com
Pillow): nenhuma foto real entra nos testes. Os testes que desenham a capa
são pulados (com motivo) quando node/Playwright/Chromium não existem; os de
validação e ``brand.py set-handles`` rodam sempre.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import brand as brandmod
import cover_compose as cc
import cover_frames
import graphics

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "cover_compose.py"
BRAND_SCRIPT = REPO / "scripts" / "brand.py"
BRAND = {**json.loads((REPO / "brand" / "brand.json").read_text("utf-8")),
         "handles": ["@gutmannesilva"]}
SUB = "que podem te fazer pagar\nmais imposto de renda"
ACCENT = (0xA8, 0xC8, 0xF0)


# ---------------------------------------------------------------- fotos sintéticas

def _portrait(path: Path, size=(1080, 1920), exif_orientation=None, marker=False) -> Path:
    """Retrato sintético: fundo em degradê, rosto (elipse cor de pele), corpo escuro."""
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=(int(150 - 60 * k), int(138 - 50 * k), int(120 - 40 * k)))
    cx, cy = w / 2, h * 0.36
    d.ellipse([cx - w * 0.17, cy - h * 0.15, cx + w * 0.17, cy + h * 0.10], fill=(60, 40, 30))  # cabelo
    d.ellipse([cx - w * 0.13, cy - h * 0.10, cx + w * 0.13, cy + h * 0.10], fill=(224, 172, 140))
    d.polygon([(w * 0.12, h), (w * 0.22, h * 0.52), (w * 0.78, h * 0.52), (w * 0.88, h)],
              fill=(38, 44, 56))
    if marker:  # bloco vermelho no canto superior esquerdo da imagem EM PÉ
        d.rectangle([0, 0, int(w * 0.2), int(h * 0.12)], fill=(230, 20, 20))
    if exif_orientation == 6:  # armazenada deitada; o EXIF manda girar 90° horário
        stored = img.transpose(Image.Transpose.ROTATE_90)
        exif = Image.Exif()
        exif[0x0112] = 6
        stored.save(path, format="JPEG", quality=92, exif=exif.tobytes())
    else:
        img.save(path)
    return path


def _landscape(path: Path, size=(1600, 900)) -> Path:
    img = Image.new("RGB", size, (20, 120, 40))  # verde nas laterais
    d = ImageDraw.Draw(img)
    w, h = size
    d.rectangle([w * 0.4, 0, w * 0.6, h], fill=(200, 60, 200))  # faixa central magenta
    img.save(path)
    return path


def _light(path: Path, size=(1080, 1920)) -> Path:
    """Foto quase branca (o pior caso de contraste para o texto e o logotipo)."""
    w, h = size
    img = Image.new("RGB", size, (240, 238, 232))
    d = ImageDraw.Draw(img)
    cx, cy = w / 2, h * 0.40
    d.ellipse([cx - w * 0.19, cy - h * 0.14, cx + w * 0.19, cy + h * 0.16], fill=(200, 170, 120))
    d.ellipse([cx - w * 0.14, cy - h * 0.10, cx + w * 0.14, cy + h * 0.09], fill=(240, 200, 175))
    d.polygon([(w * 0.05, h), (w * 0.18, h * 0.58), (w * 0.82, h * 0.58), (w * 0.95, h)],
              fill=(235, 235, 240))
    img.save(path)
    return path


def _lum(p) -> float:
    c = [v / 255 for v in p[:3]]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(img: Image.Image, box: dict) -> float:
    """WCAG entre o texto claro (p99 da luminância) e o fundo (mediana) na caixa."""
    rgb = img.convert("RGB")
    l, t = max(0, int(box["left"])), max(0, int(box["top"]))
    r, b = min(rgb.width, int(box["right"])), min(rgb.height, int(box["bottom"]))
    lums = sorted(_lum(rgb.getpixel((x, y))) for y in range(t, b) for x in range(l, r))
    fg, bg = lums[int(0.99 * (len(lums) - 1))], lums[len(lums) // 2]
    return (fg + 0.05) / (bg + 0.05)


def _wordmark(box: dict) -> dict:
    """Faixa de baixo do logotipo: o wordmark branco "Gutmann & Silva"."""
    h = box["bottom"] - box["top"]
    return {**box, "top": box["top"] + 0.62 * h}


@pytest.fixture(scope="module")
def photo(tmp_path_factory) -> Path:
    return _portrait(tmp_path_factory.mktemp("foto") / "candidato-1.png")


@pytest.fixture
def no_tools(monkeypatch):
    """Falha o teste se o navegador, subprocessos ou temporários forem usados."""
    def boom(*a, **k):
        raise AssertionError(f"nao deveria executar nada: {a!r}")
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(tempfile, "mkdtemp", boom)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", boom)


@pytest.fixture
def tmpdir_root(tmp_path, monkeypatch) -> Path:
    """Pasta temporária do sistema isolada para provar que nada sobra nela."""
    root = tmp_path / "systmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def _need_browser():
    reason = graphics.browser_status()
    if reason:
        pytest.skip(f"navegador indisponível: {reason}")


@pytest.fixture(scope="module")
def standard(tmp_path_factory, photo):
    """Uma capa padrão desenhada uma vez (PNG + medidas) para vários testes."""
    _need_browser()
    d = tmp_path_factory.mktemp("capa")
    shot = d / "shot.png"
    info = cc.inspect(photo, "3 MITOS", BRAND, area="ISENÇÃO DE IR", subtitle=SUB, shot=shot)
    out = cc.compose(photo, "3 MITOS", BRAND, d / "capa" / "capa.png",
                     area="ISENÇÃO DE IR", subtitle=SUB)
    return {"info": info, "shot": shot, "out": out}


def _near(px, ref, tol=40) -> bool:
    return sum((a - b) ** 2 for a, b in zip(px[:3], ref)) <= tol * tol


def _count(img: Image.Image, box: dict, pred) -> int:
    rgb = img.convert("RGB")
    l, t = max(0, int(box["left"])), max(0, int(box["top"]))
    r, b = min(rgb.width, int(box["right"])), min(rgb.height, int(box["bottom"]))
    px = rgb.load()
    return sum(1 for y in range(t, b) for x in range(l, r) if pred(px[x, y]))


# ---------------------------------------------------------------- tarefa (brief)

def test_requires_handles(tmp_path, photo, no_tools):
    out = tmp_path / "capa.png"
    for handles in ([], ["", "   "]):
        with pytest.raises(brandmod.BrandMissing) as exc:
            cc.compose(photo, "3 MITOS", {**BRAND, "handles": handles}, out)
        assert "@" in str(exc.value) and "informe" in str(exc.value)
    assert not out.exists()


def test_texts_are_drawn_as_written(tmp_path, photo, monkeypatch, tmpdir_root):
    # o escritório revisa o texto antes de gravar: a capa não confere conteúdo
    _stub_renderer(monkeypatch)
    out = cc.compose(photo, "GARANTIMOS A VITÓRIA", BRAND, tmp_path / "saida" / "capa.png",
                     area="ARTIGO", subtitle="veja a Lei 7.713\nhoje")
    with Image.open(out) as im:
        assert im.size == (1080, 1920)
    assert list(tmpdir_root.iterdir()) == []


def test_many_line_breaks_are_not_limited(tmp_path, photo, monkeypatch):
    # só o layout medido limita a altura do bloco (ver test_text_block_too_tall_is_an_error)
    _stub_renderer(monkeypatch)
    out = cc.compose(photo, "3\nMITOS", BRAND, tmp_path / "c.png", area="A",
                     subtitle="\n".join("abcdefghij"))
    assert out.is_file()


def test_output_size_1080x1920(standard):
    out = standard["out"]
    assert out.name == "capa.png" and out.is_file()
    with Image.open(out) as im:
        assert im.format == "PNG"
        assert im.size == (1080, 1920)
        assert im.mode in ("RGB", "RGBA")
        if im.mode == "RGBA":
            assert im.getchannel("A").getextrema() == (255, 255)
    assert not list(out.parent.glob("*.tmp"))


def test_logo_and_photo_are_inline_images(standard):
    info = standard["info"]
    assert Path(info["logo"]) == REPO / "assets" / "logo.webp"
    assert cc.LOGO == REPO / "assets" / "logo.webp"
    assert info["imgCount"] == 2 and info["allDataUris"] is True


# ---------------------------------------------------------------- validação

@pytest.mark.parametrize("title", ["", "   ", "\n \n", "X" * 29, "UM\nDOIS\nTRÊS", 12, None])
def test_bad_hook(tmp_path, photo, no_tools, title):
    with pytest.raises(cover_frames.CoverError):
        cc.compose(photo, title, BRAND, tmp_path / "c.png")
    assert not (tmp_path / "c.png").exists()


@pytest.mark.parametrize("kw", [{"area": "A" * 29}, {"subtitle": "s" * 91}, {"area": 3},
                                {"subtitle": ["x"]}])
def test_bad_area_or_subtitle(tmp_path, photo, no_tools, kw):
    with pytest.raises(cover_frames.CoverError):
        cc.compose(photo, "3 MITOS", BRAND, tmp_path / "c.png", **kw)


def test_text_normalisation():
    t = cc.normalize_texts("  3   MITOS ", "  isenção   de IR ", " que  podem \n\n mais  imposto ")
    assert t == {"hook": "3 MITOS", "area": "isenção de IR",
                 "subMain": "que podem", "subAccent": "mais imposto"}
    t = cc.normalize_texts("3\nMITOS", None, "tudo branco")
    assert t == {"hook": "3\nMITOS", "area": None, "subMain": "tudo branco", "subAccent": None}
    assert cc.normalize_texts("X" * 28, "A" * 28, "s" * 90)["hook"] == "X" * 28


@pytest.mark.parametrize("handle", ["@gutmann silva", "@" + "a" * 31, "@ação", "@gutmann-silva",
                                    "@@gs", "@", "gs/adv", "@gutmann\u200bsilva"])
def test_bad_handle(tmp_path, photo, no_tools, handle):
    with pytest.raises(cover_frames.CoverError) as exc:
        cc.compose(photo, "3 MITOS", {**BRAND, "handles": [handle]}, tmp_path / "c.png")
    assert "@ inválido" in str(exc.value)


def test_handle_normalisation():
    assert brandmod.normalize_handle(" gutmannesilva ") == "@gutmannesilva"
    assert brandmod.normalize_handle("@gs.adv_1") == "@gs.adv_1"
    assert brandmod.normalize_handle("@" + "a" * 30) == "@" + "a" * 30


def test_photo_errors(tmp_path, no_tools):
    small = _portrait(tmp_path / "pequena.png", size=(500, 900))
    fake = tmp_path / "foto.jpg"
    fake.write_bytes(b"isto nao e uma imagem")
    for p, msg in ((small, "pequena"), (fake, "imagem"), (tmp_path / "sumiu.png", "não encontrada")):
        with pytest.raises(cover_frames.CoverError) as exc:
            cc.compose(p, "3 MITOS", BRAND, tmp_path / "out" / "c.png")
        assert msg in str(exc.value)
    assert not (tmp_path / "out").exists()


def test_logo_errors(tmp_path, photo, no_tools):
    fake = tmp_path / "logo.png"
    fake.write_bytes(b"nao e imagem")
    for logo, msg in ((tmp_path / "sumiu.webp", "não encontrado"), (fake, "ilegível")):
        with pytest.raises(cover_frames.CoverError) as exc:
            cc.compose(photo, "3 MITOS", BRAND, tmp_path / "c.png", logo=logo)
        assert msg in str(exc.value)


def test_bad_brand_colors(tmp_path, photo, no_tools):
    with pytest.raises(graphics.GraphicsError):
        cc.compose(photo, "3 MITOS", {**BRAND, "bg": "navy"}, tmp_path / "c.png")


def test_renderer_missing_is_clear(tmp_path, photo, monkeypatch, tmpdir_root):
    monkeypatch.setattr(graphics, "browser_status", lambda: "node ausente")
    with pytest.raises(graphics.RendererMissing) as exc:
        cc.compose(photo, "3 MITOS", BRAND, tmp_path / "x" / "c.png")
    assert "node ausente" in str(exc.value) and "capa" in str(exc.value)
    assert not (tmp_path / "x").exists() and list(tmpdir_root.iterdir()) == []


def test_input_files_untouched(standard, photo, tmp_path):
    assert standard["out"].is_file()
    assert photo.read_bytes() == _portrait(tmp_path / "de-novo.png").read_bytes()
    committed = subprocess.run(["git", "-C", str(REPO), "show", "HEAD:assets/logo.webp"],
                               capture_output=True, check=True).stdout
    assert cc.LOGO.read_bytes() == committed


# ---------------------------------------------------------------- falha não deixa nada

def test_driver_failure_writes_nothing(tmp_path, photo, monkeypatch, tmpdir_root):
    monkeypatch.setattr(graphics, "browser_status", lambda: None)

    def broken(job, workdir, what, driver=None):
        (Path(workdir) / "lixo.png").write_bytes(b"x")
        raise graphics.GraphicsError(f"{what}: navegador caiu")
    monkeypatch.setattr(graphics, "_drive", broken)
    out = tmp_path / "a" / "b" / "capa.png"
    with pytest.raises(graphics.GraphicsError):
        cc.compose(photo, "3 MITOS", BRAND, out)
    assert not (tmp_path / "a").exists()
    assert list(tmpdir_root.iterdir()) == []


def test_existing_output_kept_when_render_fails(tmp_path, photo, monkeypatch, tmpdir_root):
    monkeypatch.setattr(graphics, "browser_status", lambda: None)
    out = tmp_path / "capa.png"
    out.write_bytes(b"capa anterior")

    def fake(job, workdir, what, driver=None):  # PNG de tamanho errado
        Image.new("RGB", (100, 100)).save(job["shot"])
        return {"boxes": {}, "safeOk": True}
    monkeypatch.setattr(graphics, "_drive", fake)
    with pytest.raises(graphics.GraphicsError):
        cc.compose(photo, "3 MITOS", BRAND, out)
    assert out.read_bytes() == b"capa anterior"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["capa.png", "systmp"]
    assert list(tmpdir_root.iterdir()) == []


def test_text_outside_safe_area_is_an_error(tmp_path, photo, monkeypatch, tmpdir_root):
    monkeypatch.setattr(graphics, "browser_status", lambda: None)

    def fake(job, workdir, what, driver=None):
        Image.new("RGB", (1080, 1920), (0, 25, 49)).save(job["shot"])
        return {"boxes": {"hook": {"top": 100, "bottom": 300, "left": 54, "right": 900}}}
    monkeypatch.setattr(graphics, "_drive", fake)
    out = tmp_path / "capa.png"
    with pytest.raises(graphics.GraphicsError) as exc:
        cc.compose(photo, "3 MITOS", BRAND, out)
    assert "área segura" in str(exc.value)
    assert not out.exists() and list(tmpdir_root.iterdir()) == []


def test_output_written_atomically(tmp_path, photo, monkeypatch, tmpdir_root):
    monkeypatch.setattr(graphics, "browser_status", lambda: None)
    replaced = []
    real_replace = os.replace

    def spy(src, dst):
        replaced.append((Path(src).name, Path(dst).name))
        assert Path(src).is_file() and not Path(dst).exists()
        real_replace(src, dst)

    def fake(job, workdir, what, driver=None):
        Image.new("RGBA", (1080, 1920), (0, 25, 49, 255)).save(job["shot"])
        return {"boxes": {"hook": {"top": 1200, "bottom": 1400, "left": 54, "right": 900}}}
    monkeypatch.setattr(graphics, "_drive", fake)
    import common
    monkeypatch.setattr(common.os, "replace", spy)  # a troca e feita em common.atomic_write
    out = cc.compose(photo, "3 MITOS", BRAND, tmp_path / "novo" / "capa.png")
    assert len(replaced) == 1 and replaced[0][1] == "capa.png"
    # temporario unico e oculto no mesmo diretorio (common.atomic_write)
    assert replaced[0][0].startswith(".capa.png-") and ".tmp" in replaced[0][0]
    assert sorted(p.name for p in out.parent.iterdir()) == ["capa.png"]
    with Image.open(out) as im:
        assert im.mode == "RGB" and im.size == (1080, 1920)
    assert list(tmpdir_root.iterdir()) == []


def _stub_renderer(monkeypatch):
    monkeypatch.setattr(graphics, "browser_status", lambda: None)

    def fake(job, workdir, what, driver=None):
        Image.new("RGB", (1080, 1920), (0, 25, 49)).save(job["shot"])
        return {"boxes": {"hook": {"top": 1200, "bottom": 1400, "left": 54, "right": 900}}}
    monkeypatch.setattr(graphics, "_drive", fake)


def test_planted_tmp_symlink_is_not_followed(tmp_path, monkeypatch, tmpdir_root):
    _stub_renderer(monkeypatch)
    photo = _portrait(tmp_path / "foto.png")
    before = photo.read_bytes()
    out = tmp_path / "capa.png"
    (tmp_path / "capa.png.tmp").symlink_to(photo)
    cc.compose(photo, "3 MITOS", BRAND, out)
    assert photo.read_bytes() == before
    with Image.open(out) as im:
        assert im.size == (1080, 1920)


def test_concurrent_composes_do_not_clobber(tmp_path, photo, monkeypatch, tmpdir_root):
    import threading
    _stub_renderer(monkeypatch)
    out = tmp_path / "saida" / "capa.png"
    errors = []

    def run():
        try:
            cc.compose(photo, "3 MITOS", BRAND, out)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(p.name for p in out.parent.iterdir()) == ["capa.png"]
    with Image.open(out) as im:
        assert im.size == (1080, 1920)


def test_no_tmp_left_after_save_failure(tmp_path, photo, monkeypatch, tmpdir_root):
    _stub_renderer(monkeypatch)
    out_dir = tmp_path / "saida"
    out_dir.mkdir()

    def broken_replace(src, dst):
        raise OSError("disco cheio")
    import common
    monkeypatch.setattr(common.os, "replace", broken_replace)  # troca em common.atomic_write
    with pytest.raises(OSError):
        cc.compose(photo, "3 MITOS", BRAND, out_dir / "capa.png")
    assert list(out_dir.iterdir()) == []


@pytest.mark.parametrize("argv", [[], ["a"], ["a", "b.json"], ["a", "b", "c"],
                                  ["a", "b", "c", "--hook", "X", "--nao-existe"]])
def test_usage_errors_exit_1(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        cc.main(argv)
    assert exc.value.code == 1
    assert "erro:" in capsys.readouterr().err


# ---------------------------------------------------------------- desenho real

def _boxes_inside(info, top, bottom, left=40, right=1040):
    for name, b in info["boxes"].items():
        if name in cc.TEXT_BOXES and b is not None:
            assert top <= b["top"] and b["bottom"] <= bottom, (name, b)
            assert left <= b["left"] and b["right"] <= right, (name, b)


def test_safe_areas_with_longest_texts(tmp_path):
    _need_browser()
    p = _portrait(tmp_path / "f.png")
    brand = {**BRAND, "handles": ["gutmannesilva", " @gs.adv "]}
    info = cc.inspect(p, "O QUE MUDA NA ISENÇÃO DO IR?", brand, area="A" * 12 + " " + "B" * 15,
                      subtitle=("palavras " * 6).strip() + "\n" + ("finais " * 5).strip())
    assert info["texts"]["handle"] == "@gutmannesilva · @gs.adv"
    _boxes_inside(info, cc.SAFE_TOP, 1920 - cc.SAFE_BOTTOM)
    _boxes_inside(info, cc.GRID_CROP[0], cc.GRID_CROP[1])
    assert info["hookLines"] <= 2
    assert not any(info["overflow"].values())
    assert info["safeOk"] is True


def test_hook_auto_fit(standard):
    info = standard["info"]
    assert info["hookLines"] == 1 and info["hookSize"] >= 150
    assert info["texts"]["hook"] == "3 MITOS"
    assert info["texts"]["area"] == "ISENÇÃO DE IR" and info["areaTransform"] == "uppercase"
    _boxes_inside(info, cc.SAFE_TOP, 1920 - cc.SAFE_BOTTOM)


def test_long_word_wraps_only_when_two_lines_fit(tmp_path, photo):
    _need_browser()
    info = cc.inspect(photo, "ABCDEFGHIJKLMNOPQRST", BRAND, subtitle="x" * 90)
    assert info["hookLines"] == 2 and info["hookSize"] >= cc.HOOK_MIN
    assert not any(info["overflow"].values())
    _boxes_inside(info, cc.SAFE_TOP, 1920 - cc.SAFE_BOTTOM)
    out = tmp_path / "c.png"
    with pytest.raises(cover_frames.CoverError) as exc:
        cc.compose(photo, "ABCDEFGHIJKLMNOPQRSTUVWXYZAB", BRAND, out)
    assert "2 linhas" in str(exc.value) and not out.exists()


@pytest.mark.parametrize("hook", ["ATENÇÃO À DECLARAÇÃO DO IRPF", "3\nMITOS SOBRE ISENÇÃO DE IR"])
def test_hook_over_two_lines_is_an_error(tmp_path, photo, tmpdir_root, hook):
    _need_browser()
    out = tmp_path / "saida" / "c.png"
    with pytest.raises(cover_frames.CoverError) as exc:
        cc.compose(photo, hook, BRAND, out)
    assert "gancho não cabe em 2 linhas" in str(exc.value)
    assert not out.parent.exists() and list(tmpdir_root.iterdir()) == []


def test_forced_break_two_lines_ok(photo):
    _need_browser()
    info = cc.inspect(photo, "QUEM TEM\nDIREITO?", BRAND)
    assert info["hookLines"] == 2 and info["texts"]["hook"] == "QUEM TEM\nDIREITO?"


def test_text_block_too_tall_is_an_error(tmp_path, photo):
    _need_browser()
    sub = "\n".join(["linha"] * 7)  # pill + 2 + 7 + @ = 11 linhas: não cabe acima de y = 520
    with pytest.raises(cover_frames.CoverError) as exc:
        cc.compose(photo, "3\nMITOS", BRAND, tmp_path / "c.png", area="TRIBUTÁRIO",
                   subtitle=sub)
    assert "texto longo demais para a capa" in str(exc.value)
    assert not (tmp_path / "c.png").exists()


def test_light_photo_contrast(tmp_path):
    _need_browser()
    p = _light(tmp_path / "clara.png")
    shot = tmp_path / "s.png"
    info = cc.inspect(p, "QUEM TEM\nDIREITO?", BRAND, area="ISENÇÃO DE IR",
                      subtitle="aposentados com doença grave\nvocê tem direito?", shot=shot)
    with Image.open(shot) as im:
        pill = _contrast(im, info["boxes"]["area"])
        mark = _contrast(im, _wordmark(info["boxes"]["logo"]))
    assert pill >= 4.5, pill
    assert mark >= 4.5, mark


def test_light_photo_long_subtitle_fits_or_refuses(tmp_path):
    _need_browser()
    p = _light(tmp_path / "clara.png")
    shot = tmp_path / "s.png"
    sub = ("o que conferir antes de enviar a declaração ao fisco neste ano\n"
           "sem erro nenhum de novo")
    assert len(sub) <= 90
    try:
        info = cc.inspect(p, "QUEM TEM\nDIREITO?", BRAND, area="TRIBUTÁRIO", subtitle=sub, shot=shot)
    except cover_frames.CoverError as e:
        assert "texto longo demais" in str(e)
        return
    assert info["boxes"]["block"]["top"] >= cc.BLOCK_TOP_MIN
    with Image.open(shot) as im:
        assert _contrast(im, info["boxes"]["area"]) >= 4.5


def test_dark_photo_still_ok(tmp_path):
    _need_browser()
    p = tmp_path / "escura.png"
    Image.new("RGB", (1080, 1920), (4, 4, 6)).save(p)
    shot = tmp_path / "s.png"
    info = cc.inspect(p, "3 MITOS", BRAND, area="ISENÇÃO DE IR", subtitle=SUB, shot=shot)
    with Image.open(shot) as im:
        assert _contrast(im, info["boxes"]["area"]) >= 4.5
        assert _contrast(im, _wordmark(info["boxes"]["logo"])) >= 4.5
    assert info["logoScrim"] <= 0.1


def test_markup_in_texts_is_inert(tmp_path, photo):
    _need_browser()
    hook = '<img src=x onerror=f()>'
    sub = '</script><b>"aspas" & \'x\'</b>\n<img src=x onerror="window.__xss=1">'
    info = cc.inspect(photo, hook, BRAND, area="<i>ÁREA</i>", subtitle=sub)
    assert info["xss"] is None
    assert info["texts"]["hook"] == hook
    assert info["texts"]["subMain"] == '</script><b>"aspas" & \'x\'</b>'
    assert info["texts"]["subAccent"] == '<img src=x onerror="window.__xss=1">'
    assert info["imgCount"] == 2


def test_exif_rotated_photo_is_upright(tmp_path):
    _need_browser()
    p = _portrait(tmp_path / "deitada.jpg", exif_orientation=6, marker=True)
    with Image.open(p) as im:
        assert im.size == (1920, 1080)  # armazenada deitada
    shot = tmp_path / "s.png"
    cc.inspect(p, "3 MITOS", BRAND, shot=shot)
    with Image.open(shot) as im:
        rgb = im.convert("RGB")
        r, g, b = rgb.getpixel((80, 120))
        assert r > 2 * g and r > 2 * b and r > 60, (r, g, b)  # escurecido pelo véu do topo
        r2, g2, b2 = rgb.getpixel((1000, 120))
        assert not (r2 > 2 * g2 and r2 > 2 * b2)


def test_landscape_photo_cover_fits(tmp_path):
    _need_browser()
    p = _landscape(tmp_path / "paisagem.png")
    shot = tmp_path / "s.png"
    info = cc.inspect(p, "3 MITOS", BRAND, shot=shot)
    assert info["objectPosition"] == "50% 50%"
    with Image.open(shot) as im:
        rgb = im.convert("RGB")
        assert rgb.size == (1080, 1920)
        # faixa central magenta (20 % da largura da foto) ocupa o meio do quadro
        r, g, b = rgb.getpixel((540, 700))
        assert r > 120 and b > 120 and g < 90, (r, g, b)
        r, g, b = rgb.getpixel((20, 700))  # bordas: verde da foto, sem faixa vazia
        assert g > r and g > b, (r, g, b)


def test_portrait_anchor(standard):
    assert standard["info"]["objectPosition"] == "50% 28%"


def test_accent_only_on_last_subtitle_line(standard):
    info = standard["info"]
    assert info["texts"]["subMain"] == "que podem te fazer pagar"
    assert info["texts"]["subAccent"] == "mais imposto de renda"
    with Image.open(standard["shot"]) as im:
        accent_in_main = _count(im, info["boxes"]["subMain"], lambda p: _near(p, ACCENT, 30))
        accent_in_last = _count(im, info["boxes"]["subAccent"], lambda p: _near(p, ACCENT, 30))
    assert accent_in_last > 500
    assert accent_in_main < 20


def test_logo_on_top(standard):
    info = standard["info"]
    box = info["boxes"]["logo"]
    assert 230 <= box["top"] <= 270
    assert abs((box["left"] + box["right"]) / 2 - 540) <= 2
    with Image.open(standard["out"]) as im:
        white = _count(im, box, lambda p: min(p[:3]) > 215)
        side = {"top": box["top"], "bottom": box["bottom"], "left": 0, "right": box["left"] - 10}
        white_side = _count(im, side, lambda p: min(p[:3]) > 215)
    assert white > 400 and white_side == 0


def test_bottom_is_navy(standard):
    with Image.open(standard["out"]) as im:
        rgb = im.convert("RGB")
        for y in (1700, 1800, 1900):
            assert _near(rgb.getpixel((540, y)), (0x00, 0x19, 0x31), 12)


@pytest.mark.parametrize("which", ["photo", "logo", "brand"])
def test_output_cannot_overwrite_an_input(tmp_path, no_tools, which):
    photo = _portrait(tmp_path / "foto.png")
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (400, 200), (255, 255, 255, 255)).save(logo)
    brand_path = tmp_path / "brand.json"
    brand_path.write_text(json.dumps(BRAND), "utf-8")
    target = {"photo": photo, "logo": logo, "brand": brand_path}[which]
    before = target.read_bytes()
    # caminho relativo/com ".." que resolve para o mesmo arquivo
    out = tmp_path / "sub" / ".." / target.name
    (tmp_path / "sub").mkdir()
    with pytest.raises(cover_frames.CoverError) as exc:
        cc.compose(photo, "3 MITOS", BRAND, out, logo=logo, brand_path=brand_path)
    assert "mesmo arquivo" in str(exc.value)
    assert target.read_bytes() == before


def test_output_cannot_overwrite_input_via_symlink(tmp_path, no_tools):
    photo = _portrait(tmp_path / "foto.png")
    link = tmp_path / "atalho.png"
    link.symlink_to(photo)
    before = photo.read_bytes()
    with pytest.raises(cover_frames.CoverError):
        cc.compose(photo, "3 MITOS", BRAND, link)
    with pytest.raises(cover_frames.CoverError):
        cc.compose(link, "3 MITOS", BRAND, photo)
    assert photo.read_bytes() == before and link.is_symlink()


def test_cli_refuses_out_equal_to_brand(tmp_path, photo):
    b = tmp_path / "brand.json"
    b.write_text(json.dumps(BRAND), "utf-8")
    before = b.read_bytes()
    r = _cli(photo, b, b, "--hook", "3 MITOS")
    assert r.returncode == 1 and "mesmo arquivo" in r.stderr
    assert b.read_bytes() == before


# ---------------------------------------------------------------- CLI

def _cli(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, timeout=120)


def _brand_file(tmp_path, handles) -> Path:
    p = tmp_path / "brand.json"
    p.write_text(json.dumps({**BRAND, "handles": handles}), "utf-8")
    return p


def test_cli_errors_exit_1(tmp_path, photo):
    out = tmp_path / "c.png"
    r = _cli(photo, _brand_file(tmp_path, []), out, "--hook", "3 MITOS")
    assert r.returncode == 1 and "erro:" in r.stderr and "set-handles" in r.stderr
    r = _cli(tmp_path / "sumiu.png", _brand_file(tmp_path, ["@gs"]), out, "--hook", "3 MITOS")
    assert r.returncode == 1 and "não encontrada" in r.stderr
    r = _cli(photo, tmp_path / "nao-ha.json", out, "--hook", "3 MITOS")
    assert r.returncode == 1 and "brand.json" in r.stderr
    assert not out.exists()
    assert "Traceback" not in r.stderr


def test_cli_ok_exit_0(tmp_path, photo):
    _need_browser()
    out = tmp_path / "capa" / "capa.png"
    r = _cli(photo, _brand_file(tmp_path, ["@gutmannesilva"]), out, "--hook", "3 MITOS",
             "--area", "ISENÇÃO DE IR", "--subtitle", "que podem te fazer pagar\\nmais imposto de renda")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(out)
    with Image.open(out) as im:
        assert im.size == (1080, 1920)


def test_cli_subtitle_escape():
    assert cc.cli_text("linha 1\\nlinha 2") == "linha 1\nlinha 2"
    assert cc.cli_text(None) is None


# ---------------------------------------------------------------- brand.py set-handles

def _seed(tmp_path) -> Path:
    p = tmp_path / "brand.json"
    brandmod.write_seed(p)
    return p


def test_set_handles_saves_and_keeps_other_keys(tmp_path, capsys):
    p = _seed(tmp_path)
    before = json.loads(p.read_text("utf-8"))
    brandmod.main(["set-handles", str(p), "gutmannesilva", " @gs.adv "])
    after = json.loads(p.read_text("utf-8"))
    assert after["handles"] == ["@gutmannesilva", "@gs.adv"]
    assert {k: v for k, v in after.items() if k != "handles"} == \
        {k: v for k, v in before.items() if k != "handles"}
    assert brandmod.require_handles(brandmod.load(p)) == ["@gutmannesilva", "@gs.adv"]
    assert "@gutmannesilva" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.tmp"))


def test_set_handles_refuses_empty_and_invalid(tmp_path):
    p = _seed(tmp_path)
    original = p.read_bytes()
    for argv in (["set-handles", str(p)], ["set-handles", str(p), "  "],
                 ["set-handles", str(p), "@gutmann silva"], ["set-handles", str(p), "@ação"],
                 ["set-handles", str(p), "@a", "@b", "@c"]):
        with pytest.raises(SystemExit) as exc:
            brandmod.main(argv)
        assert exc.value.code != 0
    assert p.read_bytes() == original


def test_set_handles_missing_file(tmp_path):
    with pytest.raises(SystemExit) as exc:
        brandmod.main(["set-handles", str(tmp_path / "nao.json"), "@gs"])
    assert exc.value.code == 1
    assert not (tmp_path / "nao.json").exists()


def test_set_handles_cli(tmp_path):
    p = _seed(tmp_path)
    r = subprocess.run([sys.executable, "-I", str(BRAND_SCRIPT), "set-handles", str(p), "@gs"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(p.read_text("utf-8"))["handles"] == ["@gs"]
