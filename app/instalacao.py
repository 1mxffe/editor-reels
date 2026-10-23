"""Itens do doctor em portugues: nome, mensagem e comando de instalacao (Mac/Homebrew/pip).

A chave de ITENS e o ``name`` devolvido por ``scripts/doctor.py::check()``.
Item desconhecido nunca e omitido: ``traduzir`` o devolve com nome=name.
Nomes e mensagens sao para quem nunca usou o terminal; o motivo tecnico do
doctor vai a parte, em ``detalhe``.
"""
from __future__ import annotations

# name do doctor -> (id, nome, opcional, mensagem se faltar, comando ou None)
ITENS: dict[str, tuple[str, str, bool, str, str | None]] = {
    "python >= 3.11": (
        "python", "Programa base do editor", False,
        "A versão instalada é antiga demais; instale a mais nova.",
        "brew install python@3.13"),
    "ffmpeg": (
        "ffmpeg", "Conversor de vídeo", False,
        "Necessário para cortar, legendar e montar o vídeo.",
        "brew install ffmpeg"),
    "ffprobe": (
        "ffprobe", "Leitor de vídeo", False,
        "Necessário para ler a duração e conferir os vídeos enviados (vem junto com o conversor de vídeo).",
        "brew install ffmpeg"),
    "node (opcional: cards e capa)": (
        "node", "Desenho dos cards e da capa", True,
        "Sem ele não há cards de gráfico nem capa.",
        "brew install node"),
    "disco livre >= 10 GB": (
        "disco", "Espaço livre no disco (10 GB)", False,
        "Libere espaço no disco: vídeos prontos ocupam bastante.",
        None),
    "faster_whisper (opcional)": (
        "whisper", "Reconhecimento de fala", True,
        "Sem ele o texto do vídeo não é gerado automaticamente.",
        "pip install -r requirements.txt"),
    "Pillow (opcional: capa)": (
        "pillow", "Imagens da capa", True,
        "Sem ele não há sugestões de quadro nem montagem da capa.",
        "pip install -r requirements.txt"),
    "chromium + playwright (opcional: graficos)": (
        "graficos", "Navegador de gráficos", True,
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
            mensagem = "Instalado." if ok else falta
        else:
            id_, nome, opcional = name, name, not it.get("required", True)
            comando = None
            mensagem = "Instalado." if ok else "Item novo da conferência; veja os detalhes técnicos."
        # o motivo cru do doctor vai separado: a tela o mostra so em "Detalhes tecnicos"
        out.append({"id": id_, "nome": nome, "ok": ok, "opcional": opcional,
                    "mensagem": mensagem, "comando": comando,
                    "detalhe": None if ok else (detail or None)})
    return {"estado": ESTADOS.get(estado, "faltam itens"), "estado_codigo": estado,
            "itens": out}
