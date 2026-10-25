"""Monta o argv real de cada tipo de tarefa e valida as opcoes do usuario.

Todos os caminhos vem de ``project`` (resolvido por Projects.path) e do
repositorio; do usuario so entram valores validados (numeros, enums, texto
curto). Texto livre vai sempre na forma ``--opcao=valor``, entao nenhum
argumento derivado do usuario comeca com ``-`` sozinho.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from projects import EXT_VIDEO

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
BRAND = REPO / "brand" / "brand.json"
FALSO = REPO / "tests" / "fixtures_app.py"  # transcricao fixa: so em modo de teste

TIPOS = ("transcrever", "cortes", "preview", "final",
         "capa-candidatos", "capa", "instalar-chromium")

SAIDAS = {
    "transcrever": ["transcricao.json"],
    "cortes": ["cortes.json"],
    "preview": ["saida/preview.mp4"],
    "final": ["saida/final.mp4"],
    "capa-candidatos": [],
    "capa": ["capa/capa.png"],
    "instalar-chromium": [],
}

MODELOS = ("tiny", "base", "small", "medium", "large", "large-v2", "large-v3")
LANG_RE = re.compile(r"[a-z]{2,3}")
MAX_TEXTO = 120


def saidas(tipo: str) -> list[str]:
    return list(SAIDAS.get(tipo, []))


def _inteiro(nome, valor, minimo, maximo):
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)  # 3.0 vale 3; inf/nan nao chegam aqui (is_integer False)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f"'{nome}' deve ser um número inteiro")
    if not minimo <= valor <= maximo:
        raise ValueError(f"'{nome}' deve estar entre {minimo} e {maximo}")
    return valor


def _texto(nome, valor, permitir_quebra=False):
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"'{nome}' deve ser um texto não vazio")
    if len(valor) > MAX_TEXTO:
        raise ValueError(f"'{nome}' longo demais (máximo {MAX_TEXTO} caracteres)")
    for c in valor:
        if ord(c) < 32 or ord(c) == 127:
            if permitir_quebra and c == "\n":
                continue
            raise ValueError(f"'{nome}' contém caracteres inválidos")
    return valor


def _enum(nome, valor, validos):
    if not isinstance(valor, str) or valor not in validos:
        raise ValueError(f"'{nome}' inválido; use " + ", ".join(validos))
    return valor


def _lang(nome, valor):
    if not isinstance(valor, str) or not LANG_RE.fullmatch(valor):
        raise ValueError(f"'{nome}' inválido; use um código como pt ou en")
    return valor


# nome de arquivo simples (sem pasta, sem comecar por '.' ou '-')
NOME_ARQ = r"[A-Za-z0-9\u00C0-\u024F][A-Za-z0-9\u00C0-\u024F()._-]{0,199}"
FOTO_RE = re.compile(r"materiais/(" + NOME_ARQ + r")\.(png|jpe?g|webp)", re.IGNORECASE)
QUADRO_RE = re.compile(r"(capa|quadros)/(" + NOME_ARQ + r")\.(png|jpe?g|webp)", re.IGNORECASE)


def _foto(nome, valor):
    """Foto da capa: so uma imagem direto em materiais/ (png, jpg ou webp)."""
    if not isinstance(valor, str) or not FOTO_RE.fullmatch(valor) or ".." in valor:
        raise ValueError("'foto' deve ser uma imagem dos materiais (png, jpg ou webp)")
    return valor


def _quadro(nome, valor):
    """Quadro escolhido para a capa: imagem em capa/ (menos a propria capa) ou quadros/."""
    if (not isinstance(valor, str) or not QUADRO_RE.fullmatch(valor) or ".." in valor
            or valor.lower().startswith("capa/capa.")):
        raise ValueError("'quadro' deve ser um dos quadros da capa (capa/... ou quadros/...)")
    return valor


# tipo -> {chave: validador(nome, valor)}
OPCOES = {
    "transcrever": {"lang": _lang, "model": lambda n, v: _enum(n, v, MODELOS)},
    "cortes": {},
    "preview": {},
    "final": {},
    "capa-candidatos": {"modo": lambda n, v: _enum(n, v, ("video", "foto")),
                        "foto": _foto,
                        "n": lambda n, v: _inteiro(n, v, 1, 8)},
    "capa": {"quadro": _quadro,
             "gancho": _texto,
             "area": _texto,
             "subtitulo": lambda n, v: _texto(n, v, permitir_quebra=True)},
    "instalar-chromium": {},
}


def validar(tipo: str, opcoes: dict) -> dict:
    if tipo not in OPCOES:
        raise ValueError("tipo de tarefa desconhecido")
    if not isinstance(opcoes, dict):
        raise ValueError("as opções devem ser um objeto JSON")
    validos = OPCOES[tipo]
    limpo = {}
    for chave, valor in opcoes.items():
        if chave not in validos:
            raise ValueError(f"opção desconhecida: {str(chave)[:40]!r}")
        limpo[chave] = validos[chave](chave, valor)
    return limpo


def _py(script: str) -> list[str]:
    return [sys.executable, "-I", str(SCRIPTS / script)]


def _entrada(project: Path) -> Path:
    for p in sorted(project.glob("entrada.*")):
        if p.suffix in EXT_VIDEO and p.is_file() and not p.is_symlink():
            return p
    raise ValueError("envie o vídeo antes de continuar")


def _arquivo_do_projeto(project: Path, rel: str, onde: str) -> Path:
    """Caminho de ``rel`` (ja validado) se for arquivo de verdade dentro do projeto."""
    alvo = project / rel
    try:
        ok = (alvo.is_file() and not alvo.is_symlink()
              and alvo.resolve().parent == (project / rel.split("/")[0]).resolve()
              and (project / rel.split("/")[0]).resolve().parent == project.resolve())
    except (OSError, RuntimeError):
        ok = False
    if not ok:
        raise ValueError(onde)
    return alvo


def argv(tipo: str, project: Path, *, falso: bool = False, marca: Path | None = None,
         **opcoes) -> list[str]:
    """argv da tarefa. ``falso=True`` (so o servidor em modo de teste decide isso, ver
    ``server.transcricao_falsa``) troca o Whisper pela transcricao fixa dos testes.
    ``marca``: brand.json usado pela capa (padrao: brand/brand.json do repositorio)."""
    opts = validar(tipo, opcoes)
    project = Path(project)
    if tipo == "transcrever" and falso:
        return [sys.executable, "-I", str(FALSO), "transcrever",
                str(_entrada(project)), str(project / "transcricao.json")]
    if tipo == "transcrever":
        cmd = _py("transcribe.py")
        if "model" in opts:
            cmd.append(f"--model={opts['model']}")
        if "lang" in opts:
            cmd.append(f"--lang={opts['lang']}")
        return cmd + [str(_entrada(project)), str(project / "transcricao.json")]
    if tipo == "cortes":
        return _py("cut.py") + ["detect", str(project / "transcricao.json"),
                                str(project / "cortes.json")]
    if tipo in ("preview", "final"):
        return _py("render.py") + [str(project), tipo]
    if tipo == "capa-candidatos":
        modo = opts.get("modo", "video")
        saida = str(project / "capa")
        if modo == "foto":
            if "foto" not in opts:
                raise ValueError("escolha a foto dos materiais")
            foto = _arquivo_do_projeto(project, opts["foto"], "a foto escolhida não está nos materiais")
            return _py("cover_frames.py") + ["photo", str(foto), saida]
        if "foto" in opts:
            raise ValueError("'foto' só vale com o modo foto")
        cmd = _py("cover_frames.py") + ["video"]
        if "n" in opts:
            cmd.append(f"--n={opts['n']}")
        return cmd + [str(_entrada(project)), saida]
    if tipo == "capa":
        if "quadro" not in opts:
            raise ValueError("escolha o quadro da capa")
        if "gancho" not in opts:
            raise ValueError("informe o gancho da capa")
        quadro = _arquivo_do_projeto(project, opts["quadro"], "o quadro escolhido não existe mais; procure os quadros de novo")
        cmd = _py("cover_compose.py") + [f"--hook={opts['gancho']}"]
        if "area" in opts:
            cmd.append(f"--area={opts['area']}")
        if "subtitulo" in opts:
            cmd.append(f"--subtitle={opts['subtitulo']}")
        if (project / "estilo.json").is_file():  # paleta/fonte do projeto; sem ele, argv de sempre
            cmd.append(f"--estilo={project / 'estilo.json'}")
        return cmd + [str(quadro), str(marca or BRAND), str(project / "capa" / "capa.png")]
    # instalar-chromium: argv fixo, nenhuma entrada do usuario
    return ["sh", "-c", "npm i -g playwright && npx playwright install chromium"]
