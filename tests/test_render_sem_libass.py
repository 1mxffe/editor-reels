"""Legendas por imagem: caminho alternativo quando o ffmpeg nao tem o filtro subtitles."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops

import captions
import common
import cut
import doctor
import legendas_imagem
import render
from test_render import CLEAN_WORDS, CUTS, _frame, _make_project, _probe_streams, _size

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


@pytest.fixture
def static_sample(tmp_path):
    out = tmp_path / "static.mp4"
    _ffmpeg("-f", "lavfi", "-i", "color=c=0x808080:size=1080x1920:rate=30:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out)
    return out


@pytest.fixture
def sem_libass(monkeypatch):
    """Forca a deteccao 'sem subtitles' e grava os comandos ffmpeg do render."""
    monkeypatch.setattr(render, "has_libass", lambda: False)
    cmds, pngs = [], []
    real_run = common.run

    def spy(cmd):
        cmds.append(list(cmd))
        if "concat" in cmd:
            track = Path(cmd[cmd.index("concat") + 4])
            pngs.extend(Image.open(p).size for p in sorted(track.parent.glob("frase-*.png")))
            cmds[-1].append(("roteiro", track.read_text("utf-8"), track.parent))
        return real_run(cmd)

    monkeypatch.setattr(render.common, "run", spy)
    return cmds, pngs


def _filter_args(cmd):
    return [a for a in cmd if isinstance(a, str)]


def test_preview_sem_libass_gera_legenda_sem_filtro_subtitles(tmp_path, static_sample, sem_libass):
    cmds, pngs = sem_libass
    proj = _make_project(tmp_path, static_sample, CLEAN_WORDS)
    out = render.render(proj, "preview")
    assert _size(out) == (540, 960)
    dur = float(_probe_streams(out)["video"]["duration"])
    assert abs(dur - (6.0 - 0.8)) < 0.15
    [cmd] = [c for c in cmds if c and c[0] == "ffmpeg" and "concat" in c]
    joined = " ".join(_filter_args(cmd))
    assert "subtitles=" not in joined and "ass=" not in joined
    assert "overlay" in joined
    roteiro, tmpdir = cmd[-1][1], cmd[-1][2]
    assert "subtitles" not in roteiro
    assert not tmpdir.exists()  # temporario removido
    assert pngs == [(540, 960), (540, 960)]
    ph = captions.phrases(captions.remap(
        json.loads((proj / "transcricao.json").read_text("utf-8"))["words"],
        cut.keep_segments(6.0, CUTS)))
    first = ph[0]
    a = _frame(out, (first["start"] + first["end"]) / 2, tmp_path / "mid.png")
    b = _frame(out, first["start"] / 2, tmp_path / "fora.png")
    c = _frame(out, first["start"] / 4, tmp_path / "fora2.png")
    w, h = a.size
    band = (0, h * 2 // 3, w, h)
    diff = ImageChops.difference(a.crop(band), b.crop(band))
    assert max(hi for _, hi in diff.getextrema()) > 60
    calm = ImageChops.difference(b.crop(band), c.crop(band))
    assert max(hi for _, hi in calm.getextrema()) < 12
    assert [p.name for p in (proj / "saida").iterdir()] == ["preview.mp4"]


def test_png_tamanho_exato_e_transparente(tmp_path):
    b = {"fg": "#ddebf5", "bg": "#001931", "font_body": "Poppins"}
    for size in ((540, 960), (1080, 1920)):
        img = legendas_imagem.draw("Olá, mundo", b, size)
        assert img.size == size and img.mode == "RGBA"
        assert img.getpixel((0, 0))[3] == 0


def test_com_libass_comando_igual_ao_atual(tmp_path, monkeypatch):
    from test_render import _proj_words, _w
    calls = []
    monkeypatch.setattr(cut, "apply", lambda v, c, o: Path(o).write_bytes(b"x"))
    monkeypatch.setattr(render, "_has_audio", lambda v: True)
    monkeypatch.setattr(render, "has_libass", lambda: True)

    def fake_run(cmd):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"mp4")
        return ""
    monkeypatch.setattr(render.common, "run", fake_run)
    proj = _proj_words(tmp_path, _w(CLEAN_WORDS))
    render.render(proj, "preview")
    [cmd] = calls
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith(render._base_filter((540, 960)) + ",subtitles=filename=")
    assert "concat" not in cmd and "-filter_complex" not in cmd
    assert cmd[:6] == ["ffmpeg", "-y", "-loglevel", "error", "-i", cmd[5]]


def test_frase_longa_ate_duas_linhas_dentro_das_margens():
    text = ("Esta é uma frase propositalmente muito comprida para testar a quebra "
            "automática em no máximo duas linhas")
    for size in ((540, 960), (1080, 1920)):
        font, _, _, lines, m = legendas_imagem.layout(text, size)
        assert 1 <= len(lines) <= 2
        assert " ".join(lines) == captions.display_text(text)
        for line in lines:
            assert font.getlength(line) <= size[0] - 2 * m["mlr"]


def test_sessenta_frases_e_caracteres_especiais(tmp_path, static_sample, sem_libass):
    cmds, pngs = sem_libass
    specials = ["ação", "R$ 1.000,00", "{chaves}", "barra\\", "aspas'\"", "emoji 😀", "100%", "a:b;c"]
    words = []
    for i in range(60):
        t = 0.05 + i * 0.09
        words.append((f"{specials[i % len(specials)]}{i}.", t, t + 0.08))
    proj = _make_project(tmp_path, static_sample, words, cuts=[])
    out = render.render(proj, "preview")
    assert _size(out) == (540, 960)
    assert len(pngs) == 60


def test_deteccao(monkeypatch):
    class P:
        returncode = 0
        stdout = (" ... ass               V->V       Render ASS\n"
                  " TSC overlay           VV->V      Overlay\n")
    monkeypatch.setattr(common, "_FILTERS_CACHE", {})
    monkeypatch.setattr(common.subprocess, "run", lambda *a, **k: P())
    assert common.ffmpeg_has_libass() is False  # sem subtitles
    monkeypatch.setattr(common, "_FILTERS_CACHE", {})
    P.stdout += " ... subtitles         V->V       Render text\n"
    assert common.ffmpeg_has_libass() is True
    # cache por processo: nao consulta de novo
    monkeypatch.setattr(common.subprocess, "run", lambda *a, **k: 1 / 0)
    assert common.ffmpeg_has_libass() is True


@pytest.mark.parametrize("exc", [FileNotFoundError("ffmpeg"), subprocess.TimeoutExpired("ffmpeg", 15)])
def test_deteccao_falhando_assume_caminho_atual(monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(common, "_FILTERS_CACHE", {})
    monkeypatch.setattr(common.subprocess, "run", boom)
    assert common.ffmpeg_has_libass() is True


def test_sem_pillow_erro_claro(tmp_path, monkeypatch, capsys):
    import builtins
    real = builtins.__import__

    def no_pil(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError(name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_pil)
    with pytest.raises(legendas_imagem.PillowMissing, match="pip install Pillow"):
        legendas_imagem.draw("oi", {"fg": "#ffffff", "bg": "#000000"}, (540, 960))


def test_doctor_sem_libass_e_informativo(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor, "_has_whisper", lambda: True)
    monkeypatch.setattr(doctor, "_free_gb", lambda path=".": 100.0)
    monkeypatch.setattr(doctor, "_graphics_reason", lambda: None)
    monkeypatch.setattr(doctor, "_has_pillow", lambda: True)
    monkeypatch.setattr(doctor, "_has_libass", lambda: False)
    status, items = doctor.check()
    assert status == "READY"
    [leg] = [i for i in items if i["name"] == doctor.LEGENDAS_ITEM]
    assert leg["ok"] is False and leg["required"] is False
    assert "legendas por imagem" in leg["detail"]
    monkeypatch.setattr(doctor, "_has_libass", lambda: True)
    status, items = doctor.check()
    assert status == "READY"
    assert [i for i in items if i["name"] == doctor.LEGENDAS_ITEM][0]["ok"] is True
    import instalacao
    t = instalacao.traduzir("READY", [{**leg}])
    assert t["itens"][0]["mensagem"] == "Legendas: usando o modo alternativo — tudo certo"
