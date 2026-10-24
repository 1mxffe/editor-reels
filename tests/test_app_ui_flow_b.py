"""Telas Gráficos (com a aba Materiais) e Capa dirigidas por Chromium headless.

O driver (tests/js/app_flow_b.mjs) sobe o app/server.py REAL em modo de teste. Os
projetos ja chegam aqui com video, fala, cortes, legendas confirmadas e preview
(montados em Python, sem Whisper nem render), para o teste ir direto aos passos
novos. A capa usa os scripts de verdade (cover_frames.py e cover_compose.py, com
Chromium). Sem node/Chromium/ffmpeg os testes sao pulados.
"""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import test_app_ui_shell as shell
from fixtures_app import montar_projeto
import projects as projects_mod
from projects import Projects

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "js" / "app_flow_b.mjs"
SCREENS = REPO / ".superpowers" / "sdd" / "2026-10-23-interface-web" / "screens-t9"
TELAS = ["graficos", "materiais", "capa"]
SVG_MAL = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
           '<script>document.title="svg-rodou";parent.document.title="svg-rodou"</script>'
           '<rect width="64" height="64" fill="#235587"/></svg>')


def _foto_sintetica(path):
    """Retrato falso: fundo, 'rosto' claro com olhos e boca (nitido para os candidatos)."""
    img = Image.new("RGB", (900, 1600), (24, 52, 84))
    d = ImageDraw.Draw(img)
    d.ellipse((270, 300, 630, 760), fill=(226, 184, 150))
    d.ellipse((360, 450, 410, 500), fill=(30, 30, 30))
    d.ellipse((490, 450, 540, 500), fill=(30, 30, 30))
    d.arc((370, 560, 530, 680), 20, 160, fill=(150, 40, 40), width=10)
    d.rectangle((200, 800, 700, 1600), fill=(10, 25, 49))
    img.save(path)


def _projeto_pronto(root, nome, video):
    """Projeto com tudo antes de Gráficos pronto: video, fala, cortes, legendas, preview."""
    slug = Projects(root).create(nome)["slug"]
    d = root / slug
    montar_projeto(d)
    shutil.copy(video, d / "entrada.mp4")
    (d / "etapas.json").write_text(json.dumps({"legendas": True,
                                               "legendas_base": projects_mod.impressao(d)}), "utf-8")
    projects_mod.registrar_origem(d, "preview")
    time.sleep(0.02)
    shutil.copy(video, d / "saida" / "preview.mp4")
    return slug


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    missing = shell._requirements()
    if missing:
        pytest.skip(f"telas de gráficos e capa nao testadas: {missing}")
    tmp = tmp_path_factory.mktemp("app_flow_b")
    video = tmp / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=720x1280:rate=30:duration=6",
                    "-c:v", "libvpx-vp9", "-b:v", "300k", "-an", str(video)],
                   check=True, capture_output=True)
    foto = tmp / "Retrato do Dr Silva.png"
    _foto_sintetica(foto)
    svg = tmp / "icone com script.svg"
    svg.write_text(SVG_MAL, "utf-8")
    roots = {"com": tmp / "com" / "projects", "sem": tmp / "sem" / "projects"}
    for r in roots.values():
        r.mkdir(parents=True)
    slugs = {"graficos": _projeto_pronto(roots["com"], "Reel gráficos", video),
             "capa": _projeto_pronto(roots["com"], "Reel capa", video),
             "semArroba": _projeto_pronto(roots["sem"], "Reel sem arroba", video)}
    marca = json.loads((REPO / "brand" / "brand.json").read_text("utf-8"))
    brands = {}
    for k, h in (("com", ["@gutmannesilva"]), ("sem", [])):
        p = tmp / f"brand-{k}.json"
        p.write_text(json.dumps({**marca, "handles": h}), "utf-8")
        brands[k] = str(p)
    cfg = {"tmp": str(tmp), "screens": str(SCREENS), "foto": str(foto), "svg": str(svg),
           "roots": {k: str(v) for k, v in roots.items()}, "brands": brands, "slugs": slugs,
           "mensagens_js": str(REPO / "app" / "web" / "mensagens.js")}
    (tmp / "cfg.json").write_text(json.dumps(cfg), "utf-8")
    r = subprocess.run(["node", str(DRIVER), str(tmp / "cfg.json")], capture_output=True,
                       text=True, env=shell._node_env(), timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    out["_roots"] = {k: str(v) for k, v in roots.items()}
    out["_slugs"] = slugs
    return out


def _ok(results, name):
    res = results[name]
    assert "error" not in res, res.get("error")
    assert not res.get("erros"), res.get("erros")
    return res


# ------------------------------------------------------------------ gráficos
def test_graphics_form_and_remove(results):
    r = _ok(results, "graficos")
    assert r["bloqueado"] is False, "Gráficos abre depois do Preview"
    # materiais: nome limpo, miniatura por <img> do endereco do arquivo, svg nunca embutido
    assert r["materiais"] == ["Retrato-do-Dr-Silva.png", "icone-com-script.svg"]
    assert all("/arquivos/materiais/" in s and "t=" in s for s in r["miniaturas"]), r["miniaturas"]
    assert r["svgEmbutido"] == 0, "nenhum <svg> de material dentro da página"
    assert r["tituloPagina"] != "svg-rodou" and r["tituloSvgAberto"] != "svg-rodou"
    assert r["materiaisDepoisApagar"] == ["Retrato-do-Dr-Silva.png"]
    # cards: adicionar, editar, erro claro, manter/remover, remover
    assert r["erroVazio"] == "Escreva o título do card."
    assert "até 60 letras" in r["erroServidor"] and "No card" in r["erroServidor"], r["erroServidor"]
    assert r["textoNaoSumiu"] == "x" * 61
    cards = r["depoisAdicionar"]
    assert [c["title"] for c in cards] == ["Prazo de 15 dias úteis", "Guarde os comprovantes"]
    assert cards[0]["material"] == "materiais/Retrato-do-Dr-Silva.png"
    assert cards[0]["at"] == pytest.approx(1.5) and cards[0]["dur"] == 4
    assert cards[1]["body"] is None and cards[1]["material"] is None
    assert r["depoisEditar"][0]["title"] == "Prazo de 15 dias corridos"
    assert r["decisaoFora"] == "drop" and r["listaFica"] == "false"
    assert r["decisaoVolta"] == "keep"
    assert [c["title"] for c in r["depoisRemover"]] == ["Prazo de 15 dias corridos"]
    assert r["itensNaTela"] == 1
    assert r["passoGraficos"] == "pronto"


# ---------------------------------------------------------------------- capa
def test_cover_flow_select_frame_and_generate(results):
    r = _ok(results, "capa")
    assert r["candidatos"] == 3
    assert r["escolhido"] == "capa/candidato-2.png"
    assert r["imgsCandidatos"] == 3 and all(w > 0 for w in r["larguras"]), r["larguras"]
    assert r["pronta"]["naturalWidth"] == 1080 and r["pronta"]["naturalHeight"] == 1920
    assert r["baixar"]["download"] == "reel-capa.png" and "/arquivos/capa/capa.png" in r["baixar"]["href"]
    d = Path(results["_roots"]["com"]) / results["_slugs"]["capa"]
    with Image.open(d / "capa" / "capa.png") as img:
        assert img.size == (1080, 1920)
    assert r["passoCapa"] == "pronto"
    # foto dos materiais vira mais um quadro, ja escolhido
    assert r["fotoEscolhida"] == "capa/foto.png"
    # erro do script chega por extenso, traduzido
    assert "até 28 letras" in r["erroGancho"] and "39" in r["erroGancho"], r["erroGancho"]
    assert r["finalBloqueado"] is False
    assert r["ganchoDepoisF5"].startswith("GANCHO") and r["escolhidoDepoisF5"] == "capa/foto.png"
    assert r["escolhidosDepoisAchar"] == 0, "quadros novos: escolha antiga apagada"


def test_cover_no_smile_detection_notice(results):
    r = _ok(results, "capa")
    aviso = r["avisoSorriso"]
    assert "não reconhece sorriso" in aviso and "você escolhe" in aviso, aviso
    s = _ok(results, "semArroba")
    assert "@" in s["aviso"] and "Instalação" in s["botao"]
    assert s["gerarDesligado"] is True
    assert "salve o @" in s["falta"]
    assert s["depoisClique"] == "instalacao"
    # Graficos e Capa vazios nao travam o Final
    assert s["passos"]["final"]["bloqueado"] is False
    assert s["passos"]["graficos"]["bloqueado"] is False and s["passos"]["capa"]["bloqueado"] is False


# ---------------------------------------------------------- texto e layout
def test_graphics_cover_screens_have_no_jargon(results):
    telas = _ok(results, "visivel")["telas"]
    assert set(TELAS) <= set(telas), telas.keys()
    for tela, texto in telas.items():
        achados = sorted({m.group(0) for m in shell.PROIBIDOS.finditer(texto)})
        assert not achados, (tela, achados)
        for termo in ("svg+xml", "graficos.json", "materiais/", "capa/", "candidato-", "upload", "render"):
            assert termo not in texto, (tela, termo)
        assert not re.search(r"\b(null|undefined|NaN)\b", texto), tela


def test_messages_for_graphics_and_cover_translated(results):
    r = _ok(results, "mensagens")
    d = dict(r["pares"])
    assert d["gancho não cabe em 2 linhas: encurte"] == "O gancho não cabe em 2 linhas na capa. Encurte o texto."
    for bruto, texto in r["pares"]:
        achados = sorted({m.group(0) for m in shell.PROIBIDOS.finditer(texto)})
        assert not achados, (bruto, texto)
        assert texto != r["generica"], bruto
        assert "json" not in texto.lower() and "/" not in texto, (bruto, texto)


def test_graphics_cover_no_horizontal_scroll_375(results):
    r = _ok(results, "scroll375")
    assert set(TELAS) <= set(r["medidas"])
    for tela, m in r["medidas"].items():
        assert m["scrollWidth"] <= m["clientWidth"], (tela, m)
        assert m["bodyScroll"] <= m["clientWidth"], (tela, m)
    pequenos = [a for a in r["alvos"] if a["h"] < 44 or a["w"] < 44]
    assert not pequenos, pequenos


def test_screenshots_written(results):
    _ok(results, "scroll375")
    for tela in TELAS:
        for largura in (1280, 375):
            assert (SCREENS / f"{tela}-{largura}.png").is_file(), (tela, largura)
