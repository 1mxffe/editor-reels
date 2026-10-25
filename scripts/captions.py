"""Legendas estaticas por frase: remapeia palavras apos os cortes, agrupa em frases e gera ASS.

Sem animacao: unico override permitido e o fade de 100 ms no inicio de cada Dialogue
(com ``estilo``, tambem um ``\\fs`` estatico quando a frase precisa de fonte menor).
Os quatro estilos do banco (faixa, pilula, duas-linhas, pequena), a posicao e o tamanho
vem de ``estilo_legenda``, a mesma descricao usada pelas legendas por imagem.
A CLI (``captions.py <palavras.json> <brand.json> <out.ass>``) e de
uso interno/depuracao: grava so o ASS; a legenda do Reel sai so pelo ``render.py``,
que aplica cortes e edicoes de legenda antes.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

FADE_MS = 100
MIN_DISPLAY = 0.4
GAP_SPLIT = 0.6
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]*$")


def remap(words: list[dict], keep: list[tuple[float, float]]) -> list[dict]:
    """Move palavras para a linha do tempo pos-corte (segmentos mantidos colados em sequencia).

    `keep` fora de ordem ou sobreposto e ordenado e fundido antes. Palavra de
    duracao zero conta como dentro do segmento que a contem.
    """
    merged: list[list[float]] = []
    for s, e in sorted(keep):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    keep = [(s, e) for s, e in merged]
    offsets, acc = [], 0.0
    for s, e in keep:
        offsets.append(acc)
        acc += e - s
    out = []
    for w in words:
        best, best_ov = None, 0.0
        for i, (s, e) in enumerate(keep):
            ov = min(w["end"], e) - max(w["start"], s)
            if ov > best_ov:
                best, best_ov = i, ov
            elif best is None and w["start"] == w["end"] and s <= w["start"] <= e:
                best = i  # duracao zero: contencao em vez de sobreposicao
        if best is None:
            continue
        s, e = keep[best]
        ns = offsets[best] + max(w["start"], s) - s
        ne = offsets[best] + min(w["end"], e) - s
        item = dict(w)
        item["start"], item["end"] = round(ns, 3), round(ne, 3)
        out.append(item)
    out.sort(key=lambda x: x["start"])
    return out


def phrases(words: list[dict], max_chars: int = 38, max_lines: int = 2) -> list[dict]:
    """Agrupa palavras em frases de ate max_lines linhas de ate max_chars caracteres."""
    result: list[dict] = []
    lines: list[str] = []
    first = last = None  # primeira/ultima palavra da frase corrente

    def close():
        nonlocal lines, first, last
        if lines:
            result.append({"text": "\n".join(lines), "start": first["start"], "end": last["end"]})
        lines, first, last = [], None, None

    for w in words:
        token = " ".join(w["w"].split())  # "\n" interno nao cria linha extra
        if not token:
            continue
        if last is not None and round(w["start"] - last["end"], 3) > GAP_SPLIT:
            close()
        if lines and len(lines[-1]) + 1 + len(token) <= max_chars:
            lines[-1] += " " + token
        elif lines and len(lines) >= max_lines:
            close()
            lines = [token]
        elif lines:
            lines.append(token)
        else:
            lines = [token]
        if first is None:
            first = w
        last = w
        if _SENTENCE_END.search(token):
            close()
    close()

    for i, p in enumerate(result):
        end = max(p["end"], p["start"] + MIN_DISPLAY)
        if i + 1 < len(result):
            end = min(end, result[i + 1]["start"])
        p["end"] = round(end, 3)
        p["start"] = round(p["start"], 3)
    return result


def apply_edits(phrase_list: list[dict], edits: list[dict]) -> tuple[list[dict], list[int]]:
    """Aplica edicoes manuais de legenda (``{"idx","base_text","text"}``) as frases automaticas.

    Uma edicao so vale se ``base_text`` ainda for o texto automatico da frase
    ``idx``; as demais (obsoletas ou fora do intervalo) sao ignoradas e seus
    ``idx`` devolvidos. Tempos nunca mudam.
    """
    out = [dict(p) for p in phrase_list]
    stale: list[int] = []
    for e in edits:
        idx = e["idx"]
        if 0 <= idx < len(out) and out[idx]["text"] == e["base_text"]:
            out[idx]["text"] = e["text"]
        else:
            stale.append(idx)
    return out, stale


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"cor invalida: {hex_rgb!r}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    cs = int(round(max(t, 0.0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


_ASS_SPECIAL = str.maketrans({"\\": " ", "{": "(", "}": ")"})


def display_text(text: str) -> str:
    """Texto exatamente como a legenda o desenha (usado pelo ASS e pela revisao).

    ``\\`` vira espaco e chaves viram parenteses (o ASS as trataria como codigo);
    cada separador de linha de ``str.splitlines`` (``\\n``, ``\\r``, U+2028...) e
    uma quebra; espacos colapsados por linha; linhas vazias saem.
    """
    lines = [" ".join(line.split()) for line in text.translate(_ASS_SPECIAL).splitlines()]
    return "\n".join(line for line in lines if line)


def _escape(text: str) -> str:
    return display_text(text).replace("\n", "\\N")


# Estilos de legenda (estilo.json). Medidas em 1080x1920, tamanho M; ``caixa``:
# "faixa" = uma caixa por linha (BorderStyle 3), "pilula" = idem com cantos
# arredondados no caminho por imagem; sem caixa = contorno (BorderStyle 1).
TIPOS = {
    "faixa": {"fontsize": 64, "outline": 14, "contorno": 0, "caixa": "faixa", "alpha": 0x73,
              "alinhar": "centro"},
    "pilula": {"fontsize": 60, "outline": 20, "contorno": 0, "caixa": "pilula",
               "alpha": round(255 * 0.15), "alinhar": "centro"},  # fundo a 85 %
    "duas-linhas": {"fontsize": 76, "outline": 0, "contorno": 5, "caixa": None, "alpha": 0,
                    "alinhar": "centro"},
    "pequena": {"fontsize": 50, "outline": 0, "contorno": 4, "caixa": None, "alpha": 0,
                "alinhar": "esquerda"},
}
ESCALA = {"P": 0.85, "M": 1.0, "G": 1.2}
MAX_LINES = 2
_ALIGN = {("centro", "baixo"): 2, ("esquerda", "baixo"): 1,
          ("centro", "meio"): 5, ("esquerda", "meio"): 4}


def estilo_legenda(estilo: dict | None, brand: dict | None, size: tuple[int, int] = (1080, 1920)) -> dict:
    """Descricao unica do desenho da legenda, usada pelo ASS e pelas legendas por imagem.

    ``estilo=None``: a faixa de sempre (64/14/72/340 em 1080x1920), com ``fg``/``bg``
    do brand. Com estilo (estilo.json), o tipo vem do item do banco e ``posicao`` /
    ``tamanho`` do proprio estilo; as cores continuam vindo do ``brand`` (ja com a
    paleta aplicada por ``estilo.aplicar_marca``)."""
    k = size[1] / 1920
    if estilo is None:
        tipo, vertical, escala = "faixa", "baixo", 1.0
    else:
        import banco as bancomod
        import estilo as estilomod
        b = bancomod.carregar()
        est = estilomod.validar(estilo, b)
        tipo = estilomod.tipo_legenda(est, b)
        vertical, escala = est["legenda"]["posicao"], ESCALA[est["legenda"]["tamanho"]]
    base = TIPOS[tipo]
    return {
        "tipo": tipo,
        "fontsize": round(base["fontsize"] * escala * k),
        "outline": round(base["outline"] * escala * k),  # folga da caixa (BorderStyle 3)
        "contorno": max(1, round(base["contorno"] * escala * k)) if base["contorno"] else 0,
        "mlr": round(72 * k),
        "mv": round(340 * k),
        "caixa": base["caixa"],
        "alpha": base["alpha"],
        "raio": round(base["outline"] * escala * k),
        "alinhar": base["alinhar"],
        "vertical": vertical,
        "an": _ALIGN[(base["alinhar"], vertical)],
        "fg": brand["fg"] if brand else None,
        "bg": brand["bg"] if brand else None,
        "font": brand["font_body"] if brand else None,
        "max_lines": MAX_LINES,
    }


def to_ass(phrases: list[dict], brand: dict, size: tuple[int, int] = (1080, 1920),
           estilo: dict | None = None) -> str:
    """ASS das frases. ``estilo=None``: saida identica a de sempre (texto como veio).

    Com ``estilo``, cada frase passa pelo mesmo layout das legendas por imagem
    (quebra em ate 2 linhas na largura util, fonte reduzida so se nao couber, com
    ``\\fs`` estatico); nenhuma tag de animacao alem do ``\\fad``."""
    w, h = size
    import brand as brandmod  # o nome da fonte vai cru para a linha Style:
    if not brandmod.valid_name(brand["font_body"]):
        raise ValueError(f"fonte invalida: {brand['font_body']!r}")
    p = estilo_legenda(estilo, brand, size)
    primary = _ass_color(p["fg"])
    if p["caixa"]:
        border, borda = 3, p["outline"]
        outline_col = back = _ass_color(p["bg"], alpha=p["alpha"])
    else:
        border, borda = 1, p["contorno"]
        outline_col, back = _ass_color(p["bg"]), _ass_color(p["bg"], alpha=0x73)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Legenda,{brand['font_body']},{p['fontsize']},{primary},{primary},{outline_col},{back},"
        f"-1,0,0,0,100,100,0,0,{border},{borda},0,{p['an']},{p['mlr']},{p['mlr']},{p['mv']},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for ph in phrases:
        if estilo is None:
            text, tags = _escape(ph["text"]), ""
        else:
            import legendas_imagem  # mesmo layout (Pillow) das legendas por imagem
            _, _, fs, lines, _ = legendas_imagem.layout(ph["text"], size, p)
            text = "\\N".join(lines)
            tags = f"\\fs{fs}" if fs != p["fontsize"] else ""
        if not text:
            continue
        events.append(
            f"Dialogue: 0,{_ts(ph['start'])},{_ts(ph['end'])},Legenda,,0,0,0,,"
            f"{{\\fad({FADE_MS},{FADE_MS}){tags}}}{text}"
        )
    return header + "\n".join(events) + ("\n" if events else "")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        common.fail("uso: captions.py <palavras.json> <brand.json> <out.ass> (uso interno/depuracao: "
                    "so o ASS; a legenda do Reel sai pelo render.py)")
    import brand as brandmod

    try:
        data = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
        b = brandmod.load(Path(argv[1]))
    except (OSError, json.JSONDecodeError, brandmod.BrandMissing) as e:
        common.fail(str(e))
    words = data.get("words") if isinstance(data, dict) else None
    if not isinstance(words, list):
        common.fail(f'{argv[0]} deve ser um objeto com a lista "words"')
    for i, w in enumerate(words):
        if not (isinstance(w, dict) and isinstance(w.get("w"), str)
                and common.is_num(w.get("start")) and common.is_num(w.get("end"))):
            common.fail(f"{argv[0]}: palavra {i} precisa de w (texto) e start/end numericos finitos")
    try:
        ass = to_ass(phrases(words), b)
    except (ValueError, KeyError, TypeError) as e:
        common.fail(f"brand/palavras invalidos para a legenda: {e}")
    out = Path(argv[2])
    try:
        with common.atomic_write(out) as tmp:
            tmp.write_text(ass, encoding="utf-8")
    except OSError as e:
        common.fail(f"nao foi possivel gravar {out}: {e}")


if __name__ == "__main__":
    main()
