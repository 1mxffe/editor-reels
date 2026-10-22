"""Documentacao que a skill segue: o que ela diz precisa bater com o codigo."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = (REPO / ".claude" / "skills" / "editor-reel" / "SKILL.md").read_text("utf-8")
README = (REPO / "README.md").read_text("utf-8")


def _usage(script, *args):
    r = subprocess.run([sys.executable, "-I", str(REPO / "scripts" / script), *args],
                       capture_output=True, text=True)
    return r.stderr + r.stdout


def test_debug_clis_are_marked_internal():
    for script, args in (("cut.py", ()), ("captions.py", ())):
        text = _usage(script, *args)
        assert "uso interno" in text and "render.py" in text, script
    for name in ("cut.py", "captions.py"):
        assert "uso interno" in (REPO / "scripts" / name).read_text("utf-8").split('"""')[1]


def test_skill_never_runs_debug_clis_or_hand_edits_cuts():
    assert "cut.py apply" not in SKILL and "captions.py" not in SKILL
    assert "remova a entrada" not in SKILL
    step4 = SKILL[SKILL.index("4. "):SKILL.index("5. ")]
    assert "review_apply.py apply" in step4 and "cuts_removed" in step4


def test_review_page_opened_in_chromium_browser():
    assert 'open -a "Google Chrome" review/review.html' in SKILL
    assert "Safari" in SKILL and "xdg-open" in SKILL
    revisao = (REPO / "references" / "revisao.md").read_text("utf-8")
    assert 'open -a "Google Chrome" review/review.html' in revisao


def test_caption_weight_and_font_fallback_documented():
    legendas = (REPO / "references" / "legendas.md").read_text("utf-8")
    assert "Poppins Bold" in legendas and "SemiBold" not in legendas
    for doc in (SKILL, README):
        assert "assets/fonts/" in doc and "SIL OFL" in doc and "Poppins-Bold.ttf" in doc
