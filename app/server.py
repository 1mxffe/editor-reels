"""Servidor HTTP local do editor de Reels (somente loopback, stdlib).

Seguranca: token por requisicao (`X-Token`), Host/Origin restritos a
127.0.0.1/localhost na porta do servidor, CSP restrita e servir estaticos
apenas de ``app/web``.
"""
from __future__ import annotations

import hmac
import json
import sys
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from projects import Projects  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent / "web"

CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
       "connect-src 'self'; style-src 'self' 'unsafe-inline'")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}

PAGINA_403 = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Acesso negado</title></head>
<body><h1>Acesso negado</h1>
<p>Abra o editor pelo ícone ou atalho do Editor de Reels; o endereço digitado
à mão não tem a chave de acesso.</p></body></html>
"""


MENSAGENS = {
    400: "Requisição malformada",
    404: "Não encontrado",
    405: "Método não permitido",
    408: "Tempo da requisição esgotado",
    414: "Endereço longo demais",
    431: "Cabeçalhos grandes demais",
    501: "Método não suportado",
}


class App:
    """Estado compartilhado do servidor (preenchido por make_server)."""

    def __init__(self, root: Path, token: str):
        self.root = Path(root)
        self.token = token
        self.projects = Projects(self.root)
        self.jobs = None  # T4 preenche


class Handler(BaseHTTPRequestHandler):
    server_version = "EditorReels"
    protocol_version = "HTTP/1.1"

    # -- infraestrutura -----------------------------------------------------
    def log_message(self, format, *args):  # sem log de acesso
        pass

    @property
    def app(self) -> App:
        return self.server.app

    def _send(self, status: int, body: bytes, content_type: str):
        comando = getattr(self, "command", None)
        # corpo da requisicao nunca e consumido: fechar a conexao evita que
        # ele seja lido como uma nova requisicao (desincronizacao)
        fechar = status >= 400 or comando not in ("GET", "HEAD", None)
        self.send_response(status)
        if fechar:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if comando != "HEAD":
            self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        """Erros da stdlib (400/414/501...) tambem saem em JSON com os headers de seguranca."""
        self.error(code, MENSAGENS.get(code, "Requisição inválida"))

    def json_reply(self, status: int, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, data, "application/json; charset=utf-8")

    def error(self, status: int, msg: str):
        self.json_reply(status, {"erro": msg})

    # -- validacoes -----------------------------------------------------------
    def _hosts_ok(self) -> bool:
        porta = self.server.server_address[1]
        validos = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0] not in validos:
            self.error(403, "Host não permitido")
            return False
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1 or (origins and origins[0] not in
                                {f"http://{h}" for h in validos}):
            self.error(403, "Origem não permitida")
            return False
        return True

    def _token_ok(self, candidato: str | None) -> bool:
        if not candidato:
            return False
        return hmac.compare_digest(candidato.encode("utf-8"),
                                   self.app.token.encode("utf-8"))

    # -- despacho -------------------------------------------------------------
    def _handle(self):
        try:
            if not self._hosts_ok():
                return
            parts = urlsplit(self.path)
            path = parts.path
            if path.startswith("/api/"):
                if not self._token_ok(self.headers.get("X-Token")):
                    return self.error(401, "Token ausente ou inválido")
                return self.api(path, parse_qs(parts.query))
            if self.command not in ("GET", "HEAD"):
                return self.error(405, "Método não permitido")
            if path == "/":
                return self.index(parse_qs(parts.query))
            if path.startswith("/static/"):
                return self.static(path[len("/static/"):])
            self.error(404, "Não encontrado")
        except Exception as exc:  # nunca vaza traceback ao cliente
            print(f"erro interno: {exc!r}", file=sys.stderr)
            try:
                self.error(500, "Erro interno")
            except Exception:
                pass

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _handle
    do_OPTIONS = do_TRACE = do_CONNECT = _handle

    # -- rotas ----------------------------------------------------------------
    def index(self, query):
        if not self._token_ok((query.get("t") or [None])[0]):
            return self._send(403, PAGINA_403.encode("utf-8"), "text/html; charset=utf-8")
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace("{{TOKEN}}", escape(self.app.token, quote=True))
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def static(self, nome: str):
        nome = unquote(nome)
        if nome == "index.html":  # template cru: so via GET /?t=
            return self.error(404, "Arquivo não encontrado")
        ctype = CONTENT_TYPES.get(Path(nome).suffix.lower())
        base = WEB_DIR.resolve()
        try:
            alvo = (base / nome).resolve()
            ok = ctype and alvo.is_relative_to(base) and alvo.is_file()
        except (OSError, ValueError):
            ok = False
        if not ok:
            return self.error(404, "Arquivo não encontrado")
        self._send(200, alvo.read_bytes(), ctype)

    def api(self, path: str, query):
        if path == "/api/ping":
            if self.command not in ("GET", "HEAD"):
                return self.error(405, "Método não permitido")
            return self.json_reply(200, {"ok": True})
        if self.server.test_mode and path == "/api/_boom":
            raise RuntimeError("falha forçada para teste")
        self.error(404, "Rota não encontrada")


def make_server(root: Path, token: str, host: str = "127.0.0.1", port: int = 0,
                max_upload: int = 4 * 1024 ** 3, test_mode: bool = False
                ) -> ThreadingHTTPServer:
    """Cria o servidor. Somente loopback e suportado (127.0.0.1/localhost);
    a checagem de Host/Origin assume isso e nao deve ser usado em 0.0.0.0."""
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.app = App(root, token)
    server.max_upload = max_upload
    server.test_mode = test_mode
    return server
