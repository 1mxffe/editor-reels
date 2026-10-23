import builtins
import shutil

import doctor


def _all_present(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor, "_has_whisper", lambda: True)
    monkeypatch.setattr(doctor, "_free_gb", lambda path=".": 100.0)
    monkeypatch.setattr(doctor, "_graphics_reason", lambda: None)
    monkeypatch.setattr(doctor, "_has_pillow", lambda: True)


def test_doctor_ready_when_all_present(monkeypatch):
    _all_present(monkeypatch)
    status, items = doctor.check()
    assert status == "READY"
    assert all(i["ok"] for i in items)
    assert {"name", "ok", "required"} <= set(items[0])


def test_doctor_missing_ffmpeg_is_missing(monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "ffmpeg" else f"/usr/bin/{name}")
    status, items = doctor.check()
    assert status == "MISSING"
    assert [i for i in items if i["name"] == "ffmpeg"][0]["ok"] is False


def test_doctor_whisper_missing_is_limits(monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor, "_has_whisper", lambda: False)
    status, _ = doctor.check()
    assert status == "READY WITH LIMITS"


def test_doctor_low_disk_is_missing(monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor, "_free_gb", lambda path=".": 2.0)
    status, _ = doctor.check()
    assert status == "MISSING"


def test_main_last_line_and_exit_code(monkeypatch, capsys):
    _all_present(monkeypatch)
    assert doctor.main() == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "READY"
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert doctor.main() == 1
    assert capsys.readouterr().out.strip().splitlines()[-1] == "MISSING"


def test_main_falls_back_to_ascii_marks(monkeypatch):
    import io
    import sys
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor, "_has_whisper", lambda: False)
    buf = io.BytesIO()
    out = io.TextIOWrapper(buf, encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", out)
    assert doctor.main() == 0
    out.flush()
    text = buf.getvalue().decode("ascii")
    assert "[ok] ffmpeg" in text
    assert "[x] faster_whisper (opcional)" in text
    assert text.strip().splitlines()[-1] == "READY WITH LIMITS"


def test_doctor_chromium_missing_is_limits(monkeypatch, capsys):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor, "_graphics_reason", lambda: "playwright (node) ausente")
    status, items = doctor.check()
    assert status == "READY WITH LIMITS"
    item = [i for i in items if "graficos" in i["name"]][0]
    assert item["ok"] is False and item["required"] is False
    assert doctor.main() == 0
    assert "playwright (node) ausente" in capsys.readouterr().out


def test_main_ascii_with_accented_detail(monkeypatch):
    import io
    import sys
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor, "_graphics_reason", lambda: "ffmpeg sem libvpx-vp9 (vídeo)")
    buf = io.BytesIO()
    out = io.TextIOWrapper(buf, encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", out)
    assert doctor.main() == 0
    out.flush()
    assert "[x] chromium + playwright (opcional: graficos) (ffmpeg sem libvpx-vp9 (v?deo))" in buf.getvalue().decode()


# ---- onda final, item 6: python >= 3.11 ----
def test_old_python_is_missing_and_graphics_not_imported(monkeypatch, capsys):
    import sys
    _all_present(monkeypatch)

    def boom():
        raise AssertionError("graphics nao pode ser importado em python antigo")
    monkeypatch.setattr(doctor, "_graphics_reason", boom)
    monkeypatch.setattr(doctor.sys, "version_info", (3, 9, 18, "final", 0))
    status, items = doctor.check()
    assert status == "MISSING"
    py = items[0]
    assert py["name"] == "python >= 3.11" and py["required"] is True and py["ok"] is False
    assert "3.9" in py["detail"] and "brew install python@3.13" in py["detail"]
    assert doctor.main() == 1
    assert "python >= 3.11" in capsys.readouterr().out


def test_current_python_item_ok(monkeypatch):
    _all_present(monkeypatch)
    status, items = doctor.check()
    assert items[0]["name"] == "python >= 3.11" and items[0]["ok"] is True


def test_doctor_runs_on_old_python():
    """doctor.py sobe no python 3.9 (stock macOS) para conseguir REPORTAR: anotacoes
    adiadas e nenhum import de script irmao no nivel do modulo."""
    import ast
    from pathlib import Path
    src = (Path(doctor.__file__)).read_text("utf-8")
    tree = ast.parse(src, feature_version=(3, 9))
    body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    assert isinstance(body[0], ast.ImportFrom) and body[0].module == "__future__"
    top = {a.name.split(".")[0] for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
           for a in n.names} | {n.module for n in tree.body if isinstance(n, ast.ImportFrom)}
    siblings = {p.stem for p in Path(doctor.__file__).parent.glob("*.py")}
    assert not (top & siblings)


# ---- onda final, item 15 (M12): node e Pillow so para cards/capa: opcionais ----
def test_node_missing_is_limits_not_missing(monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "node" else f"/usr/bin/{name}")
    status, items = doctor.check()
    assert status == "READY WITH LIMITS"
    node = [i for i in items if i["name"].startswith("node")][0]
    assert node["ok"] is False and node["required"] is False


def test_pillow_missing_is_limits_with_note(monkeypatch, capsys):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor, "_has_pillow", lambda: False)
    status, items = doctor.check()
    assert status == "READY WITH LIMITS"
    pil = [i for i in items if i["name"].startswith("Pillow")][0]
    assert pil["required"] is False and "capa" in pil["name"] and "pip install" in pil["detail"]
    assert doctor.main() == 0 and "Pillow" in capsys.readouterr().out


def test_required_items_are_python_ffmpeg_ffprobe_disk(monkeypatch):
    _all_present(monkeypatch)
    _, items = doctor.check()
    assert [i["name"] for i in items if i["required"]] == [
        "python >= 3.11", "ffmpeg", "ffprobe", f"disco livre >= {doctor.MIN_FREE_GB} GB"]


# ---- --json (interface web) ----
def test_doctor_json_flag_matches_default_exit_code(monkeypatch, capsys):
    import json
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor, "_has_whisper", lambda: False)
    assert doctor.main() == 0
    padrao = capsys.readouterr().out
    assert padrao.strip().splitlines()[-1] == "READY WITH LIMITS"
    assert doctor.main(["--json"]) == 0
    dados = json.loads(capsys.readouterr().out)
    status, items = doctor.check()
    assert dados == {"estado": status, "itens": items}
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert doctor.main() == 1
    capsys.readouterr()
    assert doctor.main(["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["estado"] == "MISSING"


def test_doctor_json_is_ascii_safe(monkeypatch, capsys):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor, "_graphics_reason", lambda: "vídeo ausente")
    doctor.main(["--json"])
    assert capsys.readouterr().out.isascii()
