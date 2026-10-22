"""Deteccao e aplicacao de cortes (silencio, muletas, repeticoes). Nunca altera o original.

``cut.py detect`` grava ``cortes.json`` (passo do fluxo).
``cut.py apply`` e uso interno/depuracao: grava o video cortado SEM legenda e SEM
cards; o Reel sai so pelo ``render.py``, que chama ``apply`` e queima o resto.
"""
import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

FILLERS = {"ãh", "ahn", "hum", "éh", "né"}
PAD = 0.15
MIN_SEGMENT = 0.01
EPS = 1e-9


def _validate_transcript(transcript) -> list:
    if not isinstance(transcript, dict):
        common.fail("transcricao invalida: esperado um objeto JSON com duration e words")
    words = transcript.get("words")
    if words is None:
        words = []
    if not isinstance(words, list):
        common.fail("transcricao invalida: words deve ser uma lista")
    if not common.is_num(transcript.get("duration")):
        common.fail("transcricao invalida: falta duration numerica")
    for i, w in enumerate(words):
        if not (isinstance(w, dict) and isinstance(w.get("w"), str)
                and common.is_num(w.get("start")) and common.is_num(w.get("end"))):
            common.fail(f"transcricao invalida: palavra {i} precisa de w (texto), start e end numericos")
    return words


def _validate_cuts(cuts) -> None:
    if not isinstance(cuts, list):
        common.fail("cortes invalidos: cuts deve ser uma lista")
    for i, c in enumerate(cuts):
        if not (isinstance(c, dict) and common.is_num(c.get("start")) and common.is_num(c.get("end"))):
            common.fail(f"cortes invalidos: o corte {i} precisa de start/end numericos")


def _norm(word: str) -> str:
    s = unicodedata.normalize("NFD", word.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s if c.isalnum())


def detect(transcript: dict, min_gap: float = 0.5, fillers: set = FILLERS) -> list:
    words = _validate_transcript(transcript)
    if not words:
        return []
    duration = float(transcript["duration"])
    filler_set = {_norm(f) for f in fillers}
    raw = []  # (start, end, kind)

    def gap(start: float, end: float, lead: bool, trail: bool) -> None:
        if end - start <= min_gap + EPS:  # tolerancia: 1.1 - 0.6 conta como 0.5
            return
        s = start if lead else start + PAD
        e = end if trail else end - PAD
        if e - s > 0:
            raw.append((s, e, "silence"))

    gap(0.0, words[0]["start"], True, False)
    for a, b in zip(words, words[1:]):
        gap(a["end"], b["start"], False, False)
    gap(words[-1]["end"], duration, False, True)

    for i, w in enumerate(words):
        n = _norm(w["w"])
        if n in filler_set:
            raw.append((w["start"], w["end"], "filler"))
        elif i + 1 < len(words) and n and n == _norm(words[i + 1]["w"]):
            raw.append((w["start"], w["end"], "repeat"))

    raw.sort(key=lambda c: (c[0], c[1]))
    merged = []
    for s, e, k in raw:
        if merged and s <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e, k])
    return [{"id": f"c{i}", "start": round(s, 3), "end": round(e, 3), "kind": k}
            for i, (s, e, k) in enumerate(merged, 1)]


def keep_segments(duration: float, cuts: list) -> list:
    segs, pos = [], 0.0
    for c in sorted(cuts, key=lambda c: c["start"]):
        s, e = max(0.0, c["start"]), min(duration, c["end"])
        if s > pos:
            segs.append((pos, s))
        pos = max(pos, e)
    if pos < duration:
        segs.append((pos, duration))
    return [(a, b) for a, b in segs if b - a >= MIN_SEGMENT]


def _probe(video: Path, args: list) -> str:
    return common.run(["ffprobe", "-v", "error", *args, str(video)]).strip()


def apply(video: Path, cuts: list, out: Path) -> None:
    video, out = Path(video), Path(out)
    if not video.exists():
        common.fail(f"video nao encontrado: {video}")
    if out.resolve() == video.resolve():
        common.fail(f"a saida nao pode ser o proprio video original: {out}")
    _validate_cuts(cuts)
    duration = float(_probe(video, ["-show_entries", "format=duration", "-of", "csv=p=0"]))
    segs = keep_segments(duration, cuts)
    if not segs:
        common.fail("nada sobrou depois dos cortes")
    has_audio = bool(_probe(video, ["-select_streams", "a", "-show_entries",
                                    "stream=index", "-of", "csv=p=0"]))
    parts, labels = [], ""
    for i, (a, b) in enumerate(segs):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        labels += f"[v{i}]"
        if has_audio:
            parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
            labels += f"[a{i}]"
    n_a = 1 if has_audio else 0
    parts.append(f"{labels}concat=n={len(segs)}:v=1:a={n_a}" + ("[v][a]" if has_audio else "[v]"))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
           "-filter_complex", ";".join(parts), "-map", "[v]"]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    with common.atomic_write(out, suffix=".mp4") as tmp:  # nome unico; some se falhar
        common.run(cmd + [str(tmp)])


def main(argv: list) -> None:
    usage = ("uso: cut.py detect <transcricao.json> <cortes.json> | "
             "cut.py apply <video> <cortes.json> <out.mp4> (apply: uso interno/depuracao, "
             "video sem legenda e sem cards; o Reel sai pelo render.py)")
    if len(argv) < 2:
        common.fail(usage)
    cmd = argv[1]
    if cmd == "detect" and len(argv) == 4:
        try:
            transcript = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            common.fail(f"transcricao ilegivel: {exc}")
        cuts = detect(transcript)
        if not (transcript.get("words")):
            common.fail("nenhuma fala detectada")
        common.write_json_atomic(Path(argv[3]), {"cuts": cuts})
    elif cmd == "apply" and len(argv) == 5:
        try:
            cuts = json.loads(Path(argv[3]).read_text(encoding="utf-8"))["cuts"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            common.fail(f"cortes.json invalido: {exc}")
        apply(Path(argv[2]), cuts, Path(argv[4]))
    else:
        common.fail(usage)


if __name__ == "__main__":
    main(sys.argv)
