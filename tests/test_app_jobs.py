import io
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest_app import client, repo_root  # noqa: F401
import jobs as jobsmod
import tarefas
from jobs import JobBusy, Jobs
from server import make_server

TOKEN = "tok-de-teste-123"


def py(codigo):
    return [sys.executable, "-c", codigo]


def esperar(j, job_id, estado=None, timeout=15):
    fim = time.time() + timeout
    while time.time() < fim:
        d = j.get(job_id)
        if d["estado"] != "rodando" and (estado is None or d["estado"] == estado):
            return d
        time.sleep(0.05)
    raise AssertionError(f"job nao terminou: {j.get(job_id)}")


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "projects"
    for s in ("a", "b"):
        (r / s).mkdir(parents=True)
    return r


def test_job_ok_collects_log_and_outputs(root):
    j = Jobs(root)
    jid = j.start("a", "cortes", py("print('oi'); print('tchau')"), root / "a",
                  saidas=["saida/preview.mp4"])
    d = esperar(j, jid)
    assert d["estado"] == "ok" and d["log"] == ["oi", "tchau"]
    assert d["saidas"] == ["saida/preview.mp4"] and d["fim"] and d["slug"] == "a"
    assert j.ativo_em("a") is None


def test_job_error_message_from_stderr_line(root):
    j = Jobs(root)
    jid = j.start("a", "cortes", py(
        "import sys; print('Traceback (most recent call last):', file=sys.stderr);"
        "print('erro: sem transcricao', file=sys.stderr); sys.exit(2)"), root / "a")
    d = esperar(j, jid)
    assert d["estado"] == "erro" and d["mensagem"] == "sem transcricao"
    assert "Traceback" not in d["mensagem"]
    jid = j.start("a", "cortes", py("import sys; sys.exit(3)"), root / "a")
    assert esperar(j, jid)["mensagem"] == "a tarefa falhou (código 3)"


def test_second_job_same_project_busy_409(root):
    j = Jobs(root)
    jid = j.start("a", "x", py("import time; time.sleep(30)"), root / "a")
    with pytest.raises(JobBusy):
        j.start("a", "y", py("pass"), root / "a")
    assert j.ativo_em("a") == jid
    j.cancel(jid)
    esperar(j, jid)


def test_busy_returns_409_over_http(root, monkeypatch, tmp_path):
    s = make_server(root, TOKEN, test_mode=True)
    monkeypatch.setattr(tarefas, "argv", lambda tipo, p, **o: py("import time; time.sleep(30)"))
    with client(s) as c:
        r = c.request("POST", "/api/projects/a/jobs/cortes", body={})
        assert r.status == 202
        jid = r.json()["job_id"]
        r2 = c.request("POST", "/api/projects/a/jobs/preview", body={})
        assert r2.status == 409 and "já existe uma tarefa" in r2.json()["erro"]
        assert c.get(f"/api/jobs/{jid}").json()["estado"] == "rodando"
        assert c.request("POST", f"/api/jobs/{jid}/cancelar", body={}).json() == {"ok": True}
        esperar(s.app.jobs, jid)
        assert c.get(f"/api/jobs/{jid}").json()["estado"] == "cancelado"
        assert c.request("POST", f"/api/jobs/{jid}/cancelar", body={}).json() == {"ok": False}


def test_jobs_in_different_projects_run_in_parallel(root):
    j = Jobs(root)
    a = j.start("a", "x", py("import time; time.sleep(30)"), root / "a")
    b = j.start("b", "x", py("import time; time.sleep(30)"), root / "b")
    assert j.get(a)["estado"] == "rodando" and j.get(b)["estado"] == "rodando"
    j.cancel(a)
    j.cancel(b)
    esperar(j, a)
    esperar(j, b)


def test_cancel_kills_process_tree(root, tmp_path):
    pidfile = tmp_path / "filho.pid"
    j = Jobs(root)
    codigo = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"open({str(pidfile)!r},'w').write(str(p.pid));time.sleep(60)")
    jid = j.start("a", "x", py(codigo), root / "a")
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text():
            break
        time.sleep(0.05)
    filho = int(pidfile.read_text())
    assert j.cancel(jid) is True
    d = esperar(j, jid)
    assert d["estado"] == "cancelado"
    for _ in range(100):
        try:
            os.kill(filho, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("filho continua vivo")


def test_cancel_sigkill_when_sigterm_ignored(root):
    j = Jobs(root)
    j.GRACA = 0.5
    jid = j.start("a", "x", py(
        "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "print('pronto',flush=True);time.sleep(60)"), root / "a")
    for _ in range(100):
        if j.get(jid)["log"]:
            break
        time.sleep(0.05)
    t0 = time.time()
    assert j.cancel(jid)
    d = esperar(j, jid)
    assert d["estado"] == "cancelado" and time.time() - t0 < 10


def test_cancel_after_finish_is_false(root):
    j = Jobs(root)
    jid = j.start("a", "x", py("pass"), root / "a")
    esperar(j, jid)
    assert j.cancel(jid) is False
    assert j.cancel("0" * 32) is False


def test_job_state_survives_new_Jobs_instance_for_finished(root):
    j = Jobs(root)
    jid = j.start("a", "x", py("print('guardado')"), root / "a", saidas=["saida/final.mp4"])
    esperar(j, jid)
    time.sleep(0.2)
    j2 = Jobs(root)
    d = j2.get(jid)
    assert d["estado"] == "ok" and d["log"] == ["guardado"] and d["saidas"] == ["saida/final.mp4"]
    assert [x["id"] for x in j2.recentes("a")] == [jid]


def test_orphan_running_job_marked_error_on_start(root):
    jid = "ab" * 16
    (root / "a" / f".tarefa-{jid}.json").write_text(json.dumps({
        "id": jid, "slug": "a", "tipo": "x", "estado": "rodando", "mensagem": "",
        "log": [], "inicio": "2026-01-01T00:00:00", "fim": None, "saidas": []}))
    j = Jobs(root)
    d = j.get(jid)
    assert d["estado"] == "erro" and d["mensagem"] == "interrompida" and d["fim"]
    assert j.ativo_em("a") is None


def test_popen_file_not_found_makes_error_job(root, monkeypatch):
    j = Jobs(root)
    jid = j.start("a", "x", ["programa-que-nao-existe-xyz"], root / "a")
    d = j.get(jid)
    assert d["estado"] == "erro" and "não encontrado" in d["mensagem"]
    assert j.ativo_em("a") is None
    jid2 = j.start("a", "x", py("pass"), root / "a")  # projeto liberado
    esperar(j, jid2)


def test_concurrent_start_same_project_exactly_one(root):
    j = Jobs(root)
    resultados = []
    barreira = threading.Barrier(8)

    def tenta():
        barreira.wait()
        try:
            resultados.append(j.start("a", "x", py("import time; time.sleep(30)"), root / "a"))
        except JobBusy:
            resultados.append("busy")

    ts = [threading.Thread(target=tenta) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ids = [r for r in resultados if r != "busy"]
    assert len(ids) == 1 and resultados.count("busy") == 7
    j.cancel(ids[0])
    esperar(j, ids[0])


def test_keeps_only_last_20_finished(root):
    j = Jobs(root)
    ids = []
    for _ in range(23):
        jid = j.start("a", "x", py("pass"), root / "a")
        esperar(j, jid)
        time.sleep(0.02)
        ids.append(jid)
    time.sleep(0.3)
    arqs = list((root / "a").glob(".tarefa-*.json"))
    assert len(arqs) == 20
    assert len(j.recentes("a")) == 20


def test_log_keeps_last_200_lines_and_decodes_invalid_bytes(root):
    j = Jobs(root)
    jid = j.start("a", "x", py(
        "import sys\nfor i in range(300): print(i)\n"
        "sys.stdout.buffer.write(b'\\xff\\xfe ruim\\n')"), root / "a")
    d = esperar(j, jid)
    assert len(d["log"]) == 200 and "ruim" in d["log"][-1]


def test_option_validation_rejects_unknown_keys(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    with pytest.raises(ValueError):
        tarefas.argv("preview", p, foo=1)
    with pytest.raises(ValueError):
        tarefas.argv("transcrever", p, model="../../x")
    with pytest.raises(ValueError):
        tarefas.argv("transcrever", p, lang="-x")
    with pytest.raises(ValueError):
        tarefas.argv("capa-candidatos", p, n=float("nan"))
    with pytest.raises(ValueError):
        tarefas.argv("capa", p, gancho="x" * 121)
    with pytest.raises(ValueError):
        tarefas.argv("capa", p, gancho="a\x00b")
    with pytest.raises(ValueError):
        tarefas.argv("capa", p, candidato=True, gancho="ok")
    with pytest.raises(ValueError):
        tarefas.argv("desconhecido", p)


def test_argv_real_shapes(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    with pytest.raises(ValueError):  # sem video
        tarefas.argv("transcrever", p)
    (p / "entrada.mp4").write_bytes(b"x")
    a = tarefas.argv("transcrever", p, lang="pt", model="small")
    assert a[:2] == [sys.executable, "-I"] and a[2].endswith("scripts/transcribe.py")
    assert a[3:] == ["--model=small", "--lang=pt", str(p / "entrada.mp4"), str(p / "transcricao.json")]
    assert tarefas.argv("cortes", p)[3:] == ["detect", str(p / "transcricao.json"), str(p / "cortes.json")]
    assert tarefas.argv("final", p)[3:] == [str(p), "final"]
    assert tarefas.argv("capa-candidatos", p, n=4)[3:] == ["video", "--n=4", str(p / "entrada.mp4"), str(p / "capa")]
    assert tarefas.argv("capa-candidatos", p, modo="photo")[3:] == ["photo", str(p / "capa" / "foto.png"), str(p / "capa")]
    c = tarefas.argv("capa", p, candidato=2, gancho="-3 MITOS", area="IR", subtitulo="a\nb")
    assert "--hook=-3 MITOS" in c and "--subtitle=a\nb" in c
    assert c[-3:] == [str(p / "capa" / "candidato-2.png"), str(tarefas.BRAND), str(p / "capa" / "capa.png")]
    with pytest.raises(ValueError):
        tarefas.argv("capa", p)  # sem gancho
    ch = tarefas.argv("instalar-chromium", p)
    assert ch[:2] == ["sh", "-c"] and "playwright install chromium" in ch[2]


def test_http_validation_and_routes(root):
    s = make_server(root, TOKEN, test_mode=True)
    with client(s) as c:
        assert c.request("POST", "/api/projects/a/jobs/cortes", body={"foo": 1}).status == 400
        assert c.request("POST", "/api/projects/a/jobs/cortes", body=[1]).status == 400
        assert c.request("POST", "/api/projects/a/jobs/nada", body={}).status == 404
        assert c.request("POST", "/api/projects/zzz/jobs/cortes", body={}).status == 404
        assert c.request("GET", "/api/projects/a/jobs/cortes").status == 405
        assert c.get("/api/jobs/nao-hex").status == 404
        assert c.get("/api/jobs/" + "0" * 32).status == 404
        assert c.request("POST", "/api/jobs/xyz/cancelar", body={}).status == 404
        # cortes sem transcricao roda de verdade e falha com mensagem em portugues
        r = c.request("POST", "/api/projects/a/jobs/cortes", body={})
        assert r.status == 202
        d = esperar(s.app.jobs, r.json()["job_id"])
        assert d["estado"] == "erro" and d["mensagem"] and "Traceback" not in d["mensagem"]
        assert d["saidas"] == ["cortes.json"]
        # transcrever sem video: 400 em portugues
        r = c.request("POST", "/api/projects/a/jobs/transcrever", body={})
        assert r.status == 400 and "vídeo" in r.json()["erro"]


# ---------------------------------------------------------------- fix round 1
def _vivo(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # zumbi conta como morto
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _espera_arquivo(p, n=100):
    for _ in range(n):
        if p.exists() and p.read_text():
            return int(p.read_text())
        time.sleep(0.05)
    raise AssertionError("pidfile ausente")


def _sumiu(pid, n=100):
    for _ in range(n):
        if not _vivo(pid):
            return True
        time.sleep(0.05)
    return False


def test_cancel_leader_dies_grandchild_ignores_sigterm(root, tmp_path):
    pidfile = tmp_path / "neto.pid"
    neto = ("import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)")
    codigo = (
        "import subprocess,sys,time;"
        f"p=subprocess.Popen([sys.executable,'-c',{neto!r}]);"
        f"open({str(pidfile)!r},'w').write(str(p.pid));time.sleep(60)")
    j = Jobs(root)
    j.GRACA = 0.5
    jid = j.start("a", "x", py(codigo), root / "a")
    pid = _espera_arquivo(pidfile)
    t0 = time.time()
    assert j.cancel(jid)
    d = esperar(j, jid, timeout=10)
    assert d["estado"] == "cancelado" and time.time() - t0 < 8
    assert _sumiu(pid)
    assert j.ativo_em("a") is None


def test_leader_exits_group_child_is_killed(root, tmp_path):
    pidfile = tmp_path / "filho.pid"
    codigo = (
        "import subprocess,sys;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"open({str(pidfile)!r},'w').write(str(p.pid))")
    j = Jobs(root)
    jid = j.start("a", "x", py(codigo), root / "a")
    pid = _espera_arquivo(pidfile)
    d = esperar(j, jid, timeout=10)
    assert d["estado"] == "ok"
    assert _sumiu(pid)


def test_setsid_descendant_holding_pipe_does_not_keep_job_running(root, tmp_path):
    pidfile = tmp_path / "daemon.pid"
    codigo = (
        "import subprocess,sys;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True);"
        f"open({str(pidfile)!r},'w').write(str(p.pid));print('fim',flush=True)")
    j = Jobs(root)
    jid = j.start("a", "x", py(codigo), root / "a")
    pid = _espera_arquivo(pidfile)
    try:
        t0 = time.time()
        d = esperar(j, jid, timeout=10)
        assert d["estado"] == "ok" and time.time() - t0 < 8 and d["log"] == ["fim"]
        assert j.ativo_em("a") is None
    finally:
        os.kill(pid, signal.SIGKILL)


def test_repeated_cancel_starts_one_escalation(root):
    # o processo ignora SIGTERM e GRACA e longa: o job continua "rodando" durante
    # todo o teste (sem depender de tempo), entao cancelar repetido deve dar True
    j = Jobs(root)
    j.GRACA = 60
    jid = j.start("a", "x", py(
        "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "print('pronto',flush=True);time.sleep(60)"), root / "a")
    for _ in range(200):
        if j.get(jid)["log"]:
            break
        time.sleep(0.05)
    assert j.get(jid)["log"] == ["pronto"], j.get(jid)
    pgid = j._procs[jid].pid
    try:
        assert j.cancel(jid) and j.cancel(jid) and j.cancel(jid)
        assert j.get(jid)["estado"] == "rodando"
        n = [t for t in threading.enumerate() if t.name == f"escalar-{jid}"]
        assert len(n) == 1
    finally:
        os.killpg(pgid, signal.SIGKILL)
    assert esperar(j, jid)["estado"] == "cancelado"


def test_giant_line_is_truncated(root):
    j = Jobs(root)
    jid = j.start("a", "x", py(
        "import sys\nfor i in range(20): sys.stdout.write('x'*1000000)\n"
        "sys.stdout.write('\\n'+'erro: '+'y'*5000+'\\n');sys.exit(1)"), root / "a")
    d = esperar(j, jid, timeout=30)
    assert all(len(l) <= 8200 for l in d["log"]) and len(d["log"]) <= 200
    assert d["estado"] == "erro" and len(d["mensagem"]) <= 500


def test_overflow_and_inf_options_are_valueerror(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    for v in (10 ** 400, float("inf"), float("nan"), -10 ** 400, "3", None):
        with pytest.raises(ValueError):
            tarefas.argv("capa-candidatos", p, n=v)


def test_overflow_option_over_http_is_400(root):
    s = make_server(root, TOKEN, test_mode=True)
    with client(s) as c:
        corpo = b'{"n": 1' + b"0" * 400 + b"}"
        r = c.request("POST", "/api/projects/a/jobs/capa-candidatos", body=corpo)
        assert r.status == 400


def _plantar(root, slug, nome_id, dados):
    (root / slug / f".tarefa-{nome_id}.json").write_text(
        dados if isinstance(dados, str) else json.dumps(dados))


def test_hostile_disk_state_is_ignored_or_sanitized(root):
    ok_id = "cd" * 16
    base = {"slug": "a", "tipo": "x", "estado": "ok", "mensagem": "", "log": [],
            "inicio": "2026-01-01T00:00:00", "fim": "2026-01-01T00:00:01", "saidas": []}
    _plantar(root, "a", "ef" * 16, {**base, "id": "x/../../b/zz", "estado": "rodando"})
    _plantar(root, "a", "01" * 16, {**base, "id": ["x"], "estado": "rodando"})
    _plantar(root, "a", "02" * 16, "{nao e json")
    _plantar(root, "a", "03" * 16, "[1,2]")
    _plantar(root, "a", ok_id, {**base, "id": ok_id, "log": "texto", "estado": "hackeado",
                                "saidas": ["../../etc/passwd", "saida/ok.mp4", 5],
                                "mensagem": 7})
    j = Jobs(root)
    assert not (root / "b" / "zz.json").exists()
    assert not any(p.name.startswith(".tarefa-x") for p in root.rglob("*") if p.is_dir())
    rec = j.recentes("a")
    assert [r["id"] for r in rec] == [ok_id]
    d = j.get(ok_id)
    assert d["log"] == [] and d["saidas"] == ["saida/ok.mp4"]
    assert d["estado"] in ("rodando", "ok", "erro", "cancelado") and d["estado"] != "rodando"
    assert d["mensagem"] == ""
    for ruim in ("ef" * 16, "01" * 16):
        with pytest.raises(KeyError):
            j.get(ruim)


def test_cancel_after_process_exit_returns_false_and_keeps_real_code(root):
    j = Jobs(root)
    for _ in range(10):
        jid = j.start("a", "x", py("pass"), root / "a")
        proc = j._procs.get(jid)
        if proc is not None:
            proc.wait()
            assert j.cancel(jid) is False
        d = esperar(j, jid)
        assert d["estado"] == "ok"


def test_argv_every_type_through_mocked_popen(root, monkeypatch):
    p = root / "a"
    (p / "entrada.mp4").write_bytes(b"x")
    chamadas = []

    class FakeProc:
        pid = 99999999
        stdout = io.BytesIO(b"")

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    def fake_popen(*a, **kw):
        chamadas.append((a, kw))
        return FakeProc()

    monkeypatch.setattr(jobsmod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(jobsmod.os, "killpg", lambda *a: None)
    j = Jobs(root)
    usuario = {"transcrever": {"lang": "pt", "model": "small"},
               "capa-candidatos": {"n": 3},
               "capa": {"gancho": "ECHO; rm -rf /", "area": "$(x)", "subtitulo": "`y`"}}
    for tipo in tarefas.TIPOS:
        monkeypatch.setattr(FakeProc, "stdout", io.BytesIO(b""))
        a = tarefas.argv(tipo, p, **usuario.get(tipo, {}))
        esperar(j, j.start("a", tipo, a, p))
    assert len(chamadas) == len(tarefas.TIPOS)
    for (args, kw), tipo in zip(chamadas, tarefas.TIPOS):
        assert isinstance(args[0], list) and not kw.get("shell")
        assert kw["start_new_session"] is True
        if tipo == "instalar-chromium":
            assert args[0] == ["sh", "-c", "npm i -g playwright && npx playwright install chromium"]
        else:
            assert args[0][0] == sys.executable and "sh" not in args[0][:1]
            assert not any(x == "-c" for x in args[0])


def test_entrada_follows_project_rule(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "entrada.txt").write_bytes(b"x")
    (p / "entrada.mp4.bak").write_bytes(b"x")
    alvo = tmp_path / "fora.mp4"
    alvo.write_bytes(b"x")
    (p / "entrada.mov").symlink_to(alvo)
    with pytest.raises(ValueError):
        tarefas.argv("transcrever", p)
    (p / "entrada.webm").write_bytes(b"x")
    assert tarefas.argv("transcrever", p)[-2].endswith("entrada.webm")


def test_upload_blocked_while_job_running(root, monkeypatch):
    s = make_server(root, TOKEN, test_mode=True)
    monkeypatch.setattr(tarefas, "argv", lambda tipo, p, **o: py("import time; time.sleep(30)"))
    with client(s) as c:
        jid = c.request("POST", "/api/projects/a/jobs/cortes", body={}).json()["job_id"]
        r = c.request("PUT", "/api/projects/a/video", body=b"abc",
                      headers={"X-Filename": "v.mp4"})
        assert r.status == 409 and "tarefa rodando" in r.json()["erro"]
        s.app.jobs.cancel(jid)
        esperar(s.app.jobs, jid)


def test_gravar_failure_makes_error_job_not_running(root, monkeypatch):
    import common
    def boom(*a, **k):
        raise OSError("disco cheio")
    monkeypatch.setattr(jobsmod.common, "write_json_atomic", boom)
    j = Jobs(root)
    jid = j.start("a", "x", py("import time; time.sleep(30)"), root / "a")
    d = j.get(jid)
    assert d["estado"] == "erro" and j.ativo_em("a") is None


def test_shutdown_kills_running_jobs(root, tmp_path):
    pidfile = tmp_path / "p.pid"
    j = Jobs(root)
    j.GRACA = 0.5
    jid = j.start("a", "x", py(
        f"import os,time;open({str(pidfile)!r},'w').write(str(os.getpid()));time.sleep(60)"),
        root / "a")
    pid = _espera_arquivo(pidfile)
    j.shutdown()
    assert _sumiu(pid) and j.get(jid)["estado"] != "rodando"


def test_server_close_shuts_jobs_down(root, tmp_path, monkeypatch):
    s = make_server(root, TOKEN, test_mode=True)
    pidfile = tmp_path / "q.pid"
    monkeypatch.setattr(tarefas, "argv", lambda tipo, p, **o: py(
        f"import os,time;open({str(pidfile)!r},'w').write(str(os.getpid()));time.sleep(60)"))
    with client(s) as c:
        c.request("POST", "/api/projects/a/jobs/cortes", body={})
        pid = _espera_arquivo(pidfile)
    assert _sumiu(pid)


def test_message_hides_project_path(root):
    j = Jobs(root)
    proj = root / "a"
    jid = j.start("a", "x", py(f"import sys;print('erro: falta {proj}/transcricao.json');sys.exit(1)"),
                  proj, ocultar=proj)
    d = esperar(j, jid)
    assert d["mensagem"] == "falta <projeto>/transcricao.json"


def test_log_published_when_output_goes_idle(root):
    # duas escritas separadas por pouco tempo: a 2a cai no limite de frequencia
    # e o log nao pode ficar defasado enquanto o processo segue ocioso
    j = Jobs(root)
    jid = j.start("a", "x", py(
        "import sys,time;sys.stdout.write('pronto');sys.stdout.flush();time.sleep(0.05);"
        "sys.stdout.write('\\n');sys.stdout.flush();time.sleep(60)"), root / "a")
    for _ in range(100):
        if j.get(jid)["log"] == ["pronto"]:
            break
        time.sleep(0.05)
    try:
        assert j.get(jid)["log"] == ["pronto"]
    finally:
        os.killpg(j._procs[jid].pid, signal.SIGKILL)
    esperar(j, jid)
