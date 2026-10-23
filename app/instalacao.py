"""Itens do doctor em portugues: nome, mensagem e comando de instalacao (Mac/Homebrew/pip).

A chave de ITENS e o ``name`` devolvido por ``scripts/doctor.py::check()``.
Item desconhecido nunca e omitido: ``traduzir`` o devolve com nome=name e
mensagem=detail.
"""
from __future__ import annotations

# name do doctor -> (id, nome, opcional, mensagem se faltar, comando ou None)
ITENS: dict[str, tuple[str, str, bool, str, str | None]] = {
    "python >= 3.11": (
        "python", "Python 3.11 ou mais novo", False,
        "O Python instalado é antigo demais; instale o 3.11 ou mais novo.",
        "brew install python@3.13"),
    "ffmpeg": (
        "ffmpeg", "ffmpeg", False,
        "Necessário para cortar, legendar e renderizar o vídeo.",
        "brew install ffmpeg"),
    "ffprobe": (
        "ffprobe", "ffprobe", False,
        "Necessário para ler a duração e conferir os vídeos enviados (vem com o ffmpeg).",
        "brew install ffmpeg"),
    "node (opcional: cards e capa)": (
        "node", "Node.js", True,
        "Sem ele não há cards de gráfico nem capa.",
        "brew install node"),
    "disco livre >= 10 GB": (
        "disco", "Espaço livre em disco (10 GB)", False,
        "Libere espaço em disco: vídeos e renders ocupam muito.",
        None),
    "faster_whisper (opcional)": (
        "whisper", "Transcrição automática (faster-whisper)", True,
        "Sem ele a transcrição automática não funciona.",
        "pip install -r requirements.txt"),
    "Pillow (opcional: capa)": (
        "pillow", "Pillow (imagens da capa)", True,
        "Sem ele não há candidatos nem composição da capa.",
        "pip install -r requirements.txt"),
    "chromium + playwright (opcional: graficos)": (
        "graficos", "Chromium + Playwright (cards de gráfico)", True,
        "Sem ele os cards de gráfico não são desenhados.",
        "npm install && npx playwright install chromium"),
}

ESTADOS = {"READY": "pronto", "READY WITH LIMITS": "pronto com limites"}


def traduzir(estado: str, itens: list[dict]) -> dict:
    out = []
    for it in itens:
        name = it.get("name", "")
        ok = bool(it.get("ok"))
        detail = it.get("detail") or ""
        conhecido = ITENS.get(name)
        if conhecido:
            id_, nome, opcional, falta, comando = conhecido
            if ok:
                mensagem = "Instalado."
            else:
                mensagem = f"{falta} ({detail})" if detail else falta
        else:
            id_, nome, opcional = name, name, not it.get("required", True)
            comando = None
            mensagem = detail
        out.append({"id": id_, "nome": nome, "ok": ok, "opcional": opcional,
                    "mensagem": mensagem, "comando": comando})
    return {"estado": ESTADOS.get(estado, "faltam itens"), "estado_codigo": estado,
            "itens": out}
