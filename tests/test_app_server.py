import pytest

from conftest_app import client, repo_root  # noqa: F401
from server import make_server

TOKEN = "tok-de-teste-123"
CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
       "connect-src 'self'; style-src 'self' 'unsafe-inline'")


@pytest.fixture
def srv(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    return make_server(root, TOKEN, test_mode=True)


def test_ping_ok(srv):
    with client(srv) as c:
        r = c.get("/api/ping")
        assert r.status == 200 and r.json() == {"ok": True}


def test_api_requires_token(srv):
    with client(srv) as c:
        r = c.get("/api/ping", token=False)
        assert r.status == 401 and "erro" in r.json()
        r = c.get("/api/ping", headers={"X-Token": "errado"})
        assert r.status == 401 and "erro" in r.json()


def test_host_header_must_match(srv):
    with client(srv) as c:
        r = c.get("/api/ping", headers={"Host": "evil.com"})
        assert r.status == 403 and "erro" in r.json()
        r = c.get("/api/ping", headers={"Host": f"evil.com:{c.port}"})
        assert r.status == 403
        r = c.get("/api/ping", headers={"Host": f"localhost:{c.port}"})
        assert r.status == 200


def test_origin_external_rejected(srv):
    with client(srv) as c:
        r = c.get("/api/ping", headers={"Origin": "http://evil.com"})
        assert r.status == 403 and "erro" in r.json()
        r = c.get("/api/ping", headers={"Origin": f"http://localhost:{c.port}"})
        assert r.status == 200
        r = c.get("/api/ping", headers={"Origin": f"http://127.0.0.1:{c.port}"})
        assert r.status == 200


def test_index_requires_token_query(srv):
    with client(srv) as c:
        r = c.get("/", token=False)
        assert r.status == 403 and b"atalho" in r.body
        r = c.get("/?t=errado", token=False)
        assert r.status == 403
        r = c.get(f"/?t={TOKEN}", token=False)
        assert r.status == 200
        assert f'<meta name="reel-token" content="{TOKEN}">'.encode() in r.body
        assert b"{{TOKEN}}" not in r.body


def test_static_only_from_web_dir(srv):
    with client(srv) as c:
        r = c.get("/static/../server.py", token=False)
        assert r.status == 404 and "erro" in r.json()
        r = c.get("/static/%2e%2e/server.py", token=False)
        assert r.status == 404
        r = c.get("/static/inexistente.js", token=False)
        assert r.status == 404
        r = c.get("/static/index.html", token=False)
        assert r.status == 200 and r.getheader("Content-Type").startswith("text/html")


def test_static_rejects_symlink_outside(srv, tmp_path):
    import server as srvmod
    alvo = tmp_path / "segredo.txt"
    alvo.write_text("x")
    link = srvmod.WEB_DIR / "link-fora.css"
    link.symlink_to(alvo)
    try:
        with client(srv) as c:
            r = c.get("/static/link-fora.css", token=False)
            assert r.status == 404
    finally:
        link.unlink()


def test_security_headers_present(srv):
    with client(srv) as c:
        for r in (c.get("/api/ping"), c.get("/api/nada"), c.get("/", token=False),
                  c.get("/api/ping", token=False)):
            assert r.getheader("Content-Security-Policy") == CSP
            assert r.getheader("X-Content-Type-Options") == "nosniff"
            assert r.getheader("Cache-Control") == "no-store"


def test_unknown_route_404_json(srv):
    with client(srv) as c:
        r = c.get("/api/nao-existe")
        assert r.status == 404 and "erro" in r.json()
        r = c.get("/qualquer", token=False)
        assert r.status == 404 and "erro" in r.json()


def test_binds_loopback_only(srv):
    assert srv.server_address[0] == "127.0.0.1"
    srv.server_close()


def test_app_object(srv):
    assert srv.app.token == TOKEN and srv.app.jobs is None
    assert srv.app.projects.root == srv.app.root
    srv.server_close()


def test_errors_never_traceback(srv, capsys):
    with client(srv) as c:
        r = c.get("/api/_boom")
        assert r.status == 500
        assert r.json() == {"erro": "Erro interno"}
        assert b"Traceback" not in r.body


def test_boom_absent_without_test_mode(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    s = make_server(root, TOKEN)
    with client(s) as c:
        assert c.get("/api/_boom").status == 404
