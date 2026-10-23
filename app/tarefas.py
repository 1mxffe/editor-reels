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


def _candidato(nome, valor):
    if valor == "foto":
        return "foto"
    return _inteiro(nome, valor, 1, 8)


# tipo -> {chave: validador(nome, valor)}
OPCOES = {
    "transcrever": {"lang": _lang, "model": lambda n, v: _enum(n, v, MODELOS)},
    "cortes": {},
    "preview": {},
    "final": {},
    "capa-candidatos": {"modo": lambda n, v: _enum(n, v, ("video", "photo")),
                        "n": lambda n, v: _inteiro(n, v, 1, 8)},
    "capa": {"candidato": _candidato,
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


def argv(tipo: str, project: Path, *, falso: bool = False, **opcoes) -> list[str]:
    """argv da tarefa. ``falso=True`` (so o servidor em modo de teste decide isso, ver
    ``server.transcricao_falsa``) troca o Whisper pela transcricao fixa dos testes."""
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
        if modo == "photo":
            return _py("cover_frames.py") + ["photo", str(project / "capa" / "foto.png"), saida]
        cmd = _py("cover_frames.py") + ["video"]
        if "n" in opts:
            cmd.append(f"--n={opts['n']}")
        return cmd + [str(_entrada(project)), saida]
    if tipo == "capa":
        if "gancho" not in opts:
            raise ValueError("informe o gancho da capa")
        cand = opts.get("candidato", 1)
        foto = ("foto.png" if cand == "foto" else f"candidato-{cand}.png")
        cmd = _py("cover_compose.py") + [f"--hook={opts['gancho']}"]
        if "area" in opts:
            cmd.append(f"--area={opts['area']}")
        if "subtitulo" in opts:
            cmd.append(f"--subtitle={opts['subtitulo']}")
        return cmd + [str(project / "capa" / foto), str(BRAND),
                      str(project / "capa" / "capa.png")]
    # instalar-chromium: argv fixo, nenhuma entrada do usuario
    return ["sh", "-c", "npm i -g playwright && npx playwright install chromium"]
