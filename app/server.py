"""Servidor HTTP local do editor de Reels (somente loopback, stdlib).

Seguranca: token por requisicao (`X-Token`), Host/Origin restritos a
127.0.0.1/localhost na porta do servidor, CSP restrita e servir estaticos
apenas de ``app/web``.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import brand  # noqa: E402
import common  # noqa: E402
import instalacao  # noqa: E402
import revisao_api  # noqa: E402
import tarefas  # noqa: E402
from jobs import ID_RE as JOB_ID_RE, JobBusy, Jobs  # noqa: E402
import projects as projects_mod  # noqa: E402
from projects import EXT_VIDEO, Projects, ProjectsError  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent / "web"

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_JSON = 64 * 1024
MAX_JSON_REVISAO = 1024 * 1024  # edicao de legendas
BLOCO = 1024 * 1024
DEADLINE_DRENAR = 30  # segundos no total; excedeu, so fecha
MAX_DRENAR = 16 * 1024 * 1024  # corpo descartado antes de fechar em erro; maior que isso so fecha
RANGE_RE = re.compile(r"bytes=([0-9]{0,18})-([0-9]{0,18})", re.ASCII)
DIGITOS_RE = re.compile(r"[0-9]+", re.ASCII)
MAX_NOME = 200
NONCE_RE = re.compile(r"[0-9a-f]{32}", re.ASCII)

# encerramento por inatividade: sem batida da pagina por IDLE_SECONDS e sem tarefa
# rodando, o servidor fecha; confere a cada CHECK_SECONDS
IDLE_SECONDS = 300
CHECK_SECONDS = 5
APP_JSON = ".app.json"  # {"porta","token","pid"} da instancia no ar, em projects/
PADRAO_RAIZ = REPO_ROOT / "projects"

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
# SVG enviado pela pessoa (materiais/): aberto direto no navegador nada roda nem carrega
CSP_SVG = "default-src 'none'; style-src 'unsafe-inline'; sandbox"

# materiais: imagens e videos de apoio, um nome limpo por arquivo
EXT_MATERIAIS = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".mp4")
MAX_MATERIAL = 200 * 1024 * 1024
MAX_GRAFICOS = 256 * 1024
NOME_EXT_RE = re.compile(r"^(.*?)(\.[A-Za-z0-9]{1,8})?$", re.DOTALL)
MARCA_INCOMPLETA = ("salve o @ do escritório na Instalação antes de gerar a capa")


def nome_material(bruto: str) -> str:
    """Mesma limpeza de ``sanitizeName`` da review/review.html: so o ultimo pedaço do
    caminho, sem controles nem <>:"|?*, espacos viram '-', sem '.'/'-' nas pontas,
    radical com ate 80 caracteres; extensao em minusculas."""
    base = re.split(r"[\\/]", str(bruto or ""))[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "-", base)
    base = re.sub(r'[<>:"|?*]', "-", base)
    base = re.sub(r"\s+", "-", base)
    m = NOME_EXT_RE.match(base)
    stem = re.sub(r"-+", "-", m.group(1) or "")
    stem = re.sub(r"^[.\-]+|[.\-]+$", "", stem)
    ext = (m.group(2) or "").lower()
    return (stem or "arquivo")[:80] + ext


def _conteudo_confere(cabeca: bytes, ext: str) -> bool:
    if ext == ".png":
        return cabeca.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return cabeca.startswith(b"\xff\xd8\xff")
    if ext == ".webp":
        return cabeca[:4] == b"RIFF" and cabeca[8:12] == b"WEBP"
    if ext == ".mp4":
        return cabeca[4:8] == b"ftyp"
    return b"<svg" in cabeca.lower()

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
        self.jobs = Jobs(self.root)  # orfaos 'rodando' viram erro
        self.brand_path = REPO_ROOT / "brand" / "brand.json"
        self.replace_lock = threading.Lock()  # troca do entrada.<ext> + limpeza
        self.ultimo_sinal = time.monotonic()  # batida da pagina; antes da 1a conta a subida
        self.max_material = MAX_MATERIAL
        self.materiais_lock = threading.Lock()  # escolha do nome livre + link

    def sinal(self) -> None:
        self.ultimo_sinal = time.monotonic()


def transcricao_falsa(server) -> bool:
    """Transcricao fixa dos testes no lugar do Whisper: so com o servidor criado em
    ``test_mode`` E ``REEL_APP_FAKE_TRANSCRIBE=1``. Fora do modo de teste a variavel
    e ignorada."""
    return bool(getattr(server, "test_mode", False)) and os.environ.get("REEL_APP_FAKE_TRANSCRIBE") == "1"


def comando_abrir_pasta(pasta: Path) -> list[str]:
    """argv (sem shell) que abre a pasta no gerenciador de arquivos do sistema."""
    return ["open" if sys.platform == "darwin" else "xdg-open", str(pasta)]


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
        self.send_header("Referrer-Policy", "no-referrer")
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
        if not DIGITOS_RE.fullmatch(bruto) or len(bruto) > 9:
            return
        n = int(bruto)
        # descarta ate MAX_DRENAR em blocos (o timeout do socket limita clientes lentos);
        # acima disso a conexao e fechada com o corpo pendente (o cliente pode ver RST)
        if 0 < n <= MAX_DRENAR:
            fim = time.monotonic() + DEADLINE_DRENAR
            try:
                while n > 0:
                    resta = fim - time.monotonic()
                    if resta <= 0:
                        break
                    self.connection.settimeout(min(resta, self.timeout))
                    lido = self.rfile.read1(min(BLOCO, n))
                    if not lido:
                        break
                    n -= len(lido)
            except (OSError, ValueError):
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
            if path == "/api/identidade":  # desafio sem chave (segunda instancia)
                return self.api_identidade(parse_qs(parts.query))
            if path.startswith("/api/"):
                query = parse_qs(parts.query)
                candidato = self.headers.get("X-Token")
                if candidato is None and self._rota_arquivo(path):
                    # <video src> nao manda cabecalho: so aqui a chave pode vir no endereco
                    candidato = (query.get("t") or [None])[0]
                if not self._token_ok(candidato):
                    return self.error(401, "Token ausente ou inválido")
                self.app.sinal()  # qualquer pedido autenticado conta como atividade
                return self.api(path, query)
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

    def api_identidade(self, query):
        """Prova que este servidor tem a chave sem revela-la: HMAC-SHA256(token, nonce)."""
        if not self._permitir("GET"):
            return
        nonce = (query.get("nonce") or [""])[0]
        if not NONCE_RE.fullmatch(nonce):
            return self.error(400, "nonce inválido")
        prova = hmac.new(self.app.token.encode("utf-8"), nonce.encode("ascii"),
                         hashlib.sha256).hexdigest()
        self.json_reply(200, {"prova": prova})

    def _rota_arquivo(self, path: str) -> bool:
        """GET/HEAD /api/projects/<slug>/arquivos/<rel> (o player do navegador)."""
        if self.command not in ("GET", "HEAD"):
            return False
        partes = path[len("/api/projects/"):].split("/", 2)
        return (path.startswith("/api/projects/") and len(partes) == 3
                and partes[1] == "arquivos")

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

    def _read_json(self, limite: int = MAX_JSON):
        """Corpo JSON (<= 64 KiB). Devolve (ok, obj); em falha a resposta ja foi enviada."""
        n = self._content_length()
        if n is None:
            return False, None
        if n > limite:
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
        if path == "/api/heartbeat":  # a pagina continua aberta (corpo ignorado)
            if not self._permitir("POST"):
                return
            self._drenar()
            self.app.sinal()
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
            if resto[1] == "jobs" and len(resto) == 2:
                if not self._permitir("GET"):
                    return
                return self.api_jobs_projeto(slug)
            if resto[1] == "jobs" and len(resto) == 3:
                if not self._permitir("POST"):
                    return
                return self.api_job_start(slug, unquote(resto[2]))
            if resto[1] == "abrir-pasta" and len(resto) == 2:
                if not self._permitir("POST"):
                    return
                return self.api_abrir_pasta(slug)
            if resto[1] == "revisao" and len(resto) == 2:
                if not self._permitir("GET", "PUT"):
                    return
                return self.api_revisao(slug)
            if resto[1] == "etapas" and len(resto) == 3 and resto[2] == "legendas":
                if not self._permitir("PUT"):
                    return
                return self.api_etapa_legendas(slug)
            if resto[1] == "materiais" and len(resto) == 2:
                if not self._permitir("GET", "PUT"):
                    return
                return self.api_materiais(slug)
            if resto[1] == "materiais" and len(resto) == 3:
                if not self._permitir("DELETE"):
                    return
                return self.api_material_apagar(slug, unquote(resto[2]))
            if resto[1] == "graficos" and len(resto) == 2:
                if not self._permitir("GET", "PUT"):
                    return
                return self.api_graficos(slug)
            if resto[1] == "arquivos" and len(resto) == 3:
                if not self._permitir("GET"):
                    return
                return self.api_arquivo(slug, unquote(resto[2]))
        if path.startswith("/api/jobs/"):
            resto = path[len("/api/jobs/"):].split("/")
            if JOB_ID_RE.fullmatch(resto[0]):
                if len(resto) == 1:
                    if not self._permitir("GET"):
                        return
                    try:
                        return self.json_reply(200, self._job_limpo(self.app.jobs.get(resto[0])))
                    except KeyError:
                        return self.error(404, "Tarefa não encontrada")
                if len(resto) == 2 and resto[1] == "cancelar":
                    if not self._permitir("POST"):
                        return
                    self._drenar()
                    return self.json_reply(200, {"ok": self.app.jobs.cancel(resto[0])})
            return self.error(404, "Tarefa não encontrada")
        self.error(404, "Rota não encontrada")

    # -- tarefas ------------------------------------------------------------------
    def api_job_start(self, slug: str, tipo: str):
        d = self._projeto(slug)
        if d is None:
            return
        if tipo not in tarefas.TIPOS:
            return self.error(404, "Tipo de tarefa desconhecido")
        ok, corpo = self._read_json()
        if not ok:
            return
        if corpo is None:
            corpo = {}
        try:
            argv = tarefas.argv(tipo, d, falso=transcricao_falsa(self.server),
                                marca=self.app.brand_path, **tarefas.validar(tipo, corpo))
        except ValueError as e:
            return self.error(400, str(e))
        if tipo == "capa" and not self._brand_info()["completa"]:
            return self.json_reply(409, {"erro": MARCA_INCOMPLETA, "codigo": "marca_incompleta"})
        trava = revisao_api.trava(slug)
        if not trava.acquire(blocking=False):
            return self.json_reply(409, {"erro": "a revisão deste projeto está em andamento",
                                         "codigo": "revisao_em_andamento"})
        try:
            if tipo in ("preview", "final"):  # o que estes cortes/legendas vao gerar
                projects_mod.registrar_origem(d, tipo)
            job_id = self.app.jobs.start(slug, tipo, argv, REPO_ROOT,
                                         tarefas.saidas(tipo), ocultar=d)
        except JobBusy:
            return self.json_reply(409, {"erro": "já existe uma tarefa rodando neste projeto",
                                         "codigo": "tarefa_rodando"})
        finally:
            trava.release()
        self.json_reply(202, {"job_id": job_id})

    def api_jobs_projeto(self, slug: str):
        """Tarefa ativa (completa, com log) e as recentes (resumo) do projeto: a pagina
        usa para retomar o acompanhamento depois de recarregar."""
        if self._projeto(slug) is None:
            return
        self._drenar()
        jobs = self.app.jobs
        ativo = None
        jid = jobs.ativo_em(slug)
        if jid:
            try:
                ativo = self._job_limpo(jobs.get(jid))
            except KeyError:
                ativo = None
        recentes = [{k: v for k, v in j.items() if k != "log"} for j in jobs.recentes(slug)]
        self.json_reply(200, {"ativo": ativo, "recentes": recentes})

    def _job_limpo(self, job: dict) -> dict:
        """Linhas do log sem o caminho do projeto nem caminhos absolutos (como a mensagem)."""
        try:
            d = self.app.projects.path(job.get("slug"))
        except ProjectsError:
            return dict(job, log=[])
        return dict(job, log=[revisao_api.sanitizar(x, d) for x in job.get("log", [])])

    def api_abrir_pasta(self, slug: str):
        """Abre ``projects/<slug>/saida`` no Finder/gerenciador de arquivos. Nunca usa
        shell; o caminho vem so de Projects.path. Em modo de teste so registra o argv
        em ``<root>/.abrir-pasta.log`` (uma linha JSON por chamada)."""
        d = self._projeto(slug)
        if d is None:
            return
        self._drenar()
        pasta = d / "saida"
        try:
            ok = (pasta.is_dir() and not pasta.is_symlink()
                  and pasta.resolve().parent == d.resolve())
        except (OSError, RuntimeError):
            ok = False
        if not ok:
            return self.error(409, "ainda não há arquivos prontos neste Reel")
        argv = comando_abrir_pasta(pasta)
        if self.server.test_mode:
            try:
                with open(self.app.root / ".abrir-pasta.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"argv": argv}, ensure_ascii=False) + "\n")
            except OSError:
                return self.error(500, "não foi possível abrir a pasta")
            return self.json_reply(200, {"ok": True})
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True,
                                    close_fds=True)
        except OSError:
            return self.error(500, "não foi possível abrir a pasta neste computador")
        threading.Thread(target=proc.wait, name="abrir-pasta", daemon=True).start()  # sem zumbi
        self.json_reply(200, {"ok": True})

    # -- revisao --------------------------------------------------------------
    def api_revisao(self, slug: str):
        d = self._projeto(slug)
        if d is None:
            return
        decisoes = None
        if self.command == "PUT":
            ok, corpo = self._read_json(MAX_JSON_REVISAO)
            if not ok:
                return
            try:
                decisoes = revisao_api.validar(corpo)
            except revisao_api.RevisaoErro as e:
                return self.error(e.status, e.msg)
        else:
            self._drenar()
        trava = revisao_api.trava(slug)
        if not trava.acquire(timeout=revisao_api.ESPERA_TRAVA):
            return self.error(409, "outra edição está em andamento neste projeto; tente de novo")
        try:
            # GET so le (regera review.json) e segue permitido com tarefa ativa; PUT nao
            if decisoes is not None and self.app.jobs.ativo_em(slug):
                return self.error(409, "há uma tarefa rodando neste projeto; aguarde terminar")
            try:
                if decisoes is None:
                    res = revisao_api.construir(d)
                else:
                    res = revisao_api.aplicar(d, decisoes)
            except revisao_api.RevisaoErro as e:
                return self.error(e.status, e.msg)
        finally:
            trava.release()
        self.json_reply(200, res)

    def api_etapa_legendas(self, slug: str):
        d = self._projeto(slug)
        if d is None:
            return
        ok, corpo = self._read_json()
        if not ok:
            return
        if not (isinstance(corpo, dict) and set(corpo) == {"confirmado"}
                and isinstance(corpo["confirmado"], bool)):
            return self.error(400, 'envie {"confirmado": true|false}')
        if corpo["confirmado"] and not (d / "transcricao.json").is_file():
            return self.error(409, "transcreva o vídeo primeiro")
        with self.app.replace_lock:
            atual = {}
            try:
                lido = json.loads((d / "etapas.json").read_text(encoding="utf-8"))
                if isinstance(lido, dict):
                    atual = lido
            except (OSError, ValueError):
                pass
            atual["legendas"] = corpo["confirmado"]
            atual["legendas_base"] = projects_mod.impressao(d)
            try:
                common.write_json_atomic(d / "etapas.json", atual)
            except OSError:
                return self.error(500, "não foi possível gravar a etapa")
        self.json_reply(200, {"legendas": corpo["confirmado"]})

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
        if self.app.jobs.ativo_em(slug):
            return self.error(409, "há uma tarefa rodando neste projeto")
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

    # -- materiais ---------------------------------------------------------------
    def _pasta_materiais(self, d: Path, criar: bool = False):
        pasta = d / "materiais"
        if criar:
            try:
                pasta.mkdir(exist_ok=True)
            except OSError:
                return None
        try:
            if pasta.is_symlink() or not pasta.is_dir() or pasta.resolve().parent != d.resolve():
                return None
        except (OSError, RuntimeError):
            return None
        return pasta

    def _lista_materiais(self, d: Path) -> list[dict]:
        pasta = self._pasta_materiais(d)
        itens = []
        if pasta is None:
            return itens
        for p in pasta.iterdir():
            ext = p.suffix.lower()
            if (p.name.startswith(".") or ext not in EXT_MATERIAIS or p.is_symlink()
                    or not p.is_file() or p.name != nome_material(p.name)):
                continue
            try:
                tam = p.stat().st_size
            except OSError:
                continue
            itens.append({"nome": p.name, "rel": f"materiais/{p.name}",
                          "tipo": "video" if ext == ".mp4" else "imagem", "tamanho": tam})
        itens.sort(key=lambda m: m["nome"])
        return itens

    def api_materiais(self, slug: str):
        d = self._projeto(slug)
        if d is None:
            return
        if self.command in ("GET", "HEAD"):
            return self.json_reply(200, {"materiais": self._lista_materiais(d)})
        nome = nome_material(unquote(self.headers.get("X-Filename") or ""))
        ext = os.path.splitext(nome)[1]
        if ext not in EXT_MATERIAIS:
            return self.error(415, "tipo de arquivo não aceito; use png, jpg, webp, svg ou mp4")
        n = self._content_length()
        if n is None:
            return
        if n == 0:
            return self.error(400, "arquivo vazio")
        if n > self.app.max_material:
            mb = self.app.max_material // (1024 * 1024)
            return self.error(413, f"arquivo grande demais (máximo {mb} MB)" if mb
                              else "arquivo grande demais")
        pasta = self._pasta_materiais(d, criar=True)
        if pasta is None:
            return self.error(500, "não foi possível usar a pasta de materiais")
        tmp = None
        try:
            fd, nome_tmp = tempfile.mkstemp(dir=d, prefix=".material-", suffix=".tmp")
            tmp = Path(nome_tmp)
            total, cabeca = 0, b""
            with os.fdopen(fd, "wb") as f:
                while total < n:
                    bloco = self.rfile.read(min(BLOCO, n - total))
                    if not bloco:
                        break
                    if len(cabeca) < 4096:
                        cabeca += bloco[:4096 - len(cabeca)]
                    total += len(bloco)
                    f.write(bloco)
                f.flush()
                os.fsync(f.fileno())
            self._corpo_lido = True
            if total != n:
                return self.error(400, "envio interrompido")
            if not _conteudo_confere(cabeca, ext):
                return self.error(415, f"o conteúdo não é um arquivo {ext[1:]} de verdade")
            radical = nome[:-len(ext)]
            with self.app.materiais_lock:
                usados = {p.name.lower() for p in pasta.iterdir()}
                final, i = nome, 1
                while final.lower() in usados:
                    i += 1
                    final = f"{radical}-{i}{ext}"
                os.link(tmp, pasta / final)  # nunca sobrescreve: falha se ja existir
        except TimeoutError:
            self.close_connection = True
            return self.error(408, "tempo esgotado no envio")
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            return self.error(400, "envio interrompido")
        except OSError as e:
            print(f"erro no envio de material: {e!r}", file=sys.stderr)
            return self.error(500, "não foi possível gravar o arquivo")
        finally:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        item = next((m for m in self._lista_materiais(d) if m["nome"] == final),
                    {"nome": final, "rel": f"materiais/{final}"})
        self.json_reply(201, item)

    def api_material_apagar(self, slug: str, nome: str):
        d = self._projeto(slug)
        if d is None:
            return
        self._drenar()
        lista = self._lista_materiais(d)
        if nome not in {m["nome"] for m in lista}:
            return self.error(404, "esse material não existe")
        try:
            (d / "materiais" / nome).unlink()
        except FileNotFoundError:
            return self.error(404, "esse material não existe")
        except OSError:
            return self.error(500, "não foi possível apagar o material")
        self.json_reply(200, {"materiais": self._lista_materiais(d)})

    # -- graficos -----------------------------------------------------------------
    def api_graficos(self, slug: str):
        d = self._projeto(slug)
        if d is None:
            return
        if self.command in ("GET", "HEAD"):
            self._drenar()
            return self.json_reply(200, self._graficos_atuais(d))
        ok, corpo = self._read_json(MAX_GRAFICOS)
        if not ok:
            return
        if not (isinstance(corpo, dict) and set(corpo) == {"cards"}
                and isinstance(corpo["cards"], list)):
            return self.error(400, 'envie {"cards": [...]}')
        for i, card in enumerate(corpo["cards"]):
            mat = card.get("material") if isinstance(card, dict) else None
            if mat not in (None, "") and not (isinstance(mat, str) and mat.startswith("materiais/")
                                              and ".." not in mat and "\\" not in mat):
                return self.error(400, f"card {i}: a imagem precisa ser um dos materiais")
        trava = revisao_api.trava(slug)
        if not trava.acquire(timeout=revisao_api.ESPERA_TRAVA):
            return self.error(409, "outra edição está em andamento neste projeto; tente de novo")
        tmp = None
        try:
            fd, nome_tmp = tempfile.mkstemp(dir=d, prefix=".graficos-", suffix=".tmp")
            tmp = Path(nome_tmp)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"cards": corpo["cards"]}, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            erro = self._validar_graficos(tmp, d)
            if erro is not None:
                return self.error(400, erro)
            os.replace(tmp, d / "graficos.json")
            tmp = None
        except OSError as e:
            print(f"erro ao gravar graficos: {e!r}", file=sys.stderr)
            return self.error(500, "não foi possível gravar os gráficos")
        finally:
            trava.release()
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        self.json_reply(200, self._graficos_atuais(d))

    @staticmethod
    def _graficos_atuais(d: Path) -> dict:
        cards, decisoes = [], {}
        try:
            doc = json.loads((d / "graficos.json").read_text(encoding="utf-8"))
            if isinstance(doc, dict) and isinstance(doc.get("cards"), list):
                cards = doc["cards"]
        except (OSError, ValueError):
            pass
        try:
            rev = json.loads((d / "revisao.json").read_text(encoding="utf-8"))
            g = rev.get("graphics") if isinstance(rev, dict) else None
            if isinstance(g, dict):
                decisoes = {k: v for k, v in g.items() if v in ("keep", "drop")}
        except (OSError, ValueError):
            pass
        return {"cards": cards, "decisoes": decisoes}

    @staticmethod
    def _validar_graficos(arquivo: Path, d: Path):
        """None se ``scripts/graphics.py validar`` aceitar; senao a mensagem limpa."""
        cmd = [sys.executable, "-I", str(REPO_ROOT / "scripts" / "graphics.py"), "validar",
               str(arquivo), str(d)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                  cwd=REPO_ROOT, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return "a conferência dos gráficos demorou demais"
        except OSError:
            return "não foi possível conferir os gráficos"
        if proc.returncode == 0 and proc.stdout.strip() == "ok":
            return None
        for linha in (proc.stderr + "\n" + proc.stdout).splitlines():
            if linha.startswith("erro:"):
                msg = linha[len("erro:"):].strip().replace(str(arquivo), "graficos.json")
                msg = msg.replace(arquivo.name, "graficos.json")
                return revisao_api.sanitizar(msg, d)[:500] or "gráficos inválidos"
        return "gráficos inválidos"

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
            self.send_header("Content-Security-Policy", CSP_SVG if alvo.suffix.lower() == ".svg" else CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
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
        self.send_header("Referrer-Policy", "no-referrer")
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


class _Servidor(ThreadingHTTPServer):
    def server_close(self):
        try:
            app = getattr(self, "app", None)  # bind falhou: TCPServer fecha antes do app
            if app is not None:
                app.jobs.shutdown()  # nao deixa ffmpeg/render orfaos
        finally:
            super().server_close()


def _env_float(nome: str):
    try:
        v = float(os.environ[nome])
    except (KeyError, ValueError):
        return None
    return v if v > 0 else None


def make_server(root: Path, token: str, host: str = "127.0.0.1", port: int = 0,
                max_upload: int = 4 * 1024 ** 3, test_mode: bool = False,
                idle_seconds: float | None = None, check_seconds: float | None = None
                ) -> ThreadingHTTPServer:
    """Cria o servidor. Somente loopback e suportado (127.0.0.1/localhost);
    a checagem de Host/Origin assume isso e nao deve ser usado em 0.0.0.0.

    ``idle_seconds``/``check_seconds`` valem para o vigia de inatividade (so ligado
    por ``main``/``iniciar_vigia``); sem eles, ``REEL_APP_IDLE_SECONDS`` e
    ``REEL_APP_CHECK_SECONDS`` so contam em ``test_mode``; senao, as constantes."""
    server = _Servidor((host, port), Handler)
    server.daemon_threads = True
    server.app = App(root, token)
    server.max_upload = max_upload
    server.test_mode = test_mode
    env_idle = _env_float("REEL_APP_IDLE_SECONDS") if test_mode else None
    env_check = _env_float("REEL_APP_CHECK_SECONDS") if test_mode else None
    server.idle_seconds = idle_seconds or env_idle or IDLE_SECONDS
    server.check_seconds = check_seconds or env_check or CHECK_SECONDS
    return server


# ------------------------------------------------------------------ lancador
def iniciar_vigia(server, encerrar, parar: threading.Event) -> threading.Thread:
    """Thread que chama ``encerrar()`` (uma vez) quando a pagina para de bater ha
    ``server.idle_seconds`` E nenhuma tarefa esta rodando. ``parar`` desliga o vigia."""
    def vigiar():
        while not parar.wait(server.check_seconds):
            parado = time.monotonic() - server.app.ultimo_sinal
            if parado >= server.idle_seconds and not server.app.jobs.algum_rodando():
                encerrar()
                return
    t = threading.Thread(target=vigiar, name="vigia-inatividade", daemon=True)
    t.start()
    return t


def comandos_navegador(url: str, plataforma: str | None = None) -> list[list[str]]:
    """argv (sem shell), em ordem de preferencia, para abrir ``url``: no Mac, o
    Google Chrome; sem ele, o navegador padrao. No Linux, ``xdg-open``."""
    plataforma = sys.platform if plataforma is None else plataforma
    if plataforma == "darwin":
        return [["open", "-a", "Google Chrome", url], ["open", url]]
    return [["xdg-open", url]]


def abrir_navegador(url: str, plataforma: str | None = None, run=subprocess.run) -> bool:
    """Tenta cada comando de ``comandos_navegador``; True no primeiro que der certo."""
    for argv in comandos_navegador(url, plataforma):
        try:
            r = run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=20, close_fds=True)
        except subprocess.TimeoutExpired:
            return True  # o comando ficou esperando o navegador: ele abriu
        except OSError:
            continue
        if r.returncode == 0:
            return True
    return False


def _ler_app_json(raiz: Path):
    """{"porta","token","pid"} validado, ou None (ausente, corrompido, campos errados)."""
    try:
        caminho = Path(raiz) / APP_JSON
        if caminho.is_symlink() or caminho.stat().st_size > 4096:
            return None
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(dados, dict):
        return None
    porta, token, pid = dados.get("porta"), dados.get("token"), dados.get("pid")
    if not (type(porta) is int and 0 < porta < 65536 and type(pid) is int and pid > 0
            and isinstance(token, str) and 0 < len(token) <= 200):
        return None
    return {"porta": porta, "token": token, "pid": pid}


def _pid_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def _prova_ok(porta: int, token: str, timeout: float = 2.0) -> bool:
    """O editor com esta chave responde nesta porta? Desafio sem enviar a chave:
    o servico prova conhecer o token devolvendo HMAC-SHA256(token, nonce)."""
    nonce = secrets.token_hex(16)
    esperado = hmac.new(token.encode("utf-8"), nonce.encode("ascii"), hashlib.sha256).hexdigest()
    conn = http.client.HTTPConnection("127.0.0.1", porta, timeout=timeout)
    try:
        conn.request("GET", f"/api/identidade?nonce={nonce}",
                     headers={"Host": f"127.0.0.1:{porta}"})
        r = conn.getresponse()
        dados = json.loads(r.read(1024).decode("utf-8"))
        prova = dados.get("prova") if isinstance(dados, dict) else None
        return (r.status == 200 and isinstance(prova, str)
                and hmac.compare_digest(prova.encode("utf-8"), esperado.encode("ascii")))
    except (OSError, ValueError, UnicodeError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def instancia_ativa(raiz: Path):
    """URL do editor que ja esta no ar para esta pasta de projetos, ou None."""
    info = _ler_app_json(raiz)
    if info is None or info["pid"] == os.getpid() or not _pid_vivo(info["pid"]):
        return None
    if not _prova_ok(info["porta"], info["token"]):
        return None
    return _url(info["porta"], info["token"])


def _url(porta: int, token: str) -> str:
    return f"http://127.0.0.1:{porta}/?t={token}"


def gravar_app_json(raiz: Path, porta: int, token: str, pid: int) -> None:
    """Grava ``.app.json`` atomicamente e so legivel pelo usuario (0600): tem a chave."""
    texto = json.dumps({"porta": porta, "token": token, "pid": pid,
                        "iniciado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    with common.atomic_write(Path(raiz) / APP_JSON) as tmp:
        os.chmod(tmp, 0o600)
        tmp.write_text(texto, encoding="utf-8")


def _travar(raiz: Path, prazo: float = 30.0) -> bool:
    """Trava ``.app.lock`` (O_EXCL, com o pid) para duas aberturas ao mesmo tempo nao
    subirem dois editores. Trava de pid morto (ou ilegivel) e apagada; viva, espera."""
    trava = Path(raiz) / ".app.lock"
    fim = time.monotonic() + prazo
    while True:
        try:
            fd = os.open(trava, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                dono = int(trava.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                dono = 0
            if dono <= 0 or not _pid_vivo(dono):
                try:
                    trava.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() > fim:
                return False
            time.sleep(0.1)
            continue
        except OSError:
            return False
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True


def _destravar(raiz: Path) -> None:
    trava = Path(raiz) / ".app.lock"
    try:
        if trava.read_text(encoding="utf-8").strip() == str(os.getpid()):
            trava.unlink()
    except OSError:
        pass


def remover_app_json(raiz: Path, pid: int) -> None:
    """Apaga ``.app.json`` so se ele for desta instancia (``pid``)."""
    info = _ler_app_json(raiz)
    if info is not None and info["pid"] == pid:
        try:
            (Path(raiz) / APP_JSON).unlink()
        except OSError:
            pass


def _argumentos(argv):
    p = argparse.ArgumentParser(
        prog="app/server.py", description="Editor de Reels: abre a página do editor no navegador.")
    p.add_argument("--porta", type=int, default=0,
                   help="porta fixa (padrão: uma porta livre qualquer)")
    p.add_argument("--sem-navegador", action="store_true",
                   help="não abre o navegador; só mostra o endereço")
    # internos (testes): pasta de projetos e tempos de inatividade
    p.add_argument("--raiz", type=Path, default=PADRAO_RAIZ, help=argparse.SUPPRESS)
    p.add_argument("--inatividade", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--intervalo-checagem", type=float, default=None, help=argparse.SUPPRESS)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _argumentos(argv)
    raiz = Path(args.raiz)
    try:
        raiz.mkdir(parents=True, exist_ok=True)
    except OSError:
        print(f"erro: não foi possível usar a pasta de projetos ({raiz.name}).", file=sys.stderr)
        return 1
    travado = _travar(raiz)
    try:
        return _main(args, raiz, travado)
    finally:
        if travado:
            _destravar(raiz)


def _main(args, raiz: Path, travado: bool) -> int:

    existente = instancia_ativa(raiz)
    if existente:
        print("O editor já estava aberto; abrindo a mesma página no navegador.", flush=True)
        print(f"Endereço: {existente}", flush=True)
        if not args.sem_navegador:
            abrir_navegador(existente)
        return 0

    if not 0 <= args.porta < 65536:
        print("erro: a porta precisa ser um número entre 1 e 65535.", file=sys.stderr)
        return 1
    token = secrets.token_urlsafe(32)
    try:
        srv = make_server(raiz, token, port=args.porta,
                          idle_seconds=args.inatividade, check_seconds=args.intervalo_checagem)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print(f"erro: a porta {args.porta} já está em uso por outro programa. "
                  "Feche esse programa ou abra o editor sem escolher a porta.", file=sys.stderr)
        else:
            print("erro: não foi possível iniciar o editor neste computador.", file=sys.stderr)
        return 1
    pid = os.getpid()
    porta = srv.server_address[1]
    parado = threading.Event()

    def encerrar(motivo: str | None = None):
        if parado.is_set():
            return
        parado.set()
        if motivo:
            print(motivo, flush=True)
        # shutdown() espera o serve_forever: nunca na thread dele (o sinal cai nela)
        threading.Thread(target=srv.shutdown, name="encerrar", daemon=True).start()

    try:
        for nome in ("SIGTERM", "SIGINT", "SIGHUP"):
            if hasattr(signal, nome):
                signal.signal(getattr(signal, nome), lambda *_: encerrar())
        gravar_app_json(raiz, porta, token, pid)
        if travado:
            _destravar(raiz)  # .app.json ja gravado: a proxima abertura reaproveita
        url = _url(porta, token)
        print("Editor de Reels aberto.", flush=True)
        print(f"Endereço: {url}", flush=True)
        print("Se o navegador não abrir sozinho, copie o endereço acima e cole no Google Chrome.",
              flush=True)
        print("Para fechar o editor, feche esta janela.", flush=True)
        if not args.sem_navegador:
            threading.Thread(target=abrir_navegador, args=(url,), name="navegador",
                             daemon=True).start()
        minutos = max(1, round(srv.idle_seconds / 60))
        iniciar_vigia(srv, lambda: encerrar(
            f"O editor fechou sozinho: a página ficou fechada por {minutos} "
            f"minuto{'s' if minutos > 1 else ''}. Para usar de novo, dê dois cliques em "
            "Abrir Editor."), parado)
        srv.serve_forever(poll_interval=0.2)
    except OSError:
        print("erro: não foi possível iniciar o editor neste computador.", file=sys.stderr)
        return 1
    finally:
        parado.set()
        try:
            srv.server_close()  # mata as tarefas em andamento (Jobs.shutdown)
        finally:
            remover_app_json(raiz, pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
