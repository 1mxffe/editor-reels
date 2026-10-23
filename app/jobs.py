"""Tarefas em segundo plano: no maximo uma rodando por projeto.

Estado em ``projects/<slug>/.tarefa-<id>.json`` (gravacao atomica). Jobs
``rodando`` que sobram de uma execucao anterior viram ``erro`` ao instanciar.

O fim de uma tarefa e decidido pela saida do processo lider (``wait``), nunca
pelo EOF do pipe: ao sair, o grupo de processos inteiro e encerrado
(SIGTERM, depois SIGKILL) e a leitura do log e abandonada apos um tempo curto.
"""
from __future__ import annotations

import collections
import json
import os
import re
import select
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import common  # noqa: E402

ID_RE = re.compile(r"[0-9a-f]{32}")
ARQ_RE = re.compile(r"\.tarefa-([0-9a-f]{32})\.json")
ERRO_RE = re.compile(r"\s*erro:\s*(.*)", re.IGNORECASE | re.DOTALL)
MAX_LOG = 200
MAX_LINHA = 8 * 1024
MAX_MENSAGEM = 500
MAX_GUARDADAS = 20
ESTADOS = ("rodando", "ok", "erro", "cancelado")


class JobBusy(Exception):
    """Ja existe uma tarefa rodando neste projeto."""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _relativo_ok(rel) -> bool:
    return (isinstance(rel, str) and bool(rel) and len(rel) <= 300
            and not rel.startswith("/") and "\\" not in rel and "\x00" not in rel
            and ".." not in rel.split("/"))


def _grupo_vivo(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _sinal(pgid: int, sig) -> None:
    try:
        os.killpg(pgid, sig)
    except OSError:
        pass


def _encerrar_grupo(pgid: int, graca: float) -> None:
    """SIGTERM no grupo; se algum membro ainda existir apos ``graca``, SIGKILL."""
    if not _grupo_vivo(pgid):
        return
    _sinal(pgid, signal.SIGTERM)
    fim = time.monotonic() + graca
    while time.monotonic() < fim and _grupo_vivo(pgid):
        time.sleep(0.02)
    if _grupo_vivo(pgid):
        _sinal(pgid, signal.SIGKILL)


class Jobs:
    GRACA = 5.0          # cancelar: segundos entre SIGTERM e SIGKILL
    GRACA_FIM = 2.0      # apos o lider sair: idem, para os descendentes
    ESPERA_LEITOR = 2.0  # tempo para drenar o pipe depois do fim

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._cancelados: set[str] = set()
        self._ocultar: dict[str, list[str]] = {}
        self._marcar_orfaos()

    # -- disco ------------------------------------------------------------
    def _arquivo(self, slug: str, job_id: str) -> Path:
        return self.root / slug / f".tarefa-{job_id}.json"

    def _gravar(self, job: dict) -> bool:
        if not ID_RE.fullmatch(str(job.get("id"))):
            return False
        try:
            common.write_json_atomic(self._arquivo(job["slug"], job["id"]), job)
            return True
        except (OSError, ValueError, TypeError):
            return False

    @staticmethod
    def _str(v, limite, padrao=""):
        return v[:limite] if isinstance(v, str) else padrao

    def _ler(self, slug: str, path: Path):
        """Le e saneia um .tarefa-<id>.json; None se invalido."""
        m = ARQ_RE.fullmatch(path.name)
        if not m:
            return None
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                return None
            dados = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            return None
        if not isinstance(dados, dict) or dados.get("id") != m.group(1):
            return None
        log = dados.get("log")
        log = [x[:MAX_LINHA + 1] for x in log if isinstance(x, str)][-MAX_LOG:] \
            if isinstance(log, list) else []
        saidas = dados.get("saidas")
        saidas = [x for x in saidas if _relativo_ok(x)][:50] if isinstance(saidas, list) else []
        estado = dados.get("estado")
        return {"id": m.group(1), "slug": slug,
                "tipo": self._str(dados.get("tipo"), 40),
                "estado": estado if estado in ESTADOS else "erro",
                "mensagem": self._str(dados.get("mensagem"), MAX_MENSAGEM),
                "log": log,
                "inicio": self._str(dados.get("inicio"), 40),
                "fim": dados.get("fim") if isinstance(dados.get("fim"), str) else None,
                "saidas": saidas}

    def _arquivos(self, slug: str | None = None):
        try:
            pastas = ([self.root / slug] if slug else
                      [d for d in self.root.iterdir() if d.is_dir() and not d.is_symlink()])
        except OSError:
            return
        for d in pastas:
            if d.is_symlink():
                continue
            try:
                for p in d.iterdir():
                    if ARQ_RE.fullmatch(p.name) and p.is_file() and not p.is_symlink():
                        yield d.name, p
            except OSError:
                continue

    def _marcar_orfaos(self) -> None:
        for slug, p in self._arquivos():
            job = self._ler(slug, p)
            if job and job["estado"] == "rodando":
                job.update(estado="erro", mensagem="interrompida", fim=_agora())
                self._gravar(job)

    def _podar(self, slug: str) -> None:
        itens = {}
        for _, p in self._arquivos(slug):
            job = self._ler(slug, p)
            if job and job["estado"] != "rodando":
                itens[job["id"]] = (job["inicio"], p)
        with self._lock:
            for jid, j in self._jobs.items():
                if j["slug"] == slug and j["estado"] != "rodando":
                    itens.setdefault(jid, (j["inicio"], None))
            velhos = sorted((v[0], jid, v[1]) for jid, v in itens.items())[:-MAX_GUARDADAS]
            for _, jid, _p in velhos:
                self._jobs.pop(jid, None)
        for _, jid, p in velhos:
            if p is not None:
                try:
                    p.unlink()
                except OSError:
                    pass

    # -- API ----------------------------------------------------------------
    def start(self, slug: str, tipo: str, argv: list[str], cwd: Path,
              saidas=(), ocultar=None) -> str:
        saidas = [s for s in saidas if _relativo_ok(s)]
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "slug": slug, "tipo": tipo, "estado": "rodando",
               "mensagem": "", "log": [], "inicio": _agora(), "fim": None,
               "saidas": saidas}
        with self._lock:  # reserva atomica do projeto; I/O fica fora do lock
            if self._ativo_unlocked(slug):
                raise JobBusy("já existe uma tarefa rodando neste projeto")
            self._jobs[job_id] = job
            if ocultar:
                self._ocultar[job_id] = sorted({str(ocultar), str(Path(ocultar).resolve())},
                                               key=len, reverse=True)
        if not self._gravar(job):
            self._falhar(job_id, "não foi possível registrar a tarefa no disco")
            return job_id
        try:
            proc = subprocess.Popen(
                list(argv), cwd=str(cwd), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, bufsize=0, start_new_session=True)
        except (OSError, ValueError) as e:
            self._falhar(job_id, ("programa não encontrado: " + str(argv[0])
                                  if isinstance(e, FileNotFoundError)
                                  else "não foi possível iniciar a tarefa"))
            return job_id
        with self._lock:
            self._procs[job_id] = proc
        threading.Thread(target=self._executar, args=(job_id, proc),
                         name=f"tarefa-{job_id}", daemon=True).start()
        return job_id

    def _falhar(self, job_id: str, mensagem: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(estado="erro", mensagem=mensagem, fim=_agora())
            copia = self._copia(job)
            self._ocultar.pop(job_id, None)
        self._gravar(copia)
        self._podar(copia["slug"])

    def _ativo_unlocked(self, slug: str):
        for j in self._jobs.values():
            if j["slug"] == slug and j["estado"] == "rodando":
                return j["id"]
        return None

    def ativo_em(self, slug: str):
        with self._lock:
            return self._ativo_unlocked(slug)

    def get(self, job_id: str) -> dict:
        if not isinstance(job_id, str) or not ID_RE.fullmatch(job_id):
            raise KeyError(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return self._copia(job)
        for slug, p in self._arquivos():
            if p.name == f".tarefa-{job_id}.json":
                dados = self._ler(slug, p)
                if dados:
                    return dados
        raise KeyError(job_id)

    @staticmethod
    def _copia(job: dict) -> dict:
        c = dict(job)
        c["log"] = list(job["log"])
        c["saidas"] = list(job["saidas"])
        return c

    def recentes(self, slug: str) -> list[dict]:
        vistos: dict[str, dict] = {}
        for _, p in self._arquivos(slug):
            dados = self._ler(slug, p)
            if dados:
                vistos[dados["id"]] = dados
        with self._lock:
            for jid, j in self._jobs.items():
                if j["slug"] == slug:
                    vistos[jid] = self._copia(j)
        itens = sorted(vistos.values(), key=lambda j: j["inicio"], reverse=True)
        return itens[:MAX_GUARDADAS]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            proc = self._procs.get(job_id)
            if job is None or proc is None or job["estado"] != "rodando":
                return False
            if job_id in self._cancelados:
                return True  # cancelamento ja em curso
            if proc.poll() is not None:  # ja saiu: vale o codigo real
                return False
            self._cancelados.add(job_id)
            _sinal(proc.pid, signal.SIGTERM)  # start_new_session: pgid == pid
        threading.Thread(target=self._escalar, args=(proc.pid,),
                         name=f"escalar-{job_id}", daemon=True).start()
        return True

    def _escalar(self, pgid: int) -> None:
        fim = time.monotonic() + self.GRACA
        while time.monotonic() < fim and _grupo_vivo(pgid):
            time.sleep(0.02)
        if _grupo_vivo(pgid):  # qualquer membro do grupo, nao so o lider
            _sinal(pgid, signal.SIGKILL)

    def shutdown(self) -> None:
        """Cancela tudo o que esta rodando e espera o fim (limitado)."""
        with self._lock:
            ids = [i for i, j in self._jobs.items() if j["estado"] == "rodando"]
        for i in ids:
            self.cancel(i)
        fim = time.monotonic() + self.GRACA + self.GRACA_FIM + self.ESPERA_LEITOR + 1
        while time.monotonic() < fim:
            with self._lock:
                if not any(self._jobs[i]["estado"] == "rodando" for i in ids
                           if i in self._jobs):
                    return
            time.sleep(0.02)

    # -- execucao -----------------------------------------------------------
    def _executar(self, job_id: str, proc) -> None:
        log = collections.deque(maxlen=MAX_LOG)
        estado = {"erro": None, "push": 0.0}
        parar = threading.Event()

        def publicar(forcar=False):
            agora = time.monotonic()
            if forcar or agora - estado["push"] > 0.2:
                estado["push"] = agora
                with self._lock:
                    if job_id in self._jobs:
                        self._jobs[job_id]["log"] = list(log)

        def leitor():
            atual = bytearray()
            corte = False

            def emitir():
                nonlocal atual, corte
                texto = atual.decode("utf-8", errors="replace").rstrip("\r")
                if corte:
                    texto += "…"
                log.append(texto)
                m = ERRO_RE.fullmatch(texto)
                if m and m.group(1).strip():
                    estado["erro"] = m.group(1).strip()
                atual, corte = bytearray(), False

            def alimentar(dados):
                nonlocal corte
                for i, parte in enumerate(dados.split(b"\n")):
                    if i > 0:
                        emitir()
                    sobra = MAX_LINHA - len(atual)
                    if len(parte) > sobra:
                        atual.extend(parte[:sobra])
                        corte = True
                    else:
                        atual.extend(parte)
                publicar()

            try:
                fd = proc.stdout.fileno()
            except (AttributeError, OSError, ValueError):
                fd = None
            try:
                while not parar.is_set():
                    if fd is not None:
                        pronto, _, _ = select.select([fd], [], [], 0.1)
                        if not pronto:
                            continue
                    dados = proc.stdout.read(65536)
                    if not dados:
                        break
                    alimentar(dados)
            except (OSError, ValueError):
                pass
            if atual:
                emitir()

        t = threading.Thread(target=leitor, name=f"leitor-{job_id}", daemon=True)
        t.start()
        try:
            codigo = proc.wait()
        except Exception:
            codigo = -1
        # fim decidido pelo lider: encerra o resto do grupo e drena o pipe
        _encerrar_grupo(proc.pid, self.GRACA_FIM)
        t.join(self.ESPERA_LEITOR)
        parar.set()
        t.join(1.0)
        try:
            proc.stdout.close()
        except Exception:
            pass
        publicar(forcar=True)
        self._finalizar(job_id, codigo, log, estado["erro"])

    def _finalizar(self, job_id: str, codigo: int, log, ultimo_erro) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["log"] = list(log)
            job["fim"] = _agora()
            if job_id in self._cancelados:
                job["estado"], job["mensagem"] = "cancelado", "tarefa cancelada"
            elif codigo == 0:
                job["estado"], job["mensagem"] = "ok", ""
            else:
                msg = ultimo_erro or f"a tarefa falhou (código {codigo})"
                for trecho in self._ocultar.get(job_id, []):
                    msg = msg.replace(trecho, "<projeto>")
                job["estado"], job["mensagem"] = "erro", msg[:MAX_MENSAGEM]
            self._procs.pop(job_id, None)
            self._cancelados.discard(job_id)
            self._ocultar.pop(job_id, None)
            copia = self._copia(job)
        self._gravar(copia)
        self._podar(copia["slug"])
