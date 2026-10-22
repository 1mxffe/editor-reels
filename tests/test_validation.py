"""Entrada malformada vira erro claro (codigo 1), nunca traceback, e numero so vale
se for finito (o json do Python aceita NaN e Infinity)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import common
import cut
import graphics
import render
import review_apply as ra

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
WORDS = [{"w": "Prazo", "start": 0.5, "end": 0.9}, {"w": "certo.", "start": 0.9, "end": 1.4}]


def _jw(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "reel"
    p.mkdir()
    (p / "entrada.mp4").write_bytes(b"x")
    _jw(p / "transcricao.json", {"duration": 3.0, "words": WORDS})
    _jw(p / "cortes.json", {"cuts": [{"id": "c1", "start": 0.0, "end": 0.4, "kind": "silence"}]})
    return p


@pytest.mark.parametrize("x,ok", [(1, True), (1.5, True), (0, True), (-2, True), (True, False),
                                  (float("nan"), False), (float("inf"), False), (float("-inf"), False),
                                  ("1", False), (None, False)])
def test_is_num(x, ok):
    assert common.is_num(x) is ok


@pytest.mark.parametrize("bad", [[["c1"]], [{"id": "c1"}], [1], [None]])
def test_non_string_cut_id_is_review_error(proj, bad):
    with pytest.raises(ra.ReviewError, match="id de corte"):
        ra.apply(proj, {"cuts_removed": bad})


@pytest.mark.parametrize("entry", ["c3", 3, None, ["c3"], {"id": "c3"}, {"id": "c3", "start": "a", "end": 1},
                                   {"id": "c3", "start": float("nan"), "end": 1}])
def test_malformed_removed_cuts_entry_is_clear_error(proj, tmp_path, entry):
    _jw(proj / "revisao.json", {"removed_cuts": [entry], "graphics": {}, "notes": []})
    with pytest.raises(ra.ReviewError, match="removed_cuts"):
        ra.apply(proj, {"notes": []})
    with pytest.raises(render.ProjectError, match="removed_cuts"):
        ra.build_review(proj)
    dec = tmp_path / "d.json"
    _jw(dec, {"notes": []})
    for args in (["apply", proj, dec], ["build", proj]):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "review_apply.py"), *map(str, args)],
                           capture_output=True, text=True)
        assert r.returncode == 1 and "removed_cuts" in r.stderr and "Traceback" not in r.stderr


@pytest.mark.parametrize("doc,name", [
    ({"duration": float("nan"), "words": WORDS}, "transcricao.json"),
    ({"duration": float("inf"), "words": WORDS}, "transcricao.json"),
    ({"duration": 3.0, "words": [{"w": "a", "start": float("nan"), "end": 1}]}, "transcricao.json"),
    ({"cuts": [{"id": "c1", "start": 0, "end": float("inf")}]}, "cortes.json"),
    ({"cuts": [{"id": "c1", "start": float("nan"), "end": 1}]}, "cortes.json"),
])
def test_render_rejects_nan_and_inf(proj, doc, name):
    (proj / name).write_text(json.dumps(doc), "utf-8")  # json.dumps grava NaN/Infinity
    with pytest.raises(render.ProjectError):
        render.render(proj, "preview")
    assert not (proj / "saida").exists()
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "render.py"), str(proj), "preview"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr


@pytest.mark.parametrize("doc", [{"duration": float("nan"), "words": WORDS},
                                 {"duration": 3.0, "words": [{"w": "a", "start": 0, "end": float("inf")}]}])
def test_cut_detect_rejects_nan_and_inf(tmp_path, doc):
    t = tmp_path / "t.json"
    t.write_text(json.dumps(doc), "utf-8")
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "cut.py"), "detect", str(t), str(tmp_path / "c.json")],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert not (tmp_path / "c.json").exists()


def test_cut_validate_cuts_rejects_inf():
    with pytest.raises(SystemExit):
        cut._validate_cuts([{"start": 0, "end": float("inf")}])


def test_captions_cli_rejects_nan_words(tmp_path):
    w = tmp_path / "w.json"
    w.write_text(json.dumps({"words": [{"w": "Oi.", "start": float("nan"), "end": 1}]}), "utf-8")
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"accent": "#a8c8f0", "bg": "#001931", "fg": "#ddebf5", "muted": "#566a7a",
                             "font_title": "Poppins", "font_body": "Poppins", "handles": [],
                             "caption_style": "static-phrase"}), "utf-8")
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "captions.py"), str(w), str(b), str(tmp_path / "o.ass")],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "palavra 0" in r.stderr and not (tmp_path / "o.ass").exists()


def test_graphics_uses_shared_is_num(tmp_path):
    with pytest.raises(graphics.GraphicsError):
        graphics.validate({"id": "k", "title": "t", "body": None, "at": float("nan"), "dur": 1,
                           "material": None}, tmp_path)
