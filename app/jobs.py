"""Tarefas em segundo plano: no maximo uma rodando por projeto.

Estado em ``projects/<slug>/.tarefa-<id>.json`` (gravacao atomica). Jobs
``rodando`` que sobram de uma execucao anterior viram ``erro`` ao instanciar.
"""
from __future__ import annotations

import collections
import json
import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import common  # noqa: E402

ID_RE = re.compile(r"[0-9a-f]{32}")
ARQ_RE = re.compile(r"\.tarefa-([0-9a-f]{32})\.json")
MAX_LOG = 200
MAX_GUARDADAS = 20
ERRO_RE = re.compile(r"\s*erro:\s*(.*)", re.IGNORECASE)


class JobBusy(Exception):
    """Ja existe uma tarefa rodando neste projeto."""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _relativo_ok(rel) -> bool:
    return (isinstance(rel, str) and rel and not rel.startswith("/")
            and "\\" not in rel and ".." not in rel.split("/"))


class Jobs:
    GRACA = 5.0  # segundos entre SIGTERM e SIGKILL

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._cancelados: set[str] = set()
        self._marcar_orfaos()

    # -- disco ------------------------------------------------------------
    def _arquivo(self, slug: str, job_id: str) -> Path:
        return self.root / slug / f".tarefa-{job_id}.json"

    def _gravar(self, job: dict) -> None:
        try:
            common.write_json_atomic(self._arquivo(job["slug"], job["id"]), job)
        except (OSError, ValueError):
            pass

    def _ler(self, path: Path):
        try:
            dados = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return dados if isinstance(dados, dict) and "id" in dados else None

    def _arquivos(self, slug: str | None = None):
        try:
            pastas = ([self.root / slug] if slug else
                      [d for d in self.root.iterdir() if d.is_dir() and not d.is_symlink()])
        except OSError:
            return
        for d in pastas:
            try:
                for p in d.iterdir():
                    if ARQ_RE.fullmatch(p.name) and p.is_file() and not p.is_symlink():
                        yield d.name, p
            except OSError:
                continue

    def _marcar_orfaos(self) -> None:
        for slug, p in self._arquivos():
            job = self._ler(p)
            if job and job.get("estado") == "rodando":
                job.update(estado="erro", mensagem="interrompida", fim=_agora())
                job["slug"] = slug
                self._gravar(job)

    def _podar(self, slug: str) -> None:
        itens = []
        for _, p in self._arquivos(slug):
            job = self._ler(p)
            if job and job.get("estado") != "rodando":
                itens.append((str(job.get("inicio", "")), p, job["id"]))
        itens.sort()
        for _, p, jid in itens[:-MAX_GUARDADAS]:
            try:
                p.unlink()
            except OSError:
                pass
            with self._lock:
                self._jobs.pop(jid, None)

    # -- API ----------------------------------------------------------------
    def start(self, slug: str, tipo: str, argv: list[str], cwd: Path,
              saidas=()) -> str:
        saidas = [s for s in saidas if _relativo_ok(s)]
        with self._lock:
            if self._ativo_unlocked(slug):
                raise JobBusy("já existe uma tarefa rodando neste projeto")
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "slug": slug, "tipo": tipo, "estado": "rodando",
                   "mensagem": "", "log": [], "inicio": _agora(), "fim": None,
                   "saidas": saidas}
            try:
                proc = subprocess.Popen(
                    list(argv), cwd=str(cwd), stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                    errors="replace", start_new_session=True)
            except (OSError, ValueError) as e:
                job.update(estado="erro", fim=_agora(),
                           mensagem=("programa não encontrado: " + str(argv[0])
                                     if isinstance(e, FileNotFoundError)
                                     else "não foi possível iniciar a tarefa"))
                self._jobs[job_id] = job
                self._gravar(job)
                job = None
            else:
                self._jobs[job_id] = job
                self._procs[job_id] = proc
                self._gravar(job)
        if job is None:
            self._podar(slug)
            return job_id
        threading.Thread(target=self._executar, args=(job_id, proc),
                         daemon=True).start()
        return job_id

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
                dados = self._ler(p)
                if dados:
                    dados["slug"] = slug
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
            dados = self._ler(p)
            if dados:
                dados["slug"] = slug
                vistos[dados["id"]] = dados
        with self._lock:
            for jid, j in self._jobs.items():
                if j["slug"] == slug:
                    vistos[jid] = self._copia(j)
        itens = sorted(vistos.values(), key=lambda j: str(j.get("inicio", "")),
                       reverse=True)
        return itens[:MAX_GUARDADAS]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            proc = self._procs.get(job_id)
            if job is None or proc is None or job["estado"] != "rodando":
                return False
            self._cancelados.add(job_id)
        self._sinal(proc, signal.SIGTERM)
        threading.Thread(target=self._escalar, args=(proc,), daemon=True).start()
        return True

    @staticmethod
    def _sinal(proc, sig) -> None:
        try:
            os.killpg(proc.pid, sig)  # start_new_session: pgid == pid
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _escalar(self, proc) -> None:
        try:
            proc.wait(timeout=self.GRACA)
        except subprocess.TimeoutExpired:
            if proc.poll() is None:  # ainda vivo apos a graca: mata o grupo todo
                self._sinal(proc, signal.SIGKILL)

    # -- execucao -----------------------------------------------------------
    def _executar(self, job_id: str, proc) -> None:
        log = collections.deque(maxlen=MAX_LOG)
        ultimo_erro = None
        try:
            for linha in proc.stdout:
                linha = linha.rstrip("\r\n")
                log.append(linha)
                m = ERRO_RE.fullmatch(linha)
                if m and m.group(1).strip():
                    ultimo_erro = m.group(1).strip()
                with self._lock:
                    self._jobs[job_id]["log"] = list(log)
        except (OSError, ValueError):
            pass
        try:
            codigo = proc.wait()
        except Exception:
            codigo = -1
        with self._lock:
            job = self._jobs[job_id]
            cancelado = job_id in self._cancelados
            job["log"] = list(log)
            job["fim"] = _agora()
            if cancelado:
                job["estado"], job["mensagem"] = "cancelado", "tarefa cancelada"
            elif codigo == 0:
                job["estado"], job["mensagem"] = "ok", ""
            else:
                job["estado"] = "erro"
                job["mensagem"] = ultimo_erro or f"a tarefa falhou (código {codigo})"
            self._procs.pop(job_id, None)
            self._cancelados.discard(job_id)
            copia = self._copia(job)
        self._gravar(copia)
        self._podar(copia["slug"])
