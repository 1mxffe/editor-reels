"""Projetos do app: slugs, caminhos permitidos e estado das etapas.

So le/escreve dentro de ``projects/``. A escrita atomica reutiliza
``scripts/common.py`` (unico import de scripts/ permitido em app/).
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import common  # noqa: E402

SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SLUG_MAX = 40
ETAPAS = ("video", "transcricao", "cortes", "legendas", "estilo",
          "preview", "graficos", "capa", "final")
# pastas servidas por resolve_file (alem de entrada.*)
PASTAS_PUBLICAS = ("saida", "capa", "materiais", "quadros")
MAX_COMPONENTES = 4
EXT_VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")


def _eh_entrada(nome: str) -> bool:
    return nome.startswith("entrada.") and nome[len("entrada"):] in EXT_VIDEO


class ProjectsError(Exception):
    """Erro de projeto com mensagem em portugues, pronta para o usuario."""


def slugify(name: str) -> str:
    texto = unicodedata.normalize("NFKD", str(name))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:SLUG_MAX].strip("-")
    if not slug:
        raise ProjectsError("nome inválido: use letras ou números")
    return slug


def _ler_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Projects:
    def __init__(self, root: Path):
        self.root = Path(root)

    # -- listagem e criacao ------------------------------------------------
    def _meta(self, d: Path) -> dict:
        meta = _ler_json(d / "projeto.json")
        if not isinstance(meta, dict):
            meta = {}
        nome = meta.get("nome")
        criado = meta.get("criado")
        if not isinstance(criado, str) or not criado:
            try:
                criado = datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds")
            except OSError:
                criado = ""
        return {"slug": d.name, "nome": nome if isinstance(nome, str) and nome else d.name,
                "criado": criado}

    def _dir_ok(self, d: Path) -> bool:
        """Pasta de projeto de verdade: nao e link e esta direto em root."""
        try:
            return (d.is_dir() and not d.is_symlink()
                    and d.resolve().parent == self.root.resolve())
        except (OSError, RuntimeError):
            return False

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        itens = [self._meta(d) for d in self.root.iterdir()
                 if SLUG_RE.fullmatch(d.name) and len(d.name) <= SLUG_MAX and self._dir_ok(d)]
        itens.sort(key=lambda p: (p["criado"], p["slug"]), reverse=True)
        return itens

    def create(self, name: str) -> dict:
        base = slugify(name)
        self.root.mkdir(parents=True, exist_ok=True)
        slug, n = base, 1
        while True:
            try:
                (self.root / slug).mkdir()
                break
            except FileExistsError:
                n += 1
                sufixo = f"-{n}"
                slug = base[:SLUG_MAX - len(sufixo)].rstrip("-") + sufixo
        criado = datetime.now().isoformat(timespec="seconds")
        nome = str(name).strip()
        common.write_json_atomic(self.root / slug / "projeto.json", {"nome": nome, "criado": criado})
        return {"slug": slug, "nome": nome, "criado": criado}

    # -- caminhos ----------------------------------------------------------
    def path(self, slug: str) -> Path:
        if (not isinstance(slug, str) or len(slug) > SLUG_MAX
                or not SLUG_RE.fullmatch(slug)):
            raise ProjectsError("projeto inválido")
        d = self.root / slug
        if d.is_symlink() or not self._dir_ok(d):
            if d.is_symlink() or d.exists():
                raise ProjectsError("projeto inválido")
            raise ProjectsError("projeto não existe")
        return d

    def resolve_file(self, slug: str, rel: str) -> Path:
        base = self.path(slug).resolve()
        if (not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel
                or rel.startswith("/")):
            raise ProjectsError("arquivo não permitido")
        partes = rel.split("/")
        if (len(partes) > MAX_COMPONENTES
                or any(p in ("", "..") or p.startswith(".") for p in partes)
                or any(len(p) > 255 or len(p.encode("utf-8", "replace")) > 255 for p in partes)):
            raise ProjectsError("arquivo não permitido")
        if len(partes) == 1:
            permitido = _eh_entrada(partes[0])
        else:
            permitido = partes[0] in PASTAS_PUBLICAS
        if not permitido:
            raise ProjectsError("arquivo não permitido")
        try:
            alvo = (base / rel).resolve()
            if base not in alvo.parents:
                raise ProjectsError("arquivo não permitido")
            if not alvo.is_file():
                raise ProjectsError("arquivo não encontrado")
        except (OSError, RuntimeError, ValueError):
            raise ProjectsError("arquivo não encontrado") from None
        return alvo

    # -- estado ------------------------------------------------------------
    def state(self, slug: str) -> dict:
        d = self.path(slug)

        def tem(rel: str) -> bool:
            return (d / rel).is_file()

        entradas = sorted(p.name for p in d.glob("entrada.*")
                          if p.is_file() and _eh_entrada(p.name))
        etapas_json = _ler_json(d / "etapas.json")
        legendas_ok = isinstance(etapas_json, dict) and etapas_json.get("legendas") is True
        duracao = None
        trans = _ler_json(d / "transcricao.json")
        if isinstance(trans, dict):
            dur = trans.get("duration")
            if common.is_num(dur) and dur >= 0:
                duracao = float(dur)
        feito = {
            "video": bool(entradas),
            "transcricao": tem("transcricao.json"),
            "cortes": tem("cortes.json"),
            "legendas": tem("legendas.json") or legendas_ok,
            "estilo": tem("estilo.json"),
            "preview": tem("saida/preview.mp4"),
            "graficos": tem("graficos.json"),
            "capa": tem("capa/capa.png"),
            "final": tem("saida/final.mp4"),
        }
        arquivos = {
            "entrada": entradas[0] if entradas else None,
            "transcricao": "transcricao.json" if feito["transcricao"] else None,
            "cortes": "cortes.json" if feito["cortes"] else None,
            "legendas": "legendas.json" if tem("legendas.json") else None,
            "estilo": "estilo.json" if feito["estilo"] else None,
            "preview": "saida/preview.mp4" if feito["preview"] else None,
            "graficos": "graficos.json" if feito["graficos"] else None,
            "capa": "capa/capa.png" if feito["capa"] else None,
            "final": "saida/final.mp4" if feito["final"] else None,
        }
        meta = self._meta(d)
        return {"slug": slug, "nome": meta["nome"], "duracao": duracao,
                "etapas": {k: ("pronto" if feito[k] else "pendente") for k in ETAPAS},
                # so o "Confirmar legendas" (etapas.json); legendas.json sozinho nao conta
                "legendas_confirmadas": legendas_ok,
                "arquivos": arquivos}
