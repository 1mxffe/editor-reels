"""Fluxo ponta a ponta pelas CLIs: detect -> render preview (a transcricao e dada, sem Whisper)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops

import captions
import cut

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".claude" / "skills" / "editor-reel" / "SKILL.md"

# Fala dentro dos trechos mantidos; uma pausa de 1,5 s (2.4-3.9) e uma muleta "ãh".
TRANSCRIPT = {
    "duration": 6.0,
    "words": [{"w": w, "start": s, "end": e} for w, s, e in [
        ("O", 0.40, 0.60), ("prazo", 0.60, 1.00), ("para", 1.00, 1.20), ("recorrer", 1.20, 1.60),
        ("conta", 1.60, 1.90), ("dias", 1.90, 2.10), ("úteis.", 2.10, 2.40),
        ("Leia", 3.90, 4.20), ("ãh", 4.20, 4.40), ("a", 4.40, 4.50), ("intimação", 4.50, 5.00),
        ("com", 5.00, 5.10), ("calma.", 5.10, 5.30),
    ]],
}
SALES_PITCH = {  # o editor nao confere texto: o escritorio revisa antes de gravar
    "duration": 6.0,
    "words": [{"w": w, "start": s, "end": e} for w, s, e in [
        ("garantimos", 0.50, 1.00), ("que", 1.00, 1.20), ("você", 1.20, 1.50),
        ("ganha", 1.50, 1.80), ("a", 1.80, 1.90), ("causa.", 1.90, 2.30),
    ]],
}


def _py(*args):
    return subprocess.run(["python3", "-I", *map(str, args)], capture_output=True, text=True)


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def _project(root: Path, video: Path, transcript: dict) -> Path:
    proj = root / "projects" / "reel"
    proj.mkdir(parents=True)
    shutil.copy(video, proj / "entrada.mp4")
    (proj / "transcricao.json").write_text(json.dumps(transcript, ensure_ascii=False), "utf-8")
    return proj


def _stream(video: Path, kind: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,duration",
         "-of", "json", str(video)], check=True, capture_output=True, text=True).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}[kind]


def _frame(video: Path, t: float, out: Path) -> Image.Image:
    _ffmpeg("-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", out)
    return Image.open(out).convert("RGB")


@pytest.fixture
def solid_sample(tmp_path, make_sample):
    """Mesmo formato do make_sample (6 s, 1080x1920, audio), mas de cor solida:
    fora das frases a faixa de legenda fica uniforme, entao qualquer diferenca e legenda."""
    out = tmp_path / "solid.mp4"
    _ffmpeg("-f", "lavfi", "-i", "color=c=0x808080:size=1080x1920:rate=30:duration=6",
            "-i", make_sample, "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", out)
    return out


def test_e2e_fixture_to_preview(tmp_path, solid_sample):
    proj = _project(tmp_path, solid_sample, TRANSCRIPT)
    brand_copy = tmp_path / "brand.json"
    shutil.copy(REPO / "brand" / "brand.json", brand_copy)

    det = _py(REPO / "scripts" / "cut.py", "detect", proj / "transcricao.json", proj / "cortes.json")
    assert det.returncode == 0, det.stderr
    cuts = json.loads((proj / "cortes.json").read_text("utf-8"))["cuts"]
    kinds = {c["kind"] for c in cuts}
    assert {"silence", "filler"} <= kinds

    r = _py(REPO / "scripts" / "render.py", proj, "preview", "--brand", brand_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    out = proj / "saida" / "preview.mp4"
    assert out.is_file()
    v = _stream(out, "video")
    assert (int(v["width"]), int(v["height"])) == (540, 960)

    # a pausa de 1,5 s perde 0,15 s de folga de cada lado: o corte economiza >= 1,2 s
    dur = float(_stream(out, "video")["duration"])
    assert dur <= 6.0 - (1.5 - 2 * cut.PAD) + 0.1
    # e nao corta demais: sai pelo menos o tempo mantido (menos 0,5 s de folga)
    kept_time = sum(b - a for a, b in cut.keep_segments(6.0, cuts))
    assert dur >= kept_time - 0.5

    # legenda queimada: quadro no meio da 1a frase difere de um quadro sem legenda
    keep = cut.keep_segments(6.0, cuts)
    first = captions.phrases(captions.remap(TRANSCRIPT["words"], keep))[0]
    with_cap = _frame(out, (first["start"] + first["end"]) / 2, tmp_path / "a.png")
    no_cap = _frame(out, first["start"] / 2, tmp_path / "b.png")
    w, h = with_cap.size
    band = (0, h * 2 // 3, w, h)
    diff = ImageChops.difference(with_cap.crop(band), no_cap.crop(band))
    assert diff.getbbox() is not None
    assert max(hi for _, hi in diff.getextrema()) > 60
    assert (proj / "entrada.mp4").read_bytes() == solid_sample.read_bytes()


def test_e2e_any_text_renders(tmp_path, make_sample):
    proj = _project(tmp_path, make_sample, SALES_PITCH)
    (proj / "cortes.json").write_text(json.dumps({"cuts": []}), "utf-8")
    r = _py(REPO / "scripts" / "render.py", proj, "preview")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == str(proj / "saida" / "preview.mp4")
    assert _stream(proj / "saida" / "preview.mp4", "video")["width"] == 540


def _frontmatter() -> dict:
    text = SKILL.read_text("utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md sem frontmatter"
    # A stdlib nao tem parser YAML: regex de "chave: valor" de uma linha. Por
    # isso a descricao nao pode ter ": " (em YAML real viraria outro mapeamento).
    fm = dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M))
    try:
        import yaml  # opcional; nao e dependencia do projeto
    except ImportError:
        return fm
    parsed = yaml.safe_load(m.group(1))
    assert parsed == fm, "frontmatter nao e YAML simples de uma linha por chave"
    return parsed


def test_skill_frontmatter_valid():
    fm = _frontmatter()
    assert fm["name"] == "editor-reel"
    assert fm["description"].strip()
    assert ": " not in fm["description"]


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_skill_doc_rules():
    text = SKILL.read_text("utf-8")
    # "final" ja e a aprovacao do preview
    gatilhos = _section(text, "## Gatilhos", "## Duração alvo")
    assert "é a aprovação do preview" in gatilhos
    # video sem audio e falha da transcricao, nao do render
    falha = _section(text, "Falha (código 1", "## Gatilhos")
    assert "áudio" not in falha
    passo2 = _section(text, "2. `python3 -I scripts/transcribe.py", "3. `python3")
    assert "sem áudio" in passo2
    assert "READY WITH LIMITS" in passo2 and "pip install faster-whisper" in passo2
    # seed so quando brand.json esta ausente
    entrevista = _section(text, "## Entrevista de marca", "## Fluxo")
    assert "só se `brand/brand.json` estiver ausente" in entrevista
    assert "nunca sobre um arquivo existente" in entrevista
    readme = (REPO / "README.md").read_text("utf-8")
    assert "seed" in readme and "nunca sobre um arquivo existente" in readme


def test_skill_commands_exist():
    refs = set(re.findall(r"scripts/[\w\-]+\.py", SKILL.read_text("utf-8")))
    assert {"scripts/doctor.py", "scripts/transcribe.py", "scripts/cut.py",
            "scripts/render.py", "scripts/brand.py"} <= refs
    for ref in refs:
        assert (REPO / ref).is_file(), ref
