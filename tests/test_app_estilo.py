"""API do banco e do estilo (passo Estilo) e os quadros de exemplo dos cartões."""
import json
import math
import os
import shutil
import time
from pathlib import Path

import pytest

from conftest import build_sample
from conftest_app import client, repo_root  # noqa: F401
from fixtures_app import CUTS, WORDS
from server import make_server

import banco
import estilo as estilomod
import estilo_api
import graphics
import tarefas

TOKEN = "tok-de-teste-123"
BANCO = repo_root / "banco"


def _png_size(p: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(p) as im:
        return im.size


def _sem_renderizador() -> str | None:
    return graphics.renderer_status()


@pytest.fixture
def srv(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    s = make_server(root, TOKEN, test_mode=True)
    brand = tmp_path / "brand.json"
    shutil.copy(repo_root / "brand" / "brand.json", brand)
    s.app.brand_path = brand
    return s


def _projeto_real(d: Path) -> Path:
    """Projeto com video de verdade (6 s, 1080x1920), transcricao e cortes fixos."""
    build_sample(d / "entrada.mp4")
    (d / "transcricao.json").write_text(json.dumps({"duration": 6.0, "words": [
        {"w": w, "start": s, "end": e} for w, s, e in WORDS]}, ensure_ascii=False), "utf-8")
    (d / "cortes.json").write_text(json.dumps({"cuts": CUTS}), "utf-8")
    return d


@pytest.fixture(scope="module")
def video_modelo(tmp_path_factory):
    return build_sample(tmp_path_factory.mktemp("video") / "entrada.mp4")


@pytest.fixture
def projeto(tmp_path, video_modelo):
    d = tmp_path / "proj"
    d.mkdir()
    shutil.copy(video_modelo, d / "entrada.mp4")
    (d / "transcricao.json").write_text(json.dumps({"duration": 6.0, "words": [
        {"w": w, "start": s, "end": e} for w, s, e in WORDS]}, ensure_ascii=False), "utf-8")
    (d / "cortes.json").write_text(json.dumps({"cuts": CUTS}), "utf-8")
    return d


@pytest.fixture
def slug_real(srv, video_modelo):
    p = srv.app.projects.create("Meu Reel")
    d = srv.app.projects.path(p["slug"])
    shutil.copy(video_modelo, d / "entrada.mp4")
    (d / "transcricao.json").write_text(json.dumps({"duration": 6.0, "words": [
        {"w": w, "start": s, "end": e} for w, s, e in WORDS]}, ensure_ascii=False), "utf-8")
    (d / "cortes.json").write_text(json.dumps({"cuts": CUTS}), "utf-8")
    return p["slug"]


def _esperar_job(c, jid, timeout=180):
    fim = time.time() + timeout
    while time.time() < fim:
        d = c.get(f"/api/jobs/{jid}").json()
        if d["estado"] != "rodando":
            return d
        time.sleep(0.2)
    raise AssertionError(f"tarefa não terminou: {d}")


# ------------------------------------------------------------------ GET /api/banco

def test_banco_endpoint_lists_items_and_errors(srv, tmp_path, monkeypatch):
    raiz = tmp_path / "banco"
    shutil.copytree(BANCO, raiz)
    torta = raiz / "paletas" / "torta"
    torta.mkdir()
    (torta / "manifesto.json").write_text('{"nome": "x", "tipo": "paleta"', "utf-8")
    monkeypatch.setattr(estilo_api, "BANCO_RAIZ", raiz)
    with client(srv) as c:
        assert c.get("/api/banco", token=False).status == 401
        r = c.get("/api/banco")
        assert r.status == 200, r.body
        dados = r.json()
    assert set(dados) == {"paletas", "legendas", "efeitos", "erros", "fontes"}
    assert sorted(i["id"] for i in dados["paletas"]) == [
        "gelo-claro", "grafite", "marca", "marinho-profundo"]
    assert len(dados["legendas"]) == 4 and len(dados["efeitos"]) == 10
    for it in dados["paletas"] + dados["legendas"] + dados["efeitos"]:
        assert {"id", "nome", "descricao", "campos", "dados", "variacoes"} <= set(it)
        assert "pasta" not in it
    marca = next(i for i in dados["paletas"] if i["id"] == "marca")
    assert 2 <= len(marca["variacoes"]) <= 3
    assert all(set(v) == {"nome", "dados"} for v in marca["variacoes"])
    assert [e["pasta"] for e in dados["erros"]] == ["paletas/torta"]
    assert "JSON" in dados["erros"][0]["motivo"]
    corpo = r.body.decode("utf-8")
    assert str(tmp_path) not in corpo and str(repo_root) not in corpo
    assert {"nome": "Poppins", "arquivo": "Poppins-Bold.ttf"}.items() <= dados["fontes"][0].items()


def test_banco_erro_com_caminho_absoluto_sai_limpo(srv, tmp_path, monkeypatch):
    """Mesmo que um motivo traga um caminho absoluto, a resposta não o mostra."""
    raiz = tmp_path / "banco"
    (raiz / "paletas").mkdir(parents=True)

    class Falso:
        erros = [{"pasta": "paletas/x", "motivo": f"falhou ao ler {raiz}/paletas/x/manifesto.json"}]

        def itens(self, tipo):
            return []

    monkeypatch.setattr(estilo_api, "_banco", lambda: Falso())
    with client(srv) as c:
        r = c.get("/api/banco")
    assert r.status == 200
    assert str(raiz) not in r.body.decode("utf-8")
    assert "manifesto.json" in r.json()["erros"][0]["motivo"]


def test_fontes_from_assets_dir(srv, tmp_path, monkeypatch):
    fontes = tmp_path / "fonts"
    fontes.mkdir()
    for nome in ("Poppins-Bold.ttf", "Poppins-Regular.ttf", "Poppins-SemiBold.ttf"):
        shutil.copy(repo_root / "assets" / "fonts" / nome, fontes / nome)
    (fontes / "Inventada-Bold.ttf").write_bytes(b"\x00\x01\x00\x00" + b"\xff" * 40)  # corrompido
    (fontes / "leia.txt").write_text("nao e fonte")
    (fontes / "Link-Bold.ttf").symlink_to(fontes / "Poppins-Bold.ttf")
    monkeypatch.setattr(estilo_api, "FONTS_DIR", fontes)
    with client(srv) as c:
        lista = c.get("/api/banco").json()["fontes"]
    assert [f["nome"] for f in lista] == ["Inventada", "Poppins"]  # famílias, sem repetir pesos
    poppins = lista[1]
    assert poppins["arquivo"] == "Poppins-Bold.ttf"
    assert sorted(poppins["arquivos"]) == ["Poppins-Bold.ttf", "Poppins-Regular.ttf",
                                           "Poppins-SemiBold.ttf"]
    assert lista[0]["arquivo"] == "Inventada-Bold.ttf"


@pytest.mark.parametrize("dados", [
    b"", b"\x00\x01", b"\x00\x01\x00\x00\xff\xff" + b"\x00" * 6,
    b"\x00\x01\x00\x00\x00\x01" + b"\x00" * 6 + b"name" + b"\x00" * 4 + b"\x7f\xff\xff\xff" + b"\x00\x00\x10\x00",
    b"\x00\x01\x00\x00\x00\x01" + b"\x00" * 6 + b"name" + b"\x00" * 4 + b"\x00\x00\x00\x1c\x00\x00\x00\x20"
    + b"\x00\x00\xff\xff\x00\x00" + b"\x00" * 20,
    os.urandom(4096),
])
def test_leitor_de_familia_tolera_ttf_corrompido(dados):
    assert estilo_api.familia_ttf(dados) is None or isinstance(estilo_api.familia_ttf(dados), str)


def test_leitor_de_familia_le_poppins():
    bruto = (repo_root / "assets" / "fonts" / "Poppins-SemiBold.ttf").read_bytes()
    assert estilo_api.familia_ttf(bruto) == "Poppins"


# ------------------------------------------------------------------ banco.quadro

def test_quadro_png_size_and_cache(projeto):
    out = projeto / "quadros"
    p1 = banco.quadro(projeto, "legenda", "faixa-azul", estilomod.DEFAULT, 1.0, out)
    assert p1.parent == out and p1.suffix == ".png" and p1.name.startswith("legenda-faixa-azul-")
    assert _png_size(p1) == (540, 960)
    m1 = p1.stat().st_mtime_ns
    time.sleep(0.02)
    p2 = banco.quadro(projeto, "legenda", "faixa-azul", estilomod.DEFAULT, 1.0, out)
    assert p2 == p1 and p2.stat().st_mtime_ns == m1  # veio do cache
    p3 = banco.quadro(projeto, "legenda", "faixa-azul", estilomod.DEFAULT, 2.0, out)
    assert p3 != p1
    outro = dict(estilomod.DEFAULT, paleta="gelo-claro")
    assert banco.quadro(projeto, "legenda", "faixa-azul", outro, 1.0, out) != p1
    assert not [x for x in out.iterdir() if x.name.startswith(".")]  # sem temporários


def test_quadro_each_tipo_renders(projeto, tmp_path):
    from PIL import Image, ImageChops
    out = projeto / "quadros"
    base = tmp_path / "base.png"
    banco._extrair_quadro(banco._video(projeto), banco._tempo_bruto(projeto, 1.0), (540, 960), base)
    tipos = [("paleta", "gelo-claro"), ("legenda", "pilula-escura")]
    if _sem_renderizador() is None:
        tipos.append(("efeito", "numero-grande"))
    for tipo, iid in tipos:
        p = banco.quadro(projeto, tipo, iid, estilomod.DEFAULT, 1.0, out)
        assert _png_size(p) == (540, 960)
        with Image.open(p) as a, Image.open(base) as b:
            diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox()
        assert diff is not None, f"{tipo} {iid}: nada desenhado sobre o quadro"
        dest = os.environ.get("QUADROS_AMOSTRA")
        if dest:
            shutil.copy(p, Path(dest) / f"{tipo}-{iid}.png")


def test_quadro_sem_libass_usa_caminho_por_imagem(projeto, monkeypatch):
    import render
    monkeypatch.setattr(render, "has_libass", lambda: False)
    cmds = []
    real = banco.subprocess.run

    def espiao(cmd, *a, **kw):
        cmds.append(list(cmd))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(banco.subprocess, "run", espiao)
    p = banco.quadro(projeto, "legenda", "duas-linhas-grandes", estilomod.DEFAULT, 1.0,
                     projeto / "quadros")
    assert _png_size(p) == (540, 960)
    assert cmds and not any("subtitles" in " ".join(c) for c in cmds)


@pytest.mark.parametrize("t", [float("nan"), float("inf"), -0.5, 1e9, True, "1", None])
def test_quadro_t_invalido(projeto, t):
    with pytest.raises(banco.BancoError):
        banco.quadro(projeto, "legenda", "faixa-azul", estilomod.DEFAULT, t, projeto / "quadros")
    assert not (projeto / "quadros").exists() or not list((projeto / "quadros").iterdir())


@pytest.mark.parametrize("tipo,iid", [
    ("paleta", "../marca"), ("paleta", "marca/../x"), ("paleta", "/etc/passwd"),
    ("paleta", "nao-existe"), ("material", "x"), ("paletas", "marca"), ("legenda", "MARCA"),
    ("efeito", 5),
])
def test_quadro_id_hostil(projeto, tipo, iid):
    with pytest.raises(banco.BancoError):
        banco.quadro(projeto, tipo, iid, estilomod.DEFAULT, 1.0, projeto / "quadros")


def test_quadro_poda_cache(projeto, monkeypatch):
    monkeypatch.setattr(banco, "MAX_QUADROS_CACHE", 3)
    out = projeto / "quadros"
    out.mkdir()
    velhos = []
    for i in range(5):
        v = out / f"paleta-marca-{i:016x}.png"
        v.write_bytes(b"x")
        os.utime(v, (1000 + i, 1000 + i))
        velhos.append(v)
    alheio = out / "q1.jpg"  # quadro da capa: não é cache, fica
    alheio.write_bytes(b"x")
    os.utime(alheio, (10, 10))
    novo = banco.quadro(projeto, "legenda", "faixa-azul", estilomod.DEFAULT, 1.0, out)
    cache = sorted(p.name for p in out.iterdir() if banco._CACHE_RE.fullmatch(p.name))
    assert len(cache) == 3 and novo.name in cache
    assert velhos[4].name in cache and velhos[0].name not in cache
    assert alheio.exists()


# ------------------------------------------------------------------ variações

def test_variacoes_no_manifesto_validadas(tmp_path):
    raiz = tmp_path / "banco"
    base = {"nome": "P", "descricao": "Uma paleta.", "tipo": "paleta", "campos": [],
            "dados": {"fundo": "#000000", "texto": "#ffffff", "destaque": "#aaaaaa", "apoio": "#555555"}}
    casos = {
        "ok": [{"nome": "Clara", "dados": dict(base["dados"], fundo="#111111")}],
        "cor-ruim": [{"nome": "X", "dados": dict(base["dados"], fundo="azul")}],
        "demais": [{"nome": f"V{i}", "dados": base["dados"]} for i in range(13)],
        "nome-longo": [{"nome": "n" * 61, "dados": base["dados"]}],
        "chave-extra": [{"nome": "X", "dados": base["dados"], "id": "x"}],
        "nao-lista": {"nome": "X"},
    }
    for pasta, var in casos.items():
        d = raiz / "paletas" / pasta
        d.mkdir(parents=True)
        (d / "manifesto.json").write_text(json.dumps({**base, "variacoes": var}), "utf-8")
    d = raiz / "paletas" / "sem"
    d.mkdir()
    (d / "manifesto.json").write_text(json.dumps(base), "utf-8")
    b = banco.carregar(raiz)
    assert sorted(i["id"] for i in b.itens("paleta")) == ["ok", "sem"]
    assert b.item("paleta", "ok")["variacoes"] == casos["ok"]
    assert b.item("paleta", "sem")["variacoes"] == []
    assert sorted(Path(e["pasta"]).name for e in b.erros) == [
        "chave-extra", "cor-ruim", "demais", "nao-lista", "nome-longo"]


def test_banco_real_tem_variacoes_em_paletas_e_legendas():
    b = banco.carregar(BANCO)
    assert b.erros == []
    for tipo in ("paleta", "legenda"):
        for it in b.itens(tipo):
            assert 2 <= len(it["variacoes"]) <= 3, it["id"]


def test_variacoes_order_selected_first(srv, slug_real):
    d = srv.app.projects.path(slug_real)
    url = "/api/banco/legendas/faixa-azul/variacoes"
    with client(srv) as c:
        r = c.get(url)
        assert r.status == 200, r.body
        lista = r.json()["variacoes"]
        assert lista[0] == {"nome": "Faixa azul", "dados": {
            "estilo": "faixa", "posicao_padrao": "baixo", "tamanho_padrao": "M"}}
        assert len(lista) >= 3
        meio = next(v for v in lista if v["dados"]["posicao_padrao"] == "meio")
        estilomod.salvar(d, {"legenda": {"estilo": "faixa-azul", "posicao": "meio", "tamanho": "M"}})
        r2 = c.get(url + f"?projeto={slug_real}").json()["variacoes"]
        assert r2[0] == meio and len(r2) == len(lista)
        assert sorted(map(json.dumps, r2)) == sorted(map(json.dumps, lista))
        # paleta: a do projeto vem primeiro
        estilomod.salvar(d, {"paleta": "grafite"})
        pal = c.get(f"/api/banco/paletas/grafite/variacoes?projeto={slug_real}").json()
        assert pal["variacoes"][0]["nome"] == "Grafite"
        # efeito sem variações: lista só com o próprio item
        ef = c.get("/api/banco/efeitos/numero-grande/variacoes").json()["variacoes"]
        assert len(ef) == 1 and ef[0]["nome"] == "Número grande"
        for ruim in ("/api/banco/legendas/nao-existe/variacoes",
                     "/api/banco/legendas/..%2F..%2Fetc/variacoes",
                     "/api/banco/torto/faixa-azul/variacoes",
                     "/api/banco/materiais/x/variacoes",
                     "/api/banco/legendas/FAIXA/variacoes",
                     "/api/banco/legendas/faixa-azul/outra-coisa"):
            assert c.get(ruim).status == 404, ruim
        assert c.get(url + "?projeto=nao-existe").status == 404
        assert c.request("POST", url, body={}).status == 405


# ------------------------------------------------------------------ GET/PUT estilo

def test_estilo_put_validates_against_banco(srv, slug_real):
    d = srv.app.projects.path(slug_real)
    url = f"/api/projects/{slug_real}/estilo"
    with client(srv) as c:
        r = c.get(url)
        assert r.status == 200 and r.json() == estilomod.DEFAULT
        assert not (d / "estilo.json").exists()
        r = c.request("PUT", url, body={"paleta": "grafite", "legenda": {"estilo": "pilula-escura"}})
        assert r.status == 200, r.body
        salvo = json.loads((d / "estilo.json").read_text("utf-8"))
        assert salvo == r.json() and salvo["paleta"] == "grafite"
        assert salvo["legenda"] == {"estilo": "pilula-escura", "posicao": "meio", "tamanho": "M"}
        assert c.get(url).json() == salvo
        antes = (d / "estilo.json").read_bytes()
        for ruim in ({"paleta": "nao-existe"}, {"cor": "azul"}, {"legenda": {"estilo": "x"}},
                     {"fonte": "Comic Sans"}, [1, 2], "texto"):
            r = c.request("PUT", url, body=json.dumps(ruim).encode())
            assert r.status == 400, ruim
            erro = r.json()["erro"]
            assert "Traceback" not in erro and str(d) not in erro and erro
        assert c.request("PUT", url, body=b"{nao json").status == 400
        assert c.request("PUT", url, body=b'{"paleta": "' + b"x" * 17000 + b'"}').status == 413
        assert (d / "estilo.json").read_bytes() == antes
        assert c.request("DELETE", url).status == 405
        assert c.get(url, token=False).status == 401
        assert c.get("/api/projects/nao-existe/estilo").status == 404


def test_estilo_put_409_com_tarefa_ativa(srv, slug_real, monkeypatch):
    d = srv.app.projects.path(slug_real)
    monkeypatch.setattr(srv.app.jobs, "ativo_em", lambda s: "x" * 32)
    with client(srv) as c:
        r = c.request("PUT", f"/api/projects/{slug_real}/estilo", body={"paleta": "grafite"})
        assert r.status == 409 and "tarefa" in r.json()["erro"]
        assert c.get(f"/api/projects/{slug_real}/estilo").status == 200  # GET segue livre
    assert not (d / "estilo.json").exists()


def test_estilo_get_arquivo_invalido_400_sem_caminho(srv, slug_real):
    d = srv.app.projects.path(slug_real)
    (d / "estilo.json").write_text('{"paleta": "sumiu"}', "utf-8")
    with client(srv) as c:
        r = c.get(f"/api/projects/{slug_real}/estilo")
    assert r.status == 400 and str(d) not in r.json()["erro"] and "sumiu" in r.json()["erro"]


# ------------------------------------------------------------------ tarefas

def test_aplicar_estilo_runs_preview_with_estilo(srv, slug_real):
    d = srv.app.projects.path(slug_real)
    url = f"/api/projects/{slug_real}/jobs/aplicar-estilo"
    with client(srv) as c:
        r = c.request("POST", url, body={"paleta": "nao-existe"})
        assert r.status == 400 and "paleta" in r.json()["erro"]
        assert not (d / "estilo.json").exists() and not (d / "saida").exists()
        r = c.request("POST", url, body={"paleta": "gelo-claro",
                                         "legenda": {"estilo": "duas-linhas-grandes"}})
        assert r.status == 202, r.body
        job = _esperar_job(c, r.json()["job_id"])
        assert job["estado"] == "ok", job
        assert job["tipo"] == "aplicar-estilo" and job["saidas"] == ["saida/preview.mp4"]
        st = c.get(f"/api/projects/{slug_real}").json()
        assert st["etapas"]["estilo"] == "pronto" and st["etapas"]["preview"] == "pronto"
        assert st["preview_desatualizado"] is False
    salvo = json.loads((d / "estilo.json").read_text("utf-8"))
    assert salvo["paleta"] == "gelo-claro" and salvo["legenda"]["estilo"] == "duas-linhas-grandes"
    assert (d / "saida" / "preview.mp4").stat().st_size > 0


def test_aplicar_estilo_409_com_tarefa_ativa_nao_grava(srv, slug_real, monkeypatch):
    d = srv.app.projects.path(slug_real)
    monkeypatch.setattr(srv.app.jobs, "ativo_em", lambda s: "x" * 32)
    with client(srv) as c:
        r = c.request("POST", f"/api/projects/{slug_real}/jobs/aplicar-estilo",
                      body={"paleta": "grafite"})
        assert r.status == 409
    assert not (d / "estilo.json").exists()


def test_quadros_job_generates_tab(srv, slug_real):
    with client(srv) as c:
        url = f"/api/projects/{slug_real}/jobs/quadros"
        for ruim in ({"aba": "fontes"}, {}, {"aba": "legendas", "t": -1},
                     {"aba": "legendas", "t": 1e9}, {"aba": "legendas", "t": "1"},
                     {"aba": "legendas", "x": 1}):
            r = c.request("POST", url, body=ruim)
            assert r.status == 400, ruim
        r = c.request("POST", url, body=b'{"aba": "legendas", "t": NaN}')
        assert r.status == 400
        r = c.request("POST", url, body={"aba": "legendas", "t": 1.0})
        assert r.status == 202, r.body
        job = _esperar_job(c, r.json()["job_id"])
        assert job["estado"] == "ok", job
        assert len(job["saidas"]) == 4
        assert all(s.startswith("quadros/legenda-") and s.endswith(".png") for s in job["saidas"])
        assert any("4" in linha for linha in job["log"])
        for s in job["saidas"]:
            arq = c.get(f"/api/projects/{slug_real}/arquivos/{s}")
            assert arq.status == 200 and arq.getheader("Content-Type") == "image/png"
        # sem t: usa um momento padrão, sempre dentro do vídeo
        r = c.request("POST", url, body={"aba": "paletas"})
        assert r.status == 202
        job = _esperar_job(c, r.json()["job_id"])
        assert job["estado"] == "ok", job
        assert len(job["saidas"]) == 4


def test_quadros_estilo_invalido_400(srv, slug_real):
    d = srv.app.projects.path(slug_real)
    (d / "estilo.json").write_text("{}}", "utf-8")
    with client(srv) as c:
        r = c.request("POST", f"/api/projects/{slug_real}/jobs/quadros", body={"aba": "legendas"})
        assert r.status == 400 and str(d) not in r.json()["erro"]


def test_tarefas_novas_validam_opcoes(tmp_path):
    p = tmp_path / "p"
    p.mkdir()
    (p / "entrada.mp4").write_bytes(b"x")
    assert "quadros" in tarefas.TIPOS and "aplicar-estilo" in tarefas.TIPOS
    a = tarefas.argv("quadros", p, aba="efeitos", t=2.5)
    assert a[1:3] == ["-I", str(repo_root / "scripts" / "banco.py")]
    assert "quadros" in a and "--aba=efeitos" in a and "--t=2.5" in a
    for ruim in ({"aba": "x"}, {"aba": "efeitos", "t": math.nan}, {"aba": "efeitos", "t": True},
                 {"aba": "efeitos", "t": -1}, {}):
        with pytest.raises(ValueError):
            tarefas.argv("quadros", p, **ruim)
    assert tarefas.argv("aplicar-estilo", p, paleta="grafite") == tarefas.argv("preview", p)
    with pytest.raises(ValueError):
        tarefas.argv("aplicar-estilo", p, paleta="nao-existe")
