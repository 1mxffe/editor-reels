import re

import brand
import captions

BR = brand.seed_from_guide()


def W(*items):
    return [{"w": w, "start": s, "end": e} for w, s, e in items]


def dialogues(ass):
    return [l for l in ass.splitlines() if l.startswith("Dialogue:")]


def style_fields(ass):
    line = next(l for l in ass.splitlines() if l.startswith("Style:"))
    fmt = next(l for l in ass.splitlines() if l.startswith("Format:") and "Fontname" in l)
    keys = [k.strip() for k in fmt[len("Format:"):].split(",")]
    vals = [v.strip() for v in line[len("Style:"):].split(",")]
    return dict(zip(keys, vals))


# remap
def test_remap_drops_cut_words_and_shifts():
    words = W(("a", 0.0, 0.5), ("eh", 1.0, 1.4), ("b", 2.0, 2.5), ("c", 2.5, 3.0))
    out = captions.remap(words, [(0.0, 0.8), (1.8, 3.0)])
    assert [w["w"] for w in out] == ["a", "b", "c"]
    assert out[1]["start"] == 1.0 and out[1]["end"] == 1.5
    assert out[2]["start"] == 1.5 and out[2]["end"] == 2.0


def test_remap_clips_straddling_word():
    out = captions.remap(W(("x", 0.7, 1.1)), [(0.0, 1.0)])
    assert out == [{"w": "x", "start": 0.7, "end": 1.0}]


def test_remap_empty_keep():
    assert captions.remap(W(("a", 0, 1)), []) == []


# phrases
def test_phrase_max_two_lines():
    words = W(*[(f"palavra{i}", i * 0.3, i * 0.3 + 0.25) for i in range(20)])
    ph = captions.phrases(words)
    assert len(ph) > 1
    for p in ph:
        lines = p["text"].split("\n")
        assert len(lines) <= 2
        assert all(len(l) <= 38 for l in lines)


def test_phrase_sentence_end_splits():
    ph = captions.phrases(W(("Oi.", 0, 0.5), ("Tudo", 0.6, 1.0), ("bem", 1.0, 1.4)))
    assert [p["text"] for p in ph] == ["Oi.", "Tudo bem"]


def test_phrase_gap_splits():
    ph = captions.phrases(W(("a", 0, 0.5), ("b", 1.3, 1.6)))
    assert len(ph) == 2


def test_phrase_no_overlap_and_min_display():
    ph = captions.phrases(W(("a.", 0, 0.1), ("b", 0.2, 0.3), ("c.", 2.0, 2.1)))
    assert ph[0]["end"] <= ph[1]["start"]
    assert ph[0]["end"] - ph[0]["start"] <= 0.2 + 1e-9  # next starts sooner than 0.4 s
    assert ph[1]["end"] - ph[1]["start"] >= 0.4 - 1e-9


def test_phrase_long_single_word():
    long = "x" * 60
    ph = captions.phrases(W(("a", 0, 0.2), (long, 0.2, 0.6), ("b", 0.6, 0.8)))
    lines = [l for p in ph for l in p["text"].split("\n")]
    assert long in lines


def test_phrase_empty():
    assert captions.phrases([]) == []


# ass
def sample_ass():
    ph = [{"text": "Linha um\nlinha dois", "start": 0.0, "end": 1.234}]
    return captions.to_ass(ph, BR)


def test_ass_has_no_animation_tags():
    ass = sample_ass()
    for tag in [r"\t(", r"\k", r"\K", r"\ko", r"\kf", r"\move", r"\fscx", r"\fscy",
                r"\frx", r"\fry", r"\frz", r"\org", r"\clip"]:
        assert tag not in ass
    assert "\\N" in ass


def test_ass_escapes_braces_and_backslash():
    ph = [{"text": "a {b} c\\d, e\nf", "start": 0, "end": 1}]
    ass = captions.to_ass(ph, BR)
    d = dialogues(ass)
    assert len(d) == 1
    text = d[0].split(",", 9)[9]
    assert text.startswith("{\\fad(")
    rest = text[text.index("}") + 1:]
    assert "{" not in rest and "}" not in rest
    assert rest == "a (b) c d, e\\Nf"


def test_fade_at_most_150ms():
    fades = re.findall(r"\\fad\((\d+),(\d+)\)", sample_ass())
    assert fades
    assert all(int(a) <= 150 and int(b) <= 150 for a, b in fades)


def test_font_and_color_from_brand():
    st = style_fields(sample_ass())
    assert st["Fontname"] == "Poppins"
    assert st["PrimaryColour"] == "&H00F5EBDD"
    assert st["BackColour"] == "&H73311900"
    assert st["BorderStyle"] == "3" and st["Name"] == "Legenda"
    assert st["Bold"] == "-1" and st["Shadow"] == "0" and st["Alignment"] == "2"
    assert st["Fontsize"] == "64" and st["Outline"] == "14"


def test_safe_area_margins():
    st = style_fields(sample_ass())
    assert int(st["MarginV"]) >= 340
    assert int(st["MarginL"]) == int(st["MarginR"]) == 72


def test_header_and_time_format():
    ass = sample_ass()
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "ScriptType: v4.00+" in ass and "WrapStyle: 2" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:01.23,Legenda," in ass


def test_scaling_draft_size():
    st = style_fields(captions.to_ass([{"text": "x", "start": 0, "end": 1}], BR, (540, 960)))
    assert st["Fontsize"] == "32" and st["MarginV"] == "170"


# --- Task 3b ---------------------------------------------------------------
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "captions.py"


def test_gap_exactly_split_threshold_does_not_split():
    # 1.1 - 0.5 == 0.6000000000000001 em float: e exatamente 0.6, nao divide.
    ph = captions.phrases(W(("a", 0, 0.5), ("b", 1.1, 1.5)))
    assert [p["text"] for p in ph] == ["a b"]
    ph = captions.phrases(W(("a", 0, 0.5), ("b", 1.102, 1.5)))
    assert len(ph) == 2


def test_remap_keeps_zero_duration_word_inside_segment():
    out = captions.remap(W(("a", 0.2, 0.4), ("x", 0.5, 0.5), ("b", 2.5, 2.5)), [(0.0, 1.0), (2.0, 3.0)])
    assert out == [{"w": "a", "start": 0.2, "end": 0.4}, {"w": "x", "start": 0.5, "end": 0.5},
                   {"w": "b", "start": 1.5, "end": 1.5}]
    # dentro de um trecho cortado continua fora
    assert captions.remap(W(("y", 1.5, 1.5)), [(0.0, 1.0), (2.0, 3.0)]) == []


def test_remap_unsorted_keep_is_sorted():
    words = W(("a", 0.0, 0.5), ("b", 2.0, 2.5))
    assert captions.remap(words, [(1.8, 3.0), (0.0, 0.8)]) == captions.remap(words, [(0.0, 0.8), (1.8, 3.0)])


def test_remap_overlapping_keep_is_merged():
    out = captions.remap(W(("a", 0.2, 0.4), ("b", 1.5, 1.8)), [(0.0, 1.0), (0.5, 2.0)])
    assert out == [{"w": "a", "start": 0.2, "end": 0.4}, {"w": "b", "start": 1.5, "end": 1.8}]


def test_token_with_newline_is_flattened():
    ph = captions.phrases(W(("um\ndois", 0, 0.5), ("tres", 0.5, 0.9)))
    assert [p["text"] for p in ph] == ["um dois tres"]


def run_cli(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def write(p, data):
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_cli_writes_ass(tmp_path):
    words = write(tmp_path / "w.json", {"words": W(("Oi.", 0, 0.5))})
    b = write(tmp_path / "brand.json", BR)
    out = tmp_path / "out.ass"
    p = run_cli(words, b, out)
    assert p.returncode == 0, p.stderr
    assert len(dialogues(out.read_text(encoding="utf-8"))) == 1
    assert not (tmp_path / "out.ass.tmp").exists()


def test_cli_missing_words_key_fails(tmp_path):
    words = write(tmp_path / "w.json", {"palavras": []})
    b = write(tmp_path / "brand.json", BR)
    p = run_cli(words, b, tmp_path / "out.ass")
    assert p.returncode == 1 and "words" in p.stderr and "Traceback" not in p.stderr
    assert not (tmp_path / "out.ass").exists()


def test_cli_bad_hex_colour_fails(tmp_path):
    words = write(tmp_path / "w.json", {"words": W(("Oi.", 0, 0.5))})
    b = write(tmp_path / "brand.json", {**BR, "fg": "branco"})
    p = run_cli(words, b, tmp_path / "out.ass")
    assert p.returncode == 1 and p.stderr.startswith("erro:") and "Traceback" not in p.stderr
    assert not (tmp_path / "out.ass").exists()


def test_cli_unwritable_output_fails(tmp_path):
    words = write(tmp_path / "w.json", {"words": W(("Oi.", 0, 0.5))})
    b = write(tmp_path / "brand.json", BR)
    p = run_cli(words, b, tmp_path / "nao" / "existe" / "out.ass")
    assert p.returncode == 1 and p.stderr.startswith("erro:") and "Traceback" not in p.stderr


# ---- onda final, item 1: o texto exibido e o que o ASS desenha ----
def test_display_text_is_what_the_ass_draws():
    raw = "Veja o art\\5 e a Lei\\13467.\n {nota}  final"
    shown = captions.display_text(raw)
    assert shown == "Veja o art 5 e a Lei 13467.\n(nota) final"
    d = dialogues(captions.to_ass([{"text": raw, "start": 0, "end": 1}], BR))[0]
    rest = d.split(",", 9)[9]
    assert rest[rest.index("}") + 1:] == shown.replace("\n", "\\N")


def test_display_text_treats_every_line_separator_as_a_break():
    for sep in ("\r\n", "\r", " ", " ", "\x85", "\v", "\f"):
        assert captions.display_text(f"PRAZO{sep}FINAL") == "PRAZO\nFINAL", repr(sep)
    assert captions.display_text("  \n a \n\n") == "a"
