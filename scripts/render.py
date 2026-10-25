"""Render do Reel: cortes, cards de graficos e legendas queimadas.

Layout do projeto (um diretorio por Reel, ``projects/<reel>/``)::

    projects/<reel>/
        entrada.<ext>      video bruto; exatamente um arquivo ``entrada.*``; nunca alterado
        transcricao.json   {"duration", "words": [{"w", "start", "end"}]} (transcribe.py)
        cortes.json        {"cuts": [{"id", "start", "end", "kind"}]} (cut.py detect / revisao)
        estilo.json        opcional: paleta, fonte, legenda e cards (scripts/estilo.py);
                           sem ele o resultado e o de sempre
        graficos.json      opcional: {"cards": [{id, title, body, at, dur, material}]}
                           (``at`` na linha do tempo cortada; ver graphics.py)
        revisao.json       opcional: {"graphics": {"<id>": "drop"}} tira o card
        saida/
            preview.mp4    rascunho 540x960
            final.mp4      arquivo final 1080x1920

Ordem fixa: transcricao + cortes (sem fala ou palavra malformada -> erro) -> palavras
mantidas e frases -> cards de graficos.json validados (menos os descartados na
revisao) -> brand.load (marca ausente ou incompleta levanta BrandMissing; nada e
inventado) -> renderizador de graficos disponivel (so com cards) -> cut.apply em
arquivo temporario -> cards desenhados (WebM com alfa) -> segunda passada: escala
para cobrir + corte central, 30 fps, cards sobrepostos no instante ``at``,
legendas ASS queimadas por cima (ffmpeg sem libass: legendas por imagem, PNG por
frase via legendas_imagem.py, mesma ordem de camadas), libx264 + aac. A saida e gravada por
``common.atomic_write`` (temporario de nome unico no mesmo diretorio, modo normal de
arquivo) e renomeada ao fim; temporarios sao apagados tambem em caso de falha.

Uso: python3 -I scripts/render.py <projeto> preview|final [--brand <brand.json>]
Saida: 0 ok; 1 erro (mensagem ``erro: ...``).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from typing import Literal  # noqa: E402

import brand as brandmod  # noqa: E402
import captions  # noqa: E402
import common  # noqa: E402
import cut  # noqa: E402
import estilo as estilomod  # noqa: E402
import graphics  # noqa: E402
import legendas_imagem  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BRAND = REPO / "brand" / "brand.json"
FONTS_DIR = REPO / "assets" / "fonts"

SIZES = {"preview": (540, 960), "final": (1080, 1920)}
FPS = 30


class ProjectError(Exception):
    """Diretorio de projeto incompleto ou invalido."""


def _find_entrada(project: Path) -> Path:
    found = sorted(p for p in project.glob("entrada.*") if p.is_file())
    if not found:
        raise ProjectError(f"nenhum arquivo entrada.* em {project}")
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise ProjectError(f"mais de um arquivo entrada.* em {project}: {names}")
    return found[0]


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProjectError(f"arquivo ausente: {path}") from None
    except (OSError, ValueError) as e:
        raise ProjectError(f"arquivo ilegivel ({path}): {e}") from e
    if not isinstance(data, dict):
        raise ProjectError(f"{path}: esperado objeto JSON")
    return data


def _load_inputs(project: Path) -> tuple[float, list, list]:
    transcript = _read_json(project / "transcricao.json")
    cuts_doc = _read_json(project / "cortes.json")
    try:
        duration = float(transcript["duration"])
        words = list(transcript.get("words") or [])
        cuts = list(cuts_doc["cuts"])
    except (KeyError, TypeError, ValueError) as e:
        raise ProjectError(f"transcricao.json ou cortes.json invalido: {e}") from e
    if not common.is_num(duration):
        raise ProjectError(f"transcricao.json invalido: duration precisa ser numero finito, nao {duration}")
    if not words:
        # Mesmo criterio do `cut.py detect`: sem fala nao ha o que legendar.
        raise ProjectError("nenhuma fala detectada em transcricao.json")
    for i, w in enumerate(words):
        if not (isinstance(w, dict) and isinstance(w.get("w"), str)
                and common.is_num(w.get("start")) and common.is_num(w.get("end"))):
            raise ProjectError(
                f"transcricao.json invalido: palavra {i} precisa de w (texto) e start/end numericos")
    for i, c in enumerate(cuts):
        if not (isinstance(c, dict) and common.is_num(c.get("start")) and common.is_num(c.get("end"))):
            raise ProjectError(f"cortes.json invalido: corte {i} precisa de start/end numericos")
    return duration, words, cuts


def load_edits(project: Path) -> list[dict]:
    """Edicoes manuais de legenda de ``legendas.json`` (ausente = nenhuma)."""
    path = Path(project) / "legendas.json"
    if not path.exists():
        return []
    doc = _read_json(path)
    edits = doc.get("edits", [])
    ok = isinstance(edits, list) and all(
        isinstance(e, dict) and isinstance(e.get("idx"), int) and not isinstance(e["idx"], bool)
        and isinstance(e.get("base_text"), str) and isinstance(e.get("text"), str)
        for e in edits)
    if not ok:
        raise ProjectError('legendas.json invalido: "edits" precisa de itens {idx, base_text, text}')
    return edits


def load_cards(project: Path) -> list[dict]:
    """Cards validados de ``graficos.json``, sem os marcados "drop" em ``revisao.json``."""
    cards = graphics.load_cards(project)
    rev_path = Path(project) / "revisao.json"
    decisions = _read_json(rev_path).get("graphics", {}) if rev_path.exists() else {}
    if not isinstance(decisions, dict):
        raise ProjectError('revisao.json invalido: "graphics" deve ser {id: keep|drop}')
    return [c for c in cards if decisions.get(c["id"]) != "drop"]


def _fit_cards(cards: list[dict], total: float) -> list[dict]:
    """Encurta cards que passam do fim do video cortado; ignora os que nao cabem 1 s."""
    fitted = []
    for c in cards:
        left = round(total - c["at"], 3)
        if left < graphics.DUR_MIN:
            print(f"aviso: grafico {c['id']!r} ignorado: comeca em {c['at']:.2f} s e o video "
                  f"cortado tem {total:.2f} s", file=sys.stderr)
            continue
        if c["dur"] > left:
            print(f"aviso: grafico {c['id']!r} encurtado para {left:.2f} s (fim do video)",
                  file=sys.stderr)
            c = {**c, "dur": left}
        fitted.append(c)
    return fitted


def _escape_filter_value(value: str) -> str:
    """Escapa um valor de opcao de filtro em dois niveis (opcao e filtergraph)."""
    lvl1 = "".join("\\" + c if c in "\\':" else c for c in value)
    return "".join("\\" + c if c in "\\'[],;" else c for c in lvl1)


def _encode_args(quality: str) -> list[str]:
    if quality == "final":
        crf, preset, abr = "18", "medium", "192k"
    else:
        crf, preset, abr = "28", "veryfast", "128k"
    return ["-c:v", "libx264", "-crf", crf, "-preset", preset, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", abr]


def _base_filter(size: tuple[int, int]) -> str:
    w, h = size
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={FPS}"


def _subtitles_filter(ass: Path) -> str:
    sub = f"subtitles=filename={_escape_filter_value(str(ass))}"
    if FONTS_DIR.is_dir():
        sub += f":fontsdir={_escape_filter_value(str(FONTS_DIR))}"
    return sub


def _video_filter(size: tuple[int, int], ass: Path) -> str:
    return f"{_base_filter(size)},{_subtitles_filter(ass)}"


def has_libass() -> bool:
    """O ffmpeg tem o filtro ``subtitles``? (falha na deteccao = sim, caminho atual)"""
    return common.ffmpeg_has_libass()


def _image_captions_filter(size: tuple[int, int], cards: list[dict], track_input: int) -> str:
    """Grafo sem libass: cards (entradas 1..n) e, por cima, a trilha de PNGs das frases."""
    parts = [f"[0:v]{_base_filter(size)}[b0]"]
    for i, c in enumerate(cards, 1):
        at, end = f"{c['at']:.3f}", f"{c['at'] + c['dur']:.3f}"
        parts.append(f"[{i}:v]setpts=PTS-STARTPTS+{at}/TB[g{i}]")
        parts.append(f"[b{i - 1}][g{i}]overlay=x=0:y=0:eof_action=pass:"
                     f"enable='between(t,{at},{end})'[b{i}]")
    parts.append(f"[{track_input}:v]format=rgba[leg]")
    parts.append(f"[b{len(cards)}][leg]overlay=x=0:y=0:eof_action=pass:repeatlast=0,"
                 "format=yuv420p[vout]")
    return ";".join(parts)


def _cards_filter(size: tuple[int, int], ass: Path, cards: list[dict]) -> str:
    """Grafo com os cards (entradas 1..n) sobrepostos ANTES das legendas (legenda por cima)."""
    parts = [f"[0:v]{_base_filter(size)}[b0]"]
    for i, c in enumerate(cards, 1):
        at, end = f"{c['at']:.3f}", f"{c['at'] + c['dur']:.3f}"
        parts.append(f"[{i}:v]setpts=PTS-STARTPTS+{at}/TB[g{i}]")
        parts.append(f"[b{i - 1}][g{i}]overlay=x=0:y=0:eof_action=pass:"
                     f"enable='between(t,{at},{end})'[b{i}]")
    parts.append(f"[b{len(cards)}]{_subtitles_filter(ass)}[vout]")
    return ";".join(parts)


def _has_audio(video: Path) -> bool:
    out = common.run(["ffprobe", "-v", "error", "-select_streams", "a",
                      "-show_entries", "stream=index", "-of", "csv=p=0", str(video)])
    return bool(out.strip())


def render(project: Path, quality: Literal["preview", "final"],
           brand_path: Path = DEFAULT_BRAND) -> Path:
    project = Path(project)
    if quality not in SIZES:
        raise ValueError(f"qualidade invalida: {quality!r} (use preview ou final)")
    size = SIZES[quality]

    # (1) entradas (estilo.json primeiro: estilo invalido e avisado antes de tudo)
    entrada = _find_entrada(project)
    arq_estilo = project / estilomod.ARQUIVO
    est = estilomod.carregar(project) if arq_estilo.exists() or arq_estilo.is_symlink() else None
    duration, words, cuts = _load_inputs(project)
    # (2)-(3) linha do tempo pos-corte e frases
    keep = cut.keep_segments(duration, cuts)
    kept = captions.remap(words, keep)
    phrases, stale = captions.apply_edits(captions.phrases(kept), load_edits(project))
    for idx in stale:  # edicao feita sobre outro corte/texto: nao se aplica
        print(f"aviso: edicao de legenda obsoleta ignorada (frase {idx})", file=sys.stderr)
    # (4) cards de graficos.json nao descartados na revisao
    cards = load_cards(project)
    # (5) marca: BrandMissing propaga, nunca inventa valores
    brand = brandmod.load(Path(brand_path))
    # estilo.json do projeto (opcional): paleta/fonte viram um brand efetivo (copia;
    # brand.json intacto) e a legenda ganha estilo/posicao/tamanho. Sem o arquivo,
    # nada muda (estilo=None: o .ass e byte a byte o de sempre).
    if est is not None:
        brand = estilomod.aplicar_marca(brand, est)
    try:
        ass_text = captions.to_ass(phrases, brand, size=size, estilo=est)
    except (ValueError, KeyError, TypeError) as e:
        raise brandmod.BrandMissing(f"brand.json com valor inválido ({brand_path}): {e}") from e
    cards = _fit_cards(cards, sum(b - a for a, b in keep))
    if cards:  # card e conteudo explicito: sem renderizador, falha (nunca some calado)
        reason = graphics.renderer_status()
        if reason:
            ids = ", ".join(repr(c["id"]) for c in cards)
            raise graphics.RendererMissing(
                f"grafico(s) {ids} precisa(m) do renderizador de graficos: {reason}. "
                "Rode scripts/doctor.py, ou descarte o grafico na revisao.")

    # (6)-(7) corte + queima de legendas
    saida = project / "saida"
    saida.mkdir(parents=True, exist_ok=True)
    out = saida / f"{quality}.mp4"
    temps: list[Path] = []
    libass = has_libass()
    tmpdir = None

    def _mktemp(prefix: str, suffix: str) -> Path:
        fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=saida)
        os.close(fd)
        path = Path(name)
        temps.append(path)
        return path

    try:
        # Nomes unicos: dois renders do mesmo projeto nao pisam um no outro.
        cut_tmp = _mktemp(".corte-", ".tmp")
        ass_tmp = _mktemp(".legendas-", ".tmp.ass")
        ass_tmp.write_text(ass_text, encoding="utf-8")
        cut.apply(entrada, cuts, cut_tmp)
        clips = []
        for i, c in enumerate(cards):
            clip = _mktemp(f".grafico-{i}-", ".tmp.webm")
            clips.append(graphics.render_clip(c, brand, clip, size=size))
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(cut_tmp)]
        for clip in clips:  # decodificador libvpx: o nativo descarta o canal alfa
            cmd += ["-c:v", "libvpx-vp9", "-i", str(clip)]
        if not libass:  # ffmpeg sem libass: legendas por imagem (PNG por frase)
            tmpdir = tempfile.TemporaryDirectory(prefix=".legendas-", dir=saida)
            tmp_root = Path(tmpdir.name)
            track = legendas_imagem.write_track(phrases, brand, size, tmp_root, estilo=est)
            cmd += ["-f", "concat", "-safe", "0", "-i", str(track), "-filter_complex",
                    _image_captions_filter(size, cards, len(clips) + 1), "-map", "[vout]"]
        elif clips:
            cmd += ["-filter_complex", _cards_filter(size, ass_tmp, cards), "-map", "[vout]"]
        else:
            cmd += ["-vf", _video_filter(size, ass_tmp), "-map", "0:v:0"]
        if _has_audio(cut_tmp):
            cmd += ["-map", "0:a:0"]
        else:
            cmd += ["-an"]
        cmd += [*_encode_args(quality), "-movflags", "+faststart", "-f", "mp4"]
        # saida com o modo normal de arquivo (0666 & ~umask), renomeada so no fim
        with common.atomic_write(out, suffix=".mp4") as tmp_out:
            common.run(cmd + [str(tmp_out)])
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()
        for p in temps:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
    return out


def main(argv: list[str] | None = None) -> None:
    parser = common.UsageParser(prog="render.py", description="Renderiza o Reel.")
    parser.add_argument("project", type=Path)
    parser.add_argument("quality", choices=sorted(SIZES))
    parser.add_argument("--brand", type=Path, default=DEFAULT_BRAND)
    args = parser.parse_args(argv)
    try:
        out = render(args.project, args.quality, brand_path=args.brand)
    except brandmod.BrandMissing as e:
        common.fail(f"{e}. Marca ausente, incompleta ou inválida (brand/brand.json): "
                    "rode a entrevista de marca antes de renderizar.")
    except legendas_imagem.PillowMissing as e:
        common.fail(str(e))
    except estilomod.EstiloError as e:
        common.fail(f"{e} (corrija ou apague {args.project / estilomod.ARQUIVO})")
    except (ProjectError, graphics.GraphicsError, OSError, ValueError) as e:
        common.fail(str(e))
    print(out)


if __name__ == "__main__":
    main()
