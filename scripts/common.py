"""Helpers compartilhados pelos scripts do editor de Reel.

Codigos de saida de todas as CLIs: 0 ok; 1 para todo erro, inclusive erro de uso
(``UsageParser``).
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import json
import math
import os
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Iterator, NoReturn


def is_num(x) -> bool:
    """Numero de verdade: int/float finito, nao bool (o json do Python aceita NaN e Infinity)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def same_file(a: Path, b: Path) -> bool:
    """``a`` e ``b`` sao (ou apontam, via link, para) o mesmo arquivo."""
    a, b = Path(a), Path(b)
    try:
        if a.exists() and b.exists():
            return os.path.samefile(a, b)
        return a.resolve() == b.resolve()
    except OSError:
        return False


def fail(msg: str, code: int = 1) -> NoReturn:
    print(f"erro: {msg}", file=sys.stderr)
    sys.exit(code)


class UsageParser(argparse.ArgumentParser):
    """argparse com erro de uso saindo com 1 (``erro: ...``), como os outros erros.

    Subcomandos (``add_subparsers``) herdam a classe."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        fail(message)


_UMASK_LOCK = threading.Lock()


def _umask() -> int:
    """umask atual (so da para ler trocando; o lock evita corrida entre threads)."""
    with _UMASK_LOCK:
        old = os.umask(0)
        os.umask(old)
    return old


@contextlib.contextmanager
def atomic_write(path: Path, *, suffix: str = "") -> Iterator[Path]:
    """Caminho temporario para gravar ``path`` de forma atomica.

    O temporario (``.<nome>-XXXXXX.tmp<suffix>``) e criado com O_EXCL no MESMO
    diretorio (nao segue link plantado, nao colide com outra execucao), com o
    modo de um arquivo normal (``0666 & ~umask``, nao o 0600 do mkstemp); quem
    grava (Python, ffmpeg, Pillow) escreve nele. Ao sair sem erro, ``os.replace``
    para ``path``; com qualquer erro o temporario e apagado e ``path`` fica como
    estava. ``suffix`` serve para o ffmpeg deduzir o formato (".mp4"). O
    diretorio de ``path`` precisa existir.
    """
    path = Path(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp" + suffix)
    tmp = Path(name)
    try:
        os.close(fd)
        os.chmod(tmp, 0o666 & ~_umask())
        yield tmp
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class LeituraRecusada(ValueError):
    """Arquivo recusado por ``ler_limitado`` (motivo em portugues)."""


def ler_limitado(path: Path, max_bytes: int) -> bytes:
    """Bytes de um arquivo comum pequeno, sem seguir link e sem travar.

    Abre com O_NOFOLLOW|O_NONBLOCK (FIFO, dispositivo e link nao travam nem sao
    seguidos), exige arquivo regular e le no maximo ``max_bytes``. Erros:
    ``LeituraRecusada`` (link, nao e arquivo, grande demais) ou ``OSError``."""
    path = Path(path)
    if path.is_symlink():
        raise LeituraRecusada("é um link (atalho); links não são aceitos")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise LeituraRecusada("é um link (atalho); links não são aceitos") from None
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise LeituraRecusada("não é um arquivo comum")
        if st.st_size > max_bytes:
            raise LeituraRecusada(f"é grande demais (máximo {max_bytes // 1024} KiB)")
        partes, total = [], 0
        while total <= max_bytes:
            bloco = os.read(fd, min(65536, max_bytes + 1 - total))
            if not bloco:
                break
            partes.append(bloco)
            total += len(bloco)
        if total > max_bytes:  # cresceu depois do fstat
            raise LeituraRecusada(f"é grande demais (máximo {max_bytes // 1024} KiB)")
        return b"".join(partes)
    finally:
        os.close(fd)


def write_json_atomic(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)  # erro de dado: nada criado
    with atomic_write(path) as tmp:
        tmp.write_text(text, encoding="utf-8")


def run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        fail(f"comando nao encontrado: {cmd[0]}")
    except OSError as e:  # PermissionError, ENOEXEC etc.
        fail(f"nao foi possivel executar {cmd[0]}: {e}")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-10:])
        fail(f"{cmd[0]} falhou (codigo {proc.returncode}): {tail}")
    return proc.stdout


_FILTERS_CACHE: dict[str, bool] = {}


def ffmpeg_has_libass() -> bool:
    """True se o ffmpeg tem os filtros ``subtitles`` e ``ass`` (libass).

    Consulta ``ffmpeg -hide_banner -filters`` uma vez por processo (timeout 15 s).
    Qualquer falha na consulta assume True: o caminho atual (ASS) segue valendo.
    """
    if "libass" not in _FILTERS_CACHE:
        try:
            proc = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                                  capture_output=True, text=True, timeout=15)
            if proc.returncode != 0:
                raise OSError(proc.returncode)
            names = {parts[1] for parts in (ln.split() for ln in proc.stdout.splitlines())
                     if len(parts) >= 3}
            _FILTERS_CACHE["libass"] = "subtitles" in names and "ass" in names
        except (OSError, subprocess.SubprocessError, ValueError):
            _FILTERS_CACHE["libass"] = True
    return _FILTERS_CACHE["libass"]
