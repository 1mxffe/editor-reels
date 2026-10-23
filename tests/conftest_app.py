"""Ajuda para os testes do app/: poe `<repo>/app` no sys.path (app/ nao e pacote)."""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "app"))


import contextlib  # noqa: E402
import http.client  # noqa: E402
import json as _json  # noqa: E402
import threading  # noqa: E402


class Client:
    """Cliente http.client que envia X-Token e Host corretos (sobrescreviveis)."""

    def __init__(self, server):
        self.server = server
        self.port = server.server_address[1]

    def request(self, method, path, body=None, headers=None, token=True):
        h = {"Host": f"127.0.0.1:{self.port}"}
        if token:
            h["X-Token"] = self.server.app.token
        h.update(headers or {})
        # valor None remove o cabecalho
        h = {k: v for k, v in h.items() if v is not None}
        if isinstance(body, (dict, list)):
            body = _json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in h.items():
                conn.putheader(k, v)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            resp = conn.getresponse()
            data = resp.read()
            resp.json = lambda: _json.loads(data.decode("utf-8"))
            resp.body = data
            return resp
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)


@contextlib.contextmanager
def client(server):
    """Sobe o servidor numa thread daemon; encerra com shutdown()+server_close()."""
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield Client(server)
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
