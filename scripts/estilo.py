"""Estilo do projeto (``projects/<slug>/estilo.json``): paleta, fonte, legenda e cards.

Sem o arquivo vale ``DEFAULT``, que reproduz o visual de sempre. O arquivo e validado
contra o banco (``banco/``): paleta e legenda precisam existir la. Chave desconhecida,
valor fora da lista ou arquivo grande demais viram ``EstiloError`` com a mensagem em
portugues. ``aplicar_marca`` devolve uma COPIA do brand com as cores da paleta e a fonte
escolhidas; ``brand/brand.json`` nunca e alterado.

Formato::

    {"paleta": "marca", "fonte": "Poppins",
     "legenda": {"estilo": "faixa-azul", "posicao": "baixo", "tamanho": "M"},
     "cards": {"estilo": "vidro"}}

Chaves ausentes recebem o padrao (posicao/tamanho da legenda: os do item no banco).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import banco as bancomod  # noqa: E402
import common  # noqa: E402

ARQUIVO = "estilo.json"
MAX_BYTES = 16 * 1024
DEFAULT = {"paleta": "marca", "fonte": "Poppins",
           "legenda": {"estilo": "faixa-azul", "posicao": "baixo", "tamanho": "M"},
           "cards": {"estilo": "vidro"}}
FONTES = ("Poppins",)
CARDS = ("vidro",)
POSICOES = ("baixo", "meio")
TAMANHOS = ("P", "M", "G")
# paleta do banco -> campos de cor do brand.json
PALETA_PARA_BRAND = {"fundo": "bg", "texto": "fg", "destaque": "accent", "apoio": "muted"}


class EstiloError(ValueError):
    """estilo.json invalido; a mensagem ja esta em portugues, pronta para o usuario."""


def _ids(b: bancomod.Banco, tipo: str) -> list[str]:
    return [it["id"] for it in b.itens(tipo)]


def _objeto(v, nome: str, chaves: tuple) -> dict:
    if not isinstance(v, dict):
        raise EstiloError(f"estilo.json: {nome} precisa ser um objeto com {', '.join(chaves)}")
    extra = sorted(set(v) - set(chaves))
    if extra:
        raise EstiloError(f"estilo.json: chave desconhecida em {nome}: {', '.join(extra)} "
                          f"(use {', '.join(chaves)})")
    return v


def validar(dados, banco: bancomod.Banco | None = None) -> dict:
    """Valida e completa um estilo; devolve um dict novo (nunca altera ``dados``)."""
    if not isinstance(dados, dict):
        raise EstiloError("estilo.json precisa ser um objeto JSON (chaves paleta, fonte, legenda, cards)")
    extra = sorted(set(dados) - set(DEFAULT))
    if extra:
        raise EstiloError(f"estilo.json: chave desconhecida: {', '.join(extra)} "
                          f"(use {', '.join(DEFAULT)})")
    b = banco if banco is not None else bancomod.carregar()
    out = copy.deepcopy(DEFAULT)

    paleta = dados.get("paleta", DEFAULT["paleta"])
    paletas = _ids(b, "paleta")
    if not isinstance(paleta, str) or paleta not in paletas:
        raise EstiloError(f"estilo.json: a paleta {paleta!r} não existe no banco "
                          f"(opções: {', '.join(paletas) or 'nenhuma'})")
    out["paleta"] = paleta

    fonte = dados.get("fonte", DEFAULT["fonte"])
    if fonte not in FONTES:
        raise EstiloError(f"estilo.json: a fonte {fonte!r} não está disponível; "
                          f"por enquanto só a fonte {', '.join(FONTES)} pode ser usada")
    out["fonte"] = fonte

    leg = _objeto(dados.get("legenda", DEFAULT["legenda"]), "legenda", ("estilo", "posicao", "tamanho"))
    legendas = _ids(b, "legenda")
    lid = leg.get("estilo", DEFAULT["legenda"]["estilo"])
    if not isinstance(lid, str) or lid not in legendas:
        raise EstiloError(f"estilo.json: o estilo de legenda {lid!r} não existe no banco "
                          f"(opções: {', '.join(legendas) or 'nenhuma'})")
    item = b.item("legenda", lid)["dados"]
    pos = leg.get("posicao", item["posicao_padrao"])
    if pos not in POSICOES:
        raise EstiloError(f"estilo.json: posição da legenda inválida {pos!r} (use baixo ou meio)")
    tam = leg.get("tamanho", item["tamanho_padrao"])
    if tam not in TAMANHOS:
        raise EstiloError(f"estilo.json: tamanho da legenda inválido {tam!r} (use P, M ou G)")
    out["legenda"] = {"estilo": lid, "posicao": pos, "tamanho": tam}

    cards = _objeto(dados.get("cards", DEFAULT["cards"]), "cards", ("estilo",))
    cest = cards.get("estilo", DEFAULT["cards"]["estilo"])
    if cest not in CARDS:
        raise EstiloError(f"estilo.json: estilo de card {cest!r} indisponível "
                          f"(por enquanto só {', '.join(CARDS)})")
    out["cards"] = {"estilo": cest}
    return out


def carregar(project: Path, banco: bancomod.Banco | None = None) -> dict:
    """Estilo do projeto; sem ``estilo.json`` devolve uma copia de ``DEFAULT``."""
    arq = Path(project) / ARQUIVO
    if not arq.exists() and not arq.is_symlink():  # link quebrado nao e "sem arquivo"
        return copy.deepcopy(DEFAULT)
    return ler(arq, banco)


def ler_bruto(arq: Path) -> bytes:
    """Bytes do ``estilo.json`` (arquivo comum, sem link, ate 16 KiB) ou ``EstiloError``."""
    try:
        return common.ler_limitado(Path(arq), MAX_BYTES)
    except common.LeituraRecusada as e:
        if "grande" in str(e):
            raise EstiloError("estilo.json é grande demais (máximo 16 KiB)") from None
        raise EstiloError(f"estilo.json recusado: {e}") from None
    except FileNotFoundError:
        raise EstiloError(f"estilo.json não encontrado: {arq}") from None
    except OSError as e:
        raise EstiloError(f"não foi possível ler o estilo.json ({e.strerror or e})") from None


def decodificar(bruto: bytes):
    """JSON de ``estilo.json``; qualquer falha (inclusive aninhamento fundo) vira EstiloError."""
    def _const(c):
        raise ValueError(f"valor {c} não é permitido")
    try:
        return json.loads(bruto.decode("utf-8"), parse_constant=_const)
    except RecursionError:
        raise EstiloError("estilo.json não é um JSON válido (aninhamento fundo demais)") from None
    except (MemoryError, OverflowError):
        raise EstiloError("estilo.json não é um JSON válido (grande ou complexo demais)") from None
    except ValueError as e:  # JSONDecodeError e UnicodeDecodeError sao ValueError
        raise EstiloError(f"estilo.json não é um JSON válido ({e})") from None


def ler(arq: Path, banco: bancomod.Banco | None = None) -> dict:
    """Le e valida um ``estilo.json`` dado pelo caminho (opcao ``--estilo`` das CLIs)."""
    return validar(decodificar(ler_bruto(arq)), banco)


def salvar(project: Path, dados: dict, banco: bancomod.Banco | None = None) -> dict:
    """Valida contra o banco e grava ``estilo.json`` de forma atomica; devolve o gravado."""
    norm = validar(dados, banco)
    texto = json.dumps(norm, ensure_ascii=False, indent=2)
    if len(texto.encode("utf-8")) > MAX_BYTES:  # nao acontece com dados validos; defesa
        raise EstiloError("estilo.json é grande demais (máximo 16 KiB)")
    common.write_json_atomic(Path(project) / ARQUIVO, norm)
    return norm


def aplicar_marca(brand: dict, est: dict, banco: bancomod.Banco | None = None) -> dict:
    """Brand efetivo: copia de ``brand`` com as cores da paleta e a fonte do estilo."""
    norm = validar(est, banco)
    b = banco if banco is not None else bancomod.carregar()
    pal = b.item("paleta", norm["paleta"])["dados"]
    out = copy.deepcopy(brand)
    for k, campo in PALETA_PARA_BRAND.items():
        out[campo] = pal[k]
    out["font_title"] = out["font_body"] = norm["fonte"]
    return out


def tipo_legenda(est: dict, banco: bancomod.Banco | None = None) -> str:
    """Tipo de desenho da legenda escolhida (faixa, pilula, duas-linhas, pequena)."""
    b = banco if banco is not None else bancomod.carregar()
    return b.item("legenda", est["legenda"]["estilo"])["dados"]["estilo"]
