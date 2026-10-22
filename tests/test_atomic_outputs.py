"""Saidas gravadas por common.atomic_write: modo normal (0666 & ~umask, nao 0600 do
mkstemp), nome temporario unico no mesmo diretorio, nada sobra em falha."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

import brand as brandmod
import captions
import cover_compose as cc
import cover_frames
import cut
import graphics
import render

REPO = Path(__file__).resolve().parent.parent
BRAND = {**json.loads((REPO / "brand" / "brand.json").read_text("utf-8")), "handles": ["@gutmannesilva"]}


@pytest.fixture(autouse=True)
def umask022():
    old = os.umask(0o022)
    yield
    os.umask(old)


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def _no_tmp(d: Path) -> bool:
    return not [p for p in d.rglob("*") if ".tmp" in p.name]


def _project(root: Path) -> Path:
    root.mkdir()
    (root / "entrada.mp4").write_bytes(b"nao e video")
    (root / "transcricao.json").write_text(json.dumps({"duration": 3.0, "words": [
        {"w": "Prazo", "start": 0.2, "end": 0.6}, {"w": "certo.", "start": 0.6, "end": 1.0}]}), "utf-8")
    (root / "cortes.json").write_text(json.dumps({"cuts": []}), "utf-8")
    return root


@pytest.mark.parametrize("quality", ["preview", "final"])
def test_render_output_mode(tmp_path, monkeypatch, quality):
    monkeypatch.setattr(cut, "apply", lambda video, cuts, out: Path(out).write_bytes(b"corte"))
    monkeypatch.setattr(render, "_has_audio", lambda video: True)

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"mp4")
        return ""
    monkeypatch.setattr(render.common, "run", fake_run)
    proj = _project(tmp_path / "p")
    out = render.render(proj, quality)
    assert out == proj / "saida" / f"{quality}.mp4" and _mode(out) == 0o644
    assert sorted(p.name for p in (proj / "saida").iterdir()) == [f"{quality}.mp4"]


def test_cover_output_mode(tmp_path, monkeypatch):
    photo = tmp_path / "foto.png"
    Image.new("RGB", (1080, 1920), (120, 110, 100)).save(photo)

    def fake_page(data, workdir, shot):
        Image.new("RGB", cc.CANVAS, (0, 25, 49)).save(shot)
        return {"hookLines": 1, "boxes": {}}
    monkeypatch.setattr(cc, "_need_browser", lambda: None)
    monkeypatch.setattr(cc, "_run_page", fake_page)
    out = cc.compose(photo, "3 MITOS", BRAND, tmp_path / "capa" / "capa.png")
    assert _mode(out) == 0o644 and _no_tmp(tmp_path)


def test_cover_frames_outputs_mode(tmp_path, make_sample):
    photo = tmp_path / "in.png"
    Image.new("RGB", (800, 800), (120, 110, 100)).save(photo)
    dest = cover_frames.from_photo(photo, tmp_path / "capa")
    assert _mode(dest) == 0o644
    paths = cover_frames.candidates(make_sample, tmp_path / "capa", n=2)
    assert paths and all(_mode(p) == 0o644 for p in paths) and _no_tmp(tmp_path)


def test_cut_apply_output_mode(tmp_path, make_sample):
    out = tmp_path / "cortado.mp4"
    cut.apply(make_sample, [{"start": 2.5, "end": 3.5}], out)
    assert _mode(out) == 0o644 and _no_tmp(tmp_path)


def test_graphics_clip_output_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(graphics, "_drive", lambda job, workdir, what, driver=None: {})

    def fake_run(cmd, what, *, env=None, timeout=None):
        Path(cmd[-1]).write_bytes(b"webm")
        return ""
    monkeypatch.setattr(graphics, "_run", fake_run)
    card = graphics.validate({"id": "k1", "title": "Prazo", "body": None, "at": 0, "dur": 1,
                              "material": None}, tmp_path)
    out = graphics.render_clip(card, BRAND, tmp_path / "k1.webm")
    assert _mode(out) == 0o644 and _no_tmp(tmp_path)


def test_captions_cli_output_mode(tmp_path):
    words = tmp_path / "w.json"
    words.write_text(json.dumps({"words": [{"w": "Oi.", "start": 0, "end": 0.5}]}), "utf-8")
    b = tmp_path / "brand.json"
    b.write_text(json.dumps(brandmod.seed_from_guide()), "utf-8")
    out = tmp_path / "out.ass"
    r = subprocess.run([sys.executable, "-I", str(REPO / "scripts" / "captions.py"), str(words), str(b),
                        str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _mode(out) == 0o644 and _no_tmp(tmp_path)


def test_fixed_tmp_names_are_gone():
    """Nenhum script grava num "<saida>.tmp" de nome fixo (seguiria link plantado)."""
    for f in (REPO / "scripts").glob("*.py"):
        src = f.read_text("utf-8")
        assert '.name + ".tmp' not in src and 'png.tmp"' not in src, f.name
