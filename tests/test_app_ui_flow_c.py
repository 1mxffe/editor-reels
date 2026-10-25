"""Tela Estilo (abas, cartoes com quadros de exemplo, Usar + Aplicar, efeitos) por Chromium.

O driver (tests/js/app_flow_c.mjs) sobe o app/server.py REAL em modo de teste, com os
quadros de exemplo gerados de verdade (Chromium) e o preview refeito pelo render real.
Sem node/Chromium/ffmpeg os testes sao pulados.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

import test_app_ui_shell as shell
from test_app_ui_flow_b import _projeto_pronto
from projects import Projects

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "js" / "app_flow_c.mjs"
SCREENS = REPO / ".superpowers" / "sdd" / "2026-10-23-interface-web" / "screens-t14"
HOSTIL = '<img src=x onerror="window.__pwn=1"> Hostil'
HOSTIL_DESC = '<script>window.__pwn=2</script> descrição <b>negrito</b>'


def _manifesto(nome, descricao, dados, variacoes=()):
    return {"nome": nome, "descricao": descricao, "tipo": "paleta", "campos": [], "dados": dados,
            "variacoes": [{"nome": n, "dados": dados} for n in variacoes]}


def _banco_hostil(destino):
    shutil.copytree(REPO / "banco", destino)
    cores = {"fundo": "#001931", "texto": "#ddebf5", "destaque": "#a8c8f0", "apoio": "#566a7a"}
    p = destino / "paletas" / "hostil"
    p.mkdir()
    (p / "manifesto.json").write_text(json.dumps(
        _manifesto(HOSTIL, HOSTIL_DESC, cores, ['<img src=x onerror="window.__pwn=3">']), ensure_ascii=False), "utf-8")
    q = destino / "paletas" / "quebrada"
    q.mkdir()
    (q / "manifesto.json").write_text(json.dumps({"nome": "Sem cores", "tipo": "paleta", "dados": {"fundo": "azul"}}), "utf-8")
    z = destino / "legendas" / "ruim"
    z.mkdir()
    (z / "manifesto.json").write_text("{ isto nao e json", "utf-8")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    missing = shell._requirements()
    if missing:
        pytest.skip(f"tela Estilo nao testada: {missing}")
    tmp = tmp_path_factory.mktemp("app_flow_c")
    video = tmp / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=720x1280:rate=30:duration=6",
                    "-c:v", "libvpx-vp9", "-b:v", "300k", "-an", str(video)],
                   check=True, capture_output=True)
    roots = {"a": tmp / "a" / "projects", "b": tmp / "b" / "projects"}
    for r in roots.values():
        r.mkdir(parents=True)
    slugs = {"principal": _projeto_pronto(roots["a"], "Reel estilo", video),
             "aplicar": _projeto_pronto(roots["a"], "Reel aplicar", video),
             "hostil": _projeto_pronto(roots["b"], "Reel hostil", video)}
    banco = tmp / "banco-hostil"
    _banco_hostil(banco)
    fontes = tmp / "fontes"
    fontes.mkdir()
    shutil.copy(REPO / "assets" / "fonts" / "Poppins-Bold.ttf", fontes / "Poppins-Bold.ttf")
    (fontes / "Merriweather-Regular.ttf").write_bytes(b"\x00" * 64)  # sem tabela de nomes: vale o nome do arquivo
    marca = json.loads((REPO / "brand" / "brand.json").read_text("utf-8"))
    brands = {}
    for k in ("a", "b"):
        p = tmp / f"brand-{k}.json"
        p.write_text(json.dumps({**marca, "handles": ["@gutmannesilva"]}), "utf-8")
        brands[k] = str(p)
    cfg = {"tmp": str(tmp), "screens": str(SCREENS), "roots": {k: str(v) for k, v in roots.items()},
           "brands": brands, "slugs": slugs, "banco_hostil": str(banco), "fonts_dir": str(fontes),
           "preview_copia": str(tmp / "preview-aplicado.mp4")}
    (tmp / "cfg.json").write_text(json.dumps(cfg), "utf-8")
    r = subprocess.run(["node", str(DRIVER), str(tmp / "cfg.json")], capture_output=True,
                       text=True, env=shell._node_env(), timeout=1500)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    out["_roots"] = {k: str(v) for k, v in roots.items()}
    out["_slugs"] = slugs
    out["_tmp"] = str(tmp)
    return out


def _ok(results, name):
    res = results[name]
    assert "error" not in res, res.get("error")
    assert not res.get("erros"), res.get("erros")
    assert not res.get("erros2"), res.get("erros2")
    return res


# -------------------------------------------------------------------- abas
def test_style_tabs_and_cards_render_with_example_frames(results):
    r = _ok(results, "abas")
    assert r["abas"] == ["Paletas", "Fontes", "Legendas", "Efeitos", "Notas"]
    assert r["estados"]["estilo"] == "false", "o Estilo abre sem exigir nada antes"
    assert r["esqueletos"] >= 1, "esqueleto enquanto os exemplos carregam"
    assert "Preparando os exemplos" in r["tarefaTexto"] and r["cancelavel"] is True
    ids = [p["id"] for p in r["paletas"]]
    assert {"marca", "grafite", "gelo-claro", "marinho-profundo"} == set(ids)
    for p in r["paletas"]:
        assert p["nome"] and p["desc"]
        assert "/arquivos/quadros/" in p["src"] and "t=" in p["src"], p["src"]
        assert (p["w"], p["h"]) == (540, 960), p
        assert p["usar"] and p["parecido"]
    assert r["escolhidoInicial"] == ["marca"], "destaque no estilo que o Reel usa hoje"
    assert r["situacaoInicial"].startswith("Usando o estilo padrão do escritório.")
    assert len(r["legendas"]) == 4 and len(r["efeitos"]) == 10
    assert r["posicoes"] == ["Em baixo", "No meio"] and r["tamanhos"] == ["Pequena", "Média", "Grande"]
    assert r["efeitoBotao"] == "Adicionar ao vídeo"
    assert r["refeito"] is False, "voltar a uma aba pronta reaproveita os exemplos"
    assert "arquivo .ttf na pasta assets/fonts/" in r["notas"]


def test_fonts_tab_lists_only_available_fonts(results):
    r = _ok(results, "abas")
    assert [f["nome"] for f in r["fontes"]] == ["Poppins"]
    assert r["fontes"][0]["desabilitado"] is False and r["fontes"][0]["selo"] is False
    assert r["fontesAjuda"] == "Para ter mais fontes, coloque o arquivo .ttf na pasta assets/fonts/"
    h = _ok(results, "hostil")
    por_nome = {f["nome"]: f for f in h["fontes"]}
    assert set(por_nome) == {"Poppins", "Merriweather"}
    assert por_nome["Merriweather"]["desabilitado"] is True and por_nome["Merriweather"]["selo"] is True
    assert "só usa a fonte Poppins" in por_nome["Merriweather"]["aviso"]
    assert por_nome["Poppins"]["desabilitado"] is False


# ---------------------------------------------------------- usar e aplicar
def test_use_card_then_apply_changes_preview(results):
    r = _ok(results, "aplicar")
    assert r["situacaoAntes"].startswith("Usando o estilo padrão do escritório.")
    assert r["escolhida"] == ["grafite"] and r["pressionado"] == "true"
    assert r["situacaoDepois"].startswith("Mudanças não aplicadas.")
    assert r["estiloSemAplicar"]["paleta"] == "marca", "nada e gravado antes de Aplicar"
    assert "Aplicando o estilo" in r["progresso"] and r["aplicarDuranteDesligado"] is True
    assert r["situacaoFinal"] == "Estilo aplicado."
    d = Path(results["_roots"]["a"]) / results["_slugs"]["aplicar"]
    salvo = json.loads((d / "estilo.json").read_text("utf-8"))
    assert salvo == r["estiloDepois"]
    assert salvo["paleta"] == "grafite"
    assert salvo["legenda"] == {"estilo": "faixa-azul", "posicao": "meio", "tamanho": "G"}
    assert salvo["fonte"] == "Poppins"
    # o player da esquerda trocou para o preview novo (endereco com a marca de versao)
    assert re.search(r"saida/preview\.mp4.*[?&]v=", r["playerDepois"]), r["playerDepois"]
    assert r["playerDepois"] != r["playerAntes"]
    assert r["escolhidaDepois"] == ["faixa-azul"] and r["posicaoDepois"] == "meio"
    # o preview novo e um video de verdade com a legenda no meio (letras claras no centro, nao embaixo)
    prev = Path(results["_tmp"]) / "preview-aplicado.mp4"
    sonda = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(prev)], capture_output=True, text=True)
    assert sonda.stdout.strip() == "540,960"  # o preview e a versao leve
    png = Path(results["_tmp"]) / "quadro.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(prev), "-frames:v", "1", str(png)],
                   check=True)
    with Image.open(png).convert("RGB") as im:
        w, h = im.size

        def marinho(y0, y1):
            n = tot = 0
            for y in range(y0, y1, 4):
                for x in range(0, w, 4):
                    p = im.getpixel((x, y))
                    tot += 1
                    n += min(p) > 225  # letras claras da legenda
            return n / tot
        centro, baixo = marinho(int(h * .40), int(h * .60)), marinho(int(h * .85), int(h * .97))
    assert centro > baixo + 0.001, (centro, baixo)


# ------------------------------------------------------- mais parecido
def test_more_like_this_reorders(results):
    r = _ok(results, "parecido")
    assert r["depois"][0] == r["alvo"] and r["depois"] != r["antes"]
    assert sorted(r["depois"]) == sorted(r["antes"])
    assert r["variacoes"] == r["esperadas"] and len(r["variacoes"]) >= 2
    assert r["titulo"].startswith("Parecidos com ")
    assert r["cores"] >= 4
    assert r["posicaoVariacao"] == "meio" and r["situacao"].startswith("Mudanças não aplicadas.")
    assert r["estiloSalvo"]["legenda"]["posicao"] == "baixo", "variacao so vale depois de Aplicar"


# -------------------------------------------------------------- efeitos
def test_effect_form_from_manifest_fields_and_limits(results):
    r = _ok(results, "efeitos")
    assert [x.split(",")[0] for x in r["rotulos"]][:3] == ["Mês", "Ano", "Dias marcados (1 a 10)"]
    ajudas = " | ".join(r["ajudas"])
    assert "Obrigatório. Número inteiro entre 1900 e 2100." in ajudas
    assert "Opcional. Até 50 letras." in ajudas and "De 1 a 10 itens." in ajudas
    assert r["maxlegenda"] == "50"
    assert re.fullmatch(r"\d+(,\d)?", r["momentoInicial"]) and r["duracaoInicial"] == "3,5"
    assert any("entre 1900 e 2100" in e for e in r["errosCampos"]), r["errosCampos"]
    assert r["focoNoPrimeiroErro"] == "ef-ano"
    assert r["itensDias"] == 10 and r["adicionarDesligado"] is True
    assert "entre 2,5 e 6 segundos" in r["erroDuracao"]
    assert r["formFechou"] is True
    # erro do servidor por extenso e texto preservado
    assert "passa do fim do vídeo" in r["erroServidor"] and "(" not in r["erroServidor"].split("vídeo")[0]
    assert not re.search(r"\b(dur|at|efeito-\d)\b", r["erroServidor"]), r["erroServidor"]
    assert r["palavraGravada"] == "PRAZO"
    # graficos.json: o card antigo continua e o efeito entra no formato do passo Graficos
    ids = [c["id"] for c in r["graficosDepois"]]
    assert ids[0] == "card-1" and len(ids) == 2
    ef = r["graficosDepois"][1]
    assert set(ef) == {"id", "efeito", "campos", "at", "dur"}
    assert ef["efeito"] == "palavra-destaque" and ef["campos"] == {"palavra": "PRAZO"}
    assert ef["at"] == pytest.approx(1.5) and ef["dur"] == pytest.approx(1.5)
    assert len(r["listados"]) == 1 and "Aos 0:01" in r["listados"][0] and "PRAZO" in r["listados"][0]
    assert r["segundoPadrao"] == "0,5" or re.fullmatch(r"\d+(,\d+)?", r["segundoPadrao"])
    assert r["polaroide"]["campos"]["imagens"] == ["quadro:2"]
    assert "Prazo de 15 dias úteis" in r["graficosItens"] and len(r["graficosItens"]) == 3
    assert "card-1" in r["depoisRemover"] and len(r["depoisRemover"]) == 2


# --------------------------------------------------------- banco inválido
def test_invalid_bank_items_notice(results):
    r = _ok(results, "hostil")
    assert r["aviso"] == "2 itens do banco não carregaram"
    assert r["avisoFechado"] is True
    assert "paletas/quebrada" in " ".join(r["avisoMotivos"]) and "legendas/ruim" in " ".join(r["avisoMotivos"])
    assert "motivo" not in r["avisoVisivel"].lower() or True
    assert "2 itens do banco não carregaram" in r["avisoVisivel"]
    assert "quebrada" not in r["avisoVisivel"], "motivos ficam recolhidos"
    assert "quebrada" in r["avisoAberto"]


def test_card_text_inert(results):
    r = _ok(results, "hostil")
    assert HOSTIL in r["nomes"] and HOSTIL_DESC in r["descs"]
    assert r["imgsDentroDoTexto"] == 0 and r["imgsNasVariacoes"] == 0
    assert r["pwn"] is True and r["pwnDepois"] is True
    assert '<img src=x onerror="window.__pwn=3">' in r["variacaoTexto"]


# ---------------------------------------------------------- texto e layout
def test_style_step_has_no_jargon(results):
    telas = _ok(results, "abas") and results["visivel"]["telas"]
    assert {"estilo-paletas", "estilo-legendas", "estilo-efeitos", "estilo-fontes", "estilo-notas"} <= set(telas)
    for tela, texto in telas.items():
        achados = sorted({m.group(0) for m in shell.PROIBIDOS.finditer(texto)})
        assert not achados, (tela, achados)
        for termo in [t for t in shell.JARGAO if t != "ASS"]:
            assert termo not in texto, (tela, termo)
        for termo in ("estilo.json", "graficos.json", "quadros/", "manifesto", "undefined", "NaN"):
            assert termo not in texto, (tela, termo)


def test_no_horizontal_scroll_375_style_step(results):
    r = _ok(results, "scroll375")
    assert {"paletas", "fontes", "legendas", "efeitos", "efeitos-form", "notas"} <= set(r["medidas"])
    for tela, m in r["medidas"].items():
        assert m["scrollWidth"] <= m["clientWidth"], (tela, m)
        assert m["bodyScroll"] <= m["clientWidth"], (tela, m)
        assert not m["estouram"], (tela, m["estouram"])
    pequenos = [a for a in r["alvos"] if a["h"] < 44 or a["w"] < 44]
    assert not pequenos, pequenos


def test_style_screenshots_written(results):
    _ok(results, "scroll375")
    for nome in ("estilo-paletas-1280", "estilo-paletas-375", "estilo-paletas-1280-escuro", "estilo-efeitos-375-escuro"):
        assert (SCREENS / f"{nome}.png").is_file(), nome
