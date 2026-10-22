"""Marca do editor de Reel: carga, validacao e semente de brand/brand.json."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

REQUIRED = ["accent", "bg", "fg", "muted", "font_title", "font_body", "handles", "caption_style"]
COLOR_KEYS = ["accent", "bg", "fg", "muted"]
TEXT_KEYS = ["font_title", "font_body", "caption_style"]
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
# Nome de fonte/estilo: vai para a linha Style: do ASS e para o CSS dos cards e da
# capa. Virgula, quebra de linha, chaves ou barra quebrariam (ou injetariam) o ASS.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 \-]{0,63}")
_HANDLE = re.compile(r"[A-Za-z0-9._]{1,30}")
MAX_HANDLES = 2
USAGE = ("uso: brand.py seed <saida.json> [--force] | brand.py check <brand.json> | "
         "brand.py set-handles <brand.json> @perfil [@perfil2]")
SET_HANDLES_HINT = "python3 -I scripts/brand.py set-handles brand/brand.json @perfil"


class BrandMissing(Exception):
    """brand.json ausente ou incompleto: rodar a entrevista de marca."""


def seed_from_guide() -> dict:
    """Semente medida em brand/guia-visual.md (v1)."""
    return {
        "accent": "#a8c8f0",
        "bg": "#001931",
        "fg": "#ddebf5",
        "muted": "#566a7a",
        "font_title": "Poppins",
        "font_body": "Poppins",
        "handles": [],
        "caption_style": "static-phrase",
    }


def write_seed(path: Path) -> None:
    common.write_json_atomic(Path(path), seed_from_guide())


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def valid_name(v) -> bool:
    """Nome de fonte ou de estilo aceito: letras ASCII, digitos, espaco e hifen, 1 a 64,
    comecando por letra ou digito ("Poppins", "Open Sans", "static-phrase")."""
    return isinstance(v, str) and _NAME.fullmatch(v) is not None and v == v.strip()


def invalid_keys(data: dict) -> list[str]:
    """Chaves presentes com tipo/valor invalido, na ordem de REQUIRED."""
    bad = []
    for k in REQUIRED:
        v = data[k]
        if k in COLOR_KEYS:
            ok = isinstance(v, str) and _HEX.fullmatch(v) is not None
        elif k in TEXT_KEYS:
            ok = valid_name(v)
        else:  # handles
            ok = isinstance(v, list) and all(_nonempty_str(h) for h in v)
        if not ok:
            bad.append(k)
    return bad


def load(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise BrandMissing(f"brand.json ausente: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BrandMissing(f"brand.json invalido ({path}): {e}") from e
    if not isinstance(data, dict):
        raise BrandMissing(f"brand.json invalido ({path}): esperado objeto JSON")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise BrandMissing(f"brand.json incompleto ({path}); faltam: {', '.join(missing)}")
    bad = invalid_keys(data)
    if bad:
        raise BrandMissing(
            f"brand.json com valor inválido ({path}): {', '.join(bad)} "
            "(cores #RRGGBB; fontes e caption_style com letras sem acento, numeros, espaco "
            "ou hifen, ate 64, ex.: Poppins; handles lista de @)"
        )
    return data


def require_handles(b: dict) -> list[str]:
    handles = b.get("handles")
    if isinstance(handles, list):
        handles = [h.strip() for h in handles if isinstance(h, str) and h.strip()]
    else:
        handles = []
    if not handles:
        raise BrandMissing("handles vazio: informe o @ das redes oficiais antes de gerar a capa "
                           f"e salve com: {SET_HANDLES_HINT}")
    return handles


def normalize_handle(h) -> str:
    """"perfil" ou "@perfil" -> "@perfil" (letras, números, ponto e sublinhado; até 30).

    ValueError com "@ inválido: ..." para qualquer outra coisa (inclusive "@@x").
    """
    if not isinstance(h, str):
        raise ValueError(f"@ inválido: {h!r} (esperado texto como @perfil)")
    s = h.strip()
    body = s[1:] if s.startswith("@") else s
    if not _HANDLE.fullmatch(body):
        raise ValueError(f"@ inválido: {s!r} (use @ seguido de 1 a 30 letras sem acento, "
                         "números, ponto ou sublinhado)")
    return "@" + body


def set_handles(path: Path, handles: list[str]) -> list[str]:
    """Grava os @ normalizados em ``handles`` de brand.json (as outras chaves ficam iguais)."""
    path = Path(path)
    norm = list(dict.fromkeys(normalize_handle(h) for h in handles))
    if not norm:
        raise ValueError("informe pelo menos um @")
    if len(norm) > MAX_HANDLES:
        raise ValueError(f"no máximo {MAX_HANDLES} @ na capa")
    if not path.is_file():
        raise BrandMissing(f"brand.json ausente: {path} (rode brand.py seed primeiro)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BrandMissing(f"brand.json invalido ({path}): {e}") from e
    if not isinstance(data, dict):
        raise BrandMissing(f"brand.json invalido ({path}): esperado objeto JSON")
    data["handles"] = norm
    common.write_json_atomic(path, data)
    return norm


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[0:1] == ["set-handles"]:
        if len(argv) < 3 or argv[1].startswith("-") or not any(a.strip() for a in argv[2:]):
            common.fail(USAGE)
        try:
            saved = set_handles(Path(argv[1]), argv[2:])
        except BrandMissing as e:
            common.fail(str(e))
        except ValueError as e:
            common.fail(str(e))
        except OSError as e:
            common.fail(f"nao foi possivel gravar {argv[1]}: {e}")
        print("handles gravados: " + " ".join(saved))
        return
    force = argv[0:1] == ["seed"] and "--force" in argv[1:]
    args = [a for a in argv if not (force and a == "--force")]
    if len(args) != 2 or args[0] not in ("seed", "check") or args[1].startswith("-"):
        common.fail(USAGE)
    cmd, target = args
    if cmd == "seed":
        out = Path(target)
        if out.exists() and not force:
            common.fail(f"{out} ja existe; seed so cria brand.json ausente (use --force para sobrescrever)")
        try:
            write_seed(out)
        except OSError as e:
            common.fail(f"nao foi possivel gravar {out}: {e}")
        print(f"semente gravada em {out}")
        return
    try:
        load(Path(target))
    except BrandMissing as e:
        common.fail(str(e))


if __name__ == "__main__":
    main()
