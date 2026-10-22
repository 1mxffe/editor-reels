"""Graficos animados (cards) renderizados por Chromium headless, quadro a quadro.

Os testes com navegador/ffmpeg reais sao pulados (com motivo) quando node,
playwright/Chromium ou o libvpx-vp9 do ffmpeg nao existem; os demais (validacao,
integracao com o render via stubs, build_review) rodam sempre.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

import cut
import graphics
import render
import review_apply as ra

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "graphics.py"
BRAND = json.loads((REPO / "brand" / "brand.json").read_text("utf-8"))

WORDS = [("O", 0.20, 0.40), ("prazo", 0.40, 0.80), ("conta", 0.80, 1.10),
         ("em", 1.10, 1.20), ("dias", 1.20, 1.50), ("úteis.", 1.50, 1.90)]


def _spec(**kw):
    base = {"id": "k1", "title": "Prazo em dias úteis", "body": "Conte só os dias úteis.",
            "at": 0.5, "dur": 1.5, "material": None}
    base.update(kw)
    return base


def _jw(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def _project(root: Path, cards=None, revisao=None, duration=3.0, entrada=b"nao e video") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "entrada.mp4").write_bytes(entrada)
    _jw(root / "transcricao.json", {"duration": duration, "words": [
        {"w": w, "start": s, "end": e} for w, s, e in WORDS]})
    _jw(root / "cortes.json", {"cuts": []})
    if cards is not None:
        _jw(root / "graficos.json", {"cards": cards})
    if revisao is not None:
        _jw(root / "revisao.json", revisao)
    return root


def _png(path: Path, size=(64, 48), color=(168, 200, 240, 255)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path)
    return path


@pytest.fixture
def no_tools(monkeypatch):
    """Falha o teste se o navegador, o ffmpeg ou um temporario forem usados."""
    def boom(*a, **k):
        raise AssertionError(f"nao deveria executar nada: {a!r}")
    monkeypatch.setattr(graphics.subprocess, "run", boom)
    monkeypatch.setattr(graphics.subprocess, "Popen", boom)
    monkeypatch.setattr(graphics.tempfile, "mkdtemp", boom)
    monkeypatch.setattr(graphics.tempfile, "TemporaryDirectory", boom)


def _need_renderer():
    reason = graphics.renderer_status()
    if reason:
        pytest.skip(f"renderizador de graficos indisponivel: {reason}")


# ---------------------------------------------------------------- validacao

@pytest.mark.parametrize("patch", [
    {"title": ""}, {"title": "   "}, {"title": "x" * 61}, {"title": 12},
    {"body": "y" * 141}, {"body": 3},
    {"dur": 0.9}, {"dur": 6.1}, {"dur": float("nan")}, {"dur": float("inf")}, {"dur": True},
    {"dur": "2"}, {"at": -0.1}, {"at": float("nan")}, {"at": False},
    {"id": ""}, {"id": 7}, {"material": 5},
    {"material": "../fora.png"}, {"material": "materiais/nao-existe.png"},
    {"material": "materiais/nota.txt"}, {"material": "materiais/falso.png"},
])
def test_invalid_spec_raises_graphics_error(tmp_path, no_tools, patch):
    (tmp_path / "proj" / "materiais").mkdir(parents=True)
    (tmp_path / "proj" / "materiais" / "nota.txt").write_text("texto", "utf-8")
    (tmp_path / "proj" / "materiais" / "falso.png").write_text("nao sou png", "utf-8")
    _png(tmp_path / "fora.png")
    out = tmp_path / "c.webm"
    with pytest.raises(graphics.GraphicsError):
        graphics.render_card(_spec(**patch), BRAND, out, project=tmp_path / "proj")
    assert not out.exists()


def test_missing_id_and_unknown_keys_rejected(tmp_path, no_tools):
    spec = _spec()
    del spec["id"]
    with pytest.raises(graphics.GraphicsError):
        graphics.validate(spec, tmp_path)
    with pytest.raises(graphics.GraphicsError):
        graphics.validate(_spec(cor="vermelho"), tmp_path)
    with pytest.raises(graphics.GraphicsError):
        graphics.validate(["nao", "objeto"], tmp_path)


def test_material_symlink_outside_project_rejected(tmp_path, no_tools):
    proj = tmp_path / "proj"
    (proj / "materiais").mkdir(parents=True)
    (proj / "materiais" / "link.png").symlink_to(_png(tmp_path / "fora.png"))
    with pytest.raises(graphics.GraphicsError):
        graphics.validate(_spec(material="materiais/link.png"), proj)


def test_validate_normalizes(tmp_path):
    _png(tmp_path / "materiais" / "foto.png")
    c = graphics.validate(_spec(body="  ", at=1, material="materiais/foto.png"), tmp_path)
    assert c["body"] is None and c["at"] == 1.0 and isinstance(c["at"], float)
    assert c["material"] == (tmp_path / "materiais" / "foto.png").resolve()
    c2 = graphics.validate(_spec(title="  Prazo em\ndias úteis "), tmp_path)
    assert c2["title"] == "Prazo em\ndias úteis" and c2["body"] == "Conte só os dias úteis."


def test_cli_invalid_spec_exit_1(tmp_path):
    spec = tmp_path / "spec.json"
    out = tmp_path / "c.webm"
    _jw(spec, _spec(dur=9))
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(spec), str(REPO / "brand" / "brand.json"),
                        str(out)], capture_output=True, text=True)
    assert r.returncode == 1 and r.stderr.startswith("erro:") and "Traceback" not in r.stderr
    assert not out.exists()


# ---------------------------------------------------------------- navegador real

def test_card_uses_poppins(tmp_path):
    _need_renderer()
    info = graphics.inspect_card(_spec(), BRAND, project=tmp_path, size=(540, 960))
    assert info["titleFont"].replace('"', "").startswith("Poppins")
    assert info["bodyFont"].replace('"', "").startswith("Poppins")
    assert info["titleWeight"] == "800" and info["bodyWeight"] == "400"


def test_title_markup_is_inert(tmp_path):
    _need_renderer()
    title = '"Aspas" <img src=x onerror="window.__xss=1">'
    info = graphics.inspect_card(_spec(title=title, body="<b>negrito?</b> & 'aspas'"), BRAND,
                                 project=tmp_path, size=(540, 960))
    assert info["xss"] is None
    assert info["titleText"] == title and info["bodyText"] == "<b>negrito?</b> & 'aspas'"
    assert info["imgCount"] == 0


def test_long_word_wraps_inside_safe_area(tmp_path):
    _need_renderer()
    _png(tmp_path / "materiais" / "foto.png", size=(400, 300))
    shot = tmp_path / "shot.png"
    spec = _spec(title="A" * 60, body=("palavra " * 18)[:140], material="materiais/foto.png")
    info = graphics.inspect_card(spec, BRAND, project=tmp_path, size=(1080, 1920), shot=shot)
    assert info["titleScroll"] <= info["titleClient"]  # quebrou, nao estourou
    box = info["card"]
    assert box["top"] >= graphics.SAFE_TOP and box["bottom"] <= 1920 - graphics.SAFE_BOTTOM
    assert box["left"] >= 0 and box["right"] <= 1080
    assert info["imgCount"] == 1 and info["imgLoaded"] is True
    im = Image.open(shot)
    assert im.size == (1080, 1920)
    l, t, r, b = im.getchannel("A").getbbox()
    assert t >= graphics.SAFE_TOP and b <= 1920 - graphics.SAFE_BOTTOM
    assert l >= 40 and r <= 1080 - 40


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    reason = graphics.renderer_status()
    if reason:
        pytest.skip(f"renderizador de graficos indisponivel: {reason}")
    d = tmp_path_factory.mktemp("clip")
    out = graphics.render_card(_spec(dur=1.2), BRAND, d / "card.webm", project=d, size=(540, 960))
    frames = d / "frames"
    frames.mkdir()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-c:v", "libvpx-vp9", "-i", str(out),
                    "-pix_fmt", "rgba", str(frames / "f%03d.png")], check=True)
    return out, sorted(frames.glob("f*.png"))


def test_card_duration_matches_spec(clip):
    out, frames = clip
    assert not out.with_name(out.name + ".tmp").exists()
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,pix_fmt:"
         "stream_tags=alpha_mode", "-of", "json", str(out)],
        check=True, capture_output=True, text=True).stdout)
    assert abs(float(probe["format"]["duration"]) - 1.2) <= 1 / 30 + 1e-6
    st = probe["streams"][0]
    assert st["codec_name"] == "vp9" and (st["width"], st["height"]) == (540, 960)
    assert st["pix_fmt"] == "yuva420p" or st.get("tags", {}).get("alpha_mode") == "1"
    assert len(frames) == 36


def _alpha_sum(path: Path) -> int:
    hist = Image.open(path).getchannel("A").histogram()
    return sum(i * n for i, n in enumerate(hist))


def test_entrance_full_by_350ms_and_exit_to_zero(clip):
    _, frames = clip
    a = [_alpha_sum(f) for f in frames]
    hold = a[18]
    assert hold > 0
    assert a[0] <= hold * 0.002                       # comeca invisivel
    assert a[4] < hold * 0.97                         # ainda entrando
    assert a[math.ceil(0.35 * 30)] >= hold * 0.99     # cheio em 350 ms
    assert all(abs(x - hold) <= hold * 0.01 for x in a[11:26])  # segura parado
    assert a[-4] < hold * 0.97                        # saindo
    assert a[-1] <= hold * 0.002                      # termina invisivel


# ---------------------------------------------------------------- render (stubs)

@pytest.fixture
def stub_pipeline(monkeypatch):
    calls = {"run": [], "clips": []}

    def fake_apply(video, cuts, out):
        Path(out).write_bytes(b"corte")

    def fake_run(cmd):
        calls["run"].append(cmd)
        Path(cmd[-1]).write_bytes(b"mp4")
        return ""

    def fake_clip(card, brand, out, *, size=graphics.CANVAS):
        calls["clips"].append({"card": card, "out": Path(out), "size": size})
        Path(out).write_bytes(b"webm")
        return Path(out)

    monkeypatch.setattr(cut, "apply", fake_apply)
    monkeypatch.setattr(render, "_has_audio", lambda video: True)
    monkeypatch.setattr(render.common, "run", fake_run)
    monkeypatch.setattr(graphics, "render_clip", fake_clip)
    monkeypatch.setattr(graphics, "renderer_status", lambda: None)
    return calls


def test_render_overlays_cards_before_subtitles(tmp_path, stub_pipeline):
    proj = _project(tmp_path / "p", cards=[_spec(id="k1", at=0.5, dur=1.5),
                                           _spec(id="k2", title="Outro card", body=None, at=1.2, dur=1.0)])
    render.render(proj, "preview")
    [cmd] = stub_pipeline["run"]
    assert "-vf" not in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "setpts=PTS-STARTPTS+0.500/TB" in fc and "setpts=PTS-STARTPTS+1.200/TB" in fc
    assert "enable='between(t,0.500,2.000)'" in fc and "enable='between(t,1.200,2.200)'" in fc
    assert fc.rindex("overlay=") < fc.index("subtitles=")
    assert fc.index("subtitles=") > fc.rindex("[b2]")
    assert cmd[cmd.index("-map") + 1] == "[vout]"
    for c in stub_pipeline["clips"]:
        i = cmd.index(str(c["out"]))
        assert cmd[i - 3:i] == ["-c:v", "libvpx-vp9", "-i"]
        assert c["size"] == (540, 960)
    assert [c["card"]["id"] for c in stub_pipeline["clips"]] == ["k1", "k2"]
    assert sorted(p.name for p in (proj / "saida").iterdir()) == ["preview.mp4"]  # temporarios limpos


def test_render_without_cards_keeps_plain_filter(tmp_path, stub_pipeline):
    proj = _project(tmp_path / "p")
    render.render(proj, "preview")
    [cmd] = stub_pipeline["run"]
    assert "-vf" in cmd and "-filter_complex" not in cmd
    assert stub_pipeline["clips"] == []


def test_dropped_card_is_not_rendered(tmp_path, stub_pipeline):
    proj = _project(tmp_path / "p", cards=[_spec(id="k1"), _spec(id="k2", title="Fica", at=1.0)],
                    revisao={"removed_cuts": [], "graphics": {"k1": "drop", "k2": "keep"}, "notes": []})
    render.render(proj, "final")
    assert [c["card"]["id"] for c in stub_pipeline["clips"]] == ["k2"]
    assert stub_pipeline["clips"][0]["size"] == (1080, 1920)


def test_card_text_is_rendered_as_written(tmp_path, stub_pipeline):
    # o escritorio revisa o texto antes de gravar: o editor nao confere conteudo
    proj = _project(tmp_path / "p", cards=[_spec(id="k1", title="Garantimos o resultado",
                                                 body="Ligue agora e resolvemos o seu caso")])
    render.render(proj, "preview")
    [clip] = stub_pipeline["clips"]
    assert clip["card"]["title"] == "Garantimos o resultado"
    assert sorted(p.name for p in (proj / "saida").iterdir()) == ["preview.mp4"]


def test_card_beyond_video_is_clipped_or_ignored(tmp_path, stub_pipeline, capsys):
    proj = _project(tmp_path / "p", cards=[_spec(id="fora", at=50.0), _spec(id="curto", at=2.5, dur=1.0),
                                           _spec(id="corta", at=1.5, dur=3.0)])
    render.render(proj, "preview")
    clips = {c["card"]["id"]: c["card"] for c in stub_pipeline["clips"]}
    assert set(clips) == {"corta"}
    assert clips["corta"]["dur"] == pytest.approx(1.5)  # 3.0 s de video - 1.5
    err = capsys.readouterr().err
    assert "fora" in err and "curto" in err and "corta" in err


def test_renderer_missing_names_card_and_writes_nothing(tmp_path, stub_pipeline, monkeypatch, capsys):
    monkeypatch.setattr(graphics, "renderer_status", lambda: "node ausente")
    proj = _project(tmp_path / "p", cards=[_spec(id="k7")])
    with pytest.raises(graphics.RendererMissing) as exc:
        render.render(proj, "preview")
    assert "k7" in str(exc.value) and "node ausente" in str(exc.value)
    assert not (proj / "saida").exists()
    with pytest.raises(SystemExit) as se:
        render.main([str(proj), "preview"])
    assert se.value.code == 1 and "k7" in capsys.readouterr().err


@pytest.mark.parametrize("doc", [
    {"cards": "nao lista"}, [], {"cards": [_spec(id="a"), _spec(id="a", at=2)]},
    {"cards": [_spec(dur=0)]}, {"cards": [_spec(material="materiais/sumiu.png")]},
])
def test_invalid_graficos_json_fails_before_saida(tmp_path, stub_pipeline, doc):
    proj = _project(tmp_path / "p")
    _jw(proj / "graficos.json", doc)
    with pytest.raises((render.ProjectError, graphics.GraphicsError)):
        render.render(proj, "preview")
    assert not (proj / "saida").exists()


def test_clip_failure_cleans_temps(tmp_path, stub_pipeline, monkeypatch):
    def broken(card, brand, out, *, size=graphics.CANVAS):
        Path(out).write_bytes(b"parcial")
        raise graphics.GraphicsError("falhou no navegador")
    monkeypatch.setattr(graphics, "render_clip", broken)
    proj = _project(tmp_path / "p", cards=[_spec()])
    with pytest.raises(graphics.GraphicsError):
        render.render(proj, "preview")
    assert list((proj / "saida").iterdir()) == []


# ---------------------------------------------------------------- render real

def test_render_preview_shows_card(tmp_path):
    _need_renderer()
    video = tmp_path / "cinza.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=0x808080:size=540x960:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)],
                   check=True)
    proj = _project(tmp_path / "p", cards=[_spec(at=0.3, dur=1.5)], entrada=video.read_bytes())
    out = render.render(proj, "preview")
    assert sorted(p.name for p in (proj / "saida").iterdir()) == ["preview.mp4"]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(out)], check=True, capture_output=True,
                               text=True).stdout)
    assert abs(dur - 3.0) < 0.15

    def region(t):
        png = tmp_path / f"f{t}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t}", "-i", str(out),
                        "-frames:v", "1", str(png)], check=True)
        # faixa do card (terco superior, dentro da zona segura), longe das legendas
        return Image.open(png).convert("L").crop((60, 170, 480, 330))

    def mean(im):
        hist = im.histogram()
        return sum(i * n for i, n in enumerate(hist)) / sum(hist)

    with_card, after = region(1.2), region(2.5)
    assert abs(mean(after) - 128) < 8          # sem card: cinza do video
    assert abs(mean(with_card) - mean(after)) > 25  # card azul-marinho por cima


# ---------------------------------------------------------------- revisao

def test_build_review_exposes_cards(tmp_path):
    proj = _project(tmp_path / "p", cards=[_spec(id="k2", title="Segundo", at=2.0),
                                           _spec(id="k1", title="Primeiro", at=0.5, dur=2.0)],
                    revisao={"removed_cuts": [], "graphics": {"k2": "drop"}, "notes": []})
    r = ra.build_review(proj)
    assert r["graphics"] == {"k2": "drop"}  # forma antiga preservada
    assert r["cards"] == [
        {"id": "k1", "title": "Primeiro", "at": 0.5, "dur": 2.0, "decision": "keep"},
        {"id": "k2", "title": "Segundo", "at": 2.0, "dur": 1.5, "decision": "drop"},
    ]
    assert ra.build_review(_project(tmp_path / "vazio"))["cards"] == []


def test_card_line_breaks_are_kept(tmp_path, no_tools):
    c = graphics.validate(_spec(title="Prazo em\ndias úteis", body="\n".join("abcdefghijkl")), tmp_path)
    assert c["title"] == "Prazo em\ndias úteis" and c["body"].count("\n") == 11


# ---- onda final, item 15 (M15): a saida da CLI nunca e o spec nem o brand.json ----
def test_cli_refuses_output_equal_to_spec_or_brand(tmp_path):
    spec = tmp_path / "spec.json"
    _jw(spec, _spec())
    brand = tmp_path / "brand.json"
    brand.write_text((REPO / "brand" / "brand.json").read_text("utf-8"), "utf-8")
    link = tmp_path / "saida.webm"
    link.symlink_to(brand)
    before = {p: p.read_bytes() for p in (spec, brand)}
    for out in (spec, brand, link, tmp_path / "." / "spec.json"):
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(spec), str(brand), str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 1 and "mesmo arquivo" in r.stderr, (out, r.stderr)
    assert {p: p.read_bytes() for p in (spec, brand)} == before and link.is_symlink()
