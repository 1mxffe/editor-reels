"""Revisao de cortes e legendas: chama scripts/review_apply.py por subprocesso.

O motor nunca e importado no processo do servidor. Caminhos vem so de
``Projects.path(slug)``; as decisoes viram um arquivo temporario (nome gerado)
dentro do projeto, removido no ``finally``.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "review_apply.py"
TIMEOUT = 120
ESPERA_TRAVA = 10  # segundos esperando outra edicao do mesmo projeto
MAX_DECISOES = 1024 * 1024
CHAVES = {"cuts_removed", "cuts_added", "caption_edits", "graphics", "notes"}
TIPOS = {"cuts_removed": list, "cuts_added": list, "caption_edits": dict,
         "graphics": dict, "notes": list}
ID_GRAFICO_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_ENTRADAS = 500      # por mapa/lista, na requisicao e no estado gravado
MAX_LEGENDA = 500
MAX_BASE = 2000
MAX_NOTA = 2000
MAX_TEXTO = 2000        # qualquer outra string
_ABS_RE = re.compile(r"(?<![\w<])/(?:[^\s/()'\":,;]+/)*([^\s/()'\":,;]*)")

_travas: dict[str, threading.Lock] = {}
_travas_mu = threading.Lock()


class RevisaoErro(Exception):
    def __init__(self, status: int, msg: str, codigo: str | None = None):
        super().__init__(msg)
        self.status = status
        self.msg = msg
        self.codigo = codigo


def trava(slug: str) -> threading.Lock:
    with _travas_mu:
        return _travas.setdefault(slug, threading.Lock())


def _checar_texto(s: str, onde: str, limite: int, quebra: bool = False) -> None:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        raise RevisaoErro(400, f"{onde}: texto com caractere inválido") from None
    if len(s) > limite:
        raise RevisaoErro(400, f"{onde}: texto longo demais (máximo {limite} caracteres)")
    for ch in s:
        if unicodedata.category(ch) == "Cc" and not (quebra and ch == "\n"):
            raise RevisaoErro(400, f"{onde}: caracteres de controle não são permitidos")


def _varrer(obj, onde: str, quebra: bool = False) -> None:
    """Toda string (inclusive chaves) sem surrogate nem controles."""
    if isinstance(obj, str):
        _checar_texto(obj, onde, MAX_TEXTO, quebra)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _varrer(k, onde, quebra)
            _varrer(v, onde, quebra)
    elif isinstance(obj, list):
        for v in obj:
            _varrer(v, onde, quebra)


def validar(decisoes) -> dict:
    try:
        return _validar(decisoes)
    except RecursionError:
        raise RevisaoErro(400, "decisões aninhadas demais") from None


def _validar(decisoes) -> dict:
    if not isinstance(decisoes, dict):
        raise RevisaoErro(400, "as decisões devem ser um objeto JSON")
    desconhecidas = set(decisoes) - CHAVES
    if desconhecidas:
        raise RevisaoErro(400, "chaves desconhecidas nas decisões: "
                               + ", ".join(sorted(map(str, desconhecidas))))
    for k, v in decisoes.items():
        if not isinstance(v, TIPOS[k]):
            raise RevisaoErro(400, f"'{k}' deve ser {'uma lista' if TIPOS[k] is list else 'um objeto'}")
        if len(v) > MAX_ENTRADAS:
            raise RevisaoErro(400, f"'{k}': máximo de {MAX_ENTRADAS} itens")
        _varrer(v, k, quebra=(k == "caption_edits"))
    for gid in decisoes.get("graphics", {}):
        if not ID_GRAFICO_RE.fullmatch(gid):
            raise RevisaoErro(400, "id de gráfico inválido (use letras, números, - e _; até 64)")
    for idx, v in decisoes.get("caption_edits", {}).items():
        texto, base = (v["text"], v.get("base_text")) if isinstance(v, dict) and "text" in v else (v, None)
        if isinstance(texto, str) and len(texto) > MAX_LEGENDA:
            raise RevisaoErro(400, f"legenda da frase {idx[:20]}: máximo {MAX_LEGENDA} caracteres")
        if isinstance(base, str) and len(base) > MAX_BASE:
            raise RevisaoErro(400, f"legenda da frase {idx[:20]}: texto base longo demais")
    for n in decisoes.get("notes", []):
        if isinstance(n, dict) and isinstance(n.get("text"), str) and len(n["text"]) > MAX_NOTA:
            raise RevisaoErro(400, f"nota longa demais (máximo {MAX_NOTA} caracteres)")
    return decisoes


def _limitar_estado(d: Path, decisoes: dict) -> None:
    novos = decisoes.get("graphics") or {}
    if not novos:
        return
    try:
        atual = json.loads((d / "revisao.json").read_text(encoding="utf-8")).get("graphics", {})
        atual = atual if isinstance(atual, dict) else {}
    except (OSError, ValueError, AttributeError):
        atual = {}
    if len(set(atual) | set(novos)) > MAX_ENTRADAS:
        raise RevisaoErro(400, f"gráficos demais no projeto (máximo {MAX_ENTRADAS})")


def sanitizar(msg: str, d: Path) -> str:
    for caminho in {str(d), str(d.resolve())}:
        msg = msg.replace(caminho, "<projeto>")
    return _ABS_RE.sub(lambda m: m.group(1) or "<caminho>", msg)


def _erro_do_script(stderr: str, d: Path) -> str | None:
    for linha in (stderr or "").splitlines():
        if linha.startswith("erro:"):
            return sanitizar(linha[len("erro:"):].strip(), d)[:500] or "revisão inválida"
    return None


def _rodar(args: list[str], d: Path) -> None:
    cmd = [sys.executable, "-I", str(SCRIPT), *args]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                cwd=REPO_ROOT, shell=False, start_new_session=True)
    except OSError:
        raise RevisaoErro(500, "não foi possível executar a revisão") from None
    try:
        _, err = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        _matar(proc)
        raise RevisaoErro(500, "a revisão excedeu o tempo limite") from None
    except BaseException:
        _matar(proc)
        raise
    if proc.returncode == 0:
        return
    msg = _erro_do_script(err, d) if proc.returncode == 1 else None
    if msg is None:
        raise RevisaoErro(500, "falha interna na revisão")
    raise RevisaoErro(400, msg)


def _matar(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=5)
    except Exception:
        pass


def construir(d: Path) -> dict:
    if not (d / "transcricao.json").is_file():
        raise RevisaoErro(409, "transcreva o vídeo primeiro")
    _rodar(["build", str(d)], d)
    try:
        return json.loads((d / "review.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RevisaoErro(500, "não foi possível ler a revisão gerada") from None


def aplicar(d: Path, decisoes: dict) -> dict:
    if not (d / "transcricao.json").is_file():
        raise RevisaoErro(409, "transcreva o vídeo primeiro")
    _limitar_estado(d, decisoes)
    for velho in d.glob(".decisoes-*.tmp"):  # sobras de um servidor morto (sob a trava do slug)
        try:
            velho.unlink()
        except OSError:
            pass
    fd, nome = tempfile.mkstemp(dir=d, prefix=".decisoes-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(decisoes, f, ensure_ascii=False)
        _rodar(["apply", str(d), nome], d)
    finally:
        try:
            os.unlink(nome)
        except OSError:
            pass
    return construir(d)
