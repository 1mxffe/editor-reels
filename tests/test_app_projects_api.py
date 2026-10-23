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


def test_upload_over_limit_streaming_count(tmp_path):
    """Content-Length mente (menor que o corpo real)? Nao e possivel com http.server:
    o corpo lido e limitado ao Content-Length; basta garantir o 413 por cabecalho."""
    root = tmp_path / "projects"
    root.mkdir()
    s = make_server(root, TOKEN, max_upload=10, test_mode=True)
    with client(s) as c:
        slug = _criar(c)
        r = c.request("PUT", f"/api/projects/{slug}/video", body=b"x" * 11,
                      headers={"X-Filename": "a.mp4"})
        assert r.status == 413


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


def test_doctor_translated_items(srv, monkeypatch):
    import doctor
    import server
    fake = ("READY WITH LIMITS", [
        {"name": "ffmpeg", "ok": True, "required": True},
        {"name": "faster_whisper (opcional)", "ok": False, "required": False},
        {"name": "item novo do futuro", "ok": False, "required": False, "detail": "motivo cru"},
    ])
    monkeypatch.setattr(doctor, "check", lambda: fake)
    monkeypatch.setattr(server, "_doctor_check", lambda: fake, raising=False)
    with client(srv) as c:
        r = c.get("/api/doctor")
        assert r.status == 200
        d = r.json()
        assert d["estado"] == "READY WITH LIMITS"
        itens = {i["id"]: i for i in d["itens"]}
        assert len(d["itens"]) == 3
        ff = itens["ffmpeg"]
        assert ff["ok"] is True and ff["opcional"] is False and ff["nome"]
        assert set(ff) == {"id", "nome", "ok", "opcional", "mensagem", "comando"}
        w = [i for i in d["itens"] if "whisper" in i["id"]][0]
        assert w["ok"] is False and w["opcional"] is True
        assert "transcri" in w["mensagem"].lower() and w["comando"]
        novo = d["itens"][2]
        assert novo["nome"] == "item novo do futuro" and novo["mensagem"] == "motivo cru"
        assert novo["comando"] is None


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
