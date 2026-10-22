"""Contrato de saida de todas as CLIs: 0 ok, 1 para todo erro (inclusive erro de uso)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import common

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
BRAND = REPO / "brand" / "brand.json"


def _run(script, *args, cwd=None):
    return subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd)


USAGE_ERRORS = [
    ("render.py", ()), ("render.py", ("proj", "prevew")), ("render.py", ("proj", "preview", "--x")),
    ("graphics.py", ()), ("graphics.py", ("a", "b", "c", "--size", "enorme")),
    ("cover_frames.py", ()), ("cover_frames.py", ("video",)), ("cover_frames.py", ("filme", "a", "b")),
    ("cover_frames.py", ("video", "v.mp4", "out", "--n", "tres")),
    ("transcribe.py", ()), ("transcribe.py", ("v.mp4", "o.json", "--modelo", "x")),
    ("cover_compose.py", ()), ("cover_compose.py", ("foto.png",)),
    ("cover_compose.py", ("foto.png", "b.json")),
    ("brand.py", ()), ("brand.py", ("semear", "x.json")), ("brand.py", ("set-handles",)),
    ("brand.py", ("set-handles", "b.json")), ("brand.py", ("check",)),
    ("captions.py", ()), ("captions.py", ("a", "b")),
    ("cut.py", ()), ("cut.py", ("detectar", "a", "b")), ("cut.py", ("apply", "a")),
    ("review_apply.py", ()), ("review_apply.py", ("apply", "p")), ("review_apply.py", ("aplicar", "p", "d")),
]


@pytest.mark.parametrize("script,args", USAGE_ERRORS, ids=lambda x: " ".join(x) if isinstance(x, tuple) else x)
def test_usage_error_exits_1(tmp_path, script, args):
    r = _run(script, *args, cwd=tmp_path)
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert "erro:" in r.stderr and "Traceback" not in r.stderr
    assert list(tmp_path.iterdir()) == []  # erro de uso nao grava nada


def _project(root: Path, words, cards=None) -> Path:
    root.mkdir()
    (root / "entrada.mp4").write_bytes(b"nao e video")
    (root / "transcricao.json").write_text(json.dumps({"duration": 3.0, "words": [
        {"w": w, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, w in enumerate(words)]}), "utf-8")
    (root / "cortes.json").write_text(json.dumps({"cuts": []}), "utf-8")
    if cards is not None:
        (root / "graficos.json").write_text(json.dumps({"cards": cards}), "utf-8")
    return root


def test_text_content_never_changes_the_exit_code(tmp_path):
    """Nenhuma CLI confere o conteudo do texto: so 0 (ok) ou 1 (erro de verdade)."""
    proj = _project(tmp_path / "p", ["Garantimos", "o", "resultado."])
    dec = tmp_path / "d.json"
    dec.write_text(json.dumps({"caption_edits": {"0": "Ligue agora e garantimos o resultado"}}), "utf-8")
    assert _run("review_apply.py", "apply", proj, dec).returncode == 0
    r = _run("render.py", proj, "preview")  # entrada falsa: falha no ffmpeg, nao no texto
    assert r.returncode == 1 and "erro:" in r.stderr
    card = {"id": "k1", "title": "Garantimos o resultado", "body": None, "at": 0, "dur": 1, "material": None}
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(card), "utf-8")
    r = _run("graphics.py", spec, BRAND, tmp_path / "c.webm", "--size", "preview")
    assert r.returncode in (0, 1), r.stderr  # 1 so sem renderizador nesta maquina
    assert (r.returncode == 0) == (tmp_path / "c.webm").is_file()
    brand = tmp_path / "brand.json"
    brand.write_text(json.dumps({**json.loads(BRAND.read_text("utf-8")), "handles": ["@gs"]}), "utf-8")
    r = _run("cover_compose.py", tmp_path / "sumiu.png", brand, tmp_path / "c.png", "--hook", "GARANTIMOS")
    assert r.returncode == 1 and "não encontrada" in r.stderr


def test_usage_parser_error_exits_1(capsys):
    p = common.UsageParser(prog="x")
    p.add_argument("a")
    with pytest.raises(SystemExit) as e:
        p.parse_args([])
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("usage: x") and "erro:" in err
    with pytest.raises(SystemExit) as e:
        p.parse_args(["--help"])
    assert e.value.code == 0
