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
        d = srv.app.projects.path(slug)
        arq = {n: (d / n).read_bytes() for n in ("cortes.json", "legendas.json", "revisao.json")}
        b = _put(c, slug, dec)
        assert a.status == b.status == 200 and a.json() == b.json()
        assert arq == {n: (d / n).read_bytes() for n in arq}


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
    {"notes": [{"t": 1, "text": "\ud800"}]},
    {"notes": [{"t": 1, "text": "a\u0000b"}]},
    {"notes": [{"t": 1, "text": "a\u001bb"}]},
    {"caption_edits": {"0": "a\u0007b"}},
    {"graphics": {"x" * 65: "keep"}},
    {"graphics": {"   ": "keep"}},
    {"graphics": {"": "keep"}},
    {"graphics": {"a\u0001b": "keep"}},
    {"graphics": {f"g{i}": "keep" for i in range(501)}},
    {"caption_edits": {"0": "a" * 501}},
    {"caption_edits": {"0": {"text": "a", "base_text": "b" * 2001}}},
    {"notes": [{"t": 1, "text": "n" * 2001}]},
    {"notes": [{"t": 1, "text": "n"}] * 501},
])
def test_put_invalid_decisions_400_no_traceback(srv, slug, corpo):
    d = srv.app.projects.path(slug)
    antes = {f.name: f.read_bytes() for f in d.iterdir()}
    with client(srv) as c:
        r = _put(c, slug, corpo)
        assert r.status == 400
        msg = r.json()["erro"]
        assert msg and "Traceback" not in msg and "File \"" not in msg
    assert {f.name: f.read_bytes() for f in d.iterdir()} == antes


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
        assert c.get(_rev(slug)).status == 200  # leitura continua permitida


def test_concurrent_revisions_are_serialized(srv, slug, monkeypatch):
    import revisao_api
    ativos, pico = [0], [0]
    mu = threading.Lock()
    real = subprocess.Popen

    class Lento(real):
        def communicate(self, *a, **k):
            with mu:
                ativos[0] += 1
                pico[0] = max(pico[0], ativos[0])
            time.sleep(0.15)
            try:
                return super().communicate(*a, **k)
            finally:
                with mu:
                    ativos[0] -= 1

    monkeypatch.setattr(revisao_api.subprocess, "Popen", Lento)
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

    monkeypatch.setattr(revisao_api, "TIMEOUT", 1)
    fake = Path(srv.app.root).parent / "lento.py"
    fake.write_text("import subprocess, sys, time\n"
                    "subprocess.Popen(['sleep', '77'])\ntime.sleep(60)\n")
    monkeypatch.setattr(revisao_api, "SCRIPT", fake)
    d = srv.app.projects.path(slug)
    with client(srv) as c:
        r = c.get(_rev(slug))
        assert r.status == 500 and "tempo" in r.json()["erro"]
        assert _put(c, slug, {}).status == 500
    assert list(d.glob(".decisoes-*")) == []
    out = subprocess.run(["pgrep", "-f", "sleep 77"], capture_output=True, text=True).stdout
    assert out.strip() == ""  # o neto foi morto junto (grupo de processos)


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


def test_deep_json_and_lone_surrogate_raw_400(srv, slug):
    with client(srv) as c:
        prof = b"[" * 990 + b"]" * 990
        assert _put(c, slug, b'{"notes": ' + prof + b"}").status == 400
        assert _put(c, slug, b'{"notes": [{"t": 1, "text": "\\ud800"}]}').status == 400


def test_error_messages_hide_absolute_paths(srv, slug):
    d = srv.app.projects.path(slug)
    with client(srv) as c:
        for nome in ("cortes.json", "graficos.json", "legendas.json", "transcricao.json"):
            alvo = d / nome
            original = alvo.read_bytes() if alvo.exists() else None
            alvo.write_text("{x")
            for r in (c.get(_rev(slug)), _put(c, slug, {"notes": []})):
                assert r.status == 400, (nome, r.body)
                msg = r.json()["erro"]
                assert str(d) not in msg and str(d.parent) not in msg, msg
                assert "/tmp" not in msg and "/home" not in msg, msg
            if original is None:
                alvo.unlink()
            else:
                alvo.write_bytes(original)


def test_script_missing_or_crash_is_500(srv, slug, monkeypatch, tmp_path):
    import revisao_api
    ruim = tmp_path / "ruim.py"
    ruim.write_text("import sys\nsys.stderr.write('Traceback...\\n')\nsys.exit(1)\n")
    crash = tmp_path / "crash.py"
    crash.write_text("raise SystemExit(3)\n")
    with client(srv) as c:
        for script in (tmp_path / "nao-existe.py", crash, ruim):
            monkeypatch.setattr(revisao_api, "SCRIPT", script)
            r = c.get(_rev(slug))
            assert r.status == 500, script
            assert str(tmp_path) not in r.json()["erro"] and "Traceback" not in r.json()["erro"]


def test_graphics_state_cap(srv, slug):
    with client(srv) as c:
        for lote in range(5):
            r = _put(c, slug, {"graphics": {f"g{lote}-{i}": "keep" for i in range(100)}})
            assert r.status == 200
        r = _put(c, slug, {"graphics": {"extra": "keep"}})
        assert r.status == 400 and "gráficos" in r.json()["erro"]


def test_lock_wait_times_out_409(srv, slug, monkeypatch):
    import revisao_api
    monkeypatch.setattr(revisao_api, "ESPERA_TRAVA", 0.2)
    t = revisao_api.trava(slug)
    t.acquire()
    try:
        with client(srv) as c:
            r = _put(c, slug, {})
            assert r.status == 409 and "outra edição" in r.json()["erro"]
    finally:
        t.release()


def test_orphan_decisions_tmp_swept(srv, slug):
    d = srv.app.projects.path(slug)
    (d / ".decisoes-abc.tmp").write_text("{}")
    with client(srv) as c:
        assert _put(c, slug, {}).status == 200
    assert list(d.glob(".decisoes-*")) == []


def test_job_start_409_has_codes(srv, slug):
    import revisao_api
    with client(srv) as c:
        t = revisao_api.trava(slug)
        t.acquire()
        try:
            r = c.request("POST", f"/api/projects/{slug}/jobs/transcrever", body={})
            assert r.json()["codigo"] == "revisao_em_andamento"
        finally:
            t.release()


def test_confirm_legendas_without_transcription_409(srv):
    p = srv.app.projects.create("Vazio")
    with client(srv) as c:
        r = c.request("PUT", f"/api/projects/{p['slug']}/etapas/legendas", body={"confirmado": True})
        assert r.status == 409
        assert c.request("PUT", f"/api/projects/{p['slug']}/etapas/legendas",
                         body={"confirmado": False}).status == 200


def test_413_2mib_stable(srv, slug):
    with client(srv) as c:
        for _ in range(100):
            assert _put(c, slug, b"x" * (2 * 1024 * 1024)).status == 413


def test_real_flow_with_ffmpeg(srv, make_sample):
    p = srv.app.projects.create("Real")
    d = srv.app.projects.path(p["slug"])
    import shutil
    shutil.copy(make_sample, d / "entrada.mp4")
    (d / "transcricao.json").write_text(json.dumps({"duration": 6.0, "words": [
        {"w": "Teste", "start": 0.5, "end": 1.0}, {"w": "real.", "start": 1.0, "end": 2.0}]}))
    subprocess.run([sys.executable, "-I", str(repo_root / "scripts" / "cut.py"), "detect", str(d / "transcricao.json"),
                    str(d / "cortes.json")],
                   check=True, cwd=repo_root, capture_output=True)
    with client(srv) as c:
        antes = c.get(_rev(p["slug"])).json()
        assert antes["cuts"]
        cid = antes["cuts"][0]["id"]
        depois = _put(c, p["slug"], {"cuts_removed": [cid]}).json()
        assert not [x for x in depois["cuts"] if x["id"] == cid and x["active"]]


def test_graphics_ids_like_the_engine(srv, slug):
    with client(srv) as c:
        r = _put(c, slug, {"graphics": {"card 1": "keep", "gráfico-1": "drop", "k.1": "keep",
                                         "a/b": "keep"}})
        assert r.status == 200 and r.json()["graphics"]["card 1"] == "keep"


def test_notes_newline_tab_and_crlf_normalized(srv, slug):
    with client(srv) as c:
        r = _put(c, slug, {"notes": [{"t": 1, "text": "linha1\r\nlinha2\rlinha3\tfim"}]})
        assert r.status == 200
        assert r.json()["notes"][0]["text"] == "linha1\nlinha2\nlinha3\tfim"
        fr = r.json()["phrases"][0]
        r = _put(c, slug, {"caption_edits": {"0": {"text": "um\r\ndois",
                                                   "base_text": fr["base_text"]}}})
        assert r.status == 200 and r.json()["phrases"][0]["text"] == "um\ndois"
        assert _put(c, slug, {"notes": [{"t": 1, "text": "a\u000bb"}]}).status == 400
        assert _put(c, slug, {"caption_edits": {"0": "a\tb"}}).status == 400


def test_sanitizar_only_real_paths(tmp_path):
    import revisao_api
    d = tmp_path / "p"
    d.mkdir()
    assert revisao_api.sanitizar(f"arquivo ilegivel ({d}/cortes.json): x", d) == \
        "arquivo ilegivel (<projeto>/cortes.json): x"
    assert revisao_api.sanitizar("de início / fim e 1/2", d) == "de início / fim e 1/2"
    assert revisao_api.sanitizar("falha em /etc/passwd agora", d) == "falha em passwd agora"
    assert revisao_api.sanitizar("ver /opt/x/y.json", d) == "ver y.json"


def test_drain_has_total_deadline(srv, slug, monkeypatch):
    import server
    import socket
    monkeypatch.setattr(server, "DEADLINE_DRENAR", 0.5)
    c0 = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        s = socket.create_connection(("127.0.0.1", c0), timeout=10)
        s.sendall((f"PUT /api/projects/{slug}/revisao HTTP/1.1\r\nHost: 127.0.0.1:{c0}\r\n"
                   f"X-Token: {TOKEN}\r\nContent-Length: {2*1024*1024}\r\n\r\n").encode())
        t0 = time.time()
        buf = b""
        # envia gotejando: o servidor deve desistir de drenar e fechar apos ~0.5 s
        try:
            for _ in range(40):
                s.sendall(b"x" * 10)
                time.sleep(0.1)
        except OSError:
            pass
        assert time.time() - t0 < 6
        s.settimeout(3)
        try:
            buf = s.recv(4096)
        except OSError:
            pass
        assert b"413" in buf.split(b"\r\n")[0] if buf else True
    finally:
        srv.shutdown()
        srv.server_close()
