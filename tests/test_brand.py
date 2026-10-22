import json

import pytest

import brand


def test_load_missing_raises(tmp_path):
    with pytest.raises(brand.BrandMissing):
        brand.load(tmp_path / "nao-existe.json")


def test_load_incomplete_names_missing_keys(tmp_path):
    p = tmp_path / "brand.json"
    p.write_text(json.dumps({"accent": "#a8c8f0", "bg": "#001931"}), encoding="utf-8")
    with pytest.raises(brand.BrandMissing) as exc:
        brand.load(p)
    msg = str(exc.value)
    for key in ("fg", "muted", "font_title", "font_body", "handles", "caption_style"):
        assert key in msg
    assert "accent" not in msg


def test_seed_has_all_required():
    seed = brand.seed_from_guide()
    assert all(k in seed for k in brand.REQUIRED)
    assert seed["accent"] == "#a8c8f0"
    assert seed["bg"] == "#001931"
    assert seed["fg"] == "#ddebf5"
    assert seed["muted"] == "#566a7a"
    assert seed["font_title"] == "Poppins" and seed["font_body"] == "Poppins"
    assert seed["handles"] == []
    assert seed["caption_style"] == "static-phrase"


def test_handles_empty_blocks_cover_only(tmp_path):
    p = tmp_path / "brand.json"
    brand.write_seed(p)
    b = brand.load(p)  # handles vazio e valido para video
    assert b["handles"] == []
    with pytest.raises(brand.BrandMissing):
        brand.require_handles(b)
    assert brand.require_handles({**b, "handles": ["@gutmannesilva"]}) == ["@gutmannesilva"]


def test_committed_brand_json_is_seed():
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "brand" / "brand.json"
    committed = brand.load(path)
    seed = brand.seed_from_guide()
    # o @ das redes foi informado pelo escritório; o resto continua a semente
    assert committed.pop("handles") == ["@gutmannesilva"]
    seed.pop("handles")
    assert committed == seed


# --- Task 3b ---------------------------------------------------------------
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "brand.py"


def write(tmp_path, data, raw=None):
    p = tmp_path / "brand.json"
    p.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
    return p


def test_load_invalid_json_raises(tmp_path):
    with pytest.raises(brand.BrandMissing, match="invalido"):
        brand.load(write(tmp_path, None, raw="{nao json"))


def test_load_non_object_raises(tmp_path):
    with pytest.raises(brand.BrandMissing, match="objeto"):
        brand.load(write(tmp_path, ["#a8c8f0"]))


@pytest.mark.parametrize("key,value", [
    ("accent", "#fff"),
    ("bg", "001931"),
    ("fg", "#ddebfz"),
    ("muted", 566),
    ("font_title", ""),
    ("font_body", 3),
    ("caption_style", "   "),
    ("handles", "@gutmannesilva"),
    ("handles", ["@ok", ""]),
    ("handles", [1]),
])
def test_load_rejects_invalid_values(tmp_path, key, value):
    data = {**brand.seed_from_guide(), key: value}
    with pytest.raises(brand.BrandMissing) as exc:
        brand.load(write(tmp_path, data))
    msg = str(exc.value)
    assert "valor inválido" in msg and key in msg


def test_load_names_all_offending_keys(tmp_path):
    data = {**brand.seed_from_guide(), "accent": "azul", "font_body": None}
    with pytest.raises(brand.BrandMissing) as exc:
        brand.load(write(tmp_path, data))
    assert "accent" in str(exc.value) and "font_body" in str(exc.value)
    assert "muted" not in str(exc.value)


def test_load_valid_returns_same_dict(tmp_path):
    data = {**brand.seed_from_guide(), "accent": "#A8C8F0", "handles": ["@gutmannesilva"]}
    assert brand.load(write(tmp_path, data)) == data


def test_require_handles_strips_and_drops_empty():
    assert brand.require_handles({"handles": ["  @gutmannesilva ", "@gs"]}) == ["@gutmannesilva", "@gs"]
    with pytest.raises(brand.BrandMissing):
        brand.require_handles({"handles": ["  ", ""]})
    with pytest.raises(brand.BrandMissing):
        brand.require_handles({"handles": "@gutmannesilva"})


def run_cli(*args, cwd=None):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd)


def test_cli_seed_refuses_existing_unless_force(tmp_path):
    p = tmp_path / "brand.json"
    p.write_text('{"meu": "conteudo"}', encoding="utf-8")
    r = run_cli("seed", p)
    assert r.returncode == 1 and "--force" in r.stderr
    assert p.read_text(encoding="utf-8") == '{"meu": "conteudo"}'
    r = run_cli("seed", p, "--force")
    assert r.returncode == 0, r.stderr
    assert brand.load(p) == brand.seed_from_guide()


def test_cli_seed_new_file(tmp_path):
    p = tmp_path / "novo" / "brand.json"
    assert run_cli("seed", p).returncode == 0
    assert brand.load(p) == brand.seed_from_guide()


def test_cli_seed_unwritable_fails_cleanly(tmp_path):
    blocker = tmp_path / "arquivo"
    blocker.write_text("x")
    r = run_cli("seed", blocker / "brand.json")
    assert r.returncode == 1 and r.stderr.startswith("erro:") and "Traceback" not in r.stderr


def test_cli_seed_unknown_option_does_not_create_file(tmp_path):
    r = run_cli("seed", "--help", cwd=tmp_path)
    assert r.returncode == 1 and "uso:" in r.stderr  # erro de uso: 1, como todo erro
    assert list(tmp_path.iterdir()) == []


def test_cli_check_exit_codes(tmp_path):
    p = tmp_path / "brand.json"
    brand.write_seed(p)
    assert run_cli("check", p).returncode == 0
    p.write_text(json.dumps({**brand.seed_from_guide(), "bg": "#12"}), encoding="utf-8")
    r = run_cli("check", p)
    assert r.returncode == 1 and "valor inválido" in r.stderr
    r = run_cli("check", tmp_path / "nada.json")
    assert r.returncode == 1 and "ausente" in r.stderr


# ---- onda final, item 5: nome de fonte valido (vai para o Style do ASS e para o CSS) ----
BAD_FONTS = ["Poppins, Montserrat", "Poppins\nStyle: X,Arial", "Pop{pins}", "Pop\\pins", "Pop;pins",
             "'Poppins'", " Poppins", "-Poppins", "P" * 65, "Poppíns", "Poppins\t"]


@pytest.mark.parametrize("key", ["font_title", "font_body"])
@pytest.mark.parametrize("name", BAD_FONTS)
def test_bad_font_names_rejected(tmp_path, key, name):
    p = tmp_path / "brand.json"
    p.write_text(json.dumps({**brand.seed_from_guide(), key: name}), encoding="utf-8")
    with pytest.raises(brand.BrandMissing, match=key):
        brand.load(p)


@pytest.mark.parametrize("name", ["Poppins", "Inter", "Open Sans", "Source Sans 3", "Noto-Sans"])
def test_good_font_names_load(tmp_path, name):
    p = tmp_path / "brand.json"
    p.write_text(json.dumps({**brand.seed_from_guide(), "font_title": name, "font_body": name}),
                 encoding="utf-8")
    assert brand.load(p)["font_body"] == name


@pytest.mark.parametrize("style", ["static,phrase", "x\ny", "{x}", " static"])
def test_bad_caption_style_rejected(tmp_path, style):
    p = tmp_path / "brand.json"
    p.write_text(json.dumps({**brand.seed_from_guide(), "caption_style": style}), encoding="utf-8")
    with pytest.raises(brand.BrandMissing, match="caption_style"):
        brand.load(p)


def test_committed_brand_and_seed_still_load(tmp_path):
    from pathlib import Path
    brand.load(Path(__file__).resolve().parent.parent / "brand" / "brand.json")
    brand.write_seed(tmp_path / "b.json")
    brand.load(tmp_path / "b.json")


def test_font_name_checked_where_it_is_written():
    import captions
    import graphics
    bad = {**brand.seed_from_guide(), "font_body": "Poppins, Montserrat"}
    with pytest.raises(ValueError, match="fonte"):
        captions.to_ass([{"text": "Oi.", "start": 0, "end": 1}], bad)
    with pytest.raises(graphics.GraphicsError, match="font_body"):
        graphics._brand_tokens(bad)
