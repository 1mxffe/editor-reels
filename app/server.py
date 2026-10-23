"""Servidor HTTP local do editor de Reels (somente loopback, stdlib).

Seguranca: token por requisicao (`X-Token`), Host/Origin restritos a
127.0.0.1/localhost na porta do servidor, CSP restrita e servir estaticos
apenas de ``app/web``.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import brand  # noqa: E402
import instalacao  # noqa: E402
from projects import EXT_VIDEO, Projects, ProjectsError  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent / "web"

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_JSON = 64 * 1024
BLOCO = 1024 * 1024
RANGE_RE = re.compile(r"bytes=([0-9]{0,18})-([0-9]{0,18})", re.ASCII)
DIGITOS_RE = re.compile(r"[0-9]+", re.ASCII)
MAX_NOME = 200

MIME = {
    ".mp4": "video/mp4", ".m4v": "video/x-m4v", ".mov": "video/quicktime",
    ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8", ".srt": "text/plain; charset=utf-8",
    ".ass": "text/plain; charset=utf-8", ".html": "text/plain; charset=utf-8",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".aac": "audio/aac", ".ogg": "audio/ogg",
}

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
        self.brand_path = REPO_ROOT / "brand" / "brand.json"
        self.replace_lock = threading.Lock()  # troca do entrada.<ext> + limpeza


def _doctor_check():
    import doctor  # scripts/ ja esta no sys.path (via projects)
    return doctor.check()


class Handler(BaseHTTPRequestHandler):
    server_version = "EditorReels"
    protocol_version = "HTTP/1.1"
    timeout = 60  # segundos por leitura/escrita: cliente lento nao prende a thread

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
        if fechar:
            self._drenar()
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

    def _drenar(self):
        """Descarta um corpo pequeno ainda nao lido antes de fechar a conexao:
        fechar com dados pendentes geraria um RST que apagaria a resposta de erro."""
        if getattr(self, "_corpo_lido", False):
            return
        self._corpo_lido = True
        headers = getattr(self, "headers", None)
        if headers is None:
            return
        bruto = headers.get("Content-Length") or "0"
        if not DIGITOS_RE.fullmatch(bruto) or len(bruto) > 7:
            return
        n = int(bruto)
        if 0 < n <= BLOCO:
            try:
                self.rfile.read(n)
            except OSError:
                pass

    def handle_expect_100(self):
        """Recusa cedo (sem 100 Continue) um envio maior que o limite."""
        bruto = self.headers.get("Content-Length") or ""
        if DIGITOS_RE.fullmatch(bruto) and (len(bruto) > 20
                                            or int(bruto) > self.server.max_upload):
            self._corpo_lido = True  # o cliente espera a resposta antes de enviar
            self.error(413, "arquivo grande demais")
            return False
        return super().handle_expect_100()

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
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception as exc:  # nunca vaza traceback ao cliente
            print(f"erro interno: {exc!r}", file=sys.stderr)
            try:
                self.error(500, "Erro interno")
            except Exception:
                self.close_connection = True

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

    def _permitir(self, *metodos) -> bool:
        if self.command in metodos or (self.command == "HEAD" and "GET" in metodos):
            return True
        self.error(405, "Método não permitido")
        return False

    def _content_length(self):
        """Content-Length validado ou None (resposta de erro ja enviada)."""
        bruto = self.headers.get("Content-Length")
        if bruto is None:
            self.error(411, "Content-Length obrigatório")
            return None
        if not DIGITOS_RE.fullmatch(bruto):
            self.error(400, "Content-Length inválido")
            return None
        if len(bruto) > 20:
            self.error(413, "arquivo grande demais")
            return None
        return int(bruto)

    def _read_json(self):
        """Corpo JSON (<= 64 KiB). Devolve (ok, obj); em falha a resposta ja foi enviada."""
        n = self._content_length()
        if n is None:
            return False, None
        if n > MAX_JSON:
            self.error(413, "Corpo grande demais")
            return False, None
        bruto = self.rfile.read(n) if n else b""
        self._corpo_lido = True
        if len(bruto) != n:
            self.error(400, "Corpo incompleto")
            return False, None
        try:
            return True, json.loads(bruto.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            self.error(400, "JSON inválido")
            return False, None

    def api(self, path: str, query):
        if path == "/api/ping":
            if not self._permitir("GET"):
                return
            return self.json_reply(200, {"ok": True})
        if self.server.test_mode and path == "/api/_boom":
            raise RuntimeError("falha forçada para teste")
        if path == "/api/config":
            if not self._permitir("GET"):
                return
            return self.json_reply(200, {"max_upload": self.server.max_upload})
        if path == "/api/doctor":
            if not self._permitir("GET"):
                return
            estado, itens = _doctor_check()
            return self.json_reply(200, instalacao.traduzir(estado, itens))
        if path == "/api/brand":
            return self.api_brand()
        if path == "/api/projects":
            return self.api_projects()
        if path.startswith("/api/projects/"):
            resto = path[len("/api/projects/"):].split("/", 2)
            slug = unquote(resto[0])
            if len(resto) == 1:
                if not self._permitir("GET"):
                    return
                return self.api_state(slug)
            if resto[1] == "video" and len(resto) == 2:
                if not self._permitir("PUT"):
                    return
                return self.api_upload(slug)
            if resto[1] == "arquivos" and len(resto) == 3:
                if not self._permitir("GET"):
                    return
                return self.api_arquivo(slug, unquote(resto[2]))
        self.error(404, "Rota não encontrada")

    # -- projetos ---------------------------------------------------------------
    def api_projects(self):
        if self.command in ("GET", "HEAD"):
            return self.json_reply(200, self.app.projects.list())
        if self.command != "POST":
            return self.error(405, "Método não permitido")
        ok, corpo = self._read_json()
        if not ok:
            return
        nome = corpo.get("nome") if isinstance(corpo, dict) else None
        if not isinstance(nome, str) or not nome.strip():
            return self.error(400, "informe o nome do projeto")
        if len(nome) > MAX_NOME:
            return self.error(400, f"nome longo demais (máximo {MAX_NOME} caracteres)")
        try:
            proj = self.app.projects.create(nome)
        except ProjectsError as e:
            return self.error(400, str(e))
        self.json_reply(201, proj)

    def _projeto(self, slug: str):
        """Pasta do projeto ou None (404/400 ja enviado)."""
        try:
            return self.app.projects.path(slug)
        except ProjectsError as e:
            self.error(404 if "não existe" in str(e) else 400, str(e))
            return None

    def api_state(self, slug: str):
        if self._projeto(slug) is None:
            return
        self.json_reply(200, self.app.projects.state(slug))

    # -- upload -----------------------------------------------------------------
    def api_upload(self, slug: str):
        d = self._projeto(slug)
        if d is None:
            return
        nome = self.headers.get("X-Filename") or ""
        ext = os.path.splitext(nome.replace("\\", "/").rsplit("/", 1)[-1])[1].lower()
        if ext not in EXT_VIDEO:
            return self.error(400, "formato não suportado; use " + ", ".join(EXT_VIDEO))
        n = self._content_length()
        if n is None:
            return
        if n == 0:
            return self.error(400, "arquivo vazio")
        if n > self.server.max_upload:
            return self.error(413, "arquivo grande demais")
        destino = d / f"entrada{ext}"
        status, msg = self._receber(d, destino, n)
        if status == 200:
            return self.json_reply(200, self.app.projects.state(slug))
        self.error(status, msg)

    def _receber(self, d: Path, destino: Path, n: int):
        """Grava o corpo num tmp unico, confere com ffprobe e troca. (status, msg)."""
        tmp = None
        try:
            fd, nome_tmp = tempfile.mkstemp(dir=d, prefix=".entrada-", suffix=".tmp")
            tmp = Path(nome_tmp)
            total = 0
            with os.fdopen(fd, "wb") as f:
                while total < n:
                    bloco = self.rfile.read(min(BLOCO, n - total))
                    if not bloco:
                        break
                    total += len(bloco)
                    f.write(bloco)
                f.flush()
                os.fsync(f.fileno())
            self._corpo_lido = True
            if total != n:
                return 400, "envio interrompido"
            try:
                valido = self._video_valido(tmp)
            except FileNotFoundError:
                return 500, "ffprobe não encontrado — rode a instalação"
            except subprocess.TimeoutExpired:
                return 504, "verificação do vídeo demorou demais"
            if not valido:
                return 400, "o arquivo não parece ser um vídeo"
            with self.app.replace_lock:
                os.replace(tmp, destino)
                tmp = None
                for ext in EXT_VIDEO:  # extensoes antigas (nunca .tmp)
                    velho = destino.with_name(f"entrada{ext}")
                    if velho != destino:
                        try:
                            velho.unlink(missing_ok=True)
                        except OSError:
                            pass
            return 200, ""
        except TimeoutError:
            self.close_connection = True
            return 408, "tempo esgotado no envio"
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            return 400, "envio interrompido"
        except OSError as e:
            print(f"erro no upload: {e!r}", file=sys.stderr)
            return 500, "não foi possível gravar o vídeo"
        except Exception as e:
            print(f"erro no upload: {e!r}", file=sys.stderr)
            return 500, "Erro interno"
        finally:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _video_valido(caminho: Path) -> bool:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_type:format=duration", "-of", "json", "-i", str(caminho)],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return False
        try:
            info = json.loads(proc.stdout)
            streams = info.get("streams") or []
            duracao = float((info.get("format") or {}).get("duration"))
        except (ValueError, TypeError, AttributeError):
            return False
        return (any(s.get("codec_type") == "video" for s in streams)
                and duracao == duracao and 0 < duracao < float("inf"))

    # -- arquivos com Range -------------------------------------------------------
    def api_arquivo(self, slug: str, rel: str):
        try:
            alvo = self.app.projects.resolve_file(slug, rel)
        except ProjectsError as e:
            msg = str(e)
            return self.error(404 if ("não existe" in msg or "encontrado" in msg
                                      or "permitido" in msg) else 400, msg)
        try:
            f = open(alvo, "rb")
        except OSError:
            return self.error(404, "arquivo não encontrado")
        with f:
            tam = os.fstat(f.fileno()).st_size
            ctype = MIME.get(alvo.suffix.lower(), "application/octet-stream")
            inicio, fim, status = 0, tam - 1, 200
            rng = self.headers.get("Range")
            if rng is not None:
                m = RANGE_RE.fullmatch(rng.strip())
                a, b = (m.group(1), m.group(2)) if m else ("", "")
                if not m or (a == "" and b == ""):
                    return self._416(tam)
                if a == "":  # sufixo: ultimos n bytes
                    n = int(b)
                    if n == 0 or tam == 0:
                        return self._416(tam)
                    inicio, fim = max(tam - n, 0), tam - 1
                else:
                    inicio = int(a)
                    fim = min(int(b), tam - 1) if b else tam - 1
                    if inicio >= tam or fim < inicio:
                        return self._416(tam)
                status = 206
            restante = fim - inicio + 1 if tam else 0
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(restante))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {inicio}-{fim}/{tam}")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                f.seek(inicio)
                while restante > 0:
                    bloco = f.read(min(BLOCO, restante))
                    if not bloco:
                        break
                    self.wfile.write(bloco)
                    restante -= len(bloco)
                if restante > 0:  # arquivo encolheu no meio: resposta truncada
                    self.close_connection = True
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

    def _416(self, tam: int):
        data = json.dumps({"erro": "intervalo não satisfatório"}).encode("utf-8")
        self.send_response(416)
        self.send_header("Connection", "close")
        self.close_connection = True
        self.send_header("Content-Range", f"bytes */{tam}")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # -- marca --------------------------------------------------------------------
    def _brand_info(self) -> dict:
        path = self.app.brand_path
        try:
            return {"handles": brand.require_handles(brand.load(path)), "completa": True}
        except brand.BrandMissing:
            try:
                dados = json.loads(Path(path).read_text(encoding="utf-8"))
                h = [x for x in dados.get("handles", []) if isinstance(x, str)]
            except (OSError, ValueError, AttributeError):
                h = []
            return {"handles": h, "completa": False}

    def api_brand(self):
        if self.command in ("GET", "HEAD"):
            return self.json_reply(200, self._brand_info())
        if self.command != "PUT":
            return self.error(405, "Método não permitido")
        ok, corpo = self._read_json()
        if not ok:
            return
        handles = corpo.get("handles") if isinstance(corpo, dict) else None
        if not isinstance(handles, list):
            return self.error(400, "informe a lista de @ em 'handles'")
        try:
            brand.set_handles(self.app.brand_path, handles)
        except ValueError as e:
            return self.error(400, str(e))
        except brand.BrandMissing:
            return self.error(404, "o arquivo da marca está ausente ou inválido")
        except OSError:
            return self.error(500, "não foi possível gravar a marca")
        self.json_reply(200, self._brand_info())


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
