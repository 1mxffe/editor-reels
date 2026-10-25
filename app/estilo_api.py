"""Rotas do passo Estilo: banco (itens, erros, fontes), variacoes e estilo.json do projeto.

``server.py`` so despacha para ``rota_banco`` e ``rota_estilo``; os cartoes (quadros de
exemplo) saem pela tarefa ``quadros`` (``scripts/banco.py quadros``) e o "Aplicar" pela
tarefa ``aplicar-estilo`` (ver ``tarefas.py``). Ids e tipos so valem se existem no banco
carregado; nenhum caminho vem do usuario; erros em portugues, sem caminho absoluto.
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import banco as bancomod  # noqa: E402
import common  # noqa: E402
import estilo as estilomod  # noqa: E402
import revisao_api  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BANCO_RAIZ = REPO / "banco"
FONTS_DIR = REPO / "assets" / "fonts"
PLURAIS = ("paletas", "legendas", "efeitos")
MAX_FONTE = 20 * 1024 * 1024
MAX_FONTES = 200
_ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_NOME_FONTE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 \-]{0,63}")  # mesma regra de brand.valid_name


def _banco():
    return bancomod.carregar(BANCO_RAIZ)


def _item_json(it: dict) -> dict:
    d = {k: it[k] for k in ("id", "nome", "descricao", "campos", "dados") if k in it}
    if "duracao" in it:
        d["duracao"] = it["duracao"]
    d["variacoes"] = list(it.get("variacoes") or [])
    return d


# ------------------------------------------------------------------ fontes

def familia_ttf(dados: bytes) -> str | None:
    """Nome da familia de um TTF/OTF (tabela ``name``: id 16, senao id 1), ou None.

    Leitura tolerante: qualquer arquivo truncado, corrompido ou com contagem absurda
    devolve None (nunca levanta)."""
    try:
        if len(dados) < 12:
            return None
        n = struct.unpack(">H", dados[4:6])[0]
        if n > 512 or 12 + 16 * n > len(dados):
            return None
        off = None
        for i in range(n):
            rec = dados[12 + 16 * i: 28 + 16 * i]
            if rec[:4] == b"name":
                off = struct.unpack(">I", rec[8:12])[0]
                break
        if off is None or off + 6 > len(dados):
            return None
        _, count, base = struct.unpack(">HHH", dados[off:off + 6])
        if count > 4096 or off + 6 + 12 * count > len(dados):
            return None
        achados: dict[tuple, str] = {}
        for i in range(count):
            p = off + 6 + 12 * i
            plat, enc, lang, nid, comp, desl = struct.unpack(">HHHHHH", dados[p:p + 12])
            if nid not in (1, 16):
                continue
            ini = off + base + desl
            bruto = dados[ini:ini + comp]
            if len(bruto) != comp or not comp:
                continue
            if plat in (0, 3):
                texto = bruto.decode("utf-16-be", "replace")
            elif plat == 1:
                texto = bruto.decode("latin-1")
            else:
                continue
            texto = texto.strip()
            if not _NOME_FONTE.fullmatch(texto):
                continue
            prio = (0 if nid == 16 else 1, 0 if (plat == 3 and lang == 0x409) else 1)
            achados.setdefault(prio, texto)
        return achados[min(achados)] if achados else None
    except (struct.error, ValueError, IndexError, UnicodeError):
        return None


def _familia_do_nome(arquivo: str) -> str | None:
    nome = Path(arquivo).stem.split("-")[0].strip()
    return nome if _NOME_FONTE.fullmatch(nome) else None


def fontes() -> list[dict]:
    """Familias de ``assets/fonts/*.ttf`` (uma entrada por familia; pesos agrupados).
    ``arquivo``: o peso Bold se existir (o das legendas), senao o primeiro."""
    if not FONTS_DIR.is_dir():
        return []
    grupos: dict[str, list[str]] = {}
    for arq in sorted(FONTS_DIR.glob("*.ttf"))[:MAX_FONTES]:
        if arq.is_symlink() or not arq.is_file():
            continue
        try:
            dados = common.ler_limitado(arq, MAX_FONTE)
        except (OSError, ValueError):
            continue
        nome = familia_ttf(dados) or _familia_do_nome(arq.name)
        if nome:
            grupos.setdefault(nome, []).append(arq.name)
    out = []
    for nome in sorted(grupos, key=str.lower):
        arqs = grupos[nome]
        bold = [a for a in arqs if a.lower().endswith("-bold.ttf")]
        out.append({"nome": nome, "arquivo": (bold or arqs)[0], "arquivos": arqs})
    return out


# ------------------------------------------------------------------ rotas

def rota_banco(h, path: str, query) -> None:
    """GET /api/banco e GET /api/banco/<tipo>/<id>/variacoes[?projeto=<slug>]."""
    partes = path[len("/api/banco"):].strip("/").split("/") if path != "/api/banco" else []
    if not partes:
        if not h._permitir("GET"):
            return
        h._drenar()
        return h.json_reply(200, listar())
    if len(partes) != 3 or partes[2] != "variacoes" or partes[0] not in PLURAIS:
        return h.error(404, "Rota não encontrada")
    if not h._permitir("GET"):
        return
    h._drenar()
    plural, iid = partes[0], partes[1]
    b = _banco()
    tipo = bancomod.PLURAL_PARA_TIPO[plural]
    if len(iid) > bancomod.MAX_ID or not _ID_RE.fullmatch(iid):
        return h.error(404, "item não encontrado no banco")
    try:
        item = b.item(tipo, iid)
    except bancomod.BancoError:
        return h.error(404, "item não encontrado no banco")
    escolhido = None
    slug = (query.get("projeto") or [None])[0]
    if slug is not None:
        d = h._projeto(slug)
        if d is None:
            return
        try:
            escolhido = _dados_escolhidos(tipo, estilomod.carregar(d, b), b)
        except estilomod.EstiloError:
            escolhido = None  # estilo.json invalido: ordem padrao
    h.json_reply(200, {"tipo": plural, "id": iid, "variacoes": variacoes(item, escolhido)})


def _dados_escolhidos(tipo: str, est: dict, b) -> dict | None:
    """``dados`` (no formato do banco) do que o projeto usa hoje para este tipo."""
    if tipo == "paleta":
        return b.item("paleta", est["paleta"])["dados"]
    if tipo == "legenda":
        return {"estilo": estilomod.tipo_legenda(est, b),
                "posicao_padrao": est["legenda"]["posicao"],
                "tamanho_padrao": est["legenda"]["tamanho"]}
    return None


def variacoes(item: dict, escolhido: dict | None = None) -> list[dict]:
    """O proprio item seguido das variacoes do manifesto; a que bate com ``escolhido``
    (o que o projeto usa) vem primeiro, as demais na ordem do manifesto."""
    lista = [{"nome": item["nome"], "dados": item["dados"]}] + [
        {"nome": v["nome"], "dados": v["dados"]} for v in item.get("variacoes") or []]
    if escolhido is not None:
        for i, v in enumerate(lista):
            if v["dados"] == escolhido:
                lista.insert(0, lista.pop(i))
                break
    return lista


def listar() -> dict:
    b = _banco()
    raiz = Path(BANCO_RAIZ)
    out = {plural: [_item_json(it) for it in b.itens(bancomod.PLURAL_PARA_TIPO[plural])]
           for plural in PLURAIS}
    out["erros"] = [{"pasta": str(e.get("pasta", ""))[:200],
                     "motivo": revisao_api.sanitizar(str(e.get("motivo", "")), raiz)[:500]}
                    for e in b.erros]
    out["fontes"] = fontes()
    return out


def rota_estilo(h, slug: str) -> None:
    """GET/PUT /api/projects/<slug>/estilo."""
    d = h._projeto(slug)
    if d is None:
        return
    if h.command in ("GET", "HEAD"):
        h._drenar()
        try:
            return h.json_reply(200, estilomod.carregar(d, _banco()))
        except estilomod.EstiloError as e:
            return h.error(400, _msg(e, d))
    ok, corpo = h._read_json(estilomod.MAX_BYTES)
    if not ok:
        return
    trava = revisao_api.trava(slug)
    if not trava.acquire(timeout=revisao_api.ESPERA_TRAVA):
        return h.error(409, "outra edição está em andamento neste projeto; tente de novo")
    try:
        if h.app.jobs.ativo_em(slug):
            return h.error(409, "há uma tarefa rodando neste projeto; aguarde terminar")
        try:
            salvo = salvar(d, corpo)
        except estilomod.EstiloError as e:
            return h.error(400, _msg(e, d))
        except OSError:
            return h.error(500, "não foi possível gravar o estilo")
    finally:
        trava.release()
    h.json_reply(200, salvo)


def salvar(d: Path, corpo) -> dict:
    """Valida contra o banco e grava ``estilo.json`` (atomico); EstiloError se invalido."""
    return estilomod.salvar(d, corpo, _banco())


def _msg(e: Exception, d: Path) -> str:
    return revisao_api.sanitizar(str(e), d)[:500] or "estilo inválido"
