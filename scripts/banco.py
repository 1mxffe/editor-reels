"""Banco de estilos e efeitos: carrega e valida ``banco/`` (paletas, legendas, efeitos, materiais).

Cada item e uma pasta com ``manifesto.json``. Item invalido nao entra em ``itens()``:
vai para ``Banco.erros`` com o motivo em portugues. Nada e executado (so JSON).

CLI: ``python3 -I scripts/banco.py listar [--json]`` | ``validar [--efeitos]`` (exit 1 se houver
erro; ``--efeitos`` tambem abre cada efeito no navegador e recusa o que nao desenha).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TIPOS = {"paleta": "paletas", "legenda": "legendas", "efeito": "efeitos", "material": "materiais"}
PLURAL_PARA_TIPO = {v: k for k, v in TIPOS.items()}
CAMPO_TIPOS = ("texto", "numero", "imagem", "cor", "escolha")
MAX_BYTES = 64 * 1024
MAX_NOME, MAX_DESCRICAO, MAX_ID, MAX_OPCOES, MAX_OPCAO = 60, 300, 40, 20, 60
MAX_EFEITO_HTML = 1024 * 1024
MAX_DURACAO = 600
LIM_CAMPO = 1_000_000
_SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_CAMPO_ID = re.compile(r"[a-z][a-z0-9_]{0,39}")
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_TOPO = {"nome", "descricao", "tipo", "duracao", "campos", "dados"}
_CAMPO_CHAVES = {"id", "rotulo", "tipo", "max", "min", "opcoes", "obrigatorio", "itens", "inteiro"}
MAX_ITENS = 20
PESOS = (400, 500, 600, 700, 800)
TRANSICOES = ("suave", "corte")
_PALETA = ("fundo", "texto", "destaque", "apoio")
_LEGENDA = {"estilo": ("faixa", "pilula", "duas-linhas", "pequena"),
            "posicao_padrao": ("baixo", "meio"),
            "tamanho_padrao": ("P", "M", "G")}


class BancoError(ValueError):
    """Consulta invalida ao banco (tipo ou item inexistente)."""


class _Invalido(Exception):
    """Motivo (em portugues) pelo qual um item nao entra no banco."""


class Banco:
    def __init__(self, raiz: Path, itens: dict[str, list[dict]], erros: list[dict]):
        self.raiz = raiz
        self._itens = itens
        self.erros = erros

    def itens(self, tipo: str) -> list[dict]:
        if tipo not in TIPOS:
            raise BancoError(f"tipo desconhecido: {tipo!r} (use {', '.join(TIPOS)})")
        return list(self._itens[tipo])

    def item(self, tipo: str, id: str) -> dict:
        for it in self.itens(tipo):
            if it["id"] == id:
                return it
        raise BancoError(f"não existe {tipo} {id!r} no banco")


def _texto(v, rotulo: str, maximo: int) -> str:
    if not isinstance(v, str) or not v.strip():
        raise _Invalido(f"{rotulo} precisa ser um texto não vazio")
    if len(v) > maximo:
        raise _Invalido(f"{rotulo} passa de {maximo} caracteres")
    if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in v):
        raise _Invalido(f"{rotulo} tem caracteres de controle ou invisíveis")
    return v


def _numero(v, rotulo: str, limite: float = LIM_CAMPO) -> float:
    # a comparacao vem ANTES de math.isfinite: int gigante estoura OverflowError ali
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _Invalido(f"{rotulo} precisa ser um número")
    if v != v or abs(v) > limite:
        raise _Invalido(f"{rotulo} precisa ser um número entre -{limite:g} e {limite:g}")
    return v


def _campo(c, vistos: set) -> dict:
    if not isinstance(c, dict):
        raise _Invalido("cada item de campos precisa ser um objeto")
    extra = set(c) - _CAMPO_CHAVES
    if extra:
        raise _Invalido(f"campo com chave desconhecida: {', '.join(sorted(extra))}")
    cid = c.get("id")
    if not isinstance(cid, str) or not _CAMPO_ID.fullmatch(cid):
        raise _Invalido(f"id de campo inválido: {cid!r} (letras minúsculas, números e _)")
    if cid in vistos:
        raise _Invalido(f"id de campo repetido: {cid}")
    vistos.add(cid)
    tipo = c.get("tipo")
    if tipo not in CAMPO_TIPOS:
        raise _Invalido(f"campo {cid}: tipo inválido {tipo!r} (use {', '.join(CAMPO_TIPOS)})")
    out = {"id": cid, "rotulo": _texto(c.get("rotulo"), f"rótulo do campo {cid}", MAX_NOME),
           "tipo": tipo}
    obrig = c.get("obrigatorio", False)
    if not isinstance(obrig, bool):
        raise _Invalido(f"campo {cid}: obrigatorio precisa ser verdadeiro ou falso")
    out["obrigatorio"] = obrig
    for lim in ("min", "max"):
        if lim in c:
            if tipo not in ("texto", "numero"):
                raise _Invalido(f"campo {cid}: {lim} só vale para texto e número")
            out[lim] = _numero(c[lim], f"{lim} do campo {cid}")
            if out[lim] < 0:
                raise _Invalido(f"campo {cid}: {lim} não pode ser negativo")
    if "min" in out and "max" in out and out["min"] > out["max"]:
        raise _Invalido(f"campo {cid}: min maior que max")
    if tipo == "escolha":
        op = c.get("opcoes")
        if (not isinstance(op, list) or not op or len(op) > MAX_OPCOES
                or not all(isinstance(o, str) for o in op)):
            raise _Invalido(f"campo {cid}: opcoes precisa ser uma lista de 1 a {MAX_OPCOES} textos")
        out["opcoes"] = [_texto(o, f"opção do campo {cid}", MAX_OPCAO) for o in op]
    elif "opcoes" in c:
        raise _Invalido(f"campo {cid}: opcoes só vale para tipo escolha")
    if "inteiro" in c:
        if tipo != "numero" or not isinstance(c["inteiro"], bool):
            raise _Invalido(f"campo {cid}: inteiro só vale para número (verdadeiro ou falso)")
        out["inteiro"] = c["inteiro"]
    if "itens" in c:  # campo lista: de itens.min a itens.max valores do mesmo tipo
        it = c["itens"]
        if tipo not in ("texto", "numero", "imagem"):
            raise _Invalido(f"campo {cid}: itens (lista) só vale para texto, número e imagem")
        if not isinstance(it, dict) or set(it) != {"min", "max"}:
            raise _Invalido(f"campo {cid}: itens precisa ter min e max (quantidade da lista)")
        for k in ("min", "max"):
            v = it[k]
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= MAX_ITENS:
                raise _Invalido(f"campo {cid}: itens.{k} precisa ser um inteiro de 0 a {MAX_ITENS}")
        if it["min"] > it["max"] or it["max"] == 0:
            raise _Invalido(f"campo {cid}: itens incoerente (precisa 0 <= min <= max e max >= 1)")
        out["itens"] = {"min": it["min"], "max": it["max"]}
    return out


def _duracao(d) -> dict:
    if not isinstance(d, dict) or set(d) != {"padrao", "min", "max"}:
        raise _Invalido("duracao precisa ter padrao, min e max")
    for k in d:
        _numero(d[k], f"duracao.{k}", MAX_DURACAO)
    if not 0 < d["min"] <= d["padrao"] <= d["max"]:
        raise _Invalido("duracao incoerente (precisa 0 < min <= padrao <= max)")
    return {k: d[k] for k in ("padrao", "min", "max")}


def _dados(tipo: str, d) -> dict:
    if not isinstance(d, dict):
        raise _Invalido("dados precisa ser um objeto")
    if tipo == "paleta":
        if set(d) != set(_PALETA):
            raise _Invalido(f"dados da paleta precisa ter exatamente: {', '.join(_PALETA)}")
        for k in _PALETA:
            if not isinstance(d[k], str) or not _HEX.fullmatch(d[k]):
                raise _Invalido(f"cor {k} inválida: {d[k]!r} (use #rrggbb)")
    elif tipo == "legenda":
        if set(d) != set(_LEGENDA):
            raise _Invalido(f"dados da legenda precisa ter exatamente: {', '.join(_LEGENDA)}")
        for k, ok in _LEGENDA.items():
            if d[k] not in ok:
                raise _Invalido(f"{k} inválido: {d[k]!r} (use {', '.join(ok)})")
    elif tipo == "efeito":
        _dados_efeito(d)
    return dict(d)


def _dados_efeito(d: dict) -> None:
    """``dados`` de efeito: livres, mas estas chaves (quando presentes) sao conferidas."""
    if d.get("area_segura") is not True:
        raise _Invalido("dados do efeito precisa de \"area_segura\": true (o efeito promete não "
                        "cobrir a faixa da legenda nem o topo da tela)")
    if "pesos" in d:
        p = d["pesos"]
        if (not isinstance(p, list) or not p or len(p) > len(PESOS)
                or any(isinstance(x, bool) or x not in PESOS for x in p)):
            raise _Invalido(f"dados.pesos precisa ser uma lista com pesos da fonte entre "
                            f"{', '.join(map(str, PESOS))}")
    if "transicao" in d and d["transicao"] not in TRANSICOES:
        raise _Invalido(f"dados.transicao inválida: {d['transicao']!r} (use {', '.join(TRANSICOES)})")
    if "exemplo" in d and not isinstance(d["exemplo"], dict):
        raise _Invalido("dados.exemplo precisa ser um objeto (campos de exemplo)")
    if "mesmo_tamanho" in d:
        g = d["mesmo_tamanho"]
        if not (isinstance(g, list) and all(isinstance(x, list) and len(x) >= 2
                                            and all(isinstance(i, str) for i in x) for x in g)):
            raise _Invalido("dados.mesmo_tamanho precisa ser uma lista de grupos de ids de campo")


def _sem_links(pasta: Path) -> None:
    if pasta.is_symlink():
        raise _Invalido("a pasta é um link (symlink); links não são aceitos")
    for p in pasta.rglob("*"):
        if p.is_symlink():
            raise _Invalido(f"{p.relative_to(pasta)} é um link (symlink); links não são aceitos")


def _carregar_item(pasta: Path, plural: str) -> dict:
    nome_pasta = pasta.name
    if ".." in nome_pasta or "/" in nome_pasta or "\\" in nome_pasta:
        raise _Invalido("nome de pasta com '..' ou barra")
    if len(nome_pasta) > MAX_ID or not _SLUG.fullmatch(nome_pasta):
        raise _Invalido(f"nome de pasta inválido {nome_pasta!r}: use minúsculas sem acento, "
                        f"números e hífens, até {MAX_ID} caracteres")
    _sem_links(pasta)
    if not pasta.is_dir():
        raise _Invalido("não é uma pasta")
    arq = pasta / "manifesto.json"
    if not arq.is_file():
        raise _Invalido("falta o arquivo manifesto.json")
    if arq.stat().st_size > MAX_BYTES:
        raise _Invalido("manifesto.json maior que 64 KiB")
    try:
        def _const(c):
            raise ValueError(f"valor {c} não é permitido")

        def _pares(pares):
            d = {}
            for k, v in pares:
                if k in d:
                    raise ValueError(f"chave repetida: {k}")
                d[k] = v
            return d
        m = json.loads(arq.read_bytes().decode("utf-8"), parse_constant=_const,
                       object_pairs_hook=_pares)
    except RecursionError as e:
        raise _Invalido("manifesto.json não é um JSON válido (aninhado fundo demais)") from e
    except (ValueError, OSError) as e:  # JSONDecodeError e UnicodeDecodeError sao ValueError
        raise _Invalido(f"manifesto.json não é um JSON válido ({e})") from e
    if not isinstance(m, dict):
        raise _Invalido("manifesto.json precisa ser um objeto JSON")
    extra = set(m) - _TOPO
    if extra:
        raise _Invalido(f"chave desconhecida no manifesto: {', '.join(sorted(extra))}")
    tipo = m.get("tipo")
    if tipo not in TIPOS:
        raise _Invalido(f"tipo inválido {tipo!r} (use {', '.join(TIPOS)})")
    if tipo != PLURAL_PARA_TIPO[plural]:
        raise _Invalido(f"tipo {tipo!r} não combina com a pasta {plural}/")
    item = {"id": nome_pasta, "tipo": tipo,
            "nome": _texto(m.get("nome"), "nome", MAX_NOME),
            "descricao": _texto(m.get("descricao"), "descricao", MAX_DESCRICAO)}
    campos = m.get("campos", [])
    if not isinstance(campos, list):
        raise _Invalido("campos precisa ser uma lista")
    vistos: set = set()
    item["campos"] = [_campo(c, vistos) for c in campos]
    if "duracao" in m:
        item["duracao"] = _duracao(m["duracao"])
    item["dados"] = _dados(tipo, m.get("dados"))
    if tipo == "efeito":
        listas = {c["id"] for c in item["campos"] if "itens" in c}
        for grupo in item["dados"].get("mesmo_tamanho", []):
            fora = [i for i in grupo if i not in listas]
            if fora:
                raise _Invalido(f"dados.mesmo_tamanho cita campos que não são listas: {', '.join(fora)}")
        if "duracao" not in item:
            raise _Invalido("efeito precisa de duracao")
        html = pasta / "efeito.html"
        if not html.exists() and not html.is_symlink():
            raise _Invalido("efeito precisa do arquivo efeito.html na pasta")
        if not html.is_file():
            raise _Invalido("efeito.html não é um arquivo comum")
        if html.stat().st_size > MAX_EFEITO_HTML:
            raise _Invalido("efeito.html é um arquivo grande demais (máximo 1 MiB)")
    item["pasta"] = pasta
    return item


def _verificar_todos(itens: list[dict]) -> dict[str, str | None]:
    """Abre cada ``efeito.html`` no Chromium (um navegador para todos) com os campos de
    exemplo: ``{id: None}`` se montou e desenhou, senao ``{id: motivo}``. Caro (segundos):
    so roda quando pedido (``carregar(..., verificar_efeitos=True)`` e ``validar --efeitos``)."""
    import graphics  # import tardio: graphics usa o banco
    return graphics.verificar_efeitos(itens)


def verificar_efeito(item: dict) -> str | None:
    """Motivo pelo qual o efeito nao funciona (``setup``/``setTime`` lancou, pagina sem CSP
    sem rede...), ou None se ele desenha."""
    return _verificar_todos([item])[item["id"]]


verificar_efeitos = _verificar_todos


def carregar(raiz: Path = REPO / "banco", *, verificar_efeitos: bool = False) -> Banco:
    """Carrega o banco (so JSON e arquivos). Com ``verificar_efeitos``, cada efeito tambem e
    aberto no navegador e o que falhar sai de ``itens()`` e vai para ``erros``."""
    banco = _carregar(Path(raiz))
    if verificar_efeitos and banco.itens("efeito"):
        motivos = _verificar_todos(banco.itens("efeito"))
        bons = []
        for it in banco._itens["efeito"]:
            if motivos.get(it["id"]):
                banco.erros.append({"pasta": str(it["pasta"].relative_to(banco.raiz)),
                                    "motivo": f"o efeito não desenha: {motivos[it['id']]}"})
            else:
                bons.append(it)
        banco._itens["efeito"] = bons
    return banco


def _carregar(raiz: Path) -> Banco:
    itens: dict[str, list[dict]] = {t: [] for t in TIPOS}
    erros: list[dict] = []

    def erro(p: Path, motivo: str) -> None:
        erros.append({"pasta": str(p.relative_to(raiz)), "motivo": motivo})

    if not raiz.is_dir():
        return Banco(raiz, itens, erros)
    for entrada in sorted(raiz.iterdir(), key=lambda p: p.name):
        if entrada.name.startswith(".") or entrada.name == "README.md":
            continue
        if entrada.is_symlink() or not entrada.is_dir() or entrada.name not in PLURAL_PARA_TIPO:
            erro(entrada, "não é uma pasta de tipo conhecida "
                          f"({', '.join(PLURAL_PARA_TIPO)}) ou é um link")
            continue
        plural = entrada.name
        for pasta in sorted(entrada.iterdir(), key=lambda p: p.name):
            if pasta.name.startswith("."):
                continue
            try:
                if not pasta.is_dir() and not pasta.is_symlink():
                    raise _Invalido("deveria ser uma pasta, é um arquivo")
                if pasta.is_symlink():
                    raise _Invalido("a pasta é um link (symlink); links não são aceitos")
                itens[PLURAL_PARA_TIPO[plural]].append(_carregar_item(pasta, plural))
            except _Invalido as e:
                erro(pasta, str(e))
    return Banco(raiz, itens, erros)


def _para_json(b: Banco) -> dict:
    lista = []
    for t in TIPOS:
        for it in b.itens(t):
            d = {k: v for k, v in it.items() if k != "pasta"}
            d["pasta"] = it["pasta"].relative_to(b.raiz).as_posix()
            lista.append(d)
    return {"itens": lista, "erros": b.erros}


def main(argv: list[str] | None = None) -> None:
    p = common.UsageParser(prog="banco.py", description="Banco de estilos e efeitos.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("listar", help="lista os itens válidos")
    pl.add_argument("--json", action="store_true")
    pv = sub.add_parser("validar", help="valida o banco; sai com 1 se houver item inválido")
    pv.add_argument("--efeitos", action="store_true",
                    help="também abre cada efeito no navegador (mais lento)")
    for s in (pl, pv):
        s.add_argument("--raiz", type=Path, default=REPO / "banco", help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.cmd == "validar" and a.efeitos:
        try:
            b = carregar(a.raiz, verificar_efeitos=True)
        except Exception as e:  # navegador ausente etc.: mensagem, nunca traceback
            common.fail(f"não foi possível verificar os efeitos: {e}")
    else:
        b = carregar(a.raiz)
    if a.cmd == "listar":
        if a.json:
            print(json.dumps(_para_json(b), ensure_ascii=False, indent=2))
            return
        for t in TIPOS:
            for it in b.itens(t):
                print(f"{t}/{it['id']}: {it['nome']} - {it['descricao']}")
        for e in b.erros:
            print(f"inválido: {e['pasta']}: {e['motivo']}", file=sys.stderr)
        return
    if not b.raiz.is_dir():
        common.fail(f"pasta do banco não encontrada: {b.raiz}")
    for e in b.erros:
        print(f"erro: {e['pasta']}: {e['motivo']}", file=sys.stderr)
    if b.erros:
        sys.exit(1)
    print(f"banco ok: {sum(len(b.itens(t)) for t in TIPOS)} itens válidos")


if __name__ == "__main__":
    main()
