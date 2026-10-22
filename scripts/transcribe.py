"""Transcricao com tempo por palavra (faster-whisper)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402


def has_audio(video: Path) -> bool:
    out = common.run([
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", str(video),
    ])
    return bool(out.strip())


def _duration(video: Path) -> float:
    out = common.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(video),
    ])
    try:
        return float(out.strip())
    except ValueError:
        common.fail(f"nao foi possivel ler a duracao do video: {video}")


def transcribe(video: Path, out_json: Path, model: str = "small", lang: str = "pt") -> dict:
    video = Path(video)
    if not video.exists():
        common.fail(f"video nao encontrado: {video}")
    if not has_audio(video):
        common.fail(f"o vídeo não tem trilha de áudio: {video}")
    duration = _duration(video)
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        common.fail("faster-whisper nao esta instalado; rode: pip install faster-whisper")
    words = []
    # Os segmentos do faster-whisper sao lazy: a decodificacao real (e seus
    # erros) acontece na iteracao, entao ela fica dentro do mesmo try.
    # SystemExit (common.fail) nao e Exception e passa direto.
    try:
        segments, _info = WhisperModel(model).transcribe(
            str(video), language=lang, word_timestamps=True, vad_filter=True
        )
        for seg in segments:
            for w in seg.words or []:
                text = w.word.strip()
                if not text:
                    continue
                words.append({"w": text, "start": round(w.start, 3), "end": round(w.end, 3)})
    except Exception as e:
        common.fail(f"falha na transcrição: {e}")
    result = {"duration": duration, "words": words}
    common.write_json_atomic(Path(out_json), result)
    return result


def main(argv=None) -> None:
    p = common.UsageParser(description="Transcreve um video com tempo por palavra.")
    p.add_argument("video", type=Path)
    p.add_argument("out_json", type=Path)
    p.add_argument("--model", default="small")
    p.add_argument("--lang", default="pt")
    a = p.parse_args(argv)
    res = transcribe(a.video, a.out_json, a.model, a.lang)
    print(f"{len(res['words'])} palavras, {res['duration']:.2f}s -> {a.out_json}")


if __name__ == "__main__":
    main()
