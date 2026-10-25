"""Graficos animados do Reel: efeitos do banco (``banco/efeitos/<id>/``) e o card antigo.

Cada efeito e uma pagina ``efeito.html`` do banco, desenhada pelo Chromium headless
quadro a quadro (``scripts/js/render_card.mjs``, Playwright para Node), com fundo
transparente; o ffmpeg junta os PNG num WebM VP9 com alfa (``yuva420p``). Nada de rede,
nada de animacao no relogio: o quadro i e o estado do efeito em ``t = i / 30``.

Item de ``graficos.json`` (``{"cards": [item, ...]}``), dois formatos::

    {"id": "k1", "efeito": "numero-grande", "campos": {"destaque": "60 dias", ...},
     "at": 2.0, "dur": 3.0}
    {"id": "k1", "title": "...", "body": "..." | null, "at": 2.0, "dur": 3.0,
     "material": "materiais/foto.png" | null}          (antigo = efeito "card-destaque")

``campos`` e validado contra o ``manifesto.json`` do efeito (tipos, ``max``/``min``,
obrigatorios, listas, imagens so dentro da pasta do projeto, texto sem caracteres de
controle); efeito desconhecido e erro. Imagem pode ser ``"quadro:<segundo>"``: um quadro
do proprio video do projeto (segundo na linha do tempo CORTADA), extraido pelo ffmpeg.
``at`` e o instante na linha do tempo CORTADA (a do preview/final); ``dur`` fica entre
``duracao.min`` e ``duracao.max`` do efeito (card antigo: titulo 1-60 caracteres, corpo
ate 140, ``dur`` de 1 a 6 s). Ordem fixa em ``render_card``: validacao (antes de qualquer
navegador, ffmpeg ou arquivo) -> navegador -> ffmpeg -> temporario unico renomeado.

Uso: python3 -I scripts/graphics.py <spec.json> <brand.json> <saida.webm>
         [--project <pasta>] [--size preview|final] [--estilo <estilo.json>]
         (``--estilo``: cores e fonte da paleta escolhida; brand.json nao muda)
     python3 -I scripts/graphics.py validar <graficos.json> <projeto>
         (so valida: imprime ``ok`` ou ``erro: ...``)
Saida: 0 ok; 1 erro (mensagem ``erro: ...``).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import base64  # noqa: E402
import functools  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

import unicodedata  # noqa: E402

import banco as bancomod  # noqa: E402
import brand as brandmod  # noqa: E402
import common  # noqa: E402
import cut as cutmod  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DRIVER = HERE / "js" / "render_card.mjs"
BANCO_RAIZ = REPO / "banco"
EFEITO_LEGADO = "card-destaque"   # o card antigo {title, body, material}
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
EFEITO_KEYS = {"id", "efeito", "campos", "at", "dur"}
TEXTO_MAX = 200       # campo de texto sem "max" no manifesto
QUADROS_MAX = 6       # quadros do video extraidos por efeito
DUR_TETO = 30.0       # nenhum efeito passa disso, mesmo que o manifesto deixe
QUADRO_LARGURA = 720  # px do quadro extraido (largura)
PESOS_PADRAO = (400, 600, 800)
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_QUADRO = re.compile(r"quadro:(\d{1,5}(?:\.\d{1,3})?)")
_CSP = re.compile(r"<meta\s+http-equiv=\"Content-Security-Policy\"\s+content=\"([^\"]*)\"", re.I)


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
    """Spec normalizada (textos sem espacos nas pontas, numeros float, imagens Path).

    Sempre traz ``efeito`` e ``campos`` (o card antigo vira ``card-destaque``) e tambem
    ``title``/``body``/``material`` (rotulo para a revisao; no card antigo, os de sempre).
    """
    if not isinstance(spec, dict):
        raise GraphicsError(f"{where}: esperado objeto {{id, efeito, campos, at, dur}} "
                            "ou {id, title, body, at, dur, material}")
    if "efeito" in spec or "campos" in spec:
        return _validate_efeito(spec, project, where)
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
    if not _sem_controle(title):
        raise GraphicsError(f"{where}: título com caracteres de controle ou invisíveis")
    if len(title) > TITLE_MAX:
        raise GraphicsError(f"{where}: título com {len(title)} caracteres (máximo {TITLE_MAX})")
    body = spec.get("body")
    if body is not None and not isinstance(body, str):
        raise GraphicsError(f"{where}: body deve ser texto ou null")
    body = (body or "").strip() or None
    if body is not None and not _sem_controle(body):
        raise GraphicsError(f"{where}: corpo com caracteres de controle ou invisíveis")
    if body is not None and len(body) > BODY_MAX:
        raise GraphicsError(f"{where}: corpo com {len(body)} caracteres (máximo {BODY_MAX})")
    at, dur = spec.get("at"), spec.get("dur")
    if not (common.is_num(at) and at >= 0):
        raise GraphicsError(f"{where}: at deve ser número >= 0 (segundos do vídeo cortado)")
    if not (common.is_num(dur) and DUR_MIN <= dur <= DUR_MAX):
        raise GraphicsError(f"{where}: dur deve ser número entre {DUR_MIN:g} e {DUR_MAX:g} s")
    material = _material(spec.get("material"), project, where)
    return {"id": cid, "title": title, "body": body, "at": float(at), "dur": float(dur),
            "material": material, "efeito": EFEITO_LEGADO,
            "campos": {"titulo": title, "texto": body, "imagem": material}}


# ---------------------------------------------------------------- efeitos do banco

def efeitos(raiz: Path | None = None) -> dict[str, dict]:
    """Efeitos validos do banco (``{id: item}``), so JSON: nao abre navegador."""
    b = bancomod.carregar(BANCO_RAIZ if raiz is None else Path(raiz))
    return {it["id"]: it for it in b.itens("efeito")}


def item_efeito(efeito_id, where: str = "efeito", raiz: Path | None = None) -> dict:
    todos = efeitos(raiz)
    if not isinstance(efeito_id, str) or efeito_id not in todos:
        raise GraphicsError(f"{where}: efeito desconhecido {efeito_id!r} (os efeitos do banco "
                            f"são: {', '.join(sorted(todos)) or 'nenhum'})")
    return todos[efeito_id]


def _validate_efeito(spec: dict, project: Path | None, where: str) -> dict:
    unknown = set(spec) - EFEITO_KEYS
    if unknown:
        raise GraphicsError(f"{where}: chaves desconhecidas: {', '.join(sorted(map(str, unknown)))} "
                            "(use id, efeito, campos, at, dur)")
    cid = spec.get("id")
    if not (isinstance(cid, str) and cid.strip() and len(cid) <= 64):
        raise GraphicsError(f"{where}: id obrigatório (texto de 1 a 64 caracteres)")
    where = f"{where} {cid!r}" if where == "card" else f"{where} ({cid!r})"
    item = item_efeito(spec.get("efeito"), where)
    campos = validar_campos(item, spec.get("campos"), project, where)
    at, dur = spec.get("at"), spec.get("dur")
    if not (common.is_num(at) and at >= 0):
        raise GraphicsError(f"{where}: o início (at) precisa ser um número de segundos, 0 ou mais "
                            "(contados no vídeo já cortado)")
    if common.is_num(dur) and dur > DUR_TETO:
        raise GraphicsError(f"{where}: a duração (dur) passa do limite de {DUR_TETO:g} s")
    dmin, dmax = item["duracao"]["min"], item["duracao"]["max"]
    if not (common.is_num(dur) and dmin <= dur <= dmax):
        raise GraphicsError(f"{where}: a duração (dur) precisa ser um número entre {dmin:g} e "
                            f"{dmax:g} s (máximo do efeito {item['nome']}: {dmax:g} s)")
    total = _duracao_cortada(project)
    if total is not None and at + dur > total + 1 / FPS:
        raise GraphicsError(f"{where}: o efeito vai de {at:g} s a {at + dur:g} s, depois do fim do "
                            f"vídeo ({total:.2f} s); comece antes ou diminua a duração")
    card = {"id": cid, "efeito": item["id"], "campos": campos, "at": float(at), "dur": float(dur),
            "title": _rotulo(item, campos), "body": None, "material": None}
    if item["id"] == EFEITO_LEGADO:
        card["body"] = campos.get("texto")
        img = campos.get("imagem")
        card["material"] = img if isinstance(img, Path) else None
    return card


def _rotulo(item: dict, campos: dict) -> str:
    """Nome curto do grafico na revisao: o primeiro texto preenchido, ou o nome do efeito."""
    for c in item["campos"]:
        v = campos.get(c["id"])
        if c["tipo"] == "texto" and v:
            texto = " · ".join(v) if isinstance(v, list) else v
            return texto if len(texto) <= 60 else texto[:59] + "…"
    return item["nome"]


def _sem_controle(v: str) -> bool:
    return not any(c != "\n" and unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in v)


def _valor(c: dict, v, project: Path | None, where: str):
    """Um valor de campo validado (None = vazio)."""
    rot = c["rotulo"]
    tipo = c["tipo"]
    if v is None:
        return None
    if tipo == "texto":
        if not isinstance(v, str):
            raise GraphicsError(f"{where}: {rot} precisa ser texto")
        v = v.strip()
        if not v:
            return None
        if not _sem_controle(v):
            raise GraphicsError(f"{where}: {rot} tem caracteres de controle ou invisíveis")
        mx = int(c.get("max", TEXTO_MAX))
        if len(v) > mx:
            raise GraphicsError(f"{where}: {rot} com {len(v)} caracteres (máximo {mx})")
        if len(v) < c.get("min", 0):
            raise GraphicsError(f"{where}: {rot} com {len(v)} caracteres (mínimo {c['min']:g})")
        return v
    if tipo == "numero":
        if not common.is_num(v):
            raise GraphicsError(f"{where}: {rot} precisa ser um número")
        if "min" in c and v < c["min"] or "max" in c and v > c["max"]:
            raise GraphicsError(f"{where}: {rot} precisa ficar entre {c.get('min', 0):g} e "
                                f"{c.get('max', bancomod.LIM_CAMPO):g}")
        if c.get("inteiro"):
            if v != int(v):
                raise GraphicsError(f"{where}: {rot} precisa ser um número inteiro")
            return int(v)
        return float(v)
    if tipo == "cor":
        if not (isinstance(v, str) and _HEX.fullmatch(v)):
            raise GraphicsError(f"{where}: {rot} precisa ser uma cor #rrggbb")
        return v.lower()
    if tipo == "escolha":
        if v not in c["opcoes"]:
            raise GraphicsError(f"{where}: {rot} precisa ser uma destas opções: {', '.join(c['opcoes'])}")
        return v
    # imagem: arquivo do projeto (materiais/...) ou quadro:<segundo> do proprio video
    if not isinstance(v, str):
        raise GraphicsError(f"{where}: {rot} precisa ser o caminho de uma imagem do projeto "
                            "ou quadro:<segundo>")
    if v.strip() == "":
        return None
    if v.startswith("quadro:"):
        return _quadro(v, project, where, rot)
    return _material(v, project, f"{where} ({rot})")


def validar_campos(item: dict, campos, project: Path | None, where: str) -> dict:
    """``campos`` de um efeito conferido contra o manifesto; devolve o dict normalizado
    (texto sem espacos nas pontas, imagens como Path ou {"quadro", "video"})."""
    if campos is None:
        campos = {}
    if not isinstance(campos, dict):
        raise GraphicsError(f"{where}: campos precisa ser um objeto {{campo: valor}}")
    defs = {c["id"]: c for c in item["campos"]}
    extra = sorted(set(map(str, campos)) - set(defs))
    if extra:
        raise GraphicsError(f"{where}: campo desconhecido para o efeito {item['nome']}: "
                            f"{', '.join(extra)} (use {', '.join(defs) or 'nenhum'})")
    out: dict = {}
    for c in item["campos"]:
        v = campos.get(c["id"])
        if "itens" in c:
            if v is None:
                v = []
            if not isinstance(v, list):
                raise GraphicsError(f"{where}: {c['rotulo']} precisa ser uma lista")
            if len(v) > c["itens"]["max"]:
                raise GraphicsError(f"{where}: {c['rotulo']} com {len(v)} itens "
                                    f"(máximo {c['itens']['max']})")
            vals = []
            for x in v:
                val = _valor(c, x, project, where)
                if val is None:
                    raise GraphicsError(f"{where}: {c['rotulo']} tem um item vazio")
                vals.append(val)
            if (vals or c["obrigatorio"]) and len(vals) < c["itens"]["min"]:
                raise GraphicsError(f"{where}: {c['rotulo']} precisa de pelo menos "
                                    f"{c['itens']['min']} itens")
            out[c["id"]] = vals
        else:
            val = _valor(c, v, project, where)
            if val is None and c["obrigatorio"]:
                raise GraphicsError(f"{where}: {c['rotulo']} é obrigatório")
            out[c["id"]] = val
    for grupo in item["dados"].get("mesmo_tamanho", []):
        if len({len(out.get(g) or []) for g in grupo}) > 1:
            rot = ", ".join(defs[g]["rotulo"] for g in grupo if g in defs)
            raise GraphicsError(f"{where}: {rot} precisam ter a mesma quantidade de itens")
    quadros = sum(1 for v in out.values() for x in (v if isinstance(v, list) else [v])
                  if isinstance(x, dict) and "quadro" in x)
    if quadros > QUADROS_MAX:
        raise GraphicsError(f"{where}: no máximo {QUADROS_MAX} quadros do vídeo por efeito")
    return out


def _trechos(root: Path | None) -> list | None:
    """Trechos mantidos do video bruto (transcricao.json + cortes.json), ou None se nao
    der para saber (arquivos ausentes ou ilegiveis)."""
    if root is None:
        return None
    try:
        dur = float(json.loads((Path(root) / "transcricao.json").read_text("utf-8"))["duration"])
        cuts = json.loads((Path(root) / "cortes.json").read_text("utf-8"))["cuts"]
        keep = cutmod.keep_segments(dur, cuts)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return keep or None


def _duracao_cortada(project: Path | None) -> float | None:
    keep = _trechos(project)
    return None if keep is None else sum(b - a for a, b in keep)


@functools.lru_cache(maxsize=32)
def _duracao_video_cache(video: str, mtime: float, size: int) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", video], capture_output=True, text=True, timeout=30)
        dur = float(out.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return dur if dur > 0 and math.isfinite(dur) else None


def _duracao_video(video: Path) -> float | None:
    """Duracao do video bruto pelo ffprobe (lista, sem shell), ou None se nao der."""
    try:
        st = Path(video).stat()
    except OSError:
        return None
    return _duracao_video_cache(str(video), st.st_mtime, st.st_size)


def _quadro(v: str, project: Path | None, where: str, rot: str) -> dict:
    m = _QUADRO.fullmatch(v.strip())
    if not m:
        raise GraphicsError(f"{where}: {rot}: use quadro:<segundo> (por exemplo quadro:2.5), não {v!r}")
    if project is None:
        raise GraphicsError(f"{where}: {rot}: quadro do vídeo precisa da pasta do projeto")
    root = Path(project).resolve()
    videos = sorted(p for p in root.glob("entrada.*") if p.is_file())
    if len(videos) != 1:
        raise GraphicsError(f"{where}: {rot}: {v} pede o vídeo do projeto, mas a pasta não tem "
                            "exatamente um arquivo entrada.*")
    video = videos[0].resolve()
    if not video.is_relative_to(root):
        raise GraphicsError(f"{where}: {rot}: o vídeo do projeto está fora da pasta do projeto")
    s = float(m.group(1))
    keep = _trechos(root)
    if keep is not None:  # segundo do video cortado -> segundo do video bruto
        total = sum(b - a for a, b in keep)
        if s > total + 1e-6:
            raise GraphicsError(f"{where}: {rot}: o segundo {s:g} está depois do fim do vídeo "
                                f"cortado ({total:.2f} s)")
        acc, bruto = 0.0, keep[-1][1] - 0.001
        for a, b in keep:
            if s <= acc + (b - a):
                bruto = min(b - 0.001, a + (s - acc))
                break
            acc += b - a
    else:  # sem cortes conhecidos: o segundo vale no video bruto
        total = _duracao_video(video)
        if total is not None and s > total:
            raise GraphicsError(f"{where}: {rot}: o segundo {s:g} está depois do fim do vídeo "
                                f"({total:.2f} s)")
        bruto = s
    return {"quadro": round(bruto, 3), "segundo": s, "video": video}


def load_cards(project: Path) -> list[dict]:
    """Cards validados de ``graficos.json`` (ausente = nenhum), na ordem do arquivo."""
    project = Path(project)
    path = project / "graficos.json"
    if not path.exists():
        return []
    return load_cards_from(path, project)


def load_cards_from(path: Path, project: Path) -> list[dict]:
    """Cards validados de um documento ``{"cards": [...]}`` em ``path`` (materiais
    relativos a ``project``); usado por ``load_cards`` e pelo subcomando ``validar``."""
    path, project = Path(path), Path(project)
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
    for weight, name in ((400, "Regular"), (500, "Medium"), (600, "SemiBold"), (700, "Bold"),
                         (800, "ExtraBold")):
        for ext in (".ttf", ".otf"):
            f = FONTS_DIR / f"Poppins-{name}{ext}"
            if f.is_file():
                out.append({"weight": weight, "url": f.resolve().as_uri(), "path": str(f.resolve())})
                break
    return out


def frame_count(dur: float) -> int:
    return max(1, round(dur * FPS))


@functools.lru_cache(maxsize=8)
def _font_data_uri(path: str) -> str:
    return "data:font/ttf;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _fontes(item: dict) -> list[dict]:
    """Pesos da Poppins que o efeito pede (``dados.pesos``), como data: URI (CSP sem file:)."""
    pesos = set(item["dados"].get("pesos", PESOS_PADRAO))
    return [{"weight": f["weight"], "url": _font_data_uri(f["path"])}
            for f in _font_files() if f["weight"] in pesos]


def _data_uri(path: Path, what: str) -> str:
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        raise GraphicsError(f"{what}: imagem ilegível ({path}): {e}") from e
    return f"data:{IMAGE_TYPES[Path(path).suffix.lower()]};base64," + base64.b64encode(raw).decode("ascii")


def extrair_quadro(video: Path, t: float, what: str = "quadro", segundo: float | None = None) -> str:
    """Um quadro do video em ``t`` s (bruto) como PNG data: URI (ffmpeg, lista, sem shell)."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{max(0.0, float(t)):.3f}", "-i", str(video),
           "-frames:v", "1", "-vf", f"scale={QUADRO_LARGURA}:-2", "-f", "image2pipe",
           "-c:v", "png", "pipe:1"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
    except FileNotFoundError:
        raise RendererMissing(f"{what}: ffmpeg ausente") from None
    except subprocess.TimeoutExpired:
        raise GraphicsError(f"{what}: tempo esgotado ao tirar o quadro do vídeo") from None
    except OSError as e:
        raise GraphicsError(f"{what}: não foi possível executar o ffmpeg: {e}") from e
    s = t if segundo is None else segundo
    if proc.returncode == 0 and not proc.stdout:  # pediu um instante que o video nao tem
        raise GraphicsError(f"{what}: o segundo {s:g} está depois do fim do vídeo; "
                            "escolha um momento dentro do vídeo")
    if proc.returncode != 0 or not proc.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        raise GraphicsError(f"{what}: não foi possível tirar a imagem do segundo {s:g} do vídeo "
                            "(o arquivo de vídeo pode estar danificado)")
    if len(proc.stdout) > MATERIAL_MAX_BYTES:
        raise GraphicsError(f"{what}: quadro do vídeo grande demais")
    return "data:image/png;base64," + base64.b64encode(proc.stdout).decode("ascii")


def _campos_pagina(campos: dict, what: str) -> dict:
    """Campos validados -> o que a pagina recebe (imagens viram data: URI)."""
    def conv(v):
        if isinstance(v, list):
            return [conv(x) for x in v]
        if isinstance(v, Path):
            return _data_uri(v, what)
        if isinstance(v, dict) and "quadro" in v:
            return extrair_quadro(v["video"], v["quadro"], what, v.get("segundo"))
        return v
    return {k: conv(v) for k, v in campos.items()}


def _card_campos(card: dict) -> dict:
    if "campos" in card:
        return card["campos"]
    return {"titulo": card["title"], "texto": card.get("body"), "imagem": card.get("material")}


def _page_data(card: dict, brand: dict, size: tuple[int, int], item: dict) -> dict:
    tokens = _brand_tokens(brand)
    n = frame_count(card["dur"])
    return {
        "campos": _campos_pagina(_card_campos(card), f"gráfico {card['id']!r}"),
        **tokens, "fontes": _fontes(item),
        "scale": size[0] / CANVAS[0], "enter": ENTER_S, "exit": EXIT_S,
        "dur": card["dur"], "fps": FPS, "lastFrameTime": (n - 1) / FPS,
        "transicao": item["dados"].get("transicao", "suave"),
        "area": {"top": SAFE_TOP, "bottom": CANVAS[1] - SAFE_BOTTOM,
                 "width": CANVAS[0], "height": CANVAS[1]},
        "safe": {"top": CARD_TOP, "maxHeight": CANVAS[1] - SAFE_BOTTOM - CARD_TOP},
    }


def _job_base(item: dict, size: tuple[int, int]) -> dict:
    return {"html": str(Path(item["pasta"]) / "efeito.html"),
            "banco": str(Path(item["pasta"]).parent.parent),
            "width": size[0], "height": size[1], "fps": FPS}


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
               timeout=60 + job.get("frames", 1) * 2 + len(job.get("verificar", [])) * 10)
    try:
        return json.loads(out)
    except ValueError:
        raise GraphicsError(f"{what}: resposta inesperada do navegador") from None


def _item_do_card(card: dict) -> dict:
    return item_efeito(card.get("efeito", EFEITO_LEGADO), f"gráfico {card['id']!r}")


def render_clip(card: dict, brand: dict, out: Path, *, size: tuple[int, int] = CANVAS) -> Path:
    """Desenha um card JA validado. Saida atomica (``common.atomic_write``)."""
    out = Path(out)
    w, h = _check_size(size)
    item = _item_do_card(card)
    data = _page_data(card, brand, (w, h), item)
    n = frame_count(card["dur"])
    what = f"gráfico {card['id']!r}"
    with tempfile.TemporaryDirectory(prefix="reel-grafico-") as td:
        frames = Path(td) / "frames"
        frames.mkdir()
        _drive({**_job_base(item, (w, h)), "frames": n, "outdir": str(frames), "data": data},
               Path(td), what)
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


def _inspecionar(card: dict, brand: dict, size: tuple[int, int], ts: list[float], *,
                 shots: bool) -> list[dict]:
    """Medidas da pagina em cada ``t`` (um navegador so); com ``shots``, o PNG de cada um."""
    item = _item_do_card(card)
    data = _page_data(card, brand, size, item)
    with tempfile.TemporaryDirectory(prefix="reel-grafico-") as td:
        job = {**_job_base(item, size), "data": data,
               "inspect": {"ts": [float(t) for t in ts], "shotdir": td if shots else None}}
        res = _drive(job, Path(td), f"gráfico {card['id']!r}")
        quadros = res["quadros"]
        for q in quadros:
            q["pageErrors"] = res.get("pageErrors", [])
            if q.get("shot"):
                q["png"] = Path(q.pop("shot")).read_bytes()
    return quadros


def _meio(dur: float) -> float:
    last = (frame_count(dur) - 1) / FPS
    return (ENTER_S + last - EXIT_S) / 2


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
    [q] = _inspecionar(card, brand, (w, h), [_meio(card["dur"]) if t is None else t],
                       shots=shot is not None)
    if shot is not None:
        Path(shot).write_bytes(q["png"])
    return {**q.get("extra", {}), "pageErrors": q["pageErrors"]}


def inspect_effect(efeito_id: str, campos: dict, brand: dict, *, project: Path | None = None,
                   t: float | None = None, dur: float | None = None,
                   size: tuple[int, int] = CANVAS, ts: list[float] | None = None) -> dict:
    """Um efeito do banco montado com ``campos`` em ``t`` s (padrao: meio do trecho parado).

    Devolve as caixas medidas em px de 1080x1920 (``caixas``, ``caixa`` = uniao),
    ``opacidade`` do efeito, ``textos`` exibidos, imagens, ``xss`` e ``png`` (bytes do
    quadro transparente em ``t``). Com ``ts``, devolve ``{"quadros": [...]}`` (um por t,
    mesmo navegador). Usado pelos testes e pelos cartões do passo Estilo.
    """
    where = f"efeito {efeito_id!r}"
    item = item_efeito(efeito_id, where)
    norm = validar_campos(item, campos, project, where)
    dur = item["duracao"]["padrao"] if dur is None else dur
    if not (common.is_num(dur) and item["duracao"]["min"] <= dur <= min(item["duracao"]["max"], DUR_TETO)):
        raise GraphicsError(f"{where}: a duração (dur) precisa ser um número entre {item['duracao']['min']:g} e "
                            f"{item['duracao']['max']:g} s")
    reason = renderer_status()
    if reason:
        raise RendererMissing(f"{where}: renderizador indisponível: {reason}")
    w, h = _check_size(size)
    card = {"id": efeito_id, "efeito": efeito_id, "campos": norm, "at": 0.0, "dur": float(dur)}
    lista = [_meio(float(dur)) if t is None else t] if ts is None else list(ts)
    quadros = _inspecionar(card, brand, (w, h), lista, shots=True)
    return {"quadros": quadros} if ts is not None else quadros[0]


_PLACEHOLDER = ("data:image/svg+xml;base64," + base64.b64encode(
    b'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600"><defs>'
    b'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#235587"/>'
    b'<stop offset="1" stop-color="#092744"/></linearGradient></defs>'
    b'<rect width="600" height="600" fill="url(#g)"/></svg>').decode("ascii"))


def _campos_exemplo(item: dict) -> dict:
    """Campos de exemplo do manifesto (``dados.exemplo``) prontos para a pagina; imagens
    viram uma imagem neutra (sem projeto na verificacao do banco)."""
    ex = dict(item["dados"].get("exemplo") or {})
    imagens = {c["id"]: c for c in item["campos"] if c["tipo"] == "imagem"}
    for k in imagens:
        ex.pop(k, None)
    sem_imagem = {**item, "campos": [c for c in item["campos"] if c["tipo"] != "imagem"]}
    norm = validar_campos(sem_imagem, ex, None, "exemplo")
    for k, c in imagens.items():
        if "itens" in c:
            norm[k] = [_PLACEHOLDER] * max(1, c["itens"]["min"])
        else:
            norm[k] = _PLACEHOLDER
    return norm


def verificar_efeitos(itens: list[dict]) -> dict[str, str | None]:
    """Abre cada efeito (um navegador para todos) com os campos de exemplo e chama
    ``setup`` e ``setTime`` em alguns instantes: ``{id: None}`` se desenhou, senao o
    motivo. Tambem confere a CSP sem rede. Sem navegador: ``RendererMissing``."""
    reason = browser_status()
    if reason:
        raise RendererMissing(f"verificação dos efeitos: navegador indisponível: {reason}")
    motivos: dict[str, str | None] = {}
    jobs = []
    size = SIZES["preview"]
    for item in itens:
        html = Path(item["pasta"]) / "efeito.html"
        try:
            texto = html.read_text("utf-8")
        except (OSError, ValueError) as e:
            motivos[item["id"]] = f"efeito.html ilegível: {e}"
            continue
        m = _CSP.search(texto)
        if not m or "default-src 'none'" not in m.group(1) or re.search(r"https?:|file:", m.group(1)):
            motivos[item["id"]] = ("efeito.html precisa da linha de segurança <meta http-equiv="
                                   "\"Content-Security-Policy\"> com default-src 'none' (sem rede)")
            continue
        try:
            campos = _campos_exemplo(item)
        except GraphicsError as e:
            motivos[item["id"]] = f"exemplo inválido no manifesto: {e}"
            continue
        dur = float(item["duracao"]["padrao"])
        card = {"id": item["id"], "efeito": item["id"], "campos": campos, "at": 0.0, "dur": dur}
        data = _page_data(card, {"bg": "#001931", "fg": "#ddebf5", "accent": "#a8c8f0",
                                 "muted": "#566a7a", "font_title": "Poppins",
                                 "font_body": "Poppins"}, size, item)
        last = data["lastFrameTime"]
        jobs.append({**_job_base(item, size), "id": item["id"], "data": data,
                     "ts": [0.0, ENTER_S / 2, _meio(dur), last - EXIT_S / 2, last]})
        motivos[item["id"]] = None
    if jobs:
        with tempfile.TemporaryDirectory(prefix="reel-efeitos-") as td:
            res = _drive({"verificar": jobs, "width": size[0], "height": size[1]}, Path(td),
                         "verificação dos efeitos")
        for j in jobs:
            motivos[j["id"]] = res.get(j["id"]) or None
    return motivos


# ---------------------------------------------------------------- CLI

def validar_main(argv: list[str]) -> None:
    """``graphics.py validar <graficos.json> <projeto>``: imprime ``ok`` (saida 0) ou
    ``erro: ...`` (saida 1). So valida; nao abre navegador nem ffmpeg."""
    parser = common.UsageParser(prog="graphics.py validar",
                                description="Valida um graficos.json sem desenhar nada.")
    parser.add_argument("graficos", type=Path)
    parser.add_argument("projeto", type=Path)
    args = parser.parse_args(argv)
    try:
        load_cards_from(args.graficos, args.projeto)
    except (GraphicsError, OSError, ValueError) as e:
        common.fail(str(e))
    print("ok")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["validar"]:
        return validar_main(argv[1:])
    parser = common.UsageParser(prog="graphics.py", description="Desenha um card de gráfico.")
    parser.add_argument("spec", type=Path)
    parser.add_argument("brand", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--project", type=Path, default=None,
                        help="pasta do projeto (materiais); padrão: pasta do spec")
    parser.add_argument("--size", choices=sorted(SIZES), default="final")
    parser.add_argument("--estilo", type=Path, default=None,
                        help="estilo.json do projeto (paleta e fonte); padrão: só o brand.json")
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
        if args.estilo is not None:
            import estilo as estilomod
            brand = estilomod.aplicar_marca(brand, estilomod.ler(args.estilo))
        project = args.project if args.project is not None else args.spec.resolve().parent
        out = render_card(spec, brand, args.out, project=project, size=SIZES[args.size])
    except brandmod.BrandMissing as e:
        common.fail(f"{e}. Rode a entrevista de marca (brand/brand.json).")
    except (GraphicsError, OSError, ValueError) as e:
        common.fail(str(e))
    print(out)


if __name__ == "__main__":
    main()
