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


@pytest.fixture
def web(tmp_path, monkeypatch):
    import server as srvmod
    w = tmp_path / "app" / "web"
    w.mkdir(parents=True)
    (w / "index.html").write_text("<meta content='{{TOKEN}}'>")
    (w / "app.css").write_text("body{}")
    (tmp_path / "app" / "fora.json").write_text('{"segredo": 1}')
    (tmp_path / "fora.json").write_text('{"segredo": 1}')
    monkeypatch.setattr(srvmod, "WEB_DIR", w)
    return w


def test_static_only_from_web_dir(srv, web):
    with client(srv) as c:
        r = c.get("/static/app.css", token=False)
        assert r.status == 200 and r.getheader("Content-Type").startswith("text/css")
        for p in ("../fora.json", "%2e%2e/fora.json", "..%2ffora.json",
                  "..%5cfora.json", "..%2Ffora.json", "app.css%00.json",
                  "%00../fora.json", "../../fora.json", "/etc/passwd",
                  "....//fora.json", "inexistente.js"):
            r = c.get("/static/" + p, token=False)
            assert r.status == 404 and "erro" in r.json(), p


def test_static_index_template_not_served(srv, web):
    with client(srv) as c:
        assert c.get("/static/index.html", token=False).status == 404


def test_static_rejects_symlink_outside(srv, web, tmp_path):
    (web / "link-fora.css").symlink_to(tmp_path / "fora.json")
    with client(srv) as c:
        assert c.get("/static/link-fora.css", token=False).status == 404


def test_head_requests(srv, web):
    with client(srv) as c:
        r = c.request("HEAD", "/api/ping")
        assert r.status == 200 and r.body == b""
        r = c.request("HEAD", "/static/app.css", token=False)
        assert r.status == 200 and r.body == b""


def test_wrong_method_405_json(srv):
    with client(srv) as c:
        r = c.request("POST", "/api/ping")
        assert r.status == 405 and "erro" in r.json()
        r = c.request("POST", "/api/desconhecida", body=b"x")
        assert r.status == 404 and "erro" in r.json()
        r = c.request("POST", "/", token=False)
        assert r.status == 405 and "erro" in r.json()


def test_stdlib_errors_are_json_with_headers(srv):
    import socket
    with client(srv) as c:
        for m in ("OPTIONS", "TRACE", "CONNECT"):
            r = c.request(m, "/api/ping")
            assert r.status in (403, 405, 501) and "erro" in r.json(), m
            assert r.getheader("Content-Security-Policy") == CSP
            assert r.getheader("X-Content-Type-Options") == "nosniff"
            assert r.getheader("Cache-Control") == "no-store"
        r = c.request("PROPFIND", "/api/ping")
        assert r.status == 501 and "erro" in r.json()
        assert r.getheader("Content-Security-Policy") == CSP

        def cru(dados):
            s = socket.create_connection(("127.0.0.1", c.port), timeout=5)
            s.sendall(dados)
            buf = b""
            while True:
                x = s.recv(65536)
                if not x:
                    break
                buf += x
            s.close()
            return buf
        for dados, codigo in ((b"LIXO\r\n\r\n", b" 400 "),
                              (b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n\r\n", b" 414 ")):
            resp = cru(dados)
            assert codigo in resp.split(b"\r\n")[0], resp[:100]
            assert b"Content-Security-Policy" in resp and b'"erro"' in resp


def test_error_closes_connection_no_smuggling(srv):
    import socket
    with client(srv) as c:
        interno = (f"GET /api/ping HTTP/1.1\r\nHost: 127.0.0.1:{c.port}\r\n"
                   f"X-Token: {TOKEN}\r\n\r\n")
        corpo = interno.encode()
        req = (f"POST /api/x HTTP/1.1\r\nHost: 127.0.0.1:{c.port}\r\n"
               f"Content-Length: {len(corpo)}\r\n\r\n").encode() + corpo
        s = socket.create_connection(("127.0.0.1", c.port), timeout=5)
        s.sendall(req)
        buf = b""
        while True:
            x = s.recv(65536)
            if not x:
                break
            buf += x
        s.close()
        assert buf.count(b"HTTP/1.") == 1 and b" 401 " in buf
        assert b"Connection: close" in buf


def test_duplicate_host_or_origin_rejected(srv):
    import socket
    with client(srv) as c:
        def cru(extra):
            s = socket.create_connection(("127.0.0.1", c.port), timeout=5)
            s.sendall((f"GET /api/ping HTTP/1.1\r\nX-Token: {TOKEN}\r\n" + extra +
                       "\r\n").encode())
            buf = s.recv(65536)
            s.close()
            return buf
        ok = f"Host: 127.0.0.1:{c.port}\r\n"
        assert b" 403 " in cru(ok + "Host: evil.com\r\n")
        assert b" 403 " in cru(ok + f"Origin: http://localhost:{c.port}\r\nOrigin: http://evil.com\r\n")
        assert b" 403 " in cru("")  # Host ausente


def test_host_origin_variants(srv):
    with client(srv) as c:
        for h in ("127.0.0.1:1", f"LOCALHOST:{c.port}", f"127.0.0.1.evil.com:{c.port}", "127.0.0.1"):
            assert c.get("/api/ping", headers={"Host": h}).status == 403, h
        for o in ("null", f"http://LOCALHOST:{c.port}", f"https://127.0.0.1:{c.port}",
                  "http://127.0.0.1:1"):
            assert c.get("/api/ping", headers={"Origin": o}).status == 403, o


def test_token_escaped_in_meta(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    tok = 'a"<>&b'
    s = make_server(root, tok)
    with client(s) as c:
        from urllib.parse import quote
        r = c.get("/?t=" + quote(tok, safe=""), token=False)
        assert r.status == 200
        assert b'content="a&quot;&lt;&gt;&amp;b"' in r.body
        assert b'a"<>&b' not in r.body


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


def test_errors_never_traceback(srv):
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
