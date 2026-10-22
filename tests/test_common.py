import json

import pytest

import common


def test_write_json_atomic_creates_parents_and_no_tmp(tmp_path):
    p = tmp_path / "a" / "b.json"
    common.write_json_atomic(p, {"x": "ção"})
    assert json.loads(p.read_text(encoding="utf-8")) == {"x": "ção"}
    assert not p.with_name("b.json.tmp").exists()


def test_fail_prints_and_exits(capsys):
    with pytest.raises(SystemExit) as e:
        common.fail("boom", 3)
    assert e.value.code == 3
    assert capsys.readouterr().err.strip() == "erro: boom"


def test_run_returns_stdout_and_fails_on_error(capsys):
    assert common.run(["echo", "oi"]).strip() == "oi"
    with pytest.raises(SystemExit):
        common.run(["sh", "-c", "echo bad >&2; exit 2"])
    assert "bad" in capsys.readouterr().err


def test_make_sample(make_sample):
    out = common.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type", "-of", "csv=p=0", str(make_sample)])
    assert "1080,1920" in out and "audio" in out


# --- Task 3b ---------------------------------------------------------------
import os  # noqa: E402
import subprocess  # noqa: E402

import conftest  # noqa: E402


def test_write_json_atomic_removes_tmp_when_replace_fails(tmp_path, monkeypatch):
    p = tmp_path / "b.json"

    def boom(src, dst):
        raise OSError("disco cheio")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        common.write_json_atomic(p, {"x": 1})
    assert not p.exists()
    assert not p.with_name("b.json.tmp").exists()


def test_write_json_atomic_removes_tmp_when_write_fails(tmp_path, monkeypatch):
    p = tmp_path / "b.json"
    real = type(p).write_text

    def partial(self, text, *a, **k):
        real(self, text[:3], *a, **k)
        raise OSError("falha no meio")

    monkeypatch.setattr(type(p), "write_text", partial)
    with pytest.raises(OSError):
        common.write_json_atomic(p, {"x": 1})
    monkeypatch.undo()
    assert not p.exists()
    assert not p.with_name("b.json.tmp").exists()


def test_run_permission_error_fails_cleanly(tmp_path, capsys):
    exe = tmp_path / "nao-executavel"
    exe.write_text("#!/bin/sh\necho oi\n")
    exe.chmod(0o644)
    with pytest.raises(SystemExit) as e:
        common.run([str(exe)])
    assert e.value.code == 1
    assert "nao foi possivel executar" in capsys.readouterr().err


def test_build_sample_skips_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(conftest.shutil, "which", lambda name: None)
    with pytest.raises(pytest.skip.Exception):
        conftest.build_sample(tmp_path / "s.mp4")


def test_build_sample_captures_ffmpeg_output(tmp_path):
    with pytest.raises(subprocess.CalledProcessError) as e:
        conftest.build_sample(tmp_path / "nao" / "existe" / "s.mp4")
    assert e.value.stderr  # capturado, nao despejado no terminal


# ---- onda final, item 10: gravacao atomica com nome unico e modo normal ----
import os  # noqa: E402
import stat  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402


@pytest.fixture
def umask022():
    old = os.umask(0o022)
    yield
    os.umask(old)


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def _leftovers(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if ".tmp" in p.name)


def test_atomic_write_mode_follows_umask(tmp_path, umask022):
    out = tmp_path / "a.bin"
    with common.atomic_write(out, suffix=".mp4") as tmp:
        assert tmp.parent == tmp_path and tmp.name.endswith(".mp4") and tmp != out
        tmp.write_bytes(b"x")
    assert out.read_bytes() == b"x" and _mode(out) == 0o644
    common.write_json_atomic(tmp_path / "b.json", {"a": 1})
    assert _mode(tmp_path / "b.json") == 0o644
    os.umask(0o077)
    common.write_json_atomic(tmp_path / "c.json", {"a": 1})
    assert _mode(tmp_path / "c.json") == 0o600
    assert _leftovers(tmp_path) == []


def test_planted_symlink_at_old_tmp_name_is_untouched(tmp_path):
    victim = tmp_path / "vitima.txt"
    victim.write_text("original", "utf-8")
    (tmp_path / "x.json.tmp").symlink_to(victim)
    common.write_json_atomic(tmp_path / "x.json", {"ok": True})
    assert victim.read_text("utf-8") == "original"
    assert (tmp_path / "x.json.tmp").is_symlink()
    assert json.loads((tmp_path / "x.json").read_text("utf-8")) == {"ok": True}


def test_concurrent_writers_do_not_collide(tmp_path):
    out = tmp_path / "x.json"
    errors = []

    def writer(n):
        try:
            for i in range(30):
                common.write_json_atomic(out, {"writer": n, "i": i, "pad": "x" * 5000})
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert json.loads(out.read_text("utf-8"))["i"] == 29
    assert _leftovers(tmp_path) == []


def test_atomic_write_failure_cleans_temp_and_keeps_old(tmp_path):
    out = tmp_path / "x.json"
    out.write_text("velho", "utf-8")
    with pytest.raises(RuntimeError):
        with common.atomic_write(out) as tmp:
            tmp.write_text("meio", "utf-8")
            raise RuntimeError("falhou no meio")
    assert out.read_text("utf-8") == "velho" and _leftovers(tmp_path) == []
    with pytest.raises(TypeError):
        common.write_json_atomic(out, {"x": object()})
    assert out.read_text("utf-8") == "velho" and _leftovers(tmp_path) == []
