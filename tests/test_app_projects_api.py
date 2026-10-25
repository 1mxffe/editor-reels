import http.client
import json
import shutil

import pytest

from conftest_app import client, repo_root  # noqa: F401
from server import make_server

TOKEN = "tok-de-teste-123"


@pytest.fixture
def srv(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    s = make_server(root, TOKEN, test_mode=True)
    brand = tmp_path / "brand.json"
    shutil.copy(repo_root / "brand" / "brand.json", brand)
    s.app.brand_path = brand
    return s


def _criar(c, nome="Meu Reel"):
    r = c.request("POST", "/api/projects", body={"nome": nome})
    assert r.status == 201, r.body
    return r.json()["slug"]


def test_create_and_list_projects(srv):
    with client(srv) as c:
        assert c.get("/api/projects").json() == []
        r = c.request("POST", "/api/projects", body={"nome": "Meu Reel"})
        assert r.status == 201
        proj = r.json()
        assert proj["slug"] == "meu-reel" and proj["nome"] == "Meu Reel"
        assert [p["slug"] for p in c.get("/api/projects").json()] == ["meu-reel"]
        st = c.get("/api/projects/meu-reel").json()
        assert st["slug"] == "meu-reel" and st["etapas"]["video"] == "pendente"
        # validacao
        assert c.request("POST", "/api/projects", body={}).status == 400
        assert c.request("POST", "/api/projects", body={"nome": 5}).status == 400
        assert c.request("POST", "/api/projects", body={"nome": "!!!"}).status == 400
        assert c.request("POST", "/api/projects", body=b"nao json").status == 400
        assert c.request("POST", "/api/projects", body=b"x" * 70000).status == 413
        assert c.get("/api/projects/nao-existe").status == 404
        assert c.request("DELETE", "/api/projects").status == 405
        assert c.get("/api/rota-inexistente").status == 404


def test_upload_valid_video_atomic(srv, make_sample):
    dados = make_sample.read_bytes()
    with client(srv) as c:
        slug = _criar(c)
        r = c.request("PUT", f"/api/projects/{slug}/video", body=dados,
                      headers={"X-Filename": "Bruto Final.MP4"})
        assert r.status == 200, r.body
        d = srv.app.projects.path(slug)
        assert (d / "entrada.mp4").read_bytes() == dados
        assert not list(d.glob("*.tmp"))
        assert c.get(f"/api/projects/{slug}").json()["etapas"]["video"] == "pronto"
        # substituir por outra extensao remove a antiga
        r = c.request("PUT", f"/api/projects/{slug}/video", body=dados,
                      headers={"X-Filename": "x.mov"})
        assert r.status == 200
        assert (d / "entrada.mov").exists() and not (d / "entrada.mp4").exists()
        assert not list(d.glob("*.tmp"))


def test_upload_text_renamed_mp4_rejected_no_leftover(srv):
    with client(srv) as c:
        slug = _criar(c)
        r = c.request("PUT", f"/api/projects/{slug}/video", body=b"isto nao e um video" * 100,
                      headers={"X-Filename": "falso.mp4"})
        assert r.status == 400
        assert r.json()["erro"] == "o arquivo não parece ser um vídeo"
        assert list(srv.app.projects.path(slug).glob("entrada*")) == []


def test_upload_empty_rejected(srv):
    with client(srv) as c:
        slug = _criar(c)
        r = c.request("PUT", f"/api/projects/{slug}/video", body=b"",
                      headers={"X-Filename": "a.mp4"})
        assert r.status == 400
        assert list(srv.app.projects.path(slug).glob("entrada*")) == []


def test_upload_over_limit_413_no_leftover(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    s = make_server(root, TOKEN, max_upload=1000, test_mode=True)
    with client(s) as c:
        slug = _criar(c)
        r = c.request("PUT", f"/api/projects/{slug}/video", body=b"x" * 5000,
                      headers={"X-Filename": "a.mp4"})
        assert r.status == 413
        assert list(s.app.projects.path(slug).glob("entrada*")) == []
        # sem Content-Length: 411
        conn = http.client.HTTPConnection("127.0.0.1", c.port, timeout=5)
        conn.putrequest("PUT", f"/api/projects/{slug}/video", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{c.port}")
        conn.putheader("X-Token", TOKEN)
        conn.putheader("X-Filename", "a.mp4")
        conn.endheaders()
        assert conn.getresponse().status == 411
        conn.close()


def test_upload_bad_extension(srv):
    with client(srv) as c:
        slug = _criar(c)
        for nome in ("a.exe", "a", "../../x.mp4.sh", None):
            r = c.request("PUT", f"/api/projects/{slug}/video", body=b"abc",
                          headers={"X-Filename": nome})
            assert r.status == 400, nome
        assert list(srv.app.projects.path(slug).glob("entrada*")) == []
        r = c.request("PUT", "/api/projects/nao-existe/video", body=b"abc",
                      headers={"X-Filename": "a.mp4"})
        assert r.status == 404


def test_file_range_206_and_416(srv):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        dados = bytes(range(256)) * 4  # 1024 bytes
        (d / "entrada.mp4").write_bytes(dados)
        url = f"/api/projects/{slug}/arquivos/entrada.mp4"
        r = c.get(url)
        assert r.status == 200 and r.body == dados
        assert r.getheader("Accept-Ranges") == "bytes"
        assert r.getheader("Content-Type") == "video/mp4"
        r = c.get(url, headers={"Range": "bytes=10-19"})
        assert r.status == 206 and r.body == dados[10:20]
        assert r.getheader("Content-Range") == "bytes 10-19/1024"
        assert r.getheader("Accept-Ranges") == "bytes"
        r = c.get(url, headers={"Range": "bytes=1000-"})
        assert r.status == 206 and r.body == dados[1000:]
        assert r.getheader("Content-Range") == "bytes 1000-1023/1024"
        r = c.get(url, headers={"Range": "bytes=-24"})
        assert r.status == 206 and r.body == dados[-24:]
        r = c.get(url, headers={"Range": "bytes=1000-5000"})
        assert r.status == 206 and r.getheader("Content-Range") == "bytes 1000-1023/1024"
        for ruim in ("bytes=2000-", "bytes=20-10", "bytes=abc", "items=0-1", "bytes=-0"):
            r = c.get(url, headers={"Range": ruim})
            assert r.status == 416, ruim
            assert r.getheader("Content-Range") == "bytes */1024"
        r = c.request("HEAD", url)
        assert r.status == 200 and r.getheader("Content-Length") == "1024" and r.body == b""
        assert r.getheader("Accept-Ranges") == "bytes"


def test_file_allowlist_via_api(srv):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        (d / "saida").mkdir()
        (d / "saida" / "preview.mp4").write_bytes(b"abc")
        assert c.get(f"/api/projects/{slug}/arquivos/saida/preview.mp4").body == b"abc"
        assert c.get(f"/api/projects/{slug}/arquivos/projeto.json").status == 404
        assert c.get(f"/api/projects/{slug}/arquivos/../projeto.json").status == 404
        assert c.get(f"/api/projects/{slug}/arquivos/%2e%2e/%2e%2e/x").status == 404
        assert c.get(f"/api/projects/{slug}/arquivos/saida%2f..%2fprojeto.json").status == 404
        assert c.get(f"/api/projects/{slug}/arquivos/entrada.mp4").status == 404
        assert c.request("POST", f"/api/projects/{slug}/arquivos/saida/preview.mp4").status == 405


def test_doctor_translated_items(srv, monkeypatch):  # noqa: C901
    import doctor
    import server
    fake = ("READY WITH LIMITS", [
        {"name": "ffmpeg", "ok": True, "required": True},
        {"name": "faster_whisper (opcional)", "ok": False, "required": False},
        {"name": "item novo do futuro", "ok": False, "required": False, "detail": "motivo cru"},
        {"name": "legendas (filtro subtitles do ffmpeg)", "ok": False, "required": False, "info": True,
         "detail": "usando legendas por imagem"},
    ])
    monkeypatch.setattr(doctor, "check", lambda: fake)
    monkeypatch.setattr(server, "_doctor_check", lambda: fake, raising=False)
    with client(srv) as c:
        r = c.get("/api/doctor")
        assert r.status == 200
        d = r.json()
        assert d["estado"] == "pronto com limites" and d["estado_codigo"] == "READY WITH LIMITS"
        itens = {i["id"]: i for i in d["itens"]}
        assert len(d["itens"]) == 4
        ff = itens["ffmpeg"]
        assert ff["ok"] is True and ff["opcional"] is False and ff["nome"]
        assert set(ff) == {"id", "nome", "ok", "opcional", "informativo", "mensagem", "comando", "detalhe"}
        assert ff["detalhe"] is None and ff["informativo"] is False
        w = [i for i in d["itens"] if "whisper" in i["id"]][0]
        assert w["ok"] is False and w["opcional"] is True
        assert "texto do vídeo" in w["mensagem"].lower() and w["comando"]
        novo = d["itens"][2]
        assert novo["nome"] == "item novo do futuro" and novo["detalhe"] == "motivo cru"
        assert "motivo cru" not in novo["mensagem"]
        assert novo["comando"] is None and novo["informativo"] is False
        leg = itens["legendas"]
        assert leg["informativo"] is True and leg["ok"] is False
        assert "libass" not in (leg["nome"] + leg["mensagem"]).lower()


def test_comando_do_navegador_de_graficos_e_o_da_tarefa():
    """O texto copiavel tem de ser o mesmo comando que a tarefa executa (sem package.json)."""
    import instalacao
    import tarefas
    cmd = instalacao.ITENS["chromium + playwright (opcional: graficos)"][4]
    assert cmd == "npm i -g playwright && npx playwright install chromium"
    from pathlib import Path
    assert tarefas.argv("instalar-chromium", Path("."))[-1] == cmd


def test_instalacao_covers_all_real_doctor_items():
    import doctor
    import instalacao
    _, items = doctor.check()
    for i in items:
        assert i["name"] in instalacao.ITENS, i["name"]


def test_brand_handles_roundtrip_and_validation(srv):
    with client(srv) as c:
        r = c.get("/api/brand")
        assert r.status == 200 and r.json() == {"handles": ["@gutmannesilva"], "completa": True}
        r = c.request("PUT", "/api/brand", body={"handles": ["novo", "@outro"]})
        assert r.status == 200 and r.json() == {"handles": ["@novo", "@outro"], "completa": True}
        assert c.get("/api/brand").json()["handles"] == ["@novo", "@outro"]
        for ruim in ({"handles": ["@@x"]}, {"handles": []}, {"handles": ["a", "b", "c"]},
                     {"handles": "x"}, {"handles": [1]}, {}, ["x"]):
            r = c.request("PUT", "/api/brand", body=ruim)
            assert r.status == 400 and "erro" in r.json(), ruim
        assert c.get("/api/brand").json()["handles"] == ["@novo", "@outro"]
        assert c.request("PUT", "/api/brand", body=b"x" * 70000).status == 413
        assert c.request("DELETE", "/api/brand").status == 405


# ---- fix round 1 ----
def _raw(c, metodo, caminho, cabecalhos, corpo=b""):
    import socket
    sk = socket.create_connection(("127.0.0.1", c.port), timeout=10)
    h = {"Host": f"127.0.0.1:{c.port}", "X-Token": TOKEN, "Connection": "close"}
    h.update(cabecalhos)
    req = f"{metodo} {caminho} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n"
    sk.sendall(req.encode("utf-8") + corpo)
    dados = b""
    while True:
        try:
            b = sk.recv(65536)
        except OSError:
            break
        if not b:
            break
        dados += b
    sk.close()
    return int(dados.split(b" ", 2)[1]) if dados else 0


def test_concurrent_uploads_one_coherent_state(srv, make_sample):
    import threading
    bom = make_sample.read_bytes()
    with client(srv) as c:
        slug = _criar(c)
        res = []

        def envia(corpo):
            r = c.request("PUT", f"/api/projects/{slug}/video", body=corpo,
                          headers={"X-Filename": "a.mp4"})
            res.append((corpo is bom, r.status))
        ts = [threading.Thread(target=envia, args=(x,)) for x in (bom, b"lixo" * 5000, bom)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        d = srv.app.projects.path(slug)
        assert not list(d.glob("*.tmp")) and not list(d.glob(".*"))
        lixo = [st for ehbom, st in res if not ehbom]
        assert lixo == [400]
        bons = [st for ehbom, st in res if ehbom]
        assert all(st in (200, 409) for st in bons) and 200 in bons
        assert (d / "entrada.mp4").read_bytes() == bom


def test_server_imports_without_conftest():
    import subprocess
    import sys
    code = ("import sys; sys.path.insert(0, %r); import server; print('ok')"
            % str(repo_root / "app"))
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                       cwd="/")
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


def test_upload_probe_timeout_cleans_tmp(srv, make_sample, monkeypatch):
    import subprocess
    import server

    def boom(caminho):
        raise subprocess.TimeoutExpired("ffprobe", 60)
    monkeypatch.setattr(server.Handler, "_video_valido", staticmethod(boom))
    with client(srv) as c:
        slug = _criar(c)
        r = c.request("PUT", f"/api/projects/{slug}/video", body=b"abc",
                      headers={"X-Filename": "a.mp4"})
        assert r.status == 504 and "demorou demais" in r.json()["erro"]
        d = srv.app.projects.path(slug)
        assert not list(d.glob("*.tmp")) and not list(d.glob(".*"))


def test_unexpected_exception_cleans_tmp(srv, monkeypatch):
    import server

    def boom(caminho):
        raise MemoryError()
    monkeypatch.setattr(server.Handler, "_video_valido", staticmethod(boom))
    with client(srv) as c:
        slug = _criar(c)
        r = c.request("PUT", f"/api/projects/{slug}/video", body=b"abc",
                      headers={"X-Filename": "a.mp4"})
        assert r.status == 500
        d = srv.app.projects.path(slug)
        assert not list(d.glob("*.tmp")) and not list(d.glob(".*"))


def test_tmp_files_not_state_nor_served(srv):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        (d / "entrada.mov.tmp").write_bytes(b"parcial")
        (d / "entrada.mp4.abc.tmp").write_bytes(b"parcial")
        st = c.get(f"/api/projects/{slug}").json()
        assert st["etapas"]["video"] == "pendente" and st["arquivos"]["entrada"] is None
        assert c.get(f"/api/projects/{slug}/arquivos/entrada.mov.tmp").status == 404


def test_replace_keeps_other_extension_tmp(srv, make_sample):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        (d / "entrada.mov.tmp").write_bytes(b"em andamento")
        (d / "entrada.mov").write_bytes(b"velho")
        r = c.request("PUT", f"/api/projects/{slug}/video", body=make_sample.read_bytes(),
                      headers={"X-Filename": "a.mp4"})
        assert r.status == 200
        assert (d / "entrada.mov.tmp").exists() and not (d / "entrada.mov").exists()


def test_config_and_expect_continue(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    s = make_server(root, TOKEN, max_upload=1000, test_mode=True)
    with client(s) as c:
        assert c.get("/api/config").json() == {"max_upload": 1000}
        assert c.get("/api/config", token=False).status == 401
        slug = _criar(c)
        st = _raw(c, "PUT", f"/api/projects/{slug}/video",
                  {"X-Filename": "a.mp4", "Content-Length": "999999", "Expect": "100-continue"})
        assert st == 413


def test_content_length_and_range_hardening(srv):
    with client(srv) as c:
        slug = _criar(c)
        base = f"/api/projects/{slug}/video"
        h = {"X-Filename": "a.mp4"}
        assert _raw(c, "PUT", base, dict(h, **{"Content-Length": "²"})) == 400
        assert _raw(c, "PUT", base, dict(h, **{"Content-Length": "9" * 5000})) == 413
        assert _raw(c, "POST", "/api/projects", {"Content-Length": "9" * 5000}) == 413
        d = srv.app.projects.path(slug)
        (d / "entrada.mp4").write_bytes(b"x" * 10)
        url = f"/api/projects/{slug}/arquivos/entrada.mp4"
        for rng in ("bytes=0-" + "9" * 5000, "bytes=" + "9" * 5000 + "-", "bytes=-" + "9" * 5000):
            r = c.get(url, headers={"Range": rng})
            assert r.status in (206, 416), rng
        assert c.get(url, headers={"Range": "bytes=" + "9" * 5000 + "-"}).status == 416


def test_json_deep_nesting_400(srv):
    with client(srv) as c:
        r = c.request("POST", "/api/projects", body=b"[" * 60000)
        assert r.status == 400


def test_project_name_limit(srv):
    with client(srv) as c:
        assert c.request("POST", "/api/projects", body={"nome": "a" * 201}).status == 400
        assert c.request("POST", "/api/projects", body={"nome": "a" * 200}).status == 201


def test_brand_missing_is_portuguese_without_path(srv):
    srv.app.brand_path.unlink()
    with client(srv) as c:
        r = c.request("PUT", "/api/brand", body={"handles": ["x"]})
        assert r.status in (404, 400)
        assert "/" not in r.json()["erro"] and "marca" in r.json()["erro"]


def test_handler_has_socket_timeout():
    import server
    assert 0 < server.Handler.timeout <= 120
