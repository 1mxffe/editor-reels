"""Verifica as dependencias do editor de Reel.

Obrigatorios: python >= 3.11, ffmpeg, ffprobe e disco. Opcionais (sem eles o status
e READY WITH LIMITS e o motivo aparece na linha do item): faster_whisper
(transcricao), Pillow (capa: candidatos e composicao), node (cards e capa) e
node + Playwright/Chromium + ffmpeg com libvpx-vp9 (cards animados). Informativo,
nunca muda o estado: ffmpeg sem o filtro subtitles (libass) usa legendas por imagem. Python 3.11 ou
mais novo e obrigatorio (versao minima suportada e testada); este arquivo sobe em
python antigo (3.9 do macOS) so para conseguir reportar isso, por isso nao importa
os outros scripts antes de conferir a versao.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_FREE_GB = 10
MIN_PYTHON = (3, 11)
PYTHON_ITEM = "python >= 3.11"


def _has_whisper() -> bool:
    try:
        return importlib.util.find_spec("faster_whisper") is not None
    except (ImportError, ValueError):
        return False


def _has_pillow() -> bool:
    try:
        return importlib.util.find_spec("PIL") is not None
    except (ImportError, ValueError):
        return False


def _free_gb(path: str = ".") -> float:
    return shutil.disk_usage(path).free / 1e9


def _graphics_reason() -> str | None:
    """None se os graficos podem ser desenhados; senao o motivo."""
    import graphics
    return graphics.renderer_status()


GRAPHICS_ITEM = "chromium + playwright (opcional: graficos)"
PILLOW_ITEM = "Pillow (opcional: capa)"
LEGENDAS_ITEM = "legendas (filtro subtitles do ffmpeg)"


def _has_libass() -> bool:
    import common
    return common.ffmpeg_has_libass()


def _python_item() -> dict:
    found = tuple(sys.version_info[:2])
    item = {"name": PYTHON_ITEM, "ok": found >= MIN_PYTHON, "required": True}
    if not item["ok"]:
        item["detail"] = (f"este é o python {found[0]}.{found[1]}; instale o 3.11 ou mais novo "
                          "(ex.: brew install python@3.13) e rode os scripts com ele")
    return item


def check() -> tuple[str, list[dict]]:
    py = _python_item()
    # Em python antigo os outros scripts nao sao suportados: nao importa graphics.
    g_reason = _graphics_reason() if py["ok"] else f"precisa de {PYTHON_ITEM}"
    graphics_item = {"name": GRAPHICS_ITEM, "ok": g_reason is None, "required": False}
    if g_reason:
        graphics_item["detail"] = g_reason
    pillow_item = {"name": PILLOW_ITEM, "ok": _has_pillow(), "required": False}
    if not pillow_item["ok"]:
        pillow_item["detail"] = ("sem ele não há candidatos nem composição da capa; "
                                 "pip install -r requirements.txt")
    # Informativo: sem libass o render usa legendas por imagem; nunca rebaixa o estado.
    leg_item = {"name": LEGENDAS_ITEM, "ok": _has_libass() if py["ok"] else True,
                "required": False, "info": True}
    if not leg_item["ok"]:
        leg_item["detail"] = "usando legendas por imagem"
    items = [
        py,
        {"name": "ffmpeg", "ok": shutil.which("ffmpeg") is not None, "required": True},
        {"name": "ffprobe", "ok": shutil.which("ffprobe") is not None, "required": True},
        {"name": "node (opcional: cards e capa)", "ok": shutil.which("node") is not None,
         "required": False},
        {"name": f"disco livre >= {MIN_FREE_GB} GB", "ok": _free_gb() >= MIN_FREE_GB, "required": True},
        {"name": "faster_whisper (opcional)", "ok": _has_whisper(), "required": False},
        pillow_item,
        graphics_item,
        leg_item,
    ]
    if any(i["required"] and not i["ok"] for i in items):
        return "MISSING", items
    if any(not i["required"] and not i["ok"] and not i.get("info") for i in items):
        return "READY WITH LIMITS", items
    return "READY", items


def _marks() -> tuple[str, str]:
    """✔/✘ quando o stdout consegue codifica-los; senao [ok]/[x]."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "✔✘".encode(enc)
    except (UnicodeEncodeError, LookupError):
        return "[ok]", "[x]"
    return "✔", "✘"


def _printable(text: str) -> str:
    """Troca por ? o que o stdout nao codifica (motivos com acento num terminal ascii)."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        return text.encode(enc, errors="replace").decode(enc)
    except LookupError:
        return text.encode("ascii", errors="replace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    argv = [] if argv is None else argv
    status, items = check()
    if "--json" in argv:
        import json
        print(json.dumps({"estado": status, "itens": items}))
        return 1 if status == "MISSING" else 0
    ok_mark, bad_mark = _marks()
    for i in items:
        detail = f" ({i['detail']})" if i.get("detail") else ""
        print(_printable(f"{ok_mark if i['ok'] else bad_mark} {i['name']}{detail}"))
    print(status)
    return 1 if status == "MISSING" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
