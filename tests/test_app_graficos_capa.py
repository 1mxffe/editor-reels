"""API de Materiais, Graficos e Capa (Task 9): envio de materiais com nome limpo,
graficos.json validado por subprocesso (scripts/graphics.py validar) e as tarefas
capa-candidatos / capa."""
import json
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image

from conftest_app import client
import tarefas
from server import make_server

REPO = Path(__file__).resolve().parent.parent
TOKEN = "tok-graficos-capa"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SVG_MAL = (b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
           b'<script>document.title="pwn"</script><rect width="10" height="10"/></svg>')


@pytest.fixture
def root(tmp_path):
    d = tmp_path / "projects"
    d.mkdir()
    return d


def _brand(tmp_path, handles=("@gutmannesilva",)):
    dados = json.loads((REPO / "brand" / "brand.json").read_text("utf-8"))
    dados["handles"] = list(handles)
    p = tmp_path / f"brand-{len(handles)}.json"
    p.write_text(json.dumps(dados), "utf-8")
    return p


def _projeto(c, nome="Materiais"):
    return c.request("POST", "/api/projects", body={"nome": nome}).json()["slug"]


def _enviar(c, slug, nome, dados):
    return c.request("PUT", f"/api/projects/{slug}/materiais", body=dados,
                     headers={"X-Filename": quote(nome)})


def _esperar_job(c, job_id, prazo=120):
    fim = time.monotonic() + prazo
    while time.monotonic() < fim:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["estado"] != "rodando":
            return job
        time.sleep(0.1)
    raise AssertionError("tarefa nao terminou")


def _png(path, size=(800, 1200), cor=(180, 140, 120)):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, cor)
    for x in range(0, size[0], 40):  # textura: nitidez para os candidatos
        for y in range(0, size[1], 40):
            img.putpixel((x, y), (0, 0, 0))
    img.save(path)
    return path


# ------------------------------------------------------------------ materiais
def test_materials_upload_whitelist_and_sanitized_name(root):
    s = make_server(root, TOKEN, test_mode=True)
    with client(s) as c:
        slug = _projeto(c)
        r = _enviar(c, slug, "Minha Foto  1.PNG", PNG)
        assert r.status == 201, r.body
        assert r.json()["nome"] == "Minha-Foto-1.png"
        r2 = _enviar(c, slug, "Minha Foto  1.PNG", PNG)
        assert r2.status == 201 and r2.json()["nome"] == "Minha-Foto-1-2.png", "nome repetido ganha sufixo"
        assert (root / slug / "materiais" / "Minha-Foto-1.png").read_bytes() == PNG
        for ruim in ("virus.exe", "texto.txt", "foto.png.exe", "pagina.html", "sem-extensao"):
            r = _enviar(c, slug, ruim, PNG)
            assert r.status == 415, ruim
            assert "png" in r.json()["erro"], "lista os formatos aceitos"
        # extensao dupla que termina em imagem: so a ultima conta, e o conteudo e conferido
        r = _enviar(c, slug, "foto.exe.png", PNG)
        assert r.status == 201 and r.json()["nome"] == "foto.exe.png"
        assert _enviar(c, slug, "falsa.png", b"MZ\x90\x00 nao e png").status == 415
        assert _enviar(c, slug, "vazio.png", b"").status == 400
        lista = c.get(f"/api/projects/{slug}/materiais").json()["materiais"]
        nomes = [m["nome"] for m in lista]
        assert nomes == sorted(nomes) and "Minha-Foto-1.png" in nomes and len(nomes) == 3
        item = next(m for m in lista if m["nome"] == "Minha-Foto-1.png")
        assert item == {"nome": "Minha-Foto-1.png", "rel": "materiais/Minha-Foto-1.png",
                        "tipo": "imagem", "tamanho": len(PNG)}
        assert not list((root / slug).glob(".material-*")), "temporario nao sobra"


def test_materials_rejects_traversal_and_big_svg_script_kept_inert(root):
    s = make_server(root, TOKEN, test_mode=True)
    s.app.max_material = 4096
    with client(s) as c:
        slug = _projeto(c)
        d = root / slug
        r = _enviar(c, slug, "../../etc/passwd.png", PNG)
        assert r.status == 201 and r.json()["nome"] == "passwd.png"
        assert (d / "materiais" / "passwd.png").is_file()
        r = _enviar(c, slug, "a\x00b/../..\\c.png", PNG)
        assert r.status == 201 and "\x00" not in r.json()["nome"] and "/" not in r.json()["nome"]
        assert (d / "materiais" / r.json()["nome"]).is_file()
        assert _enviar(c, slug, "..png", PNG).json()["nome"] == "arquivo.png"
        assert _enviar(c, slug, "grande.png", PNG + b"\x00" * 5000).status == 413
        # svg com <script>: aceito como imagem, mas servido com CSP que nao deixa rodar nada
        r = _enviar(c, slug, "icone.svg", SVG_MAL)
        assert r.status == 201
        g = c.get(f"/api/projects/{slug}/arquivos/materiais/icone.svg")
        assert g.status == 200 and g.getheader("Content-Type") == "image/svg+xml"
        csp = g.getheader("Content-Security-Policy")
        assert "sandbox" in csp and "default-src 'none'" in csp and "script-src" not in csp
        assert g.getheader("X-Content-Type-Options") == "nosniff"
        # remover: so nomes da lista real
        assert c.request("DELETE", f"/api/projects/{slug}/materiais/nao-existe.png").status == 404
        assert c.request("DELETE", f"/api/projects/{slug}/materiais/..%2Fprojeto.json").status == 404
        assert c.request("DELETE", f"/api/projects/{slug}/materiais/%2E%2E").status == 404
        assert (d / "projeto.json").is_file()
        r = c.request("DELETE", f"/api/projects/{slug}/materiais/icone.svg")
        assert r.status == 200 and not (d / "materiais" / "icone.svg").exists()
        assert "icone.svg" not in [m["nome"] for m in r.json()["materiais"]]
        assert c.request("POST", f"/api/projects/{slug}/materiais").status == 405


# ------------------------------------------------------------------ graficos
def _card(i, **kw):
    base = {"id": f"g{i}", "title": f"Prazo {i}", "body": "Conte só os dias úteis.",
            "at": 1.0 + i, "dur": 3.0, "material": None}
    base.update(kw)
    return base


def test_graficos_put_validates_each_card(root):
    s = make_server(root, TOKEN, test_mode=True)
    with client(s) as c:
        slug = _projeto(c)
        d = root / slug
        rota = f"/api/projects/{slug}/graficos"
        assert c.get(rota).json() == {"cards": [], "decisoes": {}}
        _png(d / "materiais" / "foto.png", (200, 200))
        bons = [_card(0), _card(1, material="materiais/foto.png", body=None)]
        r = c.request("PUT", rota, body={"cards": bons})
        assert r.status == 200, r.body
        assert json.loads((d / "graficos.json").read_text("utf-8"))["cards"] == bons
        assert c.get(rota).json()["cards"] == bons
        antes = (d / "graficos.json").read_bytes()
        casos = [
            ([_card(0), _card(1, title="x" * 61)], "card 1"),
            ([_card(0, dur=9)], "card 0"),
            ([_card(0), _card(0)], "repetido"),
            ([_card(0, material="materiais/sumiu.png")], "material"),
            ([_card(0, material="capa/capa.png")], "materiais"),
            ([_card(0, material="/etc/passwd")], "materiais"),
            ([_card(0, extra=1)], "desconhecidas"),
        ]
        for cards, trecho in casos:
            r = c.request("PUT", rota, body={"cards": cards})
            assert r.status == 400, (cards, r.body)
            msg = r.json()["erro"]
            assert trecho in msg, (trecho, msg)
            assert str(root) not in msg and str(Path(root).resolve()) not in msg and ".tmp" not in msg, msg
        assert (d / "graficos.json").read_bytes() == antes, "erro nao mexe no arquivo"
        assert c.request("PUT", rota, body=[1]).status == 400
        assert c.request("PUT", rota, body={"cards": [_card(0)], "x": 1}).status == 400
        grande = {"cards": [_card(0, body="a" * 300_000)]}
        assert c.request("PUT", rota, body=grande).status == 413
        assert not list(d.glob(".graficos-*")), "temporario nao sobra"
        # lista vazia vale (tirar todos os cards)
        assert c.request("PUT", rota, body={"cards": []}).status == 200
        assert c.get(rota).json()["cards"] == []


# --------------------------------------------------------------------- capa
def test_capa_options_validated():
    p = Path("/tmp/nao-usado")
    for ruim in ({"modo": "photo"}, {"modo": "foto"}, {"modo": "foto", "foto": "../x.png"},
                 {"modo": "foto", "foto": "capa/foto.png"}, {"modo": "foto", "foto": "materiais/-x.png"},
                 {"modo": "foto", "foto": "materiais/a/b.png"}, {"modo": "foto", "foto": "materiais/x.mp4"}):
        with pytest.raises(ValueError):
            tarefas.argv("capa-candidatos", p, **ruim)
    for quadro in ("capa/capa.png", "../x.png", "-x", "capa/../entrada.mp4", "saida/final.mp4",
                   "capa/a/b.png", "materiais/x.png", 3):
        with pytest.raises(ValueError):
            tarefas.argv("capa", p, quadro=quadro, gancho="3 MITOS")
    with pytest.raises(ValueError):
        tarefas.argv("capa", p, gancho="3 MITOS")  # sem quadro


def test_capa_candidatos_job_produces_three_png(root, tmp_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg ausente")
    s = make_server(root, TOKEN, test_mode=True)
    s.app.brand_path = _brand(tmp_path)
    with client(s) as c:
        slug = _projeto(c, "Capa")
        d = root / slug
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "testsrc2=size=360x640:rate=30:duration=6",
                        "-c:v", "libvpx-vp9", "-b:v", "300k", "-an", str(d / "entrada.mp4")],
                       check=True, capture_output=True)
        r = c.request("POST", f"/api/projects/{slug}/jobs/capa-candidatos", body={"modo": "video"})
        assert r.status == 202, r.body
        job = _esperar_job(c, r.json()["job_id"])
        assert job["estado"] == "ok", job
        estado = c.get(f"/api/projects/{slug}").json()
        assert estado["capa_candidatos"] == [f"capa/candidato-{i}.png" for i in (1, 2, 3)]
        for i in (1, 2, 3):
            assert (d / "capa" / f"candidato-{i}.png").read_bytes().startswith(b"\x89PNG")
        assert c.get(f"/api/projects/{slug}/arquivos/capa/candidato-2.png").status == 200
        # foto enviada aos materiais vira capa/foto.png
        _png(d / "materiais" / "retrato.png")
        r = c.request("POST", f"/api/projects/{slug}/jobs/capa-candidatos",
                      body={"modo": "foto", "foto": "materiais/retrato.png"})
        assert r.status == 202, r.body
        assert _esperar_job(c, r.json()["job_id"])["estado"] == "ok"
        assert "capa/foto.png" in c.get(f"/api/projects/{slug}").json()["capa_candidatos"]
        r = c.request("POST", f"/api/projects/{slug}/jobs/capa-candidatos",
                      body={"modo": "foto", "foto": "materiais/nao-tem.png"})
        assert r.status == 400 and "materiais" in r.json()["erro"]


def test_capa_job_error_message_hook_too_long(root, tmp_path):
    s = make_server(root, TOKEN, test_mode=True)
    s.app.brand_path = _brand(tmp_path)
    with client(s) as c:
        slug = _projeto(c, "Capa erro")
        _png(root / slug / "capa" / "candidato-1.png")
        r = c.request("POST", f"/api/projects/{slug}/jobs/capa",
                      body={"quadro": "capa/candidato-1.png", "gancho": "GANCHO " * 6})
        assert r.status == 202, r.body
        job = _esperar_job(c, r.json()["job_id"])
        assert job["estado"] == "erro"
        assert job["mensagem"].startswith("gancho com") and "máximo 28" in job["mensagem"], job
        assert str(root) not in job["mensagem"]
        assert not (root / slug / "capa" / "capa.png").exists()
        r = c.request("POST", f"/api/projects/{slug}/jobs/capa",
                      body={"quadro": "capa/candidato-9.png", "gancho": "3 MITOS"})
        assert r.status == 400 and "quadro" in r.json()["erro"]


def test_capa_needs_handle_message(root, tmp_path):
    s = make_server(root, TOKEN, test_mode=True)
    s.app.brand_path = _brand(tmp_path, handles=())
    with client(s) as c:
        slug = _projeto(c, "Sem arroba")
        _png(root / slug / "capa" / "candidato-1.png")
        assert c.get("/api/brand").json()["completa"] is False
        r = c.request("POST", f"/api/projects/{slug}/jobs/capa",
                      body={"quadro": "capa/candidato-1.png", "gancho": "3 MITOS"})
        assert r.status == 409
        assert r.json()["codigo"] == "marca_incompleta"
        assert "@" in r.json()["erro"] and "Instalação" in r.json()["erro"]
        assert c.get(f"/api/projects/{slug}/jobs").json()["ativo"] is None
        # os candidatos nao dependem do @
        r = c.request("POST", f"/api/projects/{slug}/jobs/capa-candidatos", body={"modo": "video"})
        assert r.status != 409
