"""Lancador do app: `python3 -I app/server.py`, segunda instancia, encerramento por
inatividade, `Abrir Editor.command` e a batida (heartbeat) da pagina.

O servidor roda como subprocesso de verdade, sem navegador, numa pasta de projetos
temporaria (opcao interna `--raiz`) e com tempos de inatividade curtos (opcoes
internas `--inatividade`/`--intervalo-checagem`). Esperas sao por condicao.
"""
import http.client
import http.server
import json
import os
import queue
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest_app import client
import server
from server import make_server

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "app" / "server.py"
COMMAND = REPO / "Abrir Editor.command"
URL_RE = re.compile(r"http://127\.0\.0\.1:(\d+)/\?t=([A-Za-z0-9_-]+)")


# --------------------------------------------------------------- utilidades
class Proc:
    """Subprocesso do servidor com leitura de stdout em thread (sem bloquear o teste)."""

    def __init__(self, raiz, *extra):
        self.p = subprocess.Popen(
            [sys.executable, "-I", str(SERVER), "--sem-navegador", "--raiz", str(raiz), *extra],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(REPO))
        self.linhas = queue.Queue()
        self.saida = []
        self.erro = []
        threading.Thread(target=self._ler, args=(self.p.stdout, self.saida, True), daemon=True).start()
        threading.Thread(target=self._ler, args=(self.p.stderr, self.erro, False), daemon=True).start()

    def _ler(self, f, guardar, fila):
        for linha in f:
            guardar.append(linha)
            if fila:
                self.linhas.put(linha)

    def url(self, prazo=20):
        fim = time.monotonic() + prazo
        while time.monotonic() < fim:
            try:
                linha = self.linhas.get(timeout=0.1)
            except queue.Empty:
                if self.p.poll() is not None and self.linhas.empty():
                    break
                continue
            m = URL_RE.search(linha)
            if m:
                return m.group(0), int(m.group(1)), m.group(2)
        raise AssertionError(f"servidor nao imprimiu a URL; stderr={''.join(self.erro)}")

    def esperar_fim(self, prazo=15):
        return self.p.wait(timeout=prazo)

    def matar(self):
        if self.p.poll() is None:
            self.p.kill()
            self.p.wait(timeout=10)


@pytest.fixture
def procs():
    lista = []

    def subir(raiz, *extra):
        pr = Proc(raiz, *extra)
        lista.append(pr)
        return pr

    yield subir
    for pr in lista:
        pr.matar()


@pytest.fixture
def raiz(tmp_path):
    r = tmp_path / "projects"
    r.mkdir()
    return r


def _get(porta, path, token=None, metodo="GET", timeout=5):
    conn = http.client.HTTPConnection("127.0.0.1", porta, timeout=timeout)
    try:
        h = {"Host": f"127.0.0.1:{porta}"}
        if token:
            h["X-Token"] = token
        conn.request(metodo, path, body=b"" if metodo == "POST" else None, headers=h)
        r = conn.getresponse()
        return r.status, r.read()
    finally:
        conn.close()


def _esperar(cond, prazo=10.0, passo=0.05):
    fim = time.monotonic() + prazo
    while time.monotonic() < fim:
        if cond():
            return True
        time.sleep(passo)
    return False


def _pid_morto():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------- subida e .app.json
def test_server_main_prints_url_with_token_and_writes_app_json(raiz, procs):
    pr = procs(raiz)
    url, porta, token = pr.url()
    assert "?t=" in url and len(token) >= 20
    app = json.loads((raiz / ".app.json").read_text("utf-8"))
    assert app == {"porta": porta, "token": token, "pid": pr.p.pid}
    status, corpo = _get(porta, f"/?t={token}")
    assert status == 200 and token.encode() in corpo
    status, corpo = _get(porta, "/api/ping", token)
    assert status == 200 and json.loads(corpo) == {"ok": True}
    texto = "".join(pr.saida)
    assert "Google Chrome" in texto, "diz o que fazer se o navegador nao abrir"


def test_app_json_is_private(raiz, procs):
    pr = procs(raiz)
    pr.url()
    modo = stat.S_IMODE((raiz / ".app.json").stat().st_mode)
    assert modo == 0o600, oct(modo)
    assert not [p for p in raiz.iterdir() if p.name.endswith(".tmp")], "sem temporario sobrando"


def test_random_free_port_by_default_and_fixed_with_option(raiz, procs, tmp_path):
    _, porta1, tok1 = procs(raiz).url()
    assert porta1 > 0
    outra = tmp_path / "outra"
    outra.mkdir()
    fixa = _porta_livre()
    _, porta2, tok2 = procs(outra, "--porta", str(fixa)).url()
    assert porta2 == fixa and tok1 != tok2


@pytest.mark.parametrize("sinal", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_signal_stops_server_and_removes_app_json(raiz, procs, sinal):
    pr = procs(raiz)
    _, porta, _ = pr.url()
    assert (raiz / ".app.json").exists()
    pr.p.send_signal(sinal)
    assert pr.esperar_fim() == 0, "".join(pr.erro)
    assert not (raiz / ".app.json").exists()
    assert "Traceback" not in "".join(pr.erro)
    with pytest.raises(OSError):
        _get(porta, "/api/ping", timeout=1)


def test_app_json_of_other_pid_is_not_removed_on_exit(raiz, procs):
    pr = procs(raiz)
    pr.url()
    alheio = {"porta": 1, "token": "x", "pid": os.getpid()}
    (raiz / ".app.json").write_text(json.dumps(alheio), "utf-8")
    pr.p.terminate()
    assert pr.esperar_fim() == 0
    assert json.loads((raiz / ".app.json").read_text("utf-8")) == alheio


def test_busy_port_message_in_portuguese(raiz, procs):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        porta = s.getsockname()[1]
        pr = procs(raiz, "--porta", str(porta))
        assert pr.esperar_fim() == 1
    erro = "".join(pr.erro) + "".join(pr.saida)
    assert "em uso" in erro and str(porta) in erro
    assert "Traceback" not in erro
    assert not (raiz / ".app.json").exists()


# ------------------------------------------------------------ segunda instancia
def test_second_instance_reuses_first(raiz, procs, monkeypatch, capsys):
    primeiro = procs(raiz)
    url, porta, token = primeiro.url()
    segundo = procs(raiz)
    assert segundo.esperar_fim() == 0, "".join(segundo.erro)
    assert url in "".join(segundo.saida)
    assert json.loads((raiz / ".app.json").read_text("utf-8"))["pid"] == primeiro.p.pid
    # sem --sem-navegador a segunda instancia so reabre a MESMA url no navegador
    abertos = []
    monkeypatch.setattr(server, "abrir_navegador", lambda u, **kw: abertos.append(u) or True)
    assert server.main(["--raiz", str(raiz)]) == 0
    assert abertos == [url]
    assert url in capsys.readouterr().out
    status, _ = _get(porta, "/api/ping", token)
    assert status == 200, "a primeira instancia continua no ar"


class _OutroServico(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        corpo = b'{"ok": true}' if self.path == "/sem-token" else b"nada aqui"
        self.send_response(404)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


@pytest.mark.parametrize("caso", ["corrompido", "nao_objeto", "pid_morto", "porta_fechada",
                                  "outro_servico", "token_errado"])
def test_stale_app_json_ignored(raiz, procs, caso):
    outro = None
    app_json = raiz / ".app.json"
    if caso == "corrompido":
        app_json.write_text("{isto nao e json", "utf-8")
    elif caso == "nao_objeto":
        app_json.write_text("[1, 2, 3]", "utf-8")
    elif caso == "pid_morto":
        app_json.write_text(json.dumps({"porta": _porta_livre(), "token": "abc",
                                        "pid": _pid_morto()}), "utf-8")
    elif caso == "porta_fechada":
        app_json.write_text(json.dumps({"porta": _porta_livre(), "token": "abc",
                                        "pid": os.getpid()}), "utf-8")
    else:
        outro = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OutroServico)
        threading.Thread(target=outro.serve_forever, daemon=True).start()
        app_json.write_text(json.dumps({"porta": outro.server_address[1], "token": "abc",
                                        "pid": os.getpid()}), "utf-8")
    try:
        if caso == "token_errado":  # um editor de verdade, mas com outra chave
            outro.shutdown()
            outro.server_close()
            vivo = make_server(raiz, "chave-certa", test_mode=True)
            outro = vivo
            threading.Thread(target=vivo.serve_forever, daemon=True).start()
            app_json.write_text(json.dumps({"porta": vivo.server_address[1],
                                            "token": "chave-errada", "pid": os.getpid()}), "utf-8")
        pr = procs(raiz)
        _, porta, token = pr.url()
        assert pr.p.poll() is None, "subiu um servidor novo"
        assert json.loads(app_json.read_text("utf-8")) == {"porta": porta, "token": token,
                                                           "pid": pr.p.pid}
    finally:
        if outro is not None:
            outro.shutdown()
            outro.server_close()


# ------------------------------------------------------------- inatividade
def test_auto_shutdown_after_idle_no_jobs(raiz, procs):
    pr = procs(raiz, "--inatividade", "1", "--intervalo-checagem", "0.1")
    pr.url()
    inicio = time.monotonic()
    assert pr.esperar_fim(prazo=15) == 0, "".join(pr.erro)
    assert time.monotonic() - inicio >= 0.8, "conta a partir da subida"
    assert not (raiz / ".app.json").exists()
    assert "Abrir Editor" in "".join(pr.saida), "explica como abrir de novo"


def test_heartbeat_keeps_server_alive(raiz, procs):
    pr = procs(raiz, "--inatividade", "1.5", "--intervalo-checagem", "0.1")
    _, porta, token = pr.url()
    fim = time.monotonic() + 3.5
    while time.monotonic() < fim:
        status, _ = _get(porta, "/api/heartbeat", token, metodo="POST")
        assert status == 200
        assert pr.p.poll() is None, "com a pagina aberta o servidor nao fecha"
        time.sleep(0.3)
    assert pr.esperar_fim(prazo=15) == 0, "sem batida, fecha"


def test_heartbeat_requires_token(raiz):
    srv = make_server(raiz, "tok-hb", test_mode=True)
    with client(srv) as c:
        antes = srv.app.ultimo_sinal
        r = c.request("POST", "/api/heartbeat", body=b"", token=False)
        assert r.status == 401
        r = c.request("POST", "/api/heartbeat", body=b"", headers={"X-Token": "errado"})
        assert r.status == 401
        assert srv.app.ultimo_sinal == antes
        time.sleep(0.01)
        r = c.request("POST", "/api/heartbeat", body=b"")
        assert r.status == 200 and r.json() == {"ok": True}
        assert srv.app.ultimo_sinal > antes
        assert c.request("GET", "/api/heartbeat").status == 405
        r = c.request("POST", "/api/heartbeat", body=b"{}")  # corpo ignorado
        assert r.status == 200


def test_idle_env_override_only_in_test_mode(raiz, monkeypatch):
    monkeypatch.setenv("REEL_APP_IDLE_SECONDS", "3")
    monkeypatch.setenv("REEL_APP_CHECK_SECONDS", "0.5")
    real = make_server(raiz, "t1")
    teste = make_server(raiz, "t2", test_mode=True)
    explicito = make_server(raiz, "t3", idle_seconds=7, check_seconds=0.2)
    try:
        assert (real.idle_seconds, real.check_seconds) == (server.IDLE_SECONDS, server.CHECK_SECONDS)
        assert server.IDLE_SECONDS == 120
        assert (teste.idle_seconds, teste.check_seconds) == (3.0, 0.5)
        assert (explicito.idle_seconds, explicito.check_seconds) == (7, 0.2)
    finally:
        for s in (real, teste, explicito):
            s.server_close()


def test_no_shutdown_while_job_running(raiz):
    (raiz / "reel").mkdir()
    srv = make_server(raiz, "tok", idle_seconds=0.2, check_seconds=0.05)
    encerrou = threading.Event()
    parar = threading.Event()
    try:
        jid = srv.app.jobs.start("reel", "teste",
                                 [sys.executable, "-c", "import time; time.sleep(60)"], REPO)
        assert srv.app.jobs.algum_rodando()
        server.iniciar_vigia(srv, encerrou.set, parar)
        assert not encerrou.wait(1.0), "com tarefa rodando o servidor nao fecha"
        assert srv.app.jobs.cancel(jid)
        assert _esperar(lambda: not srv.app.jobs.algum_rodando(), prazo=15)
        assert encerrou.wait(5), "terminada a tarefa e sem pagina, fecha"
    finally:
        parar.set()
        srv.server_close()


# ------------------------------------------------------------- navegador
def test_open_browser_prefers_chrome():
    url = "http://127.0.0.1:5000/?t=abc"
    assert server.comandos_navegador(url, "darwin") == [
        ["open", "-a", "Google Chrome", url], ["open", url]]
    assert server.comandos_navegador(url, "linux") == [["xdg-open", url]]

    chamadas = []

    def falso(codigos):
        def run(argv, **kw):
            chamadas.append((argv, kw))
            c = codigos.pop(0)
            if isinstance(c, BaseException):
                raise c
            return subprocess.CompletedProcess(argv, c)
        return run

    assert server.abrir_navegador(url, plataforma="darwin", run=falso([0])) is True
    assert [a for a, _ in chamadas] == [["open", "-a", "Google Chrome", url]]
    chamadas.clear()
    assert server.abrir_navegador(url, plataforma="darwin", run=falso([1, 0])) is True
    assert [a for a, _ in chamadas] == [["open", "-a", "Google Chrome", url], ["open", url]]
    chamadas.clear()
    assert server.abrir_navegador(url, plataforma="linux",
                                  run=falso([FileNotFoundError()])) is False
    chamadas.clear()
    assert server.abrir_navegador(url, plataforma="darwin", run=falso([1, 1])) is False


def test_open_browser_never_uses_shell():
    url = "http://127.0.0.1:5000/?t=a;rm -rf ~"
    vistos = []

    def run(argv, **kw):
        vistos.append((argv, kw))
        return subprocess.CompletedProcess(argv, 1)

    for plataforma in ("darwin", "linux"):
        server.abrir_navegador(url, plataforma=plataforma, run=run)
    assert vistos
    for argv, kw in vistos:
        assert isinstance(argv, list) and argv[-1] == url, "url e um argumento so"
        assert not kw.get("shell")
    fonte = SERVER.read_text("utf-8")
    assert "shell=True" not in fonte and "os.system" not in fonte


# --------------------------------------------------------- Abrir Editor.command
def test_command_file_is_executable_and_mentions_python_fallback():
    assert COMMAND.is_file()
    assert os.access(COMMAND, os.X_OK)
    texto = COMMAND.read_text("utf-8")
    assert texto.startswith("#!/bin/bash\n")
    assert 'cd "$(dirname "$0")"' in texto
    assert "/opt/homebrew/opt/python@3.13/libexec/bin/python3" in texto
    assert "brew install python@3.13 ffmpeg node git" in texto
    assert "brew.sh" in texto and "read -p" in texto
    assert "-I app/server.py" in texto
    assert "set -e" not in texto
    assert "(3, 11)" in texto or "3,11" in texto
    r = subprocess.run(["bash", "-n", str(COMMAND)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    if shutil.which("git") and (REPO / ".git").exists():
        r = subprocess.run(["git", "ls-files", "-s", COMMAND.name], cwd=REPO,
                           capture_output=True, text=True)
        if r.stdout.strip():
            assert r.stdout.startswith("100755"), "executavel tambem no git"


def _fake_python(pasta: Path, versao_ok: bool, registro: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    py = pasta / "python3"
    py.write_text("#!/bin/bash\n"
                  f'if [ "$1" = "-c" ]; then exit {0 if versao_ok else 1}; fi\n'
                  f'echo "$PWD|$*" >> "{registro}"\n', "utf-8")
    py.chmod(0o755)
    return pasta


def test_command_runs_server_with_path_python(tmp_path):
    registro = tmp_path / "registro.txt"
    bin_ = _fake_python(tmp_path / "bin", True, registro)
    r = subprocess.run(["/bin/bash", str(COMMAND)], input="\n", capture_output=True, text=True,
                       env={"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(tmp_path)},
                       cwd=str(tmp_path), timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    linhas = registro.read_text("utf-8").splitlines()
    assert linhas == [f"{REPO}|-I app/server.py"], linhas


def test_command_explains_what_to_install_without_python(tmp_path):
    registro = tmp_path / "registro.txt"
    bin_ = _fake_python(tmp_path / "bin", False, registro)  # python3 antigo (3.9 do macOS)
    if Path("/opt/homebrew/opt/python@3.13/libexec/bin/python3").exists():
        pytest.skip("python do Homebrew instalado nesta maquina")
    r = subprocess.run(["/bin/bash", str(COMMAND)], input="\n", capture_output=True, text=True,
                       env={"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(tmp_path)},
                       cwd=str(tmp_path), timeout=30)
    saida = r.stdout + r.stderr
    assert not registro.exists(), "nao tenta rodar o servidor com python antigo"
    assert "brew install python@3.13 ffmpeg node git" in saida
    assert "brew.sh" in saida and "Enter" in saida
    for jargao in ("PATH", "sys.version", "Traceback", "exit code"):
        assert jargao not in saida, jargao


# -------------------------------------------------------------- pagina
def test_page_script_sends_heartbeat_every_10s():
    js = (REPO / "app" / "web" / "app.js").read_text("utf-8")
    assert "'/api/heartbeat'" in js
    assert "keepalive: true" in js
    assert re.search(r"setInterval\(\s*batida\s*,\s*BATIDA_MS\s*\)", js)
    assert re.search(r"BATIDA_MS\s*=\s*10[_]?000", js)
    corpo = js[js.index("function batida"):]
    corpo = corpo[:corpo.index("\n}\n")]
    assert ".catch(" in corpo, "falha da batida e silenciosa"
    assert "toast" not in corpo


def test_page_heartbeat_in_browser(tmp_path):
    from test_app_ui_shell import _node_env, _requirements
    falta = _requirements()
    if falta:
        pytest.skip(f"batida na pagina nao testada: {falta}")
    marca = json.loads((REPO / "brand" / "brand.json").read_text("utf-8"))
    (tmp_path / "brand.json").write_text(json.dumps(dict(marca, handles=["@x"])), "utf-8")
    cfg = {"tmp": str(tmp_path), "brand": str(tmp_path / "brand.json")}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg), "utf-8")
    r = subprocess.run(["node", str(REPO / "tests" / "js" / "heartbeat.mjs"),
                        str(tmp_path / "cfg.json")], capture_output=True, text=True,
                       env=_node_env(), timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    res = json.loads(r.stdout)
    assert "error" not in res, res.get("error")
    assert res["inicial"] >= 1, "bate assim que a pagina abre"
    assert res["depois10s"] == res["inicial"] + 1, res
    assert res["depois20s"] == res["inicial"] + 2, res
    assert res["terminadas"] == res["depois20s"], "resposta lida: nenhum pedido pendurado"
    assert res["ociosa"] is True, "a batida nao impede a rede de ficar ociosa"
    assert all(b["metodo"] == "POST" and b["token"] for b in res["batidas"])
    assert res["fatal"] is False, "batida falhando nao mostra erro na tela"


# ---------------------------------------------------------------- documentacao
def test_como_usar_covers_install_open_steps_files_and_errors():
    doc = (REPO / "COMO-USAR.md").read_text("utf-8")
    for trecho in ("https://brew.sh", "brew install python@3.13 ffmpeg node git",
                   "/opt/homebrew/opt/python@3.13/libexec/bin",
                   "pip install --break-system-packages -r requirements.txt",
                   "Abrir Editor", "botão direito", "projects/<nome do Reel>/saida",
                   "Acesso negado", "O vídeo não envia", "A página não abre"):
        assert trecho in doc, trecho
    passos = re.findall(r"^\d\. \*\*(.+?)\*\*", doc, re.MULTILINE)
    assert passos == ["Vídeo", "Cortes", "Legendas", "Estilo", "Preview", "Gráficos",
                      "Capa", "Final"]
    for emBreve in ("Estilo", "Gráficos", "Capa"):
        linha = doc[doc.index(f"**{emBreve}**"):].split("\n\n")[0]
        assert "chega em breve" in linha, emBreve
    assert (REPO / "requirements.txt").is_file()
    readme = (REPO / "README.md").read_text("utf-8")
    assert "COMO-USAR.md" in readme and "Abrir Editor.command" in readme
