"""Rotas dos trechos (clipes) que viram um video so: lista, envio, remocao, ordem.

``server.py`` despacha para ``rota`` e, ao iniciar a tarefa ``juntar``, chama ``pre_juntar``.
A montagem em si e o ``scripts/juntar.py`` (tarefa em segundo plano). Os trechos ficam em
``projects/<slug>/clipes/<NN>-<nome>.<ext>`` e a ordem em ``clipes.json``; nenhum caminho
vem do usuario (o nome enviado so da a extensao e o nome mostrado). Alterar a lista com
tarefa rodando e recusado (409), e toda alteracao confere isso de novo com a trava do
projeto na mao, para a tarefa nao ver a lista mudar embaixo dela.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import juntar  # noqa: E402

BLOCO = 1024 * 1024
OCUPADO = "há uma tarefa rodando neste projeto"

_travas: dict[str, threading.RLock] = {}
_travas_mu = threading.Lock()


def trava(slug: str) -> threading.RLock:
    with _travas_mu:
        return _travas.setdefault(slug, threading.RLock())


def _ocupado(h, slug: str) -> bool:
    """Responde 409 e devolve True se ha tarefa rodando no projeto."""
    if h.app.jobs.ativo_em(slug):
        h.json_reply(409, {"erro": OCUPADO, "codigo": "tarefa_rodando"})
        return True
    return False


def _completar_duracoes(d: Path, clipes: list[dict]) -> None:
    """Preenche a duracao dos trechos que a lista nao guardava (lista reconstruida)."""
    for c in clipes:
        if not c.get("duracao"):
            try:
                c["duracao"] = juntar.sondar(d / "clipes" / c["arquivo"])["duracao"]
            except juntar.JuntarErro:
                c["duracao"] = 0.0


def _resposta(d: Path, extra: dict | None = None) -> dict:
    clipes, montado = juntar.ler(d)
    _completar_duracoes(d, clipes)
    itens = []
    for c in clipes:
        try:
            tam = (d / "clipes" / c["arquivo"]).stat().st_size
        except OSError:
            tam = 0
        itens.append({"arquivo": c["arquivo"], "nome": c["nome"],
                      "duracao": c["duracao"], "tamanho": tam})
    sit = juntar.situacao_montagem(d, clipes, montado)
    dados = {"clipes": itens, "total_duracao": round(sum(c["duracao"] for c in itens), 3),
             "montado": sit["montado"], "desatualizada": sit["desatualizada"],
             "max_clipes": juntar.MAX_CLIPES, "max_duracao": juntar.MAX_DURACAO}
    dados.update(extra or {})
    return dados


def rota(h, slug: str, resto: list[str]) -> None:
    """``resto`` = o que vem depois de ``clipes`` no caminho (vazio, ``ordem`` ou um arquivo)."""
    if not resto:
        if not h._permitir("GET", "PUT"):
            return
        d = h._projeto(slug)
        if d is None:
            return
        if h.command == "PUT":
            return _enviar(h, slug, d)
        h._drenar()
        return h.json_reply(200, _resposta(d))
    if len(resto) != 1:
        return h.error(404, "Rota não encontrada")
    if resto[0] == "ordem":
        if not h._permitir("POST"):
            return
        d = h._projeto(slug)
        if d is None:
            return
        return _ordenar(h, slug, d)
    if not h._permitir("DELETE"):
        return
    d = h._projeto(slug)
    if d is None:
        return
    return _remover(h, slug, d, unquote(resto[0]))


# ------------------------------------------------------------------ envio
def _enviar(h, slug: str, d: Path) -> None:
    if _ocupado(h, slug):
        return
    nome = unquote(h.headers.get("X-Filename") or "")
    base = nome.replace("\\", "/").rsplit("/", 1)[-1]
    ext = os.path.splitext(base)[1].lower()
    if ext not in juntar.EXT_VIDEO:
        return h.error(400, "formato não suportado; use " + ", ".join(juntar.EXT_VIDEO))
    n = h._content_length()
    if n is None:
        return
    if n == 0:
        return h.error(400, "arquivo vazio")
    if n > h.server.max_upload:
        return h.error(413, "arquivo grande demais")
    atuais, _ = juntar.ler(d)
    if len(atuais) >= juntar.MAX_CLIPES:
        return h.error(400, f"são trechos demais (máximo {juntar.MAX_CLIPES}); remova algum antes de enviar outro")
    pasta = juntar.pasta_clipes(d, criar=True)
    if pasta is None:
        return h.error(500, "não foi possível usar a pasta dos trechos")
    tmp = None
    try:
        fd, nome_tmp = tempfile.mkstemp(dir=d, prefix=".clipe-", suffix=".tmp")
        tmp = Path(nome_tmp)
        total = 0
        with os.fdopen(fd, "wb") as f, h.app.envio():
            while total < n:
                bloco = h.rfile.read(min(BLOCO, n - total))
                if not bloco:
                    break
                total += len(bloco)
                f.write(bloco)
            f.flush()
            os.fsync(f.fileno())
        h._corpo_lido = True
        if total != n:
            return h.error(400, "envio interrompido")
        try:
            info = juntar.sondar(tmp)
        except juntar.JuntarErro as e:
            return h.error(504 if "demorou" in str(e) else 500 if "não encontrado" in str(e) else 400, str(e))
        with trava(slug):
            if _ocupado(h, slug):
                return
            clipes, montado = juntar.ler(d)
            if len(clipes) >= juntar.MAX_CLIPES:
                return h.error(400, f"são trechos demais (máximo {juntar.MAX_CLIPES}); remova algum antes de enviar outro")
            _completar_duracoes(d, clipes)
            if sum(c["duracao"] for c in clipes) + info["duracao"] > juntar.MAX_DURACAO:
                return h.error(400, f"com este trecho o vídeo passaria de {int(juntar.MAX_DURACAO // 60)} minutos")
            arquivo = juntar.novo_arquivo(clipes, pasta, nome, ext)
            os.replace(tmp, pasta / arquivo)
            tmp = None
            clipes.append({"arquivo": arquivo, "nome": juntar.nome_exibicao(nome),
                           "duracao": info["duracao"]})
            try:
                juntar.gravar(d, clipes, montado)
            except (OSError, ValueError):
                (pasta / arquivo).unlink(missing_ok=True)
                return h.error(500, "não foi possível guardar o trecho")
        h.json_reply(200, _resposta(d, {"adicionado": arquivo}))
    except TimeoutError:
        h.close_connection = True
        h.error(408, "tempo esgotado no envio")
    except (BrokenPipeError, ConnectionResetError):
        h.close_connection = True
    except OSError as e:
        print(f"erro no envio de trecho: {e!r}", file=sys.stderr)
        h.error(500, "não foi possível gravar o trecho")
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


# ------------------------------------------------------------ remover / ordem
def _remover(h, slug: str, d: Path, arquivo: str) -> None:
    h._drenar()
    with trava(slug):
        if _ocupado(h, slug):
            return
        clipes, montado = juntar.ler(d)
        if arquivo not in {c["arquivo"] for c in clipes}:
            return h.error(404, "esse trecho não existe")
        restantes = [c for c in clipes if c["arquivo"] != arquivo]
        try:
            juntar.gravar(d, restantes, montado)
            (d / "clipes" / arquivo).unlink(missing_ok=True)
        except (OSError, ValueError):
            return h.error(500, "não foi possível apagar o trecho")
    h.json_reply(200, _resposta(d))


def _ordenar(h, slug: str, d: Path) -> None:
    ok, corpo = h._read_json()
    if not ok:
        return
    ordem = corpo.get("ordem") if isinstance(corpo, dict) else None
    if not isinstance(ordem, list) or not all(isinstance(x, str) for x in ordem):
        return h.error(400, "informe a ordem dos trechos")
    with trava(slug):
        if _ocupado(h, slug):
            return
        clipes, montado = juntar.ler(d)
        por_arquivo = {c["arquivo"]: c for c in clipes}
        if len(ordem) != len(clipes) or set(ordem) != set(por_arquivo) or len(set(ordem)) != len(ordem):
            return h.error(400, "a ordem precisa ter todos os trechos, cada um uma vez só")
        try:
            juntar.gravar(d, [por_arquivo[a] for a in ordem], montado)
        except (OSError, ValueError):
            return h.error(500, "não foi possível guardar a nova ordem")
    h.json_reply(200, _resposta(d))


# ------------------------------------------------------------------ tarefa
def pre_juntar(h, slug: str, d: Path, opts: dict) -> bool:
    """Confere a montagem antes de iniciar a tarefa. True se ja respondeu (recusou)."""
    clipes, _ = juntar.ler(d)
    if not clipes:
        h.error(400, "envie pelo menos um trecho antes de montar o vídeo")
        return True
    if len(clipes) > juntar.MAX_CLIPES:
        h.error(400, f"são trechos demais (máximo {juntar.MAX_CLIPES})")
        return True
    if sum(c["duracao"] or 0 for c in clipes) > juntar.MAX_DURACAO:
        h.error(400, f"o vídeo montado passaria de {int(juntar.MAX_DURACAO // 60)} minutos; remova alguns trechos")
        return True
    perde = juntar.perde(d)
    if perde and not opts.get("confirmar"):
        h.json_reply(409, {"erro": "montar um vídeo novo apaga o que já foi feito a partir do vídeo atual",
                           "codigo": "precisa_confirmar", "perde": perde})
        return True
    return False
