"""Revisao de cortes e legendas: chama scripts/review_apply.py por subprocesso.

O motor nunca e importado no processo do servidor. Caminhos vem so de
``Projects.path(slug)``; as decisoes viram um arquivo temporario (nome gerado)
dentro do projeto, removido no ``finally``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "review_apply.py"
TIMEOUT = 120
MAX_DECISOES = 1024 * 1024
CHAVES = {"cuts_removed", "cuts_added", "caption_edits", "graphics", "notes"}
TIPOS = {"cuts_removed": list, "cuts_added": list, "caption_edits": dict,
         "graphics": dict, "notes": list}

_travas: dict[str, threading.Lock] = {}
_travas_mu = threading.Lock()


class RevisaoErro(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status
        self.msg = msg


def trava(slug: str) -> threading.Lock:
    with _travas_mu:
        return _travas.setdefault(slug, threading.Lock())



def validar(decisoes) -> dict:
    if not isinstance(decisoes, dict):
        raise RevisaoErro(400, "as decisões devem ser um objeto JSON")
    desconhecidas = set(decisoes) - CHAVES
    if desconhecidas:
        raise RevisaoErro(400, "chaves desconhecidas nas decisões: "
                               + ", ".join(sorted(map(str, desconhecidas))))
    for k, v in decisoes.items():
        if not isinstance(v, TIPOS[k]):
            raise RevisaoErro(400, f"'{k}' deve ser {'uma lista' if TIPOS[k] is list else 'um objeto'}")
    return decisoes


def _erro_do_script(stderr: str) -> str:
    for linha in (stderr or "").splitlines():
        if linha.startswith("erro:"):
            return linha[len("erro:"):].strip()[:500] or "revisão inválida"
    return "não foi possível processar a revisão"


def _rodar(args: list[str]) -> None:
    cmd = [sys.executable, "-I", str(SCRIPT), *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT,
                           cwd=REPO_ROOT, shell=False)
    except subprocess.TimeoutExpired:
        raise RevisaoErro(500, "a revisão excedeu o tempo limite") from None
    except OSError:
        raise RevisaoErro(500, "não foi possível executar a revisão") from None
    if p.returncode != 0:
        raise RevisaoErro(400, _erro_do_script(p.stderr))


def _build(d: Path) -> dict:
    if not (d / "transcricao.json").is_file():
        raise RevisaoErro(409, "transcreva o vídeo primeiro")
    _rodar(["build", str(d)])
    try:
        return json.loads((d / "review.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RevisaoErro(500, "não foi possível ler a revisão gerada") from None


def construir(d: Path) -> dict:
    return _build(d)


def aplicar(d: Path, decisoes: dict) -> dict:
    if not (d / "transcricao.json").is_file():
        raise RevisaoErro(409, "transcreva o vídeo primeiro")
    fd, nome = _tmp(d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(decisoes, f, ensure_ascii=False)
        _rodar(["apply", str(d), nome])
    finally:
        try:
            os.unlink(nome)
        except OSError:
            pass
    return _build(d)


def _tmp(d: Path):
    import tempfile
    return tempfile.mkstemp(dir=d, prefix=".decisoes-", suffix=".tmp")
