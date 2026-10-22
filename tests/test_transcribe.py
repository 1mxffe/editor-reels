import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import transcribe


@pytest.fixture
def no_audio_video(tmp_path):
    out = tmp_path / "mudo.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30:duration=2",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
    ], check=True)
    return out


def _fake_module(segments):
    class Word:
        def __init__(self, word, start, end):
            self.word, self.start, self.end = word, start, end

    class Segment:
        def __init__(self, words):
            self.words = [Word(*w) for w in words]

    class FakeModel:
        calls = []

        def __init__(self, name, *a, **k):
            FakeModel.name = name

        def transcribe(self, path, **kwargs):
            FakeModel.calls.append(kwargs)
            return iter([Segment(s) for s in segments]), None

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = FakeModel
    return mod, FakeModel


def test_has_audio_true_with_silence_track(make_sample):
    assert transcribe.has_audio(make_sample) is True


def test_has_audio_false_for_silent_video(no_audio_video):
    assert transcribe.has_audio(no_audio_video) is False


def test_output_schema(make_sample, tmp_path, monkeypatch):
    mod, fake = _fake_module([
        [(" Olá", 0.12345, 0.5), (" mundo ", 0.5, 0.9996)],
        [("  ", 1.0, 1.1), ("tchau", 1.2, 1.6)],
    ])
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    out = tmp_path / "sub" / "t.json"
    res = transcribe.transcribe(make_sample, out)
    assert set(res) == {"duration", "words"}
    assert isinstance(res["duration"], float)
    assert 5.5 < res["duration"] < 6.5
    assert res["words"] == [
        {"w": "Olá", "start": 0.123, "end": 0.5},
        {"w": "mundo", "start": 0.5, "end": 1.0},
        {"w": "tchau", "start": 1.2, "end": 1.6},
    ]
    assert json.loads(out.read_text(encoding="utf-8")) == res
    assert fake.name == "small"
    kw = fake.calls[0]
    assert kw["language"] == "pt" and kw["word_timestamps"] is True and kw["vad_filter"] is True


def test_no_speech_gives_empty_words(make_sample, tmp_path, monkeypatch):
    mod, _ = _fake_module([])
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    out = tmp_path / "t.json"
    res = transcribe.transcribe(make_sample, out)
    assert res["words"] == []
    assert json.loads(out.read_text(encoding="utf-8"))["words"] == []


def test_no_audio_fails_clearly(no_audio_video, tmp_path, capsys):
    out = tmp_path / "t.json"
    with pytest.raises(SystemExit) as exc:
        transcribe.transcribe(no_audio_video, out)
    assert exc.value.code != 0
    assert "áudio" in capsys.readouterr().err
    assert not out.exists()
    assert not Path(str(out) + ".tmp").exists()


def test_missing_faster_whisper_fails_clearly(make_sample, tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # forca ImportError
    out = tmp_path / "t.json"
    with pytest.raises(SystemExit) as exc:
        transcribe.transcribe(make_sample, out)
    assert exc.value.code != 0
    assert "pip install faster-whisper" in capsys.readouterr().err
    assert not out.exists()


def _module_with(model_cls):
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = model_cls
    return mod


def test_segment_with_words_none_is_empty(make_sample, tmp_path, monkeypatch):
    class Seg:
        words = None

    class Model:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, path, **kw):
            return iter([Seg()]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(Model))
    res = transcribe.transcribe(make_sample, tmp_path / "t.json")
    assert res["words"] == []


def test_error_during_lazy_iteration_fails_cleanly(make_sample, tmp_path, monkeypatch, capsys):
    def boom():
        raise RuntimeError("decodificador quebrou")
        yield  # pragma: no cover

    class Model:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, path, **kw):
            return boom(), None

    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(Model))
    out = tmp_path / "t.json"
    with pytest.raises(SystemExit) as exc:
        transcribe.transcribe(make_sample, out)
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "falha na transcrição: decodificador quebrou" in err
    assert not out.exists()
    assert not Path(str(out) + ".tmp").exists()


def test_error_building_model_fails_cleanly(make_sample, tmp_path, monkeypatch, capsys):
    class Model:
        def __init__(self, *a, **k):
            raise ValueError("modelo inexistente")

    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(Model))
    out = tmp_path / "t.json"
    with pytest.raises(SystemExit) as exc:
        transcribe.transcribe(make_sample, out)
    assert exc.value.code != 0
    assert "falha na transcrição: modelo inexistente" in capsys.readouterr().err
    assert not out.exists()
