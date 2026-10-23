import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest_app import client, repo_root  # noqa: F401
from fixtures_app import montar_projeto
from server import make_server

TOKEN = "tok-de-teste-123"
SCRIPT = repo_root / "scripts" / "review_apply.py"


@pytest.fixture
def srv(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    s = make_server(root, TOKEN, test_mode=True)
    s.app.brand_path = tmp_path / "brand.json"  # nunca o brand real
    return s


@pytest.fixture
def slug(srv):
    p = srv.app.projects.create("Meu Reel")
    montar_projeto(srv.app.projects.path(p["slug"]))
    return p["slug"]


def _rev(slug):
    return f"/api/projects/{slug}/revisao"


def _put(c, slug, corpo):
    return c.request("PUT", _rev(slug), body=corpo)


def test_revisao_build_matches_script_output(srv, slug):
    d = srv.app.projects.path(slug)
    with client(srv) as c:
        r = c.get(_rev(slug))
        assert r.status == 200
        dados = r.json()
    subprocess.run([sys.executable, "-I", str(SCRIPT), "build", str(d)], check=True,
                   cwd=repo_root, capture_output=True)
    assert dados == json.loads((d / "review.json").read_text("utf-8"))
    assert {"words", "cuts", "phrases", "notes", "graphics", "kept_duration"} <= set(dados)
    assert len(dados["cuts"]) == 2


def test_revisao_without_transcription_409(srv):
    p = srv.app.projects.create("Sem Fala")
    with client(srv) as c:
        r = c.get(_rev(p["slug"]))
        assert r.status == 409 and "transcreva" in r.json()["erro"]


def test_put_cut_removed_then_build_reflects(srv, slug):
    d = srv.app.projects.path(slug)
    with client(srv) as c:
        r = _put(c, slug, {"cuts_removed": ["c2"]})
        assert r.status == 200
        ativos = {x["id"] for x in r.json()["cuts"] if x["active"]}
        assert ativos == {"c1"}
        assert {x["id"] for x in c.get(_rev(slug)).json()["cuts"] if not x["active"]} == {"c2"}
    assert [x["id"] for x in json.loads((d / "cortes.json").read_text())["cuts"]] == ["c1"]
    assert list(d.glob("*.tmp")) == [] and not [p for p in d.iterdir() if "decisoes" in p.name]


def test_put_caption_edit_pinned_to_base_text_mismatch_400(srv, slug):
    with client(srv) as c:
        fr = c.get(_rev(slug)).json()["phrases"][0]
        r = _put(c, slug, {"caption_edits": {"0": {"text": "Outro texto", "base_text": "errado"}}})
        assert r.status == 400 and "mudou" in r.json()["erro"]
        assert "Traceback" not in r.json()["erro"]
        ok = _put(c, slug, {"caption_edits": {"0": {"text": "Outro texto",
                                                    "base_text": fr["base_text"]}}})
        assert ok.status == 200
        assert ok.json()["phrases"][0]["text"] == "Outro texto" and ok.json()["phrases"][0]["edited"]


def test_put_idempotent_twice_same_decisions(srv, slug):
    dec = {"cuts_removed": ["c2"], "cuts_added": [{"start": 4.0, "end": 4.2}],
           "notes": [{"t": 1, "text": "ok"}]}
    with client(srv) as c:
        a = _put(c, slug, dec)
        b = _put(c, slug, dec)
        assert a.status == b.status == 200 and a.json() == b.json()


@pytest.mark.parametrize("corpo", [
    {"cuts_removed": ["c99"]},
    {"cuts_removed": "c1"},
    {"chave_desconhecida": 1},
    {"graphics": {"g1": "talvez"}},
    {"notes": "texto"},
    {"caption_edits": {"x": "a"}},
    [1, 2],
    b'"texto"',
    {"cuts_added": [{"start": 5, "end": 99}]},
])
def test_put_invalid_decisions_400_no_traceback(srv, slug, corpo):
    d = srv.app.projects.path(slug)
    antes = (d / "cortes.json").read_bytes()
    with client(srv) as c:
        r = _put(c, slug, corpo)
        assert r.status == 400
        msg = r.json()["erro"]
        assert msg and "Traceback" not in msg and "File \"" not in msg
    assert (d / "cortes.json").read_bytes() == antes


def test_put_body_too_large_413_and_json_errors(srv, slug):
    with client(srv) as c:
        assert _put(c, slug, b"x" * (2 * 1024 * 1024)).status == 413
        assert _put(c, slug, b"{nao json").status == 400
        assert _put(c, slug, b"[" * 100000 + b"]" * 100000).status == 400


def test_put_accepts_body_above_64k(srv, slug):
    with client(srv) as c:
        notas = [{"t": 1, "text": "n" * 200} for _ in range(500)]  # ~100 KB
        assert _put(c, slug, {"notes": notas}).status == 200


def test_methods_and_unknown_slug(srv, slug):
    with client(srv) as c:
        assert c.request("POST", _rev(slug), body={}).status == 405
        assert c.request("DELETE", _rev(slug)).status == 405
        assert c.get(_rev("nao-existe")).status == 404
        assert _put(c, "nao-existe", {}).status == 404
        assert c.get(f"/api/projects/{slug}/etapas/legendas").status == 405
        assert c.request("PUT", "/api/projects/nao-existe/etapas/legendas",
                         body={"confirmado": True}).status == 404
        assert c.request("PUT", f"/api/projects/{slug}/etapas/video",
                         body={"confirmado": True}).status == 404


def test_put_409_when_job_active(srv, slug, monkeypatch):
    monkeypatch.setattr(srv.app.jobs, "ativo_em", lambda s: {"id": "x"})
    with client(srv) as c:
        assert _put(c, slug, {}).status == 409
        assert c.get(_rev(slug)).status == 409


def test_concurrent_revisions_are_serialized(srv, slug, monkeypatch):
    import revisao_api
    ativos, pico = [0], [0]
    mu = threading.Lock()
    real = subprocess.run

    def lento(*a, **k):
        with mu:
            ativos[0] += 1
            pico[0] = max(pico[0], ativos[0])
        time.sleep(0.15)
        try:
            return real(*a, **k)
        finally:
            with mu:
                ativos[0] -= 1

    monkeypatch.setattr(revisao_api.subprocess, "run", lento)
    res = []
    with client(srv) as c:
        def uma():
            res.append(_put(c, slug, {"notes": [{"t": 1, "text": "a"}]}).status)
        ts = [threading.Thread(target=uma) for _ in range(3)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    assert res == [200, 200, 200] and pico[0] == 1


def test_script_timeout_500(srv, slug, monkeypatch):
    import revisao_api

    def estoura(*a, **k):
        raise subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(revisao_api.subprocess, "run", estoura)
    with client(srv) as c:
        r = c.get(_rev(slug))
        assert r.status == 500 and "tempo" in r.json()["erro"]


def test_legendas_confirm_marks_step(srv, slug):
    d = srv.app.projects.path(slug)
    url = f"/api/projects/{slug}/etapas/legendas"
    with client(srv) as c:
        assert c.get(f"/api/projects/{slug}").json()["etapas"]["legendas"] == "pendente"
        r = c.request("PUT", url, body={"confirmado": True})
        assert r.status == 200
        assert json.loads((d / "etapas.json").read_text())["legendas"] is True
        assert c.get(f"/api/projects/{slug}").json()["etapas"]["legendas"] == "pronto"
        assert c.request("PUT", url, body={"confirmado": False}).status == 200
        assert c.get(f"/api/projects/{slug}").json()["etapas"]["legendas"] == "pendente"
        for ruim in ({"confirmado": "sim"}, {"confirmado": True, "x": 1}, {}, [True], b"3"):
            assert c.request("PUT", url, body=ruim).status == 400
        assert c.request("PUT", url, body=b"x" * 70000).status == 413


def test_job_start_409_while_revision_runs(srv, slug):
    import revisao_api
    with client(srv) as c:
        t = revisao_api.trava(slug)
        t.acquire()
        try:
            r = c.request("POST", f"/api/projects/{slug}/jobs/transcrever", body={})
            assert r.status == 409
        finally:
            t.release()
