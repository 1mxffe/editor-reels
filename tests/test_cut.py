import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import cut

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cut.py"


def tr(words, duration=10.0):
    return {"duration": duration,
            "words": [{"w": w, "start": s, "end": e} for w, s, e in words]}


def probe(path, stream):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def test_gap_over_threshold_is_silence():
    t = tr([("ola", 0.15, 0.5), ("mundo", 2.0, 2.5)], duration=2.65)
    cuts = cut.detect(t)
    assert len(cuts) == 1
    c = cuts[0]
    assert c["kind"] == "silence" and c["id"] == "c1"
    assert abs(c["start"] - 0.65) < 1e-6 and abs(c["end"] - 1.85) < 1e-6


def test_small_gap_is_kept():
    t = tr([("ola", 0.1, 0.5), ("mundo", 0.9, 1.4)], duration=1.5)
    assert cut.detect(t) == []


def test_leading_and_trailing_silence():
    t = tr([("ola", 2.0, 2.5)], duration=5.0)
    cuts = cut.detect(t)
    assert [(c["start"], c["end"]) for c in cuts] == [(0.0, 1.85), (2.65, 5.0)]


def test_filler_word_is_cut():
    t = tr([("a", 0.0, 0.3), ("Ãh,", 0.35, 0.6), ("empresa", 0.65, 1.2)], duration=1.3)
    cuts = cut.detect(t)
    assert len(cuts) == 1
    assert cuts[0]["kind"] == "filler"
    assert (cuts[0]["start"], cuts[0]["end"]) == (0.35, 0.6)


def test_e_and_tipo_are_not_fillers():
    t = tr([("tipo", 0.0, 0.3), ("é", 0.35, 0.5), ("bom", 0.55, 0.9)], duration=1.0)
    assert cut.detect(t) == []


def test_immediate_repeat_is_cut():
    t = tr([("a", 0.0, 0.2), ("a", 0.25, 0.45), ("empresa", 0.5, 1.0)], duration=1.1)
    cuts = cut.detect(t)
    assert len(cuts) == 1
    assert cuts[0]["kind"] == "repeat"
    assert (cuts[0]["start"], cuts[0]["end"]) == (0.0, 0.2)


def test_ids_chronological_and_adjacent_merged():
    t = tr([("ola", 0.15, 0.4), ("hum", 0.4, 0.7), ("fim", 3.0, 3.3),
            ("fim", 3.35, 3.6), ("x", 3.65, 3.9)], duration=4.05)
    cuts = cut.detect(t)
    # muleta "hum" 0.4-0.7; silencio 0.7->3.0 menos PAD dos dois lados
    # (0.85-2.85); repeticao "fim" 3.0-3.3. Nenhum se encosta: 3 cortes.
    assert cuts == [
        {"id": "c1", "start": 0.4, "end": 0.7, "kind": "filler"},
        {"id": "c2", "start": 0.85, "end": 2.85, "kind": "silence"},
        {"id": "c3", "start": 3.0, "end": 3.3, "kind": "repeat"},
    ]
    starts = [c["start"] for c in cuts]
    assert starts == sorted(starts)
    for a, b in zip(cuts, cuts[1:]):
        assert a["end"] < b["start"]
    t2 = tr([("hum", 0.0, 0.5), ("ahn", 0.5, 1.0), ("ok", 1.0, 1.3)], duration=1.4)
    merged = cut.detect(t2)
    assert len(merged) == 1 and (merged[0]["start"], merged[0]["end"]) == (0.0, 1.0)
    assert merged[0]["kind"] == "filler" and merged[0]["id"] == "c1"


def test_keep_segments_complement():
    cuts = [{"id": "c1", "start": 1.0, "end": 2.0, "kind": "silence"},
            {"id": "c2", "start": 4.0, "end": 5.0, "kind": "filler"}]
    assert cut.keep_segments(6.0, cuts) == [(0.0, 1.0), (2.0, 4.0), (5.0, 6.0)]
    assert cut.keep_segments(5.0, [{"id": "c1", "start": 0.0, "end": 5.0, "kind": "silence"}]) == []


def test_empty_cuts_keep_whole():
    assert cut.keep_segments(6.0, []) == [(0.0, 6.0)]


def test_apply_shortens_duration(make_sample, tmp_path):
    out = tmp_path / "out.mp4"
    before = hashlib.sha256(make_sample.read_bytes()).hexdigest()
    cut.apply(make_sample, [{"id": "c1", "start": 2.5, "end": 3.5, "kind": "silence"}], out)
    assert out.exists() and not (tmp_path / "out.mp4.tmp.mp4").exists()
    orig = probe(make_sample, "v:0")
    v, a = probe(out, "v:0"), probe(out, "a:0")
    assert v <= orig - 0.8
    assert abs(v - a) <= 0.1
    assert hashlib.sha256(make_sample.read_bytes()).hexdigest() == before


def test_no_speech_returns_error(tmp_path):
    tj = tmp_path / "t.json"
    tj.write_text(json.dumps({"duration": 5.0, "words": []}))
    assert cut.detect(json.loads(tj.read_text())) == []
    out = tmp_path / "cortes.json"
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), "detect", str(tj), str(out)],
                       capture_output=True, text=True)
    assert p.returncode != 0
    assert "fala" in p.stderr
    assert not out.exists()


def test_cli_detect_writes_cuts(tmp_path):
    tj = tmp_path / "t.json"
    tj.write_text(json.dumps(tr([("ola", 0.15, 0.5), ("mundo", 2.0, 2.5)], 2.65)))
    out = tmp_path / "cortes.json"
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), "detect", str(tj), str(out)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert json.loads(out.read_text())["cuts"][0]["id"] == "c1"


# --- Task 3b ---------------------------------------------------------------


def run_cli(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def test_gap_equal_to_min_gap_with_float_noise_is_not_cut():
    # 1.1 - 0.6 == 0.5000000000000001 em float: tem de contar como 0.5.
    t = tr([("a", 0.0, 0.6), ("b", 1.1, 1.5)], duration=1.5)
    assert cut.detect(t) == []


@pytest.mark.parametrize("transcript,msg", [
    ([1, 2], "objeto"),
    ({"words": [{"w": "a", "start": 0.0, "end": 0.5}]}, "duration"),
    ({"duration": "x", "words": [{"w": "a", "start": 0.0, "end": 0.5}]}, "duration"),
    ({"duration": 2.0, "words": [{"w": "a", "start": 0.0}]}, "palavra"),
    ({"duration": 2.0, "words": "abc"}, "words"),
])
def test_detect_rejects_bad_shapes(transcript, msg, capsys):
    with pytest.raises(SystemExit) as exc:
        cut.detect(transcript)
    assert exc.value.code == 1
    assert msg in capsys.readouterr().err


def test_cli_detect_non_object_fails(tmp_path):
    tj = tmp_path / "t.json"
    tj.write_text("[1, 2]")
    out = tmp_path / "cortes.json"
    p = run_cli("detect", tj, out)
    assert p.returncode == 1 and "objeto" in p.stderr
    assert not out.exists()


def test_cli_apply_cuts_without_start_end_fails(tmp_path, make_sample):
    cj = tmp_path / "cortes.json"
    cj.write_text(json.dumps({"cuts": [{"id": "c1", "start": 1.0}]}))
    out = tmp_path / "out.mp4"
    p = run_cli("apply", make_sample, cj, out)
    assert p.returncode == 1 and "start/end" in p.stderr
    assert not out.exists()


def test_apply_refuses_overwriting_input(make_sample, capsys):
    before = make_sample.read_bytes()
    with pytest.raises(SystemExit) as exc:
        cut.apply(make_sample, [], make_sample.parent / "." / make_sample.name)
    assert exc.value.code == 1
    assert "original" in capsys.readouterr().err
    assert make_sample.read_bytes() == before


def test_apply_cut_at_very_start_and_end(make_sample, tmp_path):
    out = tmp_path / "out.mp4"
    cut.apply(make_sample, [{"id": "c1", "start": 0.0, "end": 1.0, "kind": "silence"},
                            {"id": "c2", "start": 5.0, "end": 6.0, "kind": "silence"}], out)
    v = probe(out, "v:0")
    assert 3.8 <= v <= 4.2


def test_apply_nothing_left_fails_without_tmp(make_sample, tmp_path, capsys):
    out = tmp_path / "out.mp4"
    with pytest.raises(SystemExit) as exc:
        cut.apply(make_sample, [{"id": "c1", "start": 0.0, "end": 6.5, "kind": "silence"}], out)
    assert exc.value.code == 1
    assert "nada sobrou" in capsys.readouterr().err
    assert not out.exists()
    assert list(tmp_path.glob("*.tmp*")) == []


@pytest.fixture
def mute_video(tmp_path):
    out = tmp_path / "mudo.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=270x480:rate=30:duration=2",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
    ], check=True)
    return out


def test_cli_apply_on_video_without_audio(mute_video, tmp_path):
    cj = tmp_path / "cortes.json"
    cj.write_text(json.dumps({"cuts": [{"id": "c1", "start": 0.5, "end": 1.0, "kind": "silence"}]}))
    out = tmp_path / "out.mp4"
    p = run_cli("apply", mute_video, cj, out)
    assert p.returncode == 0, p.stderr
    assert 1.3 <= probe(out, "v:0") <= 1.7
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout
    assert streams.strip() == ""
    assert list(tmp_path.glob("*.tmp*")) == []


def test_cli_apply_cuts_json_not_object_fails(tmp_path, make_sample):
    cj = tmp_path / "cortes.json"
    cj.write_text("[1, 2]")
    p = run_cli("apply", make_sample, cj, tmp_path / "out.mp4")
    assert p.returncode == 1 and p.stderr.startswith("erro:")
