import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import captions
import render
import review_apply as ra

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "review_apply.py"

WORDS = [
    ("O", 0.50, 0.70), ("prazo", 0.70, 1.10), ("para", 1.10, 1.30), ("recorrer", 1.30, 1.70),
    ("conta", 1.70, 1.95), ("dias", 1.95, 2.15), ("úteis.", 2.15, 2.40),
    ("Leia", 3.80, 4.10), ("a", 4.10, 4.20), ("intimação", 4.20, 4.70), ("com", 4.70, 4.90),
    ("calma.", 4.90, 5.30),
]
CUTS = [{"id": "c1", "start": 0.0, "end": 0.45, "kind": "silence"},
        {"id": "c2", "start": 2.6, "end": 3.4, "kind": "silence"}]


def _jw(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "reel"
    p.mkdir()
    (p / "entrada.mp4").write_bytes(b"nao e video")
    _jw(p / "transcricao.json", {"duration": 6.0, "words": [
        {"w": w, "start": s, "end": e} for w, s, e in WORDS]})
    _jw(p / "cortes.json", {"cuts": CUTS})
    return p


def _read(p, name):
    return json.loads((p / name).read_text("utf-8"))


def _snapshot(p):
    return {f.name: f.read_bytes() for f in sorted(p.iterdir())}


def _phrases(p):
    d, words, cuts = render._load_inputs(p)
    import cut
    return captions.phrases(captions.remap(words, cut.keep_segments(d, cuts)))


def test_restore_cut_removes_from_list(proj):
    ra.apply(proj, {"cuts_removed": ["c2"]})
    assert [c["id"] for c in _read(proj, "cortes.json")["cuts"]] == ["c1"]
    assert _read(proj, "revisao.json")["removed_cuts"] == [CUTS[1]]


def test_unknown_cut_id_is_error(proj):
    before = _snapshot(proj)
    with pytest.raises(ra.ReviewError, match="c9"):
        ra.apply(proj, {"cuts_removed": ["c9"]})
    assert _snapshot(proj) == before


def test_add_cut_from_word_click(proj):
    # clique em "calma." (4.90-5.30) vira corte manual
    ra.apply(proj, {"cuts_added": [{"start": 4.9, "end": 5.3}]})
    cuts = _read(proj, "cortes.json")["cuts"]
    assert cuts[-1] == {"id": "c3", "start": 4.9, "end": 5.3, "kind": "manual"}
    assert [c["start"] for c in cuts] == sorted(c["start"] for c in cuts)


def test_ids_never_reused(proj):
    ra.apply(proj, {"cuts_removed": ["c2"]})
    ra.apply(proj, {"cuts_added": [{"start": 4.9, "end": 5.3}]})
    assert _read(proj, "cortes.json")["cuts"][-1]["id"] == "c3"
    ra.apply(proj, {"cuts_removed": ["c3"]})
    ra.apply(proj, {"cuts_added": [{"start": 1.0, "end": 1.2}]})
    assert "c4" in [c["id"] for c in _read(proj, "cortes.json")["cuts"]]


def test_duplicate_add_skipped(proj):
    ra.apply(proj, {"cuts_added": [{"start": 4.9, "end": 5.3}]})
    ra.apply(proj, {"cuts_added": [{"start": 4.9, "end": 5.3}, {"start": 2.7, "end": 3.0}]})
    cuts = _read(proj, "cortes.json")["cuts"]
    assert len(cuts) == 3  # c1, c2, um manual; o contido em c2 e o duplicado foram ignorados


def test_overlapping_manual_cuts_merge(proj):
    ra.apply(proj, {"cuts_added": [{"start": 4.0, "end": 4.5}]})
    ra.apply(proj, {"cuts_added": [{"start": 4.4, "end": 5.0}]})
    manual = [c for c in _read(proj, "cortes.json")["cuts"] if c["kind"] == "manual"]
    assert manual == [{"id": "c3", "start": 4.0, "end": 5.0, "kind": "manual"}]


@pytest.mark.parametrize("bad", [
    {"start": 3, "end": 3}, {"start": 4, "end": 3}, {"start": -1, "end": 2},
    {"start": 1, "end": 6.5}, {"start": "a", "end": 2}, {"start": float("nan"), "end": 2},
    {"start": 1}, {"start": True, "end": 2}, "x"])
def test_invalid_ranges_rejected(proj, bad):
    before = _snapshot(proj)
    with pytest.raises(ra.ReviewError):
        ra.apply(proj, {"cuts_added": [bad]})
    assert _snapshot(proj) == before


def test_caption_edit_saved_with_base_text(proj):
    base = _phrases(proj)[0]["text"]
    ra.apply(proj, {"caption_edits": {"0": "O prazo para recorrer"}})  # chave string (JSON)
    assert _read(proj, "legendas.json") == {"edits": [
        {"idx": 0, "base_text": base, "text": "O prazo para recorrer"}]}


def test_caption_edit_replaces_and_blank_reverts(proj):
    ra.apply(proj, {"caption_edits": {0: "um"}})
    ra.apply(proj, {"caption_edits": {0: "dois"}})
    assert [e["text"] for e in _read(proj, "legendas.json")["edits"]] == ["dois"]
    ra.apply(proj, {"caption_edits": {0: "   "}})
    assert _read(proj, "legendas.json")["edits"] == []


def test_caption_edit_idx_out_of_range(proj):
    before = _snapshot(proj)
    n = len(_phrases(proj))
    for idx in (n, -1, "x"):
        with pytest.raises(ra.ReviewError):
            ra.apply(proj, {"caption_edits": {idx: "ok"}})
    assert _snapshot(proj) == before


def test_caption_edit_idx_uses_phrases_after_cut_changes(proj):
    # remover o corte c2 junta as frases: a lista nova e menor/diferente
    ra.apply(proj, {"cuts_removed": ["c2"], "caption_edits": {0: "novo"}})
    base = captions.phrases(captions.remap(
        [{"w": w, "start": s, "end": e} for w, s, e in WORDS], [(0.45, 6.0)]))[0]["text"]
    assert _read(proj, "legendas.json")["edits"][0]["base_text"] == base


def test_caption_edit_text_is_not_policed(proj):
    # o escritorio revisa o texto antes de gravar: o editor grava a edicao como veio
    ra.apply(proj, {"cuts_added": [{"start": 4.9, "end": 5.3}],
                    "notes": [{"t": 1, "text": "x"}],
                    "caption_edits": {0: "garantimos que você ganha a causa"}})
    assert _read(proj, "legendas.json")["edits"][0]["text"] == "garantimos que você ganha a causa"
    assert _read(proj, "revisao.json")["notes"] == [{"t": 1, "text": "x"}]


def test_original_untouched(proj):
    h = lambda: [hashlib.sha256((proj / n).read_bytes()).hexdigest()
                 for n in ("entrada.mp4", "transcricao.json")]
    before = h()
    ra.apply(proj, {"cuts_removed": ["c1"], "cuts_added": [{"start": 4.9, "end": 5.3}],
                    "caption_edits": {0: "texto"}, "graphics": {"g1": "drop"},
                    "notes": [{"t": 1.0, "text": "n"}]})
    assert h() == before
    assert not list(proj.glob("*.tmp"))


def test_graphics_merge_by_id(proj):
    ra.apply(proj, {"graphics": {"g1": "drop", "g2": "keep"}})
    ra.apply(proj, {"graphics": {"g1": "keep"}})
    assert _read(proj, "revisao.json")["graphics"] == {"g1": "keep", "g2": "keep"}
    with pytest.raises(ra.ReviewError):
        ra.apply(proj, {"graphics": {"g3": "talvez"}})


def test_notes_replace(proj):
    ra.apply(proj, {"notes": [{"t": 1.5, "text": "a"}, {"t": 2, "text": "b"}]})
    ra.apply(proj, {"notes": [{"t": 3, "text": "c"}]})
    assert _read(proj, "revisao.json")["notes"] == [{"t": 3, "text": "c"}]
    for bad in ([{"t": -1, "text": "x"}], [{"t": 1, "text": " "}], [{"t": "1", "text": "x"}], "x"):
        with pytest.raises(ra.ReviewError):
            ra.apply(proj, {"notes": bad})


def test_unknown_decision_key_rejected(proj):
    with pytest.raises(ra.ReviewError):
        ra.apply(proj, {"cuts_remove": ["c1"]})


def test_build_review_shape(proj):
    ra.apply(proj, {"cuts_removed": ["c1"], "caption_edits": {0: "editada"},
                    "graphics": {"g1": "drop"}, "notes": [{"t": 1, "text": "n"}]})
    r = ra.build_review(proj)
    assert r["duration"] == 6.0
    assert [w["i"] for w in r["words"]] == list(range(len(WORDS)))
    assert r["words"][1] == {"i": 1, "w": "prazo", "start": 0.7, "end": 1.1}
    assert r["cuts"] == [
        {**CUTS[0], "active": False}, {**CUTS[1], "active": True}]
    p0 = r["phrases"][0]
    assert p0["idx"] == 0 and p0["text"] == "editada" and p0["edited"] is True
    assert p0["base_text"] and p0["base_text"] != "editada" and "stale" not in p0
    assert r["phrases"][1]["edited"] is False
    assert r["graphics"] == {"g1": "drop"} and r["notes"] == [{"t": 1, "text": "n"}]
    assert r["kept_duration"] == pytest.approx(6.0 - 0.8)


def test_stale_edit_not_applied_in_build_and_render(proj, capsys):
    ra.apply(proj, {"caption_edits": {0: "editada"}})
    ra.apply(proj, {"cuts_added": [{"start": 0.7, "end": 1.1}]})  # corta "prazo": frase 0 muda
    r = ra.build_review(proj)
    assert r["phrases"][0]["text"] == _phrases(proj)[0]["text"]
    assert r["phrases"][0]["edited"] is False and r["phrases"][0]["stale"] is True
    d, words, cuts = render._load_inputs(proj)
    ph, stale = captions.apply_edits(_phrases(proj), render.load_edits(proj))
    assert stale == [0] and ph[0]["text"] != "editada"


def test_render_warns_stale_edit(proj, capsys):
    _jw(proj / "legendas.json", {"edits": [
        {"idx": 0, "base_text": "outro", "text": "Leia com atenção."}]})
    with pytest.raises(Exception):  # sem video real nem marca: falha depois do aviso
        render.render(proj, "preview", brand_path=proj / "nao-existe.json")
    assert "frase 0" in capsys.readouterr().err


def _cli(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def test_cli_exit_codes(proj, tmp_path):
    dec = tmp_path / "d.json"
    _jw(dec, {"cuts_removed": ["c2"]})
    r = _cli("apply", proj, dec)
    assert r.returncode == 0, r.stderr
    _jw(dec, {"cuts_removed": ["zz"]})
    r = _cli("apply", proj, dec)
    assert r.returncode == 1 and "zz" in r.stderr
    _jw(dec, {"caption_edits": {"0": "garantimos que você ganha a causa"}})
    r = _cli("apply", proj, dec)
    assert r.returncode == 0, r.stderr
    before = _snapshot(proj)
    dec.write_text("{nao json", "utf-8")
    assert _cli("apply", proj, dec).returncode == 1
    assert _snapshot(proj) == before
    r = _cli("build", proj)
    assert r.returncode == 0, r.stderr
    assert _read(proj, "review.json")["duration"] == 6.0
    assert _cli("build", proj / "nada").returncode == 1


def test_merge_keeps_smallest_id_and_records_absorbed(proj):
    ra.apply(proj, {"cuts_added": [{"start": 5.0, "end": 6.0}]})   # c3
    ra.apply(proj, {"cuts_added": [{"start": 1.0, "end": 2.0}]})   # c4
    ra.apply(proj, {"cuts_added": [{"start": 1.5, "end": 5.5}]})
    manual = [c for c in _read(proj, "cortes.json")["cuts"] if c["kind"] == "manual"]
    assert manual == [{"id": "c3", "start": 1.0, "end": 6.0, "kind": "manual"}]
    assert [c["id"] for c in _read(proj, "revisao.json")["removed_cuts"]] == ["c4"]


def test_partial_write_then_rerun_has_no_duplicates(proj, monkeypatch):
    import common
    real, calls = common.write_json_atomic, []

    def flaky(path, data):
        calls.append(path)
        if len(calls) == 3:
            raise OSError("disco cheio")
        return real(path, data)
    monkeypatch.setattr(common, "write_json_atomic", flaky)
    with pytest.raises(OSError):
        ra.apply(proj, {"cuts_removed": ["c2"]})
    monkeypatch.setattr(common, "write_json_atomic", real)
    r = ra.build_review(proj)
    assert [c["id"] for c in r["cuts"]].count("c2") == 1
    ra.apply(proj, {"cuts_removed": ["c2"]})
    ids = [c["id"] for c in _read(proj, "revisao.json")["removed_cuts"]]
    assert ids == ["c2"]
    r = ra.build_review(proj)
    assert sorted(c["id"] for c in r["cuts"]) == ["c1", "c2"]


# ---- onda final, item 1: barra invertida e chaves nas edicoes de legenda ----
BACKSLASH_EDIT = "Veja o art\\5 e a Lei\\13467."


@pytest.mark.parametrize("text", ["Leia com {calma}", "Leia com calma\\N", "Leia\\hcom calma", "a } b",
                                  BACKSLASH_EDIT])
def test_edit_with_backslash_or_braces_rejected(proj, text):
    before = _snapshot(proj)
    with pytest.raises(ra.ReviewError, match=r"barra invertida|chaves"):
        ra.apply(proj, {"caption_edits": {"1": text}})
    assert _snapshot(proj) == before


def test_cli_backslash_edits_exit_codes(proj, tmp_path):
    before = _snapshot(proj)
    dec = tmp_path / "d.json"
    _jw(dec, {"caption_edits": {"1": BACKSLASH_EDIT}})
    r = _cli("apply", proj, dec)
    assert r.returncode == 1 and "barra invertida" in r.stderr and "Traceback" not in r.stderr
    _jw(dec, {"caption_edits": {"1": "Leia com {calma}"}})
    r = _cli("apply", proj, dec)
    assert r.returncode == 1 and "chaves" in r.stderr and "Traceback" not in r.stderr
    assert _snapshot(proj) == before


@pytest.mark.parametrize("text", ["Leia\na intimação\ncom calma.", "Leia\u2028a intimação\rcom calma."])
def test_caption_edit_with_more_than_two_lines_rejected(proj, text):
    before = _snapshot(proj)
    with pytest.raises(ra.ReviewError, match="2 linhas"):
        ra.apply(proj, {"caption_edits": {"1": text}})
    assert _snapshot(proj) == before


def test_legit_two_line_caption_edit_passes(proj):
    ra.apply(proj, {"caption_edits": {"1": "Leia a intimação\ncom atenção."}})
    assert _read(proj, "legendas.json")["edits"][0]["text"] == "Leia a intimação\ncom atenção."


# ---- onda final, item 7: edicao de legenda presa ao texto automatico que o revisor viu ----
def test_pinned_caption_edit_applies_when_base_matches(proj):
    base = _phrases(proj)[1]["text"]
    ra.apply(proj, {"caption_edits": {"1": {"text": "Leia com atenção.", "base_text": base}}})
    assert _read(proj, "legendas.json")["edits"] == [
        {"idx": 1, "base_text": base, "text": "Leia com atenção."}]
    ra.apply(proj, {"caption_edits": {"1": {"text": "", "base_text": base}}})  # vazio volta ao automatico
    assert _read(proj, "legendas.json")["edits"] == []


def test_pinned_caption_edit_rejected_after_cuts_changed(proj):
    base = _phrases(proj)[0]["text"]
    # cortes.json mudou depois que a pagina salvou (corte em "prazo"): a frase 0 e outra
    _jw(proj / "cortes.json", {"cuts": CUTS + [{"id": "c3", "start": 0.7, "end": 1.1, "kind": "manual"}]})
    before = _snapshot(proj)
    with pytest.raises(ra.ReviewError, match="frase 0.*mudou"):
        ra.apply(proj, {"caption_edits": {"0": {"text": "Outro texto", "base_text": base}}})
    assert _snapshot(proj) == before


@pytest.mark.parametrize("bad", [{"text": "x"}, {"base_text": "y"}, {"text": 1, "base_text": "y"},
                                 {"text": "x", "base_text": "y", "extra": 1}, ["x"], 3])
def test_malformed_pinned_caption_edit_rejected(proj, bad):
    with pytest.raises(ra.ReviewError, match="frase 1"):
        ra.apply(proj, {"caption_edits": {"1": bad}})


# ---- onda final, item 11: aplicar as mesmas decisoes duas vezes ----
def test_same_decisions_applied_twice_is_a_no_op(proj, tmp_path):
    base = _phrases(proj)[1]["text"]
    dec = tmp_path / "d.json"
    _jw(dec, {"cuts_removed": ["c2"], "cuts_added": [{"start": 4.9, "end": 5.3}],
              "caption_edits": {"0": "O prazo para recorrer"}, "graphics": {"g1": "drop"},
              "notes": [{"t": 1, "text": "luz"}]})
    r = _cli("apply", proj, dec)
    assert r.returncode == 0, r.stderr
    first = _snapshot(proj)
    r = _cli("apply", proj, dec)
    assert r.returncode == 0, r.stderr
    assert _snapshot(proj) == first
    assert base  # frase 1 existe


def test_removed_cut_id_is_no_op_but_unknown_id_still_errors(proj):
    ra.apply(proj, {"cuts_removed": ["c2"]})
    ra.apply(proj, {"cuts_removed": ["c2"]})
    assert [c["id"] for c in _read(proj, "revisao.json")["removed_cuts"]] == ["c2"]
    assert [c["id"] for c in _read(proj, "cortes.json")["cuts"]] == ["c1"]
    with pytest.raises(ra.ReviewError, match="c9"):
        ra.apply(proj, {"cuts_removed": ["c9"]})


def test_invalid_graficos_json_is_review_error(proj):
    _jw(proj / "graficos.json", {"cards": [{"id": "k1"}]})
    with pytest.raises(ra.ReviewError):
        ra.apply(proj, {"graphics": {"k1": "keep"}})
