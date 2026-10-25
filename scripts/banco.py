"""Banco de estilos e efeitos: carrega e valida ``banco/`` (paletas, legendas, efeitos, materiais).

Cada item e uma pasta com ``manifesto.json``. Item invalido nao entra em ``itens()``:
vai para ``Banco.erros`` com o motivo em portugues. Nada e executado (so JSON).

Campo opcional ``variacoes`` (paletas, legendas, efeitos): ate 12 objetos ``{nome, dados}``
com ``dados`` do mesmo tipo e validacao dos ``dados`` do item ("mais parecido com este").

``quadro(project, tipo, item_id, estilo, t, out)``: o cartao do passo Estilo, um PNG 540x960
de um quadro do video do usuario com o item aplicado (cache em ``projects/<slug>/quadros/``).

CLI: ``python3 -I scripts/banco.py listar [--json]`` | ``validar [--efeitos]`` (exit 1 se houver
erro; ``--efeitos`` tambem abre cada efeito no navegador e recusa o que nao desenha) |
``quadros <projeto> --aba=paletas|legendas|efeitos [--t=<s>] [--brand=<brand.json>]`` (gera os
cartoes da aba com o estilo atual do projeto; progresso por linha; exit 1 se algum falhar).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
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
MAX_DURACAO_EFEITO = 30  # efeito sobre o video: nunca mais que isso (render quadro a quadro)
LIM_CAMPO = 1_000_000
_SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_CAMPO_ID = re.compile(r"[a-z][a-z0-9_]{0,39}")
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_TOPO = {"nome", "descricao", "tipo", "duracao", "campos", "dados", "variacoes"}
MAX_VARIACOES = 12
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


def _variacoes(tipo: str, v) -> list[dict]:
    """``variacoes`` do manifesto: ate 12 ``{nome, dados}``, dados validados como os do item."""
    if not isinstance(v, list) or len(v) > MAX_VARIACOES:
        raise _Invalido(f"variacoes precisa ser uma lista de até {MAX_VARIACOES} objetos com nome e dados")
    out = []
    for i, x in enumerate(v, 1):
        if not isinstance(x, dict) or set(x) != {"nome", "dados"}:
            raise _Invalido(f"variação {i} precisa ter exatamente nome e dados")
        nome = _texto(x["nome"], f"nome da variação {i}", MAX_NOME)
        try:
            dados = _dados(tipo, x["dados"])
        except _Invalido as e:
            raise _Invalido(f"variação {i}: {e}") from None
        out.append({"nome": nome, "dados": dados})
    return out


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
    item["variacoes"] = _variacoes(tipo, m["variacoes"]) if "variacoes" in m else []
    if tipo == "efeito":
        listas = {c["id"] for c in item["campos"] if "itens" in c}
        for grupo in item["dados"].get("mesmo_tamanho", []):
            fora = [i for i in grupo if i not in listas]
            if fora:
                raise _Invalido(f"dados.mesmo_tamanho cita campos que não são listas: {', '.join(fora)}")
        if "duracao" not in item:
            raise _Invalido("efeito precisa de duracao")
        if item["duracao"]["max"] > MAX_DURACAO_EFEITO:
            raise _Invalido(f"efeito com duração máxima acima de {MAX_DURACAO_EFEITO} s "
                            "(efeito é curto: no máximo 30 segundos)")
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


# ---------------------------------------------------------------- quadros de exemplo (passo Estilo)

QUADRO_TAMANHO = (540, 960)
QUADRO_VERSAO = 1            # muda quando o desenho do cartao muda (invalida o cache)
MAX_QUADROS_CACHE = 200      # PNGs de cache por projeto; os mais antigos saem
MAX_QUADROS_TAREFA = 24      # cartoes por tarefa "quadros"
MAX_T = 24 * 3600
FRASE_EXEMPLO = "Olá, tudo bem?"
ABAS = {"paletas": "paleta", "legendas": "legenda", "efeitos": "efeito"}
TIPOS_QUADRO = tuple(ABAS.values())
EXT_VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
TIMEOUT_FFMPEG = 60
MAX_JSON_PROJETO = 32 * 1024 * 1024
_CACHE_RE = re.compile(r"(paleta|legenda|efeito)-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{16}\.png")
_TMP_PREFIXO = ".quadro-"
BRAND_PADRAO = REPO / "brand" / "brand.json"


def _ler_json_projeto(arq: Path):
    """JSON pequeno do projeto (sem link, ate 32 MiB) ou None."""
    try:
        return json.loads(common.ler_limitado(arq, MAX_JSON_PROJETO).decode("utf-8"))
    except (OSError, ValueError, RecursionError, MemoryError):
        return None


def _video(project: Path) -> Path:
    """O ``entrada.*`` do projeto: exatamente um, arquivo comum, sem link, dentro da pasta."""
    root = Path(project).resolve()
    videos = [p for p in sorted(root.glob("entrada.*"))
              if p.suffix.lower() in EXT_VIDEO and p.is_file() and not p.is_symlink()
              and p.resolve().parent == root]
    if len(videos) != 1:
        raise BancoError("o projeto precisa de exatamente um vídeo (envie o vídeo primeiro)")
    return videos[0]


def _ffmpeg(cmd: list[str], what: str) -> None:
    """Roda ffmpeg/ffprobe (lista, sem shell, com tempo limite); erro vira BancoError sem caminhos."""
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_FFMPEG)
    except FileNotFoundError:
        raise BancoError(f"{what}: {cmd[0]} não encontrado (rode scripts/doctor.py)") from None
    except subprocess.TimeoutExpired:
        raise BancoError(f"{what}: tempo esgotado") from None
    except OSError:
        raise BancoError(f"{what}: não foi possível executar o {cmd[0]}") from None
    if proc.returncode != 0:
        raise BancoError(f"{what}: o {cmd[0]} falhou")
    return proc


def duracao(project: Path) -> float:
    """Duracao da linha do tempo CORTADA (a do preview): transcricao + cortes; sem eles,
    a do proprio video (ffprobe)."""
    project = Path(project)
    trans = _ler_json_projeto(project / "transcricao.json")
    dur = trans.get("duration") if isinstance(trans, dict) else None
    if common.is_num(dur) and dur > 0:
        import cut as cutmod
        doc = _ler_json_projeto(project / "cortes.json")
        cuts = doc.get("cuts") if isinstance(doc, dict) else None
        ok = isinstance(cuts, list) and all(
            isinstance(c, dict) and common.is_num(c.get("start")) and common.is_num(c.get("end"))
            for c in cuts)
        keep = cutmod.keep_segments(float(dur), cuts) if ok else [(0.0, float(dur))]
        return round(sum(b - a for a, b in keep), 3)
    proc = _ffmpeg(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", str(_video(project))], "duração do vídeo")
    try:
        d = float(proc.stdout.decode("utf-8", "replace").strip())
    except ValueError:
        raise BancoError("não foi possível ler a duração do vídeo") from None
    if not common.is_num(d) or d <= 0:
        raise BancoError("não foi possível ler a duração do vídeo")
    return round(d, 3)


def t_padrao(project: Path) -> float:
    """Momento padrao dos cartoes: a um terco do video cortado."""
    return round(duracao(project) / 3, 1)


def _tempo(project: Path, t) -> float:
    if isinstance(t, bool) or not isinstance(t, (int, float)) or t != t or abs(t) > MAX_T:
        raise BancoError("o momento do quadro (t) precisa ser um número de segundos")
    dur = duracao(project)
    if not 0 <= t <= dur:
        raise BancoError(f"o momento do quadro precisa ficar entre 0 e {dur:.1f} s do vídeo")
    return round(float(t), 3)


def _tempo_bruto(project: Path, t: float) -> float:
    """Segundo da linha cortada -> segundo do video bruto (mesma conta do quadro:<s> dos efeitos)."""
    import graphics
    try:
        return graphics._tempo_bruto(Path(project).resolve(), float(t), "quadro")
    except graphics.GraphicsError as e:
        raise BancoError(str(e)) from None


def _extrair_quadro(video: Path, bruto: float, size: tuple[int, int], out: Path) -> Path:
    """Um quadro do video em ``bruto`` s, na mesma montagem do render (cobrir + corte central)."""
    import render
    for ss in (bruto, max(0.0, bruto - 0.5), 0.0):  # perto do fim pode nao haver quadro
        _ffmpeg(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", str(video),
                 "-frames:v", "1", "-vf", render._base_filter(size), "-f", "image2",
                 "-c:v", "png", str(out)], "quadro do vídeo")
        if out.is_file() and out.stat().st_size > 0:
            return out
    raise BancoError(f"não foi possível tirar o quadro de {bruto:.2f} s do vídeo")


def _frase_exemplo(project: Path) -> str:
    """A primeira frase da legenda do projeto (com cortes e edicoes), ou a frase padrao."""
    try:
        import captions
        import cut as cutmod
        import render
        dur, words, cuts = render._load_inputs(Path(project))
        kept = captions.remap(words, cutmod.keep_segments(dur, cuts))
        frases, _ = captions.apply_edits(captions.phrases(kept), render.load_edits(Path(project)))
    except Exception:  # sem transcricao ou ilegivel: frase padrao
        return FRASE_EXEMPLO
    for f in frases:
        texto = captions.display_text(f["text"])
        if texto:
            return texto[:200]
    return FRASE_EXEMPLO


def estilo_do_cartao(estilo: dict, tipo: str, item: dict, banco: Banco) -> dict:
    """O estilo atual do projeto com o item do cartao no lugar (validado)."""
    import estilo as estilomod
    est = copy.deepcopy(estilomod.validar(estilo, banco))
    if tipo == "paleta":
        est["paleta"] = item["id"]
    elif tipo == "legenda" and est["legenda"]["estilo"] != item["id"]:
        est["legenda"] = {"estilo": item["id"], "posicao": item["dados"]["posicao_padrao"],
                          "tamanho": item["dados"]["tamanho_padrao"]}
    return estilomod.validar(est, banco)


def _marca_arquivo(arq: Path):
    try:
        st = arq.stat()
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


def _plano(project: Path, tipo, item_id, estilo, t, brand_path, banco) -> dict:
    """Valida tudo (antes de qualquer ffmpeg/navegador) e calcula o nome do cache."""
    import brand as brandmod
    if not isinstance(tipo, str) or tipo not in TIPOS_QUADRO:
        raise BancoError(f"tipo de cartão inválido (use {', '.join(TIPOS_QUADRO)})")
    if not isinstance(item_id, str) or len(item_id) > MAX_ID or not _SLUG.fullmatch(item_id):
        raise BancoError("identificador de item inválido")
    b = banco if banco is not None else carregar()
    item = b.item(tipo, item_id)
    est = estilo_do_cartao(estilo, tipo, item, b)
    t = _tempo(project, t)
    video = _video(project)
    try:
        marca = brandmod.load(Path(brand_path or BRAND_PADRAO))
    except brandmod.BrandMissing:
        raise BancoError("marca ausente ou incompleta (brand/brand.json): "
                         "rode a entrevista de marca na Instalação") from None
    texto = _frase_exemplo(project) if tipo in ("paleta", "legenda") else None
    chave = {"v": QUADRO_VERSAO, "tipo": tipo, "id": item_id,
             "item": {k: item.get(k) for k in ("dados", "campos", "duracao")},
             "estilo": est, "t": t, "texto": texto, "brand": marca,
             "video": [video.name, *(_marca_arquivo(video) or [])],
             "arquivos": {n: _marca_arquivo(Path(project) / n)
                          for n in ("transcricao.json", "cortes.json", "legendas.json")}}
    if tipo == "efeito":
        chave["html"] = _marca_arquivo(Path(item["pasta"]) / "efeito.html")
    bruto = json.dumps(chave, sort_keys=True, ensure_ascii=False, default=str)
    h = hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:16]
    return {"tipo": tipo, "item": item, "estilo": est, "t": t, "video": video, "brand": marca,
            "texto": texto, "banco": b, "nome": f"{tipo}-{item_id}-{h}.png"}


def nome_quadro(project: Path, tipo: str, item_id: str, estilo: dict, t: float, *,
                brand_path: Path | None = None, banco: Banco | None = None) -> str:
    """Nome do PNG de cache que ``quadro`` vai gravar (sem desenhar nada)."""
    return _plano(Path(project), tipo, item_id, estilo, t, brand_path, banco)["nome"]


def _fmt_t(x: float) -> str:
    return (f"{max(0.0, x):.3f}".rstrip("0").rstrip(".")) or "0"


def campos_exemplo(item: dict, t: float, dur: float) -> dict:
    """Campos do cartao de um efeito: ``dados.exemplo`` do manifesto; o que faltar e
    obrigatorio ganha um valor padrao; imagens viram quadros do proprio video (``quadro:<s>``)."""
    ex = dict(item["dados"].get("exemplo") or {})
    out = {}
    for c in item["campos"]:
        cid = c["id"]
        if c["tipo"] == "imagem":
            if "itens" in c:
                n = min(c["itens"]["max"], max(c["itens"]["min"], 3))
                ts = [t, t - 1.5, t + 1.5, t - 3, t + 3, t - 4.5][:n]
                out[cid] = [f"quadro:{_fmt_t(min(dur, x))}" for x in ts]
            elif c["obrigatorio"]:
                out[cid] = f"quadro:{_fmt_t(t)}"
            continue
        if cid in ex:
            out[cid] = ex[cid]
            continue
        if not c["obrigatorio"] and not ("itens" in c and c["itens"]["min"] > 0):
            continue
        if c["tipo"] == "texto":
            v = c["rotulo"][:int(c.get("max", 60))]
        elif c["tipo"] == "numero":
            v = c.get("min", 1)
        elif c["tipo"] == "cor":
            v = "#a8c8f0"
        else:  # escolha
            v = c["opcoes"][0]
        out[cid] = [v] * max(1, c["itens"]["min"]) if "itens" in c else v
    return out


def _png_rgba(dados: bytes, size: tuple[int, int]):
    import io

    from PIL import Image
    img = Image.open(io.BytesIO(dados)).convert("RGBA")
    return img if img.size == size else img.resize(size)


def _camada_efeito(project: Path, efeito_id: str, item: dict, brand: dict, t: float,
                   size: tuple[int, int]):
    import graphics
    campos = campos_exemplo(item, t, duracao(project))
    q = graphics.inspect_effect(efeito_id, campos, brand, project=project, size=size)
    return _png_rgba(q["png"], size)


def _com_legenda(img, texto: str, brand: dict, est: dict, size: tuple[int, int], td: Path):
    """A legenda de exemplo pelo MESMO caminho do render: libass (ASS de ``captions.to_ass``)
    ou, sem libass, o PNG de ``legendas_imagem.draw`` sobreposto."""
    import captions
    import legendas_imagem
    import render
    if not render.has_libass():
        out = img.copy()
        out.alpha_composite(legendas_imagem.draw(texto, brand, size, est))
        return out
    from PIL import Image
    base, ass, saida = td / "base.png", td / "legenda.ass", td / "com-legenda.png"
    img.convert("RGB").save(base)
    frase = [{"text": texto, "start": 0.0, "end": 5.0}]
    ass.write_text(captions.to_ass(frase, brand, size=size, estilo=est), encoding="utf-8")
    _ffmpeg(["ffmpeg", "-nostdin", "-y", "-v", "error", "-loop", "1", "-framerate", "10",
             "-i", str(base), "-vf", render._subtitles_filter(ass), "-ss", "0.5",
             "-frames:v", "1", "-f", "image2", "-c:v", "png", str(saida)], "legenda de exemplo")
    with Image.open(saida) as im:
        return im.convert("RGBA")


def _desenhar(project: Path, plano: dict, td: Path):
    import estilo as estilomod
    import graphics
    from PIL import Image
    size = QUADRO_TAMANHO
    frame = _extrair_quadro(plano["video"], _tempo_bruto(project, plano["t"]), size, td / "quadro.png")
    with Image.open(frame) as im:
        img = im.convert("RGBA")
    if img.size != size:
        img = img.resize(size)
    b, tipo, item = plano["banco"], plano["tipo"], plano["item"]
    brand = estilomod.aplicar_marca(plano["brand"], plano["estilo"], b)
    if tipo == "efeito":
        img.alpha_composite(_camada_efeito(project, item["id"], item, brand, plano["t"], size))
        return img
    if tipo == "paleta":  # um card de exemplo nas cores da paleta (sem navegador: so a legenda)
        try:
            card = b.item("efeito", graphics.EFEITO_LEGADO)
            img.alpha_composite(_camada_efeito(project, card["id"], card, brand, plano["t"], size))
        except (BancoError, graphics.GraphicsError) as e:
            print(f"aviso: cartão da paleta {item['nome']} sem o card de exemplo: {e}",
                  file=sys.stderr)
    return _com_legenda(img, plano["texto"], brand, plano["estilo"], size, td)


def _pasta_quadros(project: Path, out: Path) -> Path:
    root = Path(project).resolve()
    out = Path(out)
    if out.is_symlink():
        raise BancoError("a pasta dos quadros não pode ser um link")
    out.mkdir(parents=True, exist_ok=True)
    real = out.resolve()
    if not (real == root or real.is_relative_to(root)) or not real.is_dir():
        raise BancoError("a pasta dos quadros precisa ficar dentro do projeto")
    return real


def _podar(pasta: Path, manter: Path) -> None:
    """Mantem no maximo MAX_QUADROS_CACHE PNGs de cache (os mais novos); temporarios velhos saem."""
    agora = time.time()
    cache = []
    for p in pasta.iterdir():
        try:
            if p.name.startswith(_TMP_PREFIXO) and p.is_file() and agora - p.stat().st_mtime > 600:
                p.unlink()
            elif _CACHE_RE.fullmatch(p.name) and p.is_file() and not p.is_symlink():
                cache.append((p.stat().st_mtime_ns, p.name, p))
        except OSError:
            continue
    cache.sort()
    sobra = len(cache) - MAX_QUADROS_CACHE
    for _, _, p in cache:
        if sobra <= 0:
            break
        if p == manter:
            continue
        try:
            p.unlink()
            sobra -= 1
        except OSError:
            pass


def quadro(project: Path, tipo: str, item_id: str, estilo: dict, t: float, out: Path, *,
           brand_path: Path | None = None, banco: Banco | None = None) -> Path:
    """Cartao do passo Estilo: PNG 540x960 de um quadro do video do usuario no segundo ``t``
    (linha do tempo cortada) com o item aplicado sobre o ``estilo`` atual do projeto.

    ``tipo``: paleta (cores aplicadas, legenda de exemplo e um card), legenda (a legenda de
    exemplo pelo mesmo caminho do render, libass ou por imagem) ou efeito
    (``graphics.inspect_effect`` composto sobre o quadro). ``out``: a pasta do cache
    (``projects/<slug>/quadros``), dentro do projeto. Devolve o caminho do PNG; se ja existe
    (mesmo tipo, item, estilo, t, video, transcricao e marca), devolve o do cache sem desenhar."""
    project = Path(project)
    plano = _plano(project, tipo, item_id, estilo, t, brand_path, banco)
    pasta = _pasta_quadros(project, out)
    dest = pasta / plano["nome"]
    if dest.is_file() and not dest.is_symlink():
        return dest
    fd, nome = tempfile.mkstemp(prefix=_TMP_PREFIXO, suffix=".tmp.png", dir=pasta)
    os.close(fd)
    tmp = Path(nome)
    try:
        with tempfile.TemporaryDirectory(prefix="reel-quadro-") as td:
            img = _desenhar(project, plano, Path(td))
        img.convert("RGB").save(tmp, "PNG")
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    _podar(pasta, dest)
    return dest


def _cli_quadros(a) -> None:
    import estilo as estilomod
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # cancelar: limpa temporarios
    project = Path(a.project)
    try:
        b = carregar()
        est = estilomod.carregar(project, b)
        t = a.t if a.t is not None else t_padrao(project)
        itens = b.itens(ABAS[a.aba])[:MAX_QUADROS_TAREFA]
    except (BancoError, ValueError, OSError) as e:
        common.fail(str(e))
    if not itens:
        common.fail("não há itens nesta aba do banco")
    falhas = []
    for i, it in enumerate(itens, 1):
        print(f"cartão {i} de {len(itens)}: {it['nome']}", flush=True)
        try:
            p = quadro(project, ABAS[a.aba], it["id"], est, t, project / "quadros",
                       brand_path=a.brand, banco=b)
            print(f"pronto: quadros/{p.name}", flush=True)
        except Exception as e:  # um cartao ruim nao derruba os outros; nunca traceback
            print(f"aviso: {it['nome']}: {e}", flush=True)
            falhas.append(it["nome"])
    if falhas:
        common.fail(f"não foi possível gerar {len(falhas)} de {len(itens)} cartões: "
                    f"{', '.join(falhas)}")
    print(f"{len(itens)} cartões prontos", flush=True)


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
    pq = sub.add_parser("quadros", help="gera os cartões de uma aba do passo Estilo")
    pq.add_argument("project", type=Path)
    pq.add_argument("--aba", required=True, choices=sorted(ABAS))
    pq.add_argument("--t", type=float, default=None)
    pq.add_argument("--brand", type=Path, default=BRAND_PADRAO)
    a = p.parse_args(argv)
    if a.cmd == "quadros":
        return _cli_quadros(a)
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
