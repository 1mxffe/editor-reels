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


# --- audio extraido pelo ffmpeg (evita av.open do faster-whisper) ---

def _capturing_model(box):
    class Model:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, audio, **kw):
            box["audio"] = audio
            return iter([]), None

    return Model


def test_model_receives_float32_mono_array_not_path(make_sample, tmp_path, monkeypatch):
    import numpy as np
    box = {}
    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(_capturing_model(box)))
    transcribe.transcribe(make_sample, tmp_path / "t.json")
    a = box["audio"]
    assert isinstance(a, np.ndarray) and not isinstance(a, (str, Path))
    assert a.dtype == np.float32 and a.ndim == 1
    assert float(np.abs(a).max()) <= 1.0 and float(np.abs(a).max()) > 0.01


def test_roundtrip_length_matches_duration(make_sample, tmp_path, monkeypatch):
    box = {}
    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(_capturing_model(box)))
    res = transcribe.transcribe(make_sample, tmp_path / "t.json")
    assert abs(len(box["audio"]) - res["duration"] * 16000) < 0.15 * 16000
    assert abs(len(box["audio"]) / 16000 - 6.0) < 0.3


def test_poisoned_av_open_is_never_called(make_sample, tmp_path, monkeypatch):
    audio = pytest.importorskip("faster_whisper.audio")
    if not hasattr(audio, "av"):
        pytest.skip("faster_whisper.audio sem av")

    def poisoned(*a, **k):
        raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")

    monkeypatch.setattr(audio.av, "open", poisoned)
    box = {}
    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(_capturing_model(box)))
    transcribe.transcribe(make_sample, tmp_path / "t.json")
    assert "audio" in box


def test_no_audio_message_mentions_sem_som(no_audio_video, tmp_path, capsys):
    with pytest.raises(SystemExit):
        transcribe.transcribe(no_audio_video, tmp_path / "t.json")
    assert "áudio" in capsys.readouterr().err


def test_ffmpeg_missing_fails_clearly(make_sample, tmp_path, monkeypatch, capsys):
    import shutil
    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(_capturing_model({})))
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    monkeypatch.setenv("PATH", "")
    out = tmp_path / "t.json"
    with pytest.raises(SystemExit) as exc:
        transcribe.transcribe(make_sample, out)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ") and "ffmpeg" in err and "Traceback" not in err
    assert not out.exists()


def test_temp_dir_removed(make_sample, tmp_path, monkeypatch):
    import tempfile
    seen = []
    real = tempfile.TemporaryDirectory

    class Spy(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            seen.append(Path(self.name))

    monkeypatch.setattr(tempfile, "TemporaryDirectory", Spy)
    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(_capturing_model({})))
    transcribe.transcribe(make_sample, tmp_path / "t.json")
    assert seen and all(not p.exists() for p in seen)


def test_temp_dir_removed_on_model_error(make_sample, tmp_path, monkeypatch):
    import tempfile
    seen = []
    real = tempfile.TemporaryDirectory

    class Spy(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            seen.append(Path(self.name))

    class Model:
        def __init__(self, *a, **k):
            raise ValueError("x")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", Spy)
    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(Model))
    with pytest.raises(SystemExit):
        transcribe.transcribe(make_sample, tmp_path / "t.json")
    assert all(not p.exists() for p in seen)


def test_empty_wav_fails_clearly(make_sample, tmp_path, monkeypatch, capsys):
    import wave

    def fake_run(cmd, **kw):
        with wave.open(cmd[-1], "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: fake_run(cmd, **kw)
                        if cmd[0] == "ffmpeg" else subprocess.CompletedProcess(
                            cmd, 0, "0\n" if "stream=index" in cmd else "6.0\n", ""))
    monkeypatch.setitem(sys.modules, "faster_whisper", _module_with(_capturing_model({})))
    with pytest.raises(SystemExit):
        transcribe.transcribe(make_sample, tmp_path / "t.json")
    err = capsys.readouterr().err
    assert err.startswith("erro: falha na transcrição:") and "som" in err
