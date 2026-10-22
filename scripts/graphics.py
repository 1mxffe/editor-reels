"""Graficos animados do Reel: cards (titulo + corpo opcional + imagem de apoio).

Cada card e uma pagina HTML/CSS (``scripts/js/card.html``) desenhada pelo
Chromium headless quadro a quadro (``scripts/js/render_card.mjs``, Playwright
para Node), com fundo transparente; o ffmpeg junta os PNG num WebM VP9 com
alfa (``yuva420p``). Nada de rede, nada de animacao no relogio: o quadro i e o
estado do card em ``t = i / 30``. Sem dependencia do HyperFrames.

Spec de um card (``graficos.json`` do projeto: ``{"cards": [spec, ...]}``)::

    {"id": "k1", "title": "...", "body": "..." | null, "at": 2.0, "dur": 3.0,
     "material": "materiais/foto.png" | null}

``at`` e o instante na linha do tempo CORTADA (a do preview/final). Limites:
titulo 1-60 caracteres, corpo ate 140, ``dur`` de 1 a 6 s, ``at`` >= 0; o
material e uma imagem (png/jpg/jpeg/webp/svg) dentro da pasta do projeto.
Ordem fixa em ``render_card``: validacao (antes de qualquer navegador, ffmpeg ou
arquivo) -> navegador -> ffmpeg -> temporario unico renomeado.

Uso: python3 -I scripts/graphics.py <spec.json> <brand.json> <saida.webm>
         [--project <pasta>] [--size preview|final]
Saida: 0 ok; 1 erro (mensagem ``erro: ...``).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import base64  # noqa: E402
import functools  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

import brand as brandmod  # noqa: E402
import common  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TEMPLATE = HERE / "js" / "card.html"
DRIVER = HERE / "js" / "render_card.mjs"
FONTS_DIR = REPO / "assets" / "fonts"

CANVAS = (1080, 1920)
SIZES = {"preview": (540, 960), "final": CANVAS}
FPS = 30
SAFE_TOP = 250        # px a partir do topo (1080x1920)
SAFE_BOTTOM = 340     # px livres embaixo: faixa das legendas
CARD_TOP = 320        # o card fica no terco superior/meio, longe das legendas
ENTER_S = 0.35        # entrada ease-out cubic-bezier(.16,1,.3,1)
EXIT_S = 0.30         # saida cubic-bezier(.4,0,.2,1)
TITLE_MAX, BODY_MAX = 60, 140
DUR_MIN, DUR_MAX = 1.0, 6.0
MATERIAL_MAX_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".svg": "image/svg+xml"}
SPEC_KEYS = {"id", "title", "body", "at", "dur", "material"}
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


class GraphicsError(ValueError):
    """Card invalido ou falha ao desenha-lo (mensagem clara, sem traceback)."""


class RendererMissing(GraphicsError):
    """node, Playwright/Chromium ou ffmpeg com libvpx-vp9 indisponivel."""


# ---------------------------------------------------------------- validacao

def _sniff_image(path: Path, ext: str) -> bool:
    with open(path, "rb") as f:
        head = f.read(2048)
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return b"<svg" in head.lower()


def _material(value, project: Path | None, where: str) -> Path | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise GraphicsError(f"{where}: material deve ser o caminho de uma imagem do projeto ou null")
    root = Path(project if project is not None else Path.cwd()).resolve()
    p = Path(value)
    if not p.is_absolute():
        p = root / p
    try:
        resolved = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise GraphicsError(f"{where}: material não encontrado: {value}") from None
    if not resolved.is_relative_to(root):
        raise GraphicsError(f"{where}: material fora da pasta do projeto: {value}")
    ext = resolved.suffix.lower()
    if not resolved.is_file() or ext not in IMAGE_TYPES:
        raise GraphicsError(
            f"{where}: material precisa ser imagem png, jpg, jpeg, webp ou svg: {value}")
    try:
        size = resolved.stat().st_size
        ok = _sniff_image(resolved, ext)
    except OSError as e:
        raise GraphicsError(f"{where}: material ilegível ({value}): {e}") from e
    if size > MATERIAL_MAX_BYTES:
        raise GraphicsError(f"{where}: material maior que 20 MB: {value}")
    if not ok:
        raise GraphicsError(f"{where}: {value} não é uma imagem {ext[1:]} válida")
    return resolved


def validate(spec, project: Path | None = None, where: str = "card") -> dict:
    """Spec normalizada (textos sem espacos nas pontas, numeros float, material Path)."""
    if not isinstance(spec, dict):
        raise GraphicsError(f"{where}: esperado objeto {{id, title, body, at, dur, material}}")
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise GraphicsError(f"{where}: chaves desconhecidas: {', '.join(sorted(map(str, unknown)))}")
    cid = spec.get("id")
    if not (isinstance(cid, str) and cid.strip() and len(cid) <= 64):
        raise GraphicsError(f"{where}: id obrigatório (texto de 1 a 64 caracteres)")
    where = f"{where} {cid!r}" if where == "card" else f"{where} ({cid!r})"
    title = spec.get("title")
    if not isinstance(title, str) or not title.strip():
        raise GraphicsError(f"{where}: título obrigatório")
    title = title.strip()
    if len(title) > TITLE_MAX:
        raise GraphicsError(f"{where}: título com {len(title)} caracteres (máximo {TITLE_MAX})")
    body = spec.get("body")
    if body is not None and not isinstance(body, str):
        raise GraphicsError(f"{where}: body deve ser texto ou null")
    body = (body or "").strip() or None
    if body is not None and len(body) > BODY_MAX:
        raise GraphicsError(f"{where}: corpo com {len(body)} caracteres (máximo {BODY_MAX})")
    at, dur = spec.get("at"), spec.get("dur")
    if not (common.is_num(at) and at >= 0):
        raise GraphicsError(f"{where}: at deve ser número >= 0 (segundos do vídeo cortado)")
    if not (common.is_num(dur) and DUR_MIN <= dur <= DUR_MAX):
        raise GraphicsError(f"{where}: dur deve ser número entre {DUR_MIN:g} e {DUR_MAX:g} s")
    return {"id": cid, "title": title, "body": body, "at": float(at), "dur": float(dur),
            "material": _material(spec.get("material"), project, where)}


def load_cards(project: Path) -> list[dict]:
    """Cards validados de ``graficos.json`` (ausente = nenhum), na ordem do arquivo."""
    project = Path(project)
    path = project / "graficos.json"
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise GraphicsError(f"graficos.json ilegível ({path}): {e}") from e
    if not (isinstance(doc, dict) and isinstance(doc.get("cards"), list)):
        raise GraphicsError('graficos.json inválido: esperado {"cards": [...]}')
    cards, seen = [], set()
    for i, spec in enumerate(doc["cards"]):
        card = validate(spec, project, where=f"graficos.json, card {i}")
        if card["id"] in seen:
            raise GraphicsError(f"graficos.json: id repetido {card['id']!r}")
        seen.add(card["id"])
        cards.append(card)
    return cards


# ---------------------------------------------------------------- ambiente

@functools.lru_cache(maxsize=1)
def _npm_root() -> str:
    if shutil.which("npm") is None:
        return ""
    try:
        return subprocess.run(["npm", "root", "-g"], capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _node_env() -> dict:
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path("/opt/pw-browsers").is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/pw-browsers"
    cands = [env.get("NODE_PATH", ""), _npm_root(), "/usr/local/lib/node_modules",
             "/opt/homebrew/lib/node_modules"]
    env["NODE_PATH"] = os.pathsep.join(dict.fromkeys(c for c in cands if c))
    return env


@functools.lru_cache(maxsize=1)
def browser_status() -> str | None:
    """None se o Chromium headless (node + Playwright) abre; senao o motivo.

    Basta para imagens paradas (capa); os cards animados pedem tambem o ffmpeg
    com libvpx-vp9 (``renderer_status``).
    """
    if shutil.which("node") is None:
        return "node ausente"
    try:
        probe = subprocess.run(
            ["node", "-e", "const {chromium}=require('playwright');"
                           "process.stdout.write(require('fs').existsSync(chromium.executablePath())?'ok':'no')"],
            capture_output=True, text=True, env=_node_env(), timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return f"não foi possível verificar node/playwright: {e}"
    if probe.returncode != 0:
        return "playwright (node) ausente: npm i -g playwright"
    if probe.stdout != "ok":
        return "Chromium do Playwright ausente: npx playwright install chromium"
    return None


@functools.lru_cache(maxsize=1)
def renderer_status() -> str | None:
    """None se os cards podem ser desenhados; senao o motivo (para doctor e render)."""
    if shutil.which("node") is None:
        return "node ausente"
    if shutil.which("ffmpeg") is None:
        return "ffmpeg ausente"
    try:
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                             text=True, timeout=30).stdout
        dec = subprocess.run(["ffmpeg", "-hide_banner", "-decoders"], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return f"não foi possível verificar node/ffmpeg: {e}"
    if " libvpx-vp9 " not in enc or " libvpx-vp9 " not in dec:
        return "ffmpeg sem libvpx-vp9 (vídeo com transparência)"
    return browser_status()


# ---------------------------------------------------------------- desenho

def _brand_tokens(brand: dict) -> dict:
    if not isinstance(brand, dict):
        raise GraphicsError("marca inválida: esperado o objeto de brand.json")
    bad = [k for k in ("bg", "fg", "accent", "muted")
           if not (isinstance(brand.get(k), str) and _HEX.fullmatch(brand[k]))]
    bad += [k for k in ("font_title", "font_body") if not brandmod.valid_name(brand.get(k))]
    if bad:
        raise GraphicsError(f"brand.json sem valor válido para: {', '.join(bad)}")
    return {"colors": {k: brand[k] for k in ("bg", "fg", "accent", "muted")},
            "fonts": {"title": brand["font_title"].strip(), "body": brand["font_body"].strip()}}


def _check_size(size) -> tuple[int, int]:
    try:
        w, h = (int(size[0]), int(size[1]))
    except (TypeError, ValueError, IndexError):
        raise GraphicsError(f"tamanho inválido: {size!r}") from None
    if w <= 0 or w * 16 != h * 9:
        raise GraphicsError(f"tamanho precisa ser vertical 9:16 (ex.: 540x960), não {w}x{h}")
    return w, h


def _font_files() -> list[dict]:
    out = []
    for weight, name in ((400, "Regular"), (600, "SemiBold"), (700, "Bold"), (800, "ExtraBold")):
        for ext in (".ttf", ".otf"):
            f = FONTS_DIR / f"Poppins-{name}{ext}"
            if f.is_file():
                out.append({"weight": weight, "url": f.resolve().as_uri(), "path": str(f.resolve())})
                break
    return out


def frame_count(dur: float) -> int:
    return max(1, round(dur * FPS))


def _page_data(card: dict, brand: dict, size: tuple[int, int]) -> dict:
    tokens = _brand_tokens(brand)
    image = None
    if card.get("material") is not None:
        mat = Path(card["material"])
        try:
            raw = mat.read_bytes()
        except OSError as e:
            raise GraphicsError(f"card {card['id']!r}: material ilegível ({mat}): {e}") from e
        image = f"data:{IMAGE_TYPES[mat.suffix.lower()]};base64," + base64.b64encode(raw).decode("ascii")
    n = frame_count(card["dur"])
    return {
        "title": card["title"], "body": card.get("body"), "image": image,
        **tokens, "fontFiles": _font_files(),
        "scale": size[0] / CANVAS[0], "enter": ENTER_S, "exit": EXIT_S,
        "lastFrameTime": (n - 1) / FPS,
        "safe": {"top": CARD_TOP, "maxHeight": CANVAS[1] - SAFE_BOTTOM - CARD_TOP},
    }


def _run(cmd: list[str], what: str, *, env=None, timeout=None) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except FileNotFoundError:
        raise RendererMissing(f"{what}: comando não encontrado: {cmd[0]}") from None
    except subprocess.TimeoutExpired:
        raise GraphicsError(f"{what}: tempo esgotado") from None
    except OSError as e:
        raise GraphicsError(f"{what}: não foi possível executar {cmd[0]}: {e}") from e
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-10:])
        raise GraphicsError(f"{what} falhou (código {proc.returncode}): {tail}")
    return proc.stdout


def _drive(job: dict, workdir: Path, what: str, driver: Path = DRIVER) -> dict:
    job_path = workdir / "job.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    out = _run(["node", str(driver), str(job_path)], what, env=_node_env(),
               timeout=60 + job.get("frames", 1) * 2)
    try:
        return json.loads(out)
    except ValueError:
        raise GraphicsError(f"{what}: resposta inesperada do navegador") from None


def render_clip(card: dict, brand: dict, out: Path, *, size: tuple[int, int] = CANVAS) -> Path:
    """Desenha um card JA validado. Saida atomica (``common.atomic_write``)."""
    out = Path(out)
    w, h = _check_size(size)
    data = _page_data(card, brand, (w, h))
    n = frame_count(card["dur"])
    what = f"gráfico {card['id']!r}"
    with tempfile.TemporaryDirectory(prefix="reel-grafico-") as td:
        frames = Path(td) / "frames"
        frames.mkdir()
        _drive({"html": str(TEMPLATE), "width": w, "height": h, "frames": n, "fps": FPS,
                "outdir": str(frames), "data": data}, Path(td), what)
        with common.atomic_write(out, suffix=".webm") as tmp:
            _run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                  "-i", str(frames / "f%05d.png"), "-frames:v", str(n),
                  "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
                  # clipe intermediario (vai ser reencodado em H.264): realtime e
                  # ~3x mais rapido que "good" sem perda visivel no crf 20
                  "-b:v", "0", "-crf", "20", "-deadline", "realtime", "-cpu-used", "8",
                  "-row-mt", "1", "-an", "-f", "webm", str(tmp)], f"{what} (ffmpeg)",
                 timeout=120 + n * 2)
    return out


def render_card(spec: dict, brand: dict, out: Path, *, project: Path | None = None,
                size: tuple[int, int] = CANVAS) -> Path:
    """Valida e desenha o card em ``out`` (WebM VP9 com alfa)."""
    card = validate(spec, project)
    _brand_tokens(brand)
    reason = renderer_status()
    if reason:
        raise RendererMissing(f"gráfico {card['id']!r}: renderizador indisponível: {reason}")
    return render_clip(card, brand, out, size=size)


def inspect_card(spec: dict, brand: dict, *, project: Path | None = None,
                 size: tuple[int, int] = CANVAS, t: float | None = None,
                 shot: Path | None = None) -> dict:
    """Estado do card montado no navegador em ``t`` (padrao: meio do trecho parado).

    Para testes e diagnostico: fonte calculada, caixa do card em px de 1080x1920,
    texto exibido, imagens; ``shot`` grava o PNG transparente desse quadro.
    """
    card = validate(spec, project)
    reason = renderer_status()
    if reason:
        raise RendererMissing(f"gráfico {card['id']!r}: renderizador indisponível: {reason}")
    w, h = _check_size(size)
    data = _page_data(card, brand, (w, h))
    if t is None:
        t = (ENTER_S + data["lastFrameTime"] - EXIT_S) / 2
    with tempfile.TemporaryDirectory(prefix="reel-grafico-") as td:
        job = {"html": str(TEMPLATE), "width": w, "height": h, "fps": FPS, "data": data,
               "inspect": {"t": t, "shot": str(shot) if shot else None}}
        return _drive(job, Path(td), f"gráfico {card['id']!r}")


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> None:
    parser = common.UsageParser(prog="graphics.py", description="Desenha um card de gráfico.")
    parser.add_argument("spec", type=Path)
    parser.add_argument("brand", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--project", type=Path, default=None,
                        help="pasta do projeto (materiais); padrão: pasta do spec")
    parser.add_argument("--size", choices=sorted(SIZES), default="final")
    args = parser.parse_args(argv)
    for what, path in (("do spec", args.spec), ("do brand.json", args.brand)):
        if common.same_file(args.out, path):
            common.fail(f"a saída {args.out} é o mesmo arquivo {what}; escolha outro caminho "
                        "(por exemplo saida/card.webm)")
    try:
        try:
            spec = json.loads(args.spec.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            common.fail(f"spec ilegível ({args.spec}): {e}")
        brand = brandmod.load(args.brand)
        project = args.project if args.project is not None else args.spec.resolve().parent
        out = render_card(spec, brand, args.out, project=project, size=SIZES[args.size])
    except brandmod.BrandMissing as e:
        common.fail(f"{e}. Rode a entrevista de marca (brand/brand.json).")
    except (GraphicsError, OSError, ValueError) as e:
        common.fail(str(e))
    print(out)


if __name__ == "__main__":
    main()
