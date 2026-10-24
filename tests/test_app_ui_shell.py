"""Casca da pagina do app (app/web) dirigida por Chromium headless contra o servidor real.

O driver e Node + Playwright (tests/js/app_shell.mjs), que sobe o app/server.py de
verdade em porta efemera (tests/js/serve_for_test.py) e devolve observacoes em JSON;
cada teste afirma sobre o seu cenario. Sem node/Chromium/ffmpeg os testes de tela
sao pulados; as checagens estaticas e as do servidor rodam sempre.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest_app import client
from server import make_server

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "app" / "web"
DRIVER = REPO / "tests" / "js" / "app_shell.mjs"
BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
SCREENS = REPO / ".superpowers" / "sdd" / "2026-10-23-interface-web" / "screens"
MAX_UPLOAD = 2 * 1024 * 1024
PASSOS = ["video", "cortes", "legendas", "estilo", "preview", "graficos", "capa", "final"]
PROIBIDOS = re.compile(r"\b(ffmpeg|ffprobe|chromium|playwright|node|pillow|whisper|token|api|json|"
                       r"job|tarefa|ass|srt|codec)\b", re.IGNORECASE)
JARGAO = ("transcri", "ASS", "ffmpeg", "ffprobe", "slug", "JSON", "render", "upload", "job")


def _node_env():
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=BROWSERS)
    cands = [env.get("NODE_PATH", ""), "/usr/local/lib/node_modules_global", "/node-tools/node_modules"]
    if shutil.which("npm"):
        try:
            cands.append(subprocess.run(["npm", "root", "-g"], capture_output=True, text=True,
                                        timeout=20).stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    env["NODE_PATH"] = os.pathsep.join(c for c in cands if c)
    return env


def _requirements():
    for prog in ("node", "ffmpeg", "ffprobe"):
        if shutil.which(prog) is None:
            return f"{prog} ausente"
    probe = subprocess.run(
        ["node", "-e", "const {chromium}=require('playwright');"
                       "process.stdout.write(require('fs').existsSync(chromium.executablePath())?'ok':'no')"],
        capture_output=True, text=True, env=_node_env(), timeout=30)
    if probe.returncode != 0:
        return "playwright (node) ausente"
    if probe.stdout != "ok":
        return f"Chromium do Playwright ausente em {BROWSERS}"
    return None


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    missing = _requirements()
    if missing:
        pytest.skip(f"casca da pagina nao testada: {missing}")
    tmp = tmp_path_factory.mktemp("app_shell")
    marca = json.loads((REPO / "brand" / "brand.json").read_text("utf-8"))
    (tmp / "brand_ok.json").write_text(json.dumps(dict(marca, handles=["@gutmannesilva"])), "utf-8")
    (tmp / "brand_falta.json").write_text(json.dumps(dict(marca, handles=[])), "utf-8")
    video = tmp / "video.mp4"
    # VP9 em MP4 (o Chromium do Playwright nao tem H.264); ~500 KB para o envio lento
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=360x640:rate=30:duration=12",
                    "-c:v", "libvpx-vp9", "-b:v", "400k", "-an", str(video)],
                   check=True, capture_output=True)
    assert 300_000 < video.stat().st_size < MAX_UPLOAD, video.stat().st_size
    (tmp / "lixo.mp4").write_bytes(b"isto nao e um video " * 50)
    (tmp / "grande.mp4").write_bytes(os.urandom(MAX_UPLOAD + 512 * 1024))
    cfg = {"tmp": str(tmp), "brand_ok": str(tmp / "brand_ok.json"),
           "brand_falta": str(tmp / "brand_falta.json"), "video": str(video),
           "lixo": str(tmp / "lixo.mp4"), "grande": str(tmp / "grande.mp4"),
           "max_upload": MAX_UPLOAD, "screens": str(SCREENS)}
    (tmp / "cfg.json").write_text(json.dumps(cfg), "utf-8")
    r = subprocess.run(["node", str(DRIVER), str(tmp / "cfg.json")], capture_output=True,
                       text=True, env=_node_env(), timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _ok(results, name):
    res = results[name]
    assert "error" not in res, res.get("error")
    assert not res.get("erros"), res.get("erros")
    return res


# ------------------------------------------------------------------ tela
def test_shell_two_columns_and_stepper(results):
    r = _ok(results, "shell")
    player, painel = r["player"], r["painel"]
    assert player["x"] < painel["x"], "player deve ficar a esquerda do painel"
    assert player["x"] + player["width"] <= painel["x"] + 1
    assert abs(player["y"] - painel["y"]) < 40, "as duas colunas comecam na mesma altura"
    assert 300 <= player["width"] <= 440
    assert [p["id"] for p in r["passos"]] == PASSOS
    assert [p["texto"].split("\n")[0] for p in r["passos"]]
    assert all(p["estado"] in ("pendente", "andamento", "pronto") for p in r["passos"])
    textos = " ".join(p["texto"] for p in r["passos"])
    for titulo in ("Vídeo", "Cortes", "Legendas", "Estilo", "Preview", "Gráficos", "Capa", "Final"):
        assert titulo in textos
    ids = {c["id"] for c in r["controles"]}
    assert {"player-play", "player-menos5", "player-mais5"} <= ids
    rotulos = " ".join(c["texto"] + " " + c["rotulo"] for c in r["controles"])
    assert "5 s" in rotulos and ("Tocar" in rotulos or "Play" in rotulos)
    assert re.fullmatch(r"\d+:\d\d / \d+:\d\d", r["tempo"]), r["tempo"]
    assert r["nativos"] is False, "sem controles nativos do navegador"
    assert r["instalacaoBotao"] == 1
    assert r["telaInicial"] == "video"
    assert "default-src 'self'" in r["csp"]


def test_steps_locked_until_previous_ready(results):
    r = _ok(results, "locked")
    antes = {p["id"]: p for p in r["antes"]}
    assert antes["video"]["bloqueado"] is False
    assert all(antes[p]["bloqueado"] for p in PASSOS[1:])
    assert r["painelAposBloqueado"] == "video", "passo bloqueado nao abre"
    assert "anterior" in r["toast"]
    depois = {p["id"]: p for p in r["depoisVideo"]}
    assert depois["video"]["estado"] == "pronto"
    assert depois["cortes"]["bloqueado"] is False
    assert all(depois[p]["bloqueado"] for p in PASSOS[2:])
    cortes = {p["id"]: p for p in r["depoisCortes"]}
    assert cortes["cortes"]["estado"] == "pronto" and cortes["legendas"]["bloqueado"] is False
    assert "Reconhecer a fala do vídeo" in r["textoCortes"], "Cortes ja e a tela de verdade"
    assert "Vídeo recebido" in r["voltou"], "voltar ao passo nao perde o que foi feito"
    assert "Reel bloqueio" in r["aposRecarregar"], "reabre o ultimo projeto"
    assert r["storage"] == ["editor-reels:ultimo-projeto"], "localStorage so guarda o ultimo projeto"
    assert r["busca"].startswith("?t="), "a chave continua no endereco: F5 precisa funcionar"
    assert r["fatalAposF5"] is False, "recarregar a pagina (F5) nao pode cair na tela de erro"


def test_install_screen_lists_items_and_handle_form(results):
    r = _ok(results, "install")
    assert r["telaInicial"] == "instalacao", "primeira execucao abre a Instalacao"
    itens = {i["id"]: i for i in r["itens"]}
    assert list(itens) == ["python", "ffmpeg", "disco", "whisper", "pillow", "node", "graficos"]
    assert itens["python"]["ok"] == "true" and "✓" in itens["python"]["texto"]
    assert itens["ffmpeg"]["ok"] == "false" and "✗" in itens["ffmpeg"]["texto"]
    assert itens["ffmpeg"]["comando"] == "brew install ffmpeg" and itens["ffmpeg"]["copiar"]
    assert itens["python"]["comando"] is None, "item instalado nao mostra comando"
    assert "Opcional" in itens["whisper"]["texto"]
    assert r["copiado"] == "brew install ffmpeg"
    assert r["botaoCopiar"] == "Copiado"
    assert "faltam itens" in r["resumo"].lower() or "falta" in r["resumo"].lower()
    assert r["chromiumSemProjeto"] == 0 and r["comandoChromium"] == 1
    assert "Abra ou crie um Reel para instalar com um clique" in r["dicaSemProjeto"]
    assert r["detalhes"], "motivo tecnico do doctor fica em Detalhes tecnicos"
    for d in r["detalhes"]:
        assert d["resumo"] == "Detalhes técnicos" and d["aberto"] is False
    assert r["chromiumComProjeto"] == 1 and "navegador de gráficos" in r["textoBotao"]
    assert "@ inválido" in r["erroHandle"], "mensagem do servidor por extenso"
    assert "@gutmannesilva" in r["salvo"]
    assert r["brand"] == {"handles": ["@gutmannesilva"], "completa": True}
    for emoji in ("✔", "✘", "✅", "❌"):
        assert emoji not in r["textoTela"]


def test_visible_text_has_no_jargon(results):
    """Tudo o que a pessoa le nas telas de Instalacao (com itens faltando) e Video:
    nenhum termo tecnico. Comandos copiaveis e o <details> recolhido ficam de fora."""
    telas = dict(_ok(results, "install")["visivel"])
    telas["video-enviado"] = _ok(results, "upload")["visivel"]
    for tela, texto in telas.items():
        achados = sorted({m.group(0) for m in PROIBIDOS.finditer(texto)})
        assert not achados, (tela, achados)
    assert "Detalhes técnicos" in telas["instalacao"]


def test_stale_response_of_previous_project_ignored(results):
    r = _ok(results, "corrida")
    assert "Reel B" in r["cabecalho"] and "Reel A" not in r["cabecalho"]
    passos = {p["id"]: p for p in r["passos"]}
    assert passos["video"]["estado"] != "pronto", "estado do Reel A nao pode vazar para o B"
    assert passos["cortes"]["bloqueado"] is True
    assert r["temInfoVideo"] == 0
    assert r["storage"] == r["b"]
    d = r["depoisEnvio"]
    assert "Reel B" in d["cabecalho"], "terminar o envio do A nao troca de projeto"
    assert any("Reel A lento" in t for t in d["toasts"])
    assert d["estadoA"] == "pronto"
    assert {p["id"]: p for p in d["passos"]}["video"]["estado"] != "pronto"
    assert d["src"] == "", "o player do Reel B nao mostra o video do A"


def test_last_project_kept_on_network_error(results):
    r = _ok(results, "rede")
    assert r["comFalha"] == r["slug"], "falha de rede nao apaga o ultimo projeto"
    assert r["com404"] is None, "projeto que nao existe mais e esquecido"


def test_video_upload_progress_and_error_message(results):
    r = _ok(results, "upload")
    assert "o arquivo não parece ser um vídeo" in r["erroServidor"].lower()
    assert "conexão" in r["erroRede"]
    assert any(0 < v < 100 for v in r["progresso"]), r["progresso"][:20]
    assert "%" in r["textoEnviando"]
    assert "cancelad" in r["cancelado"].lower()
    assert r["estado"]["etapas"]["video"] == "pronto"
    assert re.fullmatch(r"0:1[12]", r["info"]["duracao"]), r["info"]
    assert "Vertical" in r["info"]["formato"] and "360 × 640" in r["info"]["formato"]
    assert "/arquivos/entrada.mp4" in r["src"]
    assert r["aposMais5"] == pytest.approx(5, abs=0.5)
    assert r["aposMenos5"] == pytest.approx(0, abs=0.5)
    assert r["tocando"] is True and r["rotuloPlay"] == "Pausar"
    assert r["pausadoPorEspaco"] is True
    assert re.fullmatch(r"\d:\d\d / 0:1[12]", r["tempo"]), r["tempo"]


def test_upload_over_limit_refused_in_client(results):
    r = _ok(results, "upload")
    assert r["putsGrande"] == 0, "arquivo acima do limite nao e enviado"
    assert "limite" in r["erroGrande"] and "MB" in r["erroGrande"]


def test_no_horizontal_scroll_375(results):
    r = _ok(results, "scroll375")
    for tela, m in r["medidas"].items():
        assert m["scrollWidth"] <= m["clientWidth"], (tela, m)
        assert m["bodyScroll"] <= m["clientWidth"], (tela, m)
    pequenos = [a for a in r["alvos"] if a["h"] < 44 or a["w"] < 44]
    assert not pequenos, pequenos


def test_all_text_via_textcontent(results):
    r = _ok(results, "xss")
    assert r["xss"] is False
    assert "<img" in r["lista"] and "<img" in r["cabecalho"]
    assert r["imgs"] == []
    for js in WEB.rglob("*.js"):
        texto = js.read_text("utf-8")
        assert "innerHTML" not in texto and "outerHTML" not in texto, js
        assert "insertAdjacentHTML" not in texto and "document.write" not in texto, js


def test_csp_blocks_external_request(results):
    r = _ok(results, "csp")
    assert r["fetchErro"], "fetch externo deve falhar"
    bloqueados = {v["uri"].split("/")[2] if "//" in v["uri"] else v["uri"] for v in r["violacoes"]}
    assert "example.com" in bloqueados
    diretivas = {v["diretiva"] for v in r["violacoes"]}
    assert {"connect-src", "img-src", "script-src-elem"} <= diretivas, diretivas
    assert r["inline"] is False, "script inline bloqueado"
    assert r["externos"] == [] or all("example.com" in u for u in r["externos"])
    assert all(u.startswith(r["base"]) for u in r["carga"]), r["carga"]


def test_missing_token_friendly_error(results):
    r = _ok(results, "token")
    assert r["semStatus"] == 403 and r["erradoStatus"] == 403
    assert "Acesso negado" in r["semTexto"] and "Traceback" not in r["semTexto"]
    assert "abra o editor" in r["fatal"].lower()


def test_dark_theme_renders(results):
    r = _ok(results, "dark")

    def lum(cor):
        n = [int(x) for x in re.findall(r"\d+", cor)[:3]]
        return sum(n) / 3

    assert lum(r["light"]["fundo"]) > 200 and lum(r["light"]["texto"]) < 80
    assert lum(r["dark"]["fundo"]) < 50 and lum(r["dark"]["texto"]) > 180
    assert "Poppins" in r["light"]["fonte"]


def test_keyboard_focus_reaches_steps(results):
    r = _ok(results, "focus")
    assert r["achou"], r["visitados"]
    assert r["achou"]["outline"] != "none" or r["achou"]["sombra"] != "none"
    assert r["painel"] == "video"


# ------------------------------------------------------- checagens estaticas
def test_page_has_no_inline_script_or_external_resource():
    html = (WEB / "index.html").read_text("utf-8")
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) is None, "script inline"
    assert '<script type="module" src="/static/app.js"></script>' in html
    assert "{{TOKEN}}" in html
    for f in WEB.rglob("*"):
        if f.suffix in (".html", ".css", ".js"):
            texto = f.read_text("utf-8")
            # o namespace do SVG nao e rede; qualquer outro endereco e
            assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", texto), f
            assert "__TOKEN__" not in texto, f


def test_font_is_the_brand_file():
    fonte = WEB / "fonts" / "Poppins-Bold.ttf"
    assert fonte.read_bytes() == (REPO / "assets" / "fonts" / "Poppins-Bold.ttf").read_bytes()
    # so copias exatas das fontes da marca (assets/fonts), nada de fora
    nomes = sorted(p.name for p in (WEB / "fonts").iterdir())
    assert nomes == sorted(f"Poppins-{n}.ttf" for n in ("Regular", "Medium", "SemiBold", "Bold", "ExtraBold"))
    css = (WEB / "app.css").read_text("utf-8")
    for peso, n in ((400, "Regular"), (500, "Medium"), (600, "SemiBold"), (700, "Bold"), (800, "ExtraBold")):
        assert f'url("/static/fonts/Poppins-{n}.ttf")' in css and f"font-weight: {peso};" in css, n
    for p in (WEB / "fonts").iterdir():
        assert p.name.startswith("Poppins-") and p.suffix == ".ttf", p.name
        assert p.read_bytes() == (REPO / "assets" / "fonts" / p.name).read_bytes(), p.name


def test_ui_text_has_no_jargon():
    for f in [WEB / "index.html", *WEB.rglob("*.js")]:
        # so os textos entre aspas que comecam com maiuscula (frases mostradas)
        for frase in re.findall(r"'([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^'\n]{3,})'", f.read_text("utf-8")):
            for termo in JARGAO:
                assert termo not in frase, (f.name, frase)


# ------------------------------------------------------------ servidor
TOKEN = "tok-casca-123"


@pytest.fixture
def srv(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    return make_server(root, TOKEN, test_mode=True)


def test_referrer_policy_no_referrer(srv, tmp_path):
    with client(srv) as c:
        slug = c.request("POST", "/api/projects", body={"nome": "Ref"}).json()["slug"]
        (srv.app.root / slug / "entrada.mp4").write_bytes(b"0123456789")
        for r in (c.get(f"/?t={TOKEN}", token=False), c.get("/", token=False),
                  c.get("/api/ping"), c.get("/static/app.css", token=False),
                  c.get(f"/api/projects/{slug}/arquivos/entrada.mp4"),
                  c.get(f"/api/projects/{slug}/arquivos/entrada.mp4", headers={"Range": "bytes=99-"})):
            assert r.getheader("Referrer-Policy") == "no-referrer", r.status


def test_static_serves_fonts_and_step_modules(srv):
    with client(srv) as c:
        r = c.get("/static/fonts/Poppins-Bold.ttf", token=False)
        assert r.status == 200 and r.getheader("Content-Type") == "font/ttf"
        r = c.get("/static/passos/video.js", token=False)
        assert r.status == 200 and r.getheader("Content-Type").startswith("text/javascript")
        for p in ("passos/../../server.py", "fonts/../../projects.py", "passos/%2e%2e/%2e%2e/server.py"):
            assert c.get("/static/" + p, token=False).status == 404, p


def test_file_route_accepts_token_in_query_for_video_tag(srv):
    with client(srv) as c:
        slug = c.request("POST", "/api/projects", body={"nome": "Player"}).json()["slug"]
        (srv.app.root / slug / "entrada.mp4").write_bytes(b"0123456789")
        rota = f"/api/projects/{slug}/arquivos/entrada.mp4"
        assert c.get(rota, token=False).status == 401
        assert c.get(rota + "?t=errado", token=False).status == 401
        r = c.get(rota + f"?t={TOKEN}", token=False, headers={"Range": "bytes=2-4"})
        assert r.status == 206 and r.body == b"234"
        # so a rota de arquivos (GET/HEAD) aceita a chave no endereco
        assert c.get(f"/api/projects?t={TOKEN}", token=False).status == 401
        assert c.get(f"/api/projects/{slug}?t={TOKEN}", token=False).status == 401
        assert c.request("PUT", f"/api/projects/{slug}/video?t={TOKEN}", body=b"x",
                         token=False, headers={"X-Filename": "a.mp4"}).status == 401
