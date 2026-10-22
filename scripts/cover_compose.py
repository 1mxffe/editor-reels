"""Capa do Reel (1080x1920): retrato + logotipo + gancho + @, no padrão do Figma.

Caminho automático (sem Figma) da capa, no padrão do frame "Capa Reels —
Isenção de IR: 3 mitos" do arquivo POSTS-OUTUBRO (``brand/guia-visual.md``):
foto cobrindo o quadro (retrato ancorado no terço de cima), vinheta azul-marinho
no topo, logotipo do escritório centralizado a ~13 % da altura, degradê
azul-marinho subindo da base, pill da área, gancho enorme em Poppins ExtraBold,
subtítulo em SemiBold com a ÚLTIMA linha (depois do último "\\n") na cor de
destaque, e o @ das redes no rodapé do bloco de texto.

Página HTML (``scripts/js/cover.html``) desenhada pelo Chromium headless
(``scripts/js/render_cover.mjs``, Playwright para Node), o mesmo esquema dos
cards de ``graphics.py``: dados em JSON, texto só por textContent, CSP sem rede,
foto/logotipo/fontes como data: URI lidos aqui. Sem os TTF de Poppins em
``assets/fonts`` o navegador usa a sans-serif da máquina (o desenho das letras
muda; o layout não).

Ordem fixa em ``compose``: saída diferente da foto, do logotipo e do
brand.json -> marca -> textos (validação, @ obrigatório e formato do @; nada é
aberto antes) -> foto (Pillow: abre pelo conteúdo, EXIF, lado menor >= 600 px,
reduz a <= 3000 px; luminância atrás do logotipo define o véu do topo) ->
navegador -> gancho em até 2 linhas, bloco de texto abaixo de y = 520, área
segura -> temporário único (``common.atomic_write``) renomeado.

Limites: gancho 1-28 caracteres (até 2 linhas), área até 28, subtítulo até 90.
Áreas seguras: todo texto em y de 250 a 1580 (fora da faixa de interface do
Instagram) e dentro do recorte 3:4 da grade do perfil (y de 240 a 1680).

Uso: python3 -I scripts/cover_compose.py <foto> <brand.json> <saida.png> --hook "3 MITOS"
         [--area "ISENÇÃO DE IR"] [--subtitle "linha branca\\nlinha em destaque"] [--logo <arquivo>]
Saída: 0 ok (imprime o caminho); 1 erro (mensagem ``erro: ...``, nada gravado).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import base64  # noqa: E402
import io  # noqa: E402
import tempfile  # noqa: E402

from PIL import Image  # noqa: E402

import brand as brandmod  # noqa: E402
import common  # noqa: E402
import graphics  # noqa: E402
from cover_frames import CoverError, _created_chain, load_photo  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TEMPLATE = HERE / "js" / "cover.html"
DRIVER = HERE / "js" / "render_cover.mjs"
LOGO = REPO / "assets" / "logo.webp"

CANVAS = (1080, 1920)
MARGIN = 54                   # ~5 % da largura (guia visual)
SAFE_TOP, SAFE_BOTTOM = 250, 340
GRID_CROP = (240, 1680)       # recorte 3:4 central da grade do perfil (1080x1440)
LOGO_TOP, LOGO_WIDTH = 250, 260   # medido no frame 272:2: ~13-20 % da altura
BLOCK_BOTTOM = 1496           # base do bloco pill/gancho/subtítulo
HANDLE_TOP = 1530             # linha do @ (termina antes de 1580)
HOOK_MAX, HOOK_MIN, HOOK_STEP = 200, 100, 2
SUB_SIZE, AREA_SIZE, HANDLE_SIZE = 60, 24, 30
BLOCK_TOP_MIN = 520           # bloco de texto começando acima disto cobre o rosto
SHADE = (300, 150, 40)        # px acima do topo MEDIDO do bloco: 0 -> 55 % -> 88 % do azul
WORDMARK_LUM = 0.87           # luminância do wordmark branco (#f0f0f0) de assets/logo.webp
LOGO_CONTRAST = 5.5           # alvo do wordmark sobre o fundo local (WCAG 4,5 + folga)
HOOK_MAX_CHARS, AREA_MAX_CHARS, SUB_MAX_CHARS = 28, 28, 90
PHOTO_MAX_SIDE = 3000
TEXT_BOXES = ("pill", "area", "hook", "subMain", "subAccent", "handle")


# ---------------------------------------------------------------- textos

def _lines(value: str) -> list[str]:
    """Linhas não vazias, espaços colapsados; todo separador de ``str.splitlines``
    (``\\n``, ``\\r``, U+2028...) é quebra."""
    return [" ".join(line.split()) for line in value.splitlines() if line.strip()]


def normalize_texts(hook, area=None, subtitle=None) -> dict:
    """Textos limpos (espaços colapsados por linha) ou ``CoverError``.

    O subtítulo é dividido no ÚLTIMO "\\n": antes dele, linha(s) brancas; depois,
    a linha em destaque. Sem "\\n", tudo branco.
    """
    if not isinstance(hook, str):
        raise CoverError("gancho obrigatório (texto de 1 a 28 caracteres, ex.: \"3 MITOS\")")
    lines = _lines(hook)
    if not lines:
        raise CoverError("gancho vazio: informe 1 a 28 caracteres (ex.: \"3 MITOS\")")
    if len(lines) > 2:
        raise CoverError("gancho com mais de 2 linhas")
    hook_n = "\n".join(lines)
    if len(" ".join(lines)) > HOOK_MAX_CHARS:
        raise CoverError(f"gancho com {len(' '.join(lines))} caracteres (máximo {HOOK_MAX_CHARS})")
    if area is not None and not isinstance(area, str):
        raise CoverError("área deve ser texto")
    area_n = " ".join((area or "").split()) or None
    if area_n and len(area_n) > AREA_MAX_CHARS:
        raise CoverError(f"área com {len(area_n)} caracteres (máximo {AREA_MAX_CHARS})")
    if subtitle is not None and not isinstance(subtitle, str):
        raise CoverError("subtítulo deve ser texto")
    sub = _lines(subtitle or "")
    if len(" ".join(sub)) > SUB_MAX_CHARS:
        raise CoverError(f"subtítulo com {len(' '.join(sub))} caracteres (máximo {SUB_MAX_CHARS})")
    if len(sub) >= 2:
        sub_main, sub_accent = "\n".join(sub[:-1]), sub[-1]
    else:
        sub_main, sub_accent = (sub[0] if sub else None), None
    return {"hook": hook_n, "area": area_n, "subMain": sub_main, "subAccent": sub_accent}


def _guard_output(out: Path, inputs: dict) -> None:
    """A saída nunca pode ser (nem apontar para) a foto, o logotipo ou o brand.json."""
    for what, path in inputs.items():
        if path is not None and common.same_file(out, path):
            raise CoverError(f"a saída {out} é o mesmo arquivo {what}; escolha outro caminho "
                             "(por exemplo capa/capa.png)")


def _handles(raw: list[str]) -> str:
    try:
        norm = list(dict.fromkeys(brandmod.normalize_handle(h) for h in raw))
    except ValueError as e:
        raise CoverError(str(e)) from None
    return " · ".join(norm[:2])


# ---------------------------------------------------------------- imagens

def _data_uri(img: Image.Image, fmt: str) -> str:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.save(buf, format="JPEG", quality=92)
        mime = "image/jpeg"
    else:
        img.save(buf, format="PNG")
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _lum(rgb) -> float:
    """Luminância relativa (WCAG) de uma cor sRGB 0-255."""
    c = [v / 255 for v in rgb[:3]]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _logo_box(logo_size: tuple[int, int]) -> tuple[float, float, float, float]:
    h = LOGO_WIDTH * logo_size[1] / logo_size[0]
    return (CANVAS[0] / 2 - LOGO_WIDTH / 2, LOGO_TOP, CANVAS[0] / 2 + LOGO_WIDTH / 2, LOGO_TOP + h)


def logo_scrim(img: Image.Image, position: str, logo_size: tuple[int, int], bg: str) -> float:
    """Opacidade do véu azul-marinho atrás do logotipo para o wordmark branco
    chegar a LOGO_CONTRAST contra o pedaço da foto que fica atrás dele.

    Mapeia a caixa do logotipo (com folga de 24 px) para a foto como o
    ``object-fit: cover`` do navegador, pega a cor do pixel no percentil 90 de
    luminância (o fundo claro é o que atrapalha) e procura a menor opacidade.
    """
    w, h = img.size
    s = max(CANVAS[0] / w, CANVAS[1] / h)
    px, py = (float(v.rstrip("%")) / 100 for v in position.split())
    ox, oy = (CANVAS[0] - w * s) * px, (CANVAS[1] - h * s) * py
    x0, y0, x1, y1 = _logo_box(logo_size)
    box = (max(0, int((x0 - 24 - ox) / s)), max(0, int((y0 - 24 - oy) / s)),
           min(w, int((x1 + 24 - ox) / s) + 1), min(h, int((y1 + 24 - oy) / s) + 1))
    region = img.crop(box)
    region.thumbnail((160, 160))
    pixels = sorted(_pixels(region), key=_lum)
    if not pixels:
        return 0.0
    c = pixels[int(0.9 * (len(pixels) - 1))]
    navy = tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5))
    limit = (WORDMARK_LUM + 0.05) / LOGO_CONTRAST - 0.05
    for step in range(0, 96):
        a = step / 100
        mix = [a * n + (1 - a) * v for n, v in zip(navy, c)]
        if _lum(mix) <= limit:
            return a
    return 0.95


def _pixels(img: Image.Image) -> list[tuple]:
    rgb = img.convert("RGB")
    return [rgb.getpixel((x, y)) for y in range(rgb.height) for x in range(rgb.width)]


def _photo(photo: Path) -> tuple[str, str, Image.Image]:
    """(data URI JPEG, object-position, imagem): retrato ancorado no terço de cima."""
    img = load_photo(Path(photo))  # CoverError: ausente, ilegível, pequena
    portrait = img.height >= img.width
    if max(img.size) > PHOTO_MAX_SIDE:
        img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE), Image.Resampling.LANCZOS)
    return _data_uri(img, "JPEG"), ("50% 28%" if portrait else "50% 50%"), img


def _logo(logo: Path) -> tuple[str, tuple[int, int]]:
    logo = Path(logo)
    if not logo.is_file():
        raise CoverError(f"logotipo não encontrado: {logo}")
    try:
        with Image.open(logo) as im:
            im.load()
            img = im.convert("RGBA")
    except Exception as e:  # formato desconhecido, truncado...
        raise CoverError(f"logotipo ilegível ({logo.name}): {e}") from None
    if max(img.size) > 2000:
        img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
    return _data_uri(img, "PNG"), img.size


def _fonts() -> list[dict]:
    out = []
    for f in graphics._font_files():
        p = Path(f["path"])
        mime = "font/otf" if p.suffix.lower() == ".otf" else "font/ttf"
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        out.append({"weight": f["weight"],
                    "url": f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")})
    return out


# ---------------------------------------------------------------- montagem

def _layout() -> dict:
    return {"width": CANVAS[0], "height": CANVAS[1], "margin": MARGIN,
            "safeTop": SAFE_TOP, "safeBottom": SAFE_BOTTOM,
            "gridTop": GRID_CROP[0], "gridBottom": GRID_CROP[1],
            "logoTop": LOGO_TOP, "logoWidth": LOGO_WIDTH, "blockBottom": BLOCK_BOTTOM,
            "handleTop": HANDLE_TOP, "hookMax": HOOK_MAX, "hookMin": HOOK_MIN,
            "hookStep": HOOK_STEP, "subSize": SUB_SIZE, "areaSize": AREA_SIZE,
            "handleSize": HANDLE_SIZE, "shade": list(SHADE)}


def _prepare(photo, title, brand, area, subtitle, logo, out=None, brand_path=None) -> dict:
    """Tudo o que não escreve nada: guarda da saída, textos, imagens e dados da página."""
    logo_path = Path(logo) if logo is not None else LOGO
    if out is not None:
        _guard_output(out, {"da foto": photo, "do logotipo": logo_path, "do brand.json": brand_path})
    tokens = graphics._brand_tokens(brand)
    t = normalize_texts(title, area, subtitle)
    handle = _handles(brandmod.require_handles(brand))
    photo_uri, position, img = _photo(photo)
    logo_uri, logo_size = _logo(logo_path)
    scrim = logo_scrim(img, position, logo_size, tokens["colors"]["bg"])
    return {"data": {**t, "handle": handle, "photo": photo_uri, "photoPosition": position,
                     "logo": logo_uri, "logoScrim": scrim, **tokens, "fontFiles": _fonts(),
                     "layout": _layout()},
            "logo": logo_path}


def _check_measures(info: dict) -> None:
    """Contrato medido no navegador: gancho em até 2 linhas e bloco abaixo do rosto."""
    if info.get("hookLines", 0) > 2:
        raise CoverError("gancho não cabe em 2 linhas: encurte")
    block = (info.get("boxes") or {}).get("block")
    if block is not None and block["top"] < BLOCK_TOP_MIN:
        raise CoverError("texto longo demais para a capa: encurte o subtítulo")


def _need_browser() -> None:
    reason = graphics.browser_status()
    if reason:
        raise graphics.RendererMissing(f"capa: renderizador indisponível: {reason}")


def _run_page(data: dict, workdir: Path, shot: Path | None) -> dict:
    job = {"html": str(TEMPLATE), "width": CANVAS[0], "height": CANVAS[1], "data": data,
           "shot": str(shot) if shot else None}
    return graphics._drive(job, workdir, "capa", driver=DRIVER)


def outside_safe_area(info: dict) -> list[str]:
    """Nomes das caixas de texto fora das áreas seguras ou das margens."""
    bad = []
    lo, hi = max(SAFE_TOP, GRID_CROP[0]), min(CANVAS[1] - SAFE_BOTTOM, GRID_CROP[1])
    for name in TEXT_BOXES:
        b = (info.get("boxes") or {}).get(name)
        if b is None:
            continue
        if b["top"] < lo or b["bottom"] > hi or b["left"] < MARGIN - 14 \
                or b["right"] > CANVAS[0] - MARGIN + 14:
            bad.append(name)
    return bad


def inspect(photo: Path, title: str, brand: dict, *, area: str | None = None,
            subtitle: str | None = None, logo: Path | None = None,
            shot: Path | None = None) -> dict:
    """Medidas da capa montada no navegador (caixas em px de 1080x1920, textos,
    corpo do gancho, linhas...). Para testes e diagnóstico; ``shot`` grava o PNG."""
    prep = _prepare(photo, title, brand, area, subtitle, logo)
    _need_browser()
    with tempfile.TemporaryDirectory(prefix="reel-capa-") as td:
        info = _run_page(prep["data"], Path(td), Path(shot) if shot else None)
    _check_measures(info)
    info["logo"] = str(prep["logo"])
    info["logoScrim"] = prep["data"]["logoScrim"]
    return info


def compose(photo: Path, title: str, brand: dict, out_png: Path, *, area: str | None = None,
            subtitle: str | None = None, logo: Path | None = None,
            brand_path: Path | None = None) -> Path:
    """Desenha a capa em ``out_png`` (PNG 1080x1920 opaco, gravado de forma atômica).

    ``title`` é o gancho (texto grande). Levanta ``BrandMissing`` sem @ (nada é
    aberto nem gravado), ``CoverError`` para texto/foto/@ inválidos e ``GraphicsError``/``RendererMissing`` do
    navegador. Foto e logotipo nunca são alterados; ``out_png`` igual à foto, ao
    logotipo ou a ``brand_path`` (mesmo via link) é recusado com ``CoverError``.
    """
    out = Path(out_png)
    prep = _prepare(photo, title, brand, area, subtitle, logo, out=out, brand_path=brand_path)
    _need_browser()
    with tempfile.TemporaryDirectory(prefix="reel-capa-") as td:
        shot = Path(td) / "capa.png"
        info = _run_page(prep["data"], Path(td), shot)
        _check_measures(info)
        bad = outside_safe_area(info)
        if bad:
            raise graphics.GraphicsError(
                f"capa: texto fora da área segura ({', '.join(bad)}); encurte o texto")
        try:
            with Image.open(shot) as im:
                im.load()
                size = im.size
                img = im.convert("RGB")
        except Exception as e:
            raise graphics.GraphicsError(f"capa: o navegador não gerou a imagem: {e}") from None
        if size != CANVAS:
            raise graphics.GraphicsError(f"capa: imagem com {size[0]}x{size[1]}, esperado 1080x1920")
        created = _created_chain(out.parent)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            # nome único criado com O_EXCL (não segue link plantado nem colide com
            # outra execução), modo normal de arquivo
            with common.atomic_write(out, suffix=".png") as tmp:
                img.save(tmp, format="PNG")
        except BaseException:
            for d in created:  # só o que esta chamada criou, e só se ficou vazio
                try:
                    d.rmdir()
                except OSError:
                    break
            raise
    return out


# ---------------------------------------------------------------- CLI

def cli_text(value: str | None) -> str | None:
    """Na linha de comando, "\\n" digitado (barra + n) vira quebra de linha."""
    return None if value is None else value.replace("\\n", "\n")


def main(argv: list[str] | None = None) -> None:
    parser = common.UsageParser(prog="cover_compose.py", description="Desenha a capa do Reel.")
    parser.add_argument("photo", type=Path, help="capa/candidato-N.png ou capa/foto.png")
    parser.add_argument("brand", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--hook", required=True, help='gancho, ex.: "3 MITOS" (até 28 caracteres)')
    parser.add_argument("--area", default=None, help='pill da área, ex.: "ISENÇÃO DE IR"')
    parser.add_argument("--subtitle", default=None,
                        help='subtítulo; a parte depois do último \\n sai em destaque')
    parser.add_argument("--logo", type=Path, default=None, help="padrão: assets/logo.webp")
    args = parser.parse_args(argv)
    try:
        b = brandmod.load(args.brand)
        out = compose(args.photo, cli_text(args.hook), b, args.out, area=cli_text(args.area),
                      subtitle=cli_text(args.subtitle), logo=args.logo, brand_path=args.brand)
    except brandmod.BrandMissing as e:
        common.fail(str(e))
    except (CoverError, graphics.GraphicsError, OSError, ValueError) as e:
        common.fail(str(e))
    print(out)


if __name__ == "__main__":
    main()
