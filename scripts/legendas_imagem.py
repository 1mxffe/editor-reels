"""Legendas por imagem: caminho alternativo quando o ffmpeg nao tem libass.

Cada frase (a mesma lista que alimentaria o ASS, ja com cortes e edicoes) vira um
PNG RGBA transparente do tamanho exato da saida, desenhado com Pillow e as fontes
Poppins do repositorio, replicando o estilo de ``captions.to_ass``: Poppins Bold,
cor ``fg``, faixa ``bg`` translucida por linha (BorderStyle 3, alpha 0x73), base
centralizada a ``MarginV`` do rodape, ate 2 linhas dentro da largura util. Com
``estilo`` (estilo.json) as medidas, a caixa (faixa, pilula arredondada) ou o
contorno, a posicao e o tamanho vem da mesma descricao do ASS
(``captions.estilo_legenda``), e o ASS usa este mesmo ``layout``.

As frases sao compostas por UMA entrada ffmpeg: um roteiro do demuxer ``concat``
(PNG transparente nos intervalos, PNG da frase durante a frase) e um unico
``overlay``. Escala para centenas de frases sem crescer a linha de comando nem o
filtergraph (uma entrada ``-loop 1`` por frase abriria dezenas de decodificadores).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import captions  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FONT = REPO / "assets" / "fonts" / "Poppins-Bold.ttf"  # o Style do ASS usa Bold=-1
MAX_LINES = 2


class PillowMissing(Exception):
    pass


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise PillowMissing("as legendas por imagem precisam do Pillow; "
                            "rode: pip install Pillow") from None
    return Image, ImageDraw, ImageFont


def _rgb(hex_rgb: str) -> tuple[int, int, int]:
    captions._ass_color(hex_rgb)  # mesma validacao do ASS
    h = hex_rgb.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _metrics(size: tuple[int, int], estilo: dict | None = None) -> dict:
    """Medidas do desenho: a mesma descricao que o ASS usa (``captions.estilo_legenda``)."""
    return captions.estilo_legenda(estilo, None, size)


def _win_metrics() -> tuple[int, int, int]:
    """(unitsPerEm, usWinAscent, usWinDescent) lidos das tabelas head e OS/2 do TTF."""
    data = FONT.read_bytes()
    n = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(n):
        rec = data[12 + 16 * i: 28 + 16 * i]
        tables[rec[:4]] = struct.unpack(">I", rec[8:12])[0]
    upem = struct.unpack(">H", data[tables[b"head"] + 18: tables[b"head"] + 20])[0]
    os2 = tables[b"OS/2"]
    asc, desc = struct.unpack(">HH", data[os2 + 74: os2 + 78])
    return upem, asc, desc


def _font(fontsize: int):
    """Fonte na escala do libass: usWinAscent+usWinDescent = Fontsize (como o VSFilter).

    Devolve (fonte, ascendente em px): a linha ocupa ``fontsize`` px de altura."""
    _, _, ImageFont = _pil()
    upem, asc, desc = _win_metrics()
    px = fontsize * upem / (asc + desc)
    return ImageFont.truetype(str(FONT), max(1, round(px))), fontsize * asc / (asc + desc)


def wrap(text: str, font, max_width: float, max_lines: int = MAX_LINES) -> list[str]:
    """Linhas finais: as do texto (``display_text``) re-quebradas na largura util."""
    shown = captions.display_text(text)
    if not shown:
        return []
    orig = shown.split("\n")  # quebras de captions.phrases, como no ASS, quando cabem
    if len(orig) <= max_lines and all(font.getlength(line) <= max_width for line in orig):
        return orig
    lines: list[str] = []
    for w in shown.split():
        if lines and font.getlength(lines[-1] + " " + w) <= max_width:
            lines[-1] += " " + w
        else:
            lines.append(w)
    if len(lines) <= max_lines and all(font.getlength(line) <= max_width for line in lines):
        return lines
    return None  # nao cabe: o chamador reduz a fonte


def layout(text: str, size: tuple[int, int], params: dict | None = None):
    """(fonte, ascendente, tamanho, linhas, medidas) da frase; ``params`` vem de
    ``captions.estilo_legenda`` (``None`` = faixa de sempre). O ASS com estilo usa
    este mesmo layout, entao as quebras e o tamanho sao iguais nos dois caminhos."""
    m = params if params is not None else _metrics(size)
    max_width = size[0] - 2 * m["mlr"] - 2 * m["outline"] - 2 * m.get("contorno", 0)
    max_lines = m.get("max_lines", MAX_LINES)
    fs = m["fontsize"]
    while True:
        font, ascent = _font(fs)
        lines = wrap(text, font, max_width, max_lines)
        if lines is not None or fs <= 8:
            break
        fs -= 1
    if lines is None:
        lines = wrap(text, font, 10 ** 9, max_lines)  # ultimo recurso
    return font, ascent, fs, lines, m


def draw(text: str, brand: dict, size: tuple[int, int], estilo: dict | None = None, *,
         params: dict | None = None):
    """PNG RGBA da frase. ``estilo=None``: a faixa de sempre (igual ao golden).
    ``params``: ``captions.estilo_legenda`` ja calculado (evita refazer por frase)."""
    Image, ImageDraw, _ = _pil()
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    p = params if params is not None else captions.estilo_legenda(estilo, brand, size)
    font, ascent, line_h, lines, m = layout(text, size, p)
    if not lines:
        return img
    fg, bg = _rgb(p["fg"]), _rgb(p["bg"])
    pad = m["outline"]
    w, h = size
    if p["vertical"] == "meio":  # bloco centrado na tela, como o \an5 do libass
        top0 = (h - line_h * len(lines)) / 2
    else:
        top0 = h - m["mv"] - line_h * len(lines)

    def x_de(lw: float) -> float:
        return float(m["mlr"]) if p["alinhar"] == "esquerda" else (w - lw) / 2

    if p["caixa"]:
        alpha = 255 - p["alpha"]
        for i, line in enumerate(lines):  # uma caixa por linha; sobreposicao escurece, como no libass
            lw = font.getlength(line)
            x0, y0 = x_de(lw), top0 + i * line_h
            rect = [round(x0 - pad), round(y0 - pad), round(x0 + lw + pad) - 1,
                    round(y0 + line_h + pad) - 1]
            box = Image.new("RGBA", size, (0, 0, 0, 0))
            if p["caixa"] == "pilula":
                ImageDraw.Draw(box).rounded_rectangle(rect, radius=p["raio"], fill=(*bg, alpha))
            else:
                ImageDraw.Draw(box).rectangle(rect, fill=(*bg, alpha))
            img.alpha_composite(box)
    td = ImageDraw.Draw(img)
    stroke = {"stroke_width": p["contorno"], "stroke_fill": (*bg, 255)} if p["contorno"] else {}
    for i, line in enumerate(lines):
        lw = font.getlength(line)
        td.text((x_de(lw), top0 + i * line_h + ascent), line, font=font,
                fill=(*fg, 255), anchor="ls", **stroke)
    return img


def write_track(phrases: list[dict], brand: dict, size: tuple[int, int], tmpdir: Path,
                estilo: dict | None = None) -> Path:
    """Grava os PNGs e o roteiro concat em ``tmpdir``; devolve o roteiro."""
    Image, _, _ = _pil()
    tmpdir = Path(tmpdir)
    blank = tmpdir / "vazio.png"
    Image.new("RGBA", size, (0, 0, 0, 0)).save(blank)
    params = captions.estilo_legenda(estilo, brand, size)
    entries: list[tuple[Path, float]] = []
    t = 0.0
    for i, p in enumerate(phrases):
        if not captions.display_text(p["text"]):
            continue
        start, end = max(p["start"], t), p["end"]
        if end <= start:
            continue
        if start > t:
            entries.append((blank, start - t))
        png = tmpdir / f"frase-{i:04d}.png"
        draw(p["text"], brand, size, params=params).save(png)
        entries.append((png, end - start))
        t = end
    entries.append((blank, 1.0))
    lines = ["ffconcat version 1.0"]
    for path, dur in entries:
        lines += [f"file '{path.name}'", f"duration {dur:.3f}"]
    lines.append(f"file '{blank.name}'")  # o concat ignora a duracao do ultimo item
    script = tmpdir / "legendas.ffconcat"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return script
