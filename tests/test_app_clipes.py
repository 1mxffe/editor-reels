"""Juntar varios trechos num unico video: lista, envio, ordem, remocao e a tarefa ``juntar``.

Os trechos sao videos de cor solida (vermelho, verde, azul) de resolucoes, taxas e audio
diferentes; o resultado e conferido com ffprobe e pela cor do primeiro quadro. Sem ffmpeg
os testes sao pulados.
"""
import json
import shutil
import subprocess
import sys
import time
from urllib.parse import quote

import pytest

from conftest_app import client, repo_root  # noqa: F401
from server import make_server
import juntar

TOKEN = "tok-clipes-123"

# nome, cor, tamanho, fps, duracao, audio (None = sem audio; (taxa, canais))
CLIPES = {
    "horizontal": ("red", "640x360", 25, 2.0, None),            # deitado, sem audio
    "vertical": ("lime", "720x1280", 30, 3.0, (44100, 2)),      # em pe, com audio
    "quadrado": ("blue", "500x500", 24, 1.0, (22050, 1)),       # quadrado, audio mono
}
COR = {"horizontal": (255, 0, 0), "vertical": (0, 255, 0), "quadrado": (0, 0, 255)}


def _gerar(destino, cor, tam, fps, dur, audio):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={cor}:s={tam}:r={fps}:d={dur}"]
    if audio:
        taxa, canais = audio
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={taxa}:duration={dur}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-ac", str(audio[1]), "-shortest"]
    subprocess.run(cmd + [str(destino)], check=True, capture_output=True)


@pytest.fixture(scope="module")
def amostras(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg ausente")
    pasta = tmp_path_factory.mktemp("clipes_amostras")
    out = {}
    for nome, args in CLIPES.items():
        _gerar(pasta / f"{nome}.mp4", *args)
        out[nome] = (pasta / f"{nome}.mp4").read_bytes()
    _gerar(pasta / "curto.mp4", "gray", "160x90", 30, 0.3, None)
    out["curto"] = (pasta / "curto.mp4").read_bytes()
    return out


@pytest.fixture
def srv(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    s = make_server(root, TOKEN, test_mode=True)
    brand = tmp_path / "brand.json"
    shutil.copy(repo_root / "brand" / "brand.json", brand)
    s.app.brand_path = brand
    return s


def _criar(c, nome="Meu Reel"):
    r = c.request("POST", "/api/projects", body={"nome": nome})
    assert r.status == 201, r.body
    return r.json()["slug"]


def _enviar(c, slug, dados, nome="trecho.mp4"):
    return c.request("PUT", f"/api/projects/{slug}/clipes", body=dados, headers={"X-Filename": quote(nome, safe="")})


def _lista(c, slug):
    r = c.get(f"/api/projects/{slug}/clipes")
    assert r.status == 200, r.body
    return r.json()


def _juntar(c, slug, **corpo):
    return c.request("POST", f"/api/projects/{slug}/jobs/juntar", body=corpo)


def _fim(c, job_id, prazo=120):
    fim = time.time() + prazo
    while time.time() < fim:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["estado"] != "rodando":
            return j
        time.sleep(0.1)
    raise AssertionError("a tarefa nao terminou")


def _montar(c, slug, **corpo):
    r = _juntar(c, slug, **corpo)
    assert r.status == 202, r.body
    return _fim(c, r.json()["job_id"])


def _sonda(caminho):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels"
                          ":format=duration", "-of", "json", str(caminho)],
                         capture_output=True, text=True, check=True).stdout
    dados = json.loads(out)
    video = next(s for s in dados["streams"] if s["codec_type"] == "video")
    audio = [s for s in dados["streams"] if s["codec_type"] == "audio"]
    return video, audio, float(dados["format"]["duration"])


def _cor_do_centro(caminho, t):
    cru = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(caminho), "-frames:v", "1",
                          "-vf", "crop=2:2:540:960", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return tuple(cru[:3])


def _perto(cor, esperada, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(cor, esperada))


def _tres(c, slug, amostras, ordem=("horizontal", "vertical", "quadrado")):
    for nome in ordem:
        r = _enviar(c, slug, amostras[nome], f"{nome}.mp4")
        assert r.status == 200, r.body
    return _lista(c, slug)


# ------------------------------------------------------------------ montagem
def test_three_different_clips_become_one_vertical_video(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        (d / "entrada.mov").write_bytes(b"video antigo")  # outra extensao: sai depois do sucesso
        dados = _tres(c, slug, amostras)
        assert [x["nome"] for x in dados["clipes"]] == ["horizontal", "vertical", "quadrado"]
        assert all(x["duracao"] > 0 and x["tamanho"] > 0 for x in dados["clipes"])
        assert dados["total_duracao"] == pytest.approx(6.0, abs=0.4)
        assert dados["montado"] is False
        assert [p.parent.name for p in (d / "clipes").iterdir()] == ["clipes"] * 3
        assert c.get(f"/api/projects/{slug}").json()["clipes"] == 3
        job = _montar(c, slug)
        assert job["estado"] == "ok", job
        video, audio, dur = _sonda(d / "entrada.mp4")
        assert (video["width"], video["height"]) == (1080, 1920)
        assert video["r_frame_rate"] == "30/1" and video["pix_fmt"] == "yuv420p"
        assert dur == pytest.approx(6.0, abs=0.3)
        assert len(audio) == 1 and audio[0]["sample_rate"] == "48000" and audio[0]["channels"] == 2
        assert not (d / "entrada.mov").exists()
        assert not list(d.glob(".juntar-*")) and not list(d.glob(".clipe-*.tmp"))
        # faixas pretas no deitado (sem distorcer) e a cor de cada trecho no meio da tela
        assert _perto(_cor_do_centro(d / "entrada.mp4", 0.5), COR["horizontal"])
        assert _perto(_cor_do_centro(d / "entrada.mp4", 3.0), COR["vertical"])
        assert _perto(_cor_do_centro(d / "entrada.mp4", 5.5), COR["quadrado"])
        st = c.get(f"/api/projects/{slug}").json()
        assert st["etapas"]["video"] == "pronto" and st["video_montado_de_clipes"] is True
        assert st["montagem_desatualizada"] is False and st["clipes"] == 3
        assert _lista(c, slug)["montado"] is True


def test_single_clip_is_also_normalized(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        assert _enviar(c, slug, amostras["horizontal"], "so um.mp4").status == 200
        assert _montar(c, slug)["estado"] == "ok"
        video, audio, dur = _sonda(srv.app.projects.path(slug) / "entrada.mp4")
        assert (video["width"], video["height"]) == (1080, 1920) and len(audio) == 1
        assert dur == pytest.approx(2.0, abs=0.3)


def test_reorder_changes_the_result_and_marks_it_outdated(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        dados = _tres(c, slug, amostras)
        arqs = [x["arquivo"] for x in dados["clipes"]]
        assert _montar(c, slug)["estado"] == "ok"
        assert _perto(_cor_do_centro(d / "entrada.mp4", 0.5), COR["horizontal"])
        nova = [arqs[2], arqs[0], arqs[1]]
        r = c.request("POST", f"/api/projects/{slug}/clipes/ordem", body={"ordem": nova})
        assert r.status == 200 and [x["arquivo"] for x in r.json()["clipes"]] == nova
        st = c.get(f"/api/projects/{slug}").json()
        assert st["video_montado_de_clipes"] is True and st["montagem_desatualizada"] is True
        assert _lista(c, slug)["desatualizada"] is True
        assert _montar(c, slug)["estado"] == "ok"
        assert _perto(_cor_do_centro(d / "entrada.mp4", 0.5), COR["quadrado"])
        assert _perto(_cor_do_centro(d / "entrada.mp4", 2.0), COR["horizontal"])
        assert c.get(f"/api/projects/{slug}").json()["montagem_desatualizada"] is False


def test_remove_clip_updates_list_and_file(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        dados = _tres(c, slug, amostras)
        meio = dados["clipes"][1]["arquivo"]
        r = c.request("DELETE", f"/api/projects/{slug}/clipes/{meio}")
        assert r.status == 200 and [x["nome"] for x in r.json()["clipes"]] == ["horizontal", "quadrado"]
        assert not (d / "clipes" / meio).exists()
        assert c.request("DELETE", f"/api/projects/{slug}/clipes/{meio}").status == 404
        for hostil in ("..%2Fentrada.mp4", "..", "%2e%2e%2f%2e%2e%2fprojeto.json", "clipes.json", "99-nao-existe.mp4"):
            assert c.request("DELETE", f"/api/projects/{slug}/clipes/{hostil}").status == 404, hostil
        assert (d / "projeto.json").exists()
        # novo envio nao reaproveita o numero do apagado
        novo = _enviar(c, slug, amostras["vertical"], "vertical.mp4").json()["adicionado"]
        assert novo != meio and novo.split("-")[0] == "04"


def test_invalid_order_is_400_and_changes_nothing(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        arqs = [x["arquivo"] for x in _tres(c, slug, amostras)["clipes"]]
        url = f"/api/projects/{slug}/clipes/ordem"
        ruins = [{"ordem": arqs[:2]}, {"ordem": arqs + ["04-extra.mp4"]}, {"ordem": [arqs[0]] * 3},
                 {"ordem": [arqs[0], arqs[1], arqs[1]]}, {"ordem": arqs[:2] + ["../entrada.mp4"]},
                 {"ordem": "tudo"}, {"ordem": [1, 2, 3]}, {"outra": arqs}, [], {"ordem": []}]
        for corpo in ruins:
            assert c.request("POST", url, body=corpo).status == 400, corpo
        assert c.request("POST", url, body=b"nao json").status == 400
        assert [x["arquivo"] for x in _lista(c, slug)["clipes"]] == arqs
        assert c.request("POST", url, body={"ordem": list(reversed(arqs))}).status == 200


def test_hostile_names_are_sanitized(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        nomes = ["../../etc/passwd.mp4", "..\\..\\x\\<script>alert(1)</script>.mov", "a b;rm -rf *.webm",
                 "%2e%2e%2f%2e%2e%2fentrada.mp4", "çãõ ação‮\x07.mkv"]
        for n in nomes:
            r = _enviar(c, slug, amostras["curto"], n)
            assert r.status == 200, (n, r.body)
        itens = _lista(c, slug)["clipes"]
        assert len(itens) == len(nomes)
        import re
        for it in itens:
            assert re.fullmatch(r"[0-9]{2}-[a-z0-9][a-z0-9._-]*\.(mp4|mov|webm|mkv)", it["arquivo"]), it
            assert "/" not in it["nome"] and "\\" not in it["nome"] and "\x07" not in it["nome"]
        # tudo caiu dentro de clipes/: nada fora dele e a pasta do projeto segue so com o esperado
        assert sorted(p.name for p in d.iterdir() if p.name != "clipes") == ["clipes.json", "projeto.json"]
        assert len(list((d / "clipes").iterdir())) == len(nomes)
        assert itens[0]["nome"] == "passwd"
        for ruim in ("a.exe", "a", "a.mp4.sh", ".mp4"):
            assert _enviar(c, slug, amostras["curto"], ruim).status == 400, ruim


def test_text_renamed_to_mp4_is_rejected_without_leftovers(srv):
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe ausente")
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        r = _enviar(c, slug, b"isto nao e um video" * 200, "falso.mp4")
        assert r.status == 400 and "vídeo" in r.json()["erro"]
        assert _enviar(c, slug, b"", "vazio.mp4").status == 400
        assert not list(d.glob(".clipe-*.tmp"))
        assert not list((d / "clipes").iterdir()) if (d / "clipes").exists() else True
        assert _lista(c, slug)["clipes"] == []


def test_upload_over_limit_413(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    s = make_server(root, TOKEN, max_upload=1000, test_mode=True)
    with client(s) as c:
        slug = _criar(c)
        assert _enviar(c, slug, b"x" * 5000, "a.mp4").status == 413
        assert not list(s.app.projects.path(slug).glob(".clipe-*.tmp"))


def test_limits_on_count_and_total_duration(srv, amostras, monkeypatch):
    with client(srv) as c:
        slug = _criar(c)
        monkeypatch.setattr(juntar, "MAX_CLIPES", 3)
        for i in range(3):
            assert _enviar(c, slug, amostras["curto"], f"c{i}.mp4").status == 200
        r = _enviar(c, slug, amostras["curto"], "c4.mp4")
        assert r.status == 400 and "demais" in r.json()["erro"]
        assert len(_lista(c, slug)["clipes"]) == 3
        monkeypatch.setattr(juntar, "MAX_CLIPES", 40)
        monkeypatch.setattr(juntar, "MAX_DURACAO", 1.0)  # 3 x 0,3 s ja e quase isso; mais um estoura
        assert _enviar(c, slug, amostras["horizontal"], "longo.mp4").status == 400
        r = _juntar(c, slug)
        assert r.status in (202, 400)
        if r.status == 202:
            assert _fim(c, r.json()["job_id"])["estado"] == "ok"


def test_empty_list_cannot_be_assembled(srv):
    with client(srv) as c:
        slug = _criar(c)
        r = _juntar(c, slug)
        assert r.status == 400 and "trecho" in r.json()["erro"]
        assert _juntar(c, slug, confirmar="sim").status == 400
        assert _juntar(c, slug, outra=1).status == 400


# ------------------------------------------------------------ confirmar e falhas
def _derivados(d):
    (d / "transcricao.json").write_text('{"duration": 5, "words": []}')
    (d / "cortes.json").write_text('{"cuts": []}')
    (d / "legendas.json").write_text('{"edits": []}')
    (d / "revisao.json").write_text("{}")
    (d / "review.json").write_text("{}")
    (d / "graficos.json").write_text('{"cards": []}')
    (d / "etapas.json").write_text('{"legendas": true}')
    (d / "saida").mkdir(exist_ok=True)
    (d / "saida" / "preview.mp4").write_bytes(b"p")
    (d / "saida" / "final.mp4").write_bytes(b"f")
    (d / "saida" / ".origem-preview.json").write_text("{}")
    # o que NUNCA e apagado
    (d / "estilo.json").write_text("{}")
    (d / "materiais").mkdir(exist_ok=True)
    (d / "materiais" / "logo.png").write_bytes(b"png")
    (d / "capa").mkdir(exist_ok=True)
    (d / "capa" / "capa.png").write_bytes(b"png")


DERIVADOS = ["transcricao.json", "cortes.json", "legendas.json", "revisao.json", "review.json",
             "graficos.json", "etapas.json", "saida/preview.mp4", "saida/final.mp4"]
INTACTOS = ["estilo.json", "materiais/logo.png", "capa/capa.png", "projeto.json"]


def test_derived_files_need_explicit_confirmation(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        _tres(c, slug, amostras)
        (d / "entrada.mp4").write_bytes(b"video anterior")
        _derivados(d)
        r = _juntar(c, slug)
        assert r.status == 409, r.body
        corpo = r.json()
        assert corpo["codigo"] == "precisa_confirmar" and corpo["erro"]
        assert corpo["perde"] == ["cortes", "legendas", "gráficos", "vídeos gerados"]
        assert _juntar(c, slug, confirmar=False).status == 409
        # nada mudou e nenhuma tarefa foi criada
        assert (d / "entrada.mp4").read_bytes() == b"video anterior"
        assert all((d / rel).exists() for rel in DERIVADOS + INTACTOS)
        assert c.get(f"/api/projects/{slug}/jobs").json() == {"ativo": None, "recentes": []}
        # com confirmacao: some so o que dependia do video
        assert _montar(c, slug, confirmar=True)["estado"] == "ok"
        assert not any((d / rel).exists() for rel in DERIVADOS)
        assert all((d / rel).exists() for rel in INTACTOS)
        assert len(list((d / "clipes").iterdir())) == 3
        assert (d / "entrada.mp4").stat().st_size > 1000
        # sem derivados, montar de novo nao pede nada
        assert _montar(c, slug)["estado"] == "ok"


def test_failed_first_clip_deletes_nothing(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        arqs = [x["arquivo"] for x in _tres(c, slug, amostras)["clipes"]]
        (d / "clipes" / arqs[0]).write_bytes(b"estragou depois de enviar" * 50)
        (d / "entrada.mp4").write_bytes(b"video anterior")
        _derivados(d)
        job = _montar(c, slug, confirmar=True)
        assert job["estado"] == "erro" and job["mensagem"]
        assert str(d) not in job["mensagem"] and "Traceback" not in job["mensagem"]
        assert (d / "entrada.mp4").read_bytes() == b"video anterior"
        assert all((d / rel).exists() for rel in DERIVADOS + INTACTOS)
        assert not list(d.glob(".juntar-*"))


def test_failed_assembly_keeps_previous_video(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        arqs = [x["arquivo"] for x in _tres(c, slug, amostras)["clipes"]]
        (d / "entrada.mp4").write_bytes(b"video anterior")
        # o 1o passa; o 3o e lido (ffprobe ok) mas nao da para recodificar: cabecalho de video valido
        # com o resto truncado
        corte = amostras["quadrado"]
        (d / "clipes" / arqs[2]).write_bytes(corte[: len(corte) // 3])
        job = _montar(c, slug)
        assert job["estado"] == "erro", job
        assert (d / "entrada.mp4").read_bytes() == b"video anterior"
        assert not list(d.glob(".juntar-*")) and not list(d.glob(".clipe-*.tmp"))
        st = c.get(f"/api/projects/{slug}").json()
        assert st["video_montado_de_clipes"] is False


def test_double_click_second_request_is_409(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        _tres(c, slug, amostras)
        primeiro = _juntar(c, slug)
        assert primeiro.status == 202
        segundo = _juntar(c, slug)
        assert segundo.status == 409 and segundo.json()["codigo"] == "tarefa_rodando"
        assert _fim(c, primeiro.json()["job_id"])["estado"] == "ok"


def test_list_cannot_change_while_a_job_runs(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        arqs = [x["arquivo"] for x in _tres(c, slug, amostras)["clipes"]]
        jid = srv.app.jobs.start(slug, "preview", [sys.executable, "-c", "import time; time.sleep(30)"],
                                 d, [])
        try:
            r = _enviar(c, slug, amostras["curto"], "novo.mp4")
            assert r.status == 409 and r.json()["codigo"] == "tarefa_rodando"
            assert c.request("DELETE", f"/api/projects/{slug}/clipes/{arqs[0]}").status == 409
            r = c.request("POST", f"/api/projects/{slug}/clipes/ordem", body={"ordem": arqs[::-1]})
            assert r.status == 409
            assert _juntar(c, slug).status == 409
            assert _lista(c, slug)["clipes"][0]["arquivo"] == arqs[0]  # a leitura continua livre
        finally:
            srv.app.jobs.cancel(jid)
            _fim(c, jid, 20)
        assert not list(d.glob(".clipe-*.tmp"))


# ------------------------------------------------------------ compatibilidade e robustez
def test_direct_video_upload_still_works_and_leaves_clips_alone(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        arqs = [x["arquivo"] for x in _tres(c, slug, amostras)["clipes"]]
        assert _montar(c, slug)["estado"] == "ok"
        r = c.request("PUT", f"/api/projects/{slug}/video", body=amostras["vertical"],
                      headers={"X-Filename": "bruto.mp4"})
        assert r.status == 200
        st = r.json()
        assert st["clipes"] == 3 and st["video_montado_de_clipes"] is False
        assert (d / "entrada.mp4").read_bytes() == amostras["vertical"]
        assert [x["arquivo"] for x in _lista(c, slug)["clipes"]] == arqs


def test_corrupt_list_is_rebuilt_from_the_folder(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        arqs = [x["arquivo"] for x in _tres(c, slug, amostras)["clipes"]]
        (d / "clipes.json").write_text("{ isto nao e json")
        dados = _lista(c, slug)
        assert [x["arquivo"] for x in dados["clipes"]] == sorted(arqs)
        assert all(x["duracao"] > 0 for x in dados["clipes"])
        assert c.get(f"/api/projects/{slug}").json()["clipes"] == 3
        assert _montar(c, slug)["estado"] == "ok"
        # a lista volta a ser valida depois de gravar de novo
        assert json.loads((d / "clipes.json").read_text("utf-8"))["montado"]
        # arquivo apagado a mao some da lista; arquivo solto entra no fim
        (d / "clipes" / arqs[0]).unlink()
        assert [x["arquivo"] for x in _lista(c, slug)["clipes"]] == arqs[1:]


def test_routes_auth_methods_and_missing_project(srv, amostras):
    with client(srv) as c:
        slug = _criar(c)
        assert c.get(f"/api/projects/{slug}/clipes", token=False).status == 401
        assert c.request("PUT", f"/api/projects/{slug}/clipes", body=amostras["curto"], token=False,
                         headers={"X-Filename": "a.mp4"}).status == 401
        assert c.request("POST", f"/api/projects/{slug}/clipes", body={}).status == 405
        assert c.request("DELETE", f"/api/projects/{slug}/clipes").status == 405
        assert c.get(f"/api/projects/{slug}/clipes/ordem").status == 405
        assert c.request("PUT", f"/api/projects/{slug}/clipes/ordem", body={}).status == 405
        assert c.get(f"/api/projects/{slug}/clipes/99-a.mp4").status == 405
        assert c.get("/api/projects/nao-existe/clipes").status == 404
        assert _enviar(c, "nao-existe", amostras["curto"]).status == 404
        assert c.request("POST", "/api/projects/nao-existe/clipes/ordem", body={"ordem": []}).status == 404
        assert c.request("DELETE", "/api/projects/nao-existe/clipes/99-a.mp4").status == 404
        assert _juntar(c, "nao-existe").status == 404
        assert c.get(f"/api/projects/{slug}/clipes/a/b").status == 404
        # os trechos nao sao servidos como arquivo
        assert c.get(f"/api/projects/{slug}/arquivos/clipes/01-a.mp4").status == 404


def test_cancel_cleans_temporary_folder(srv, amostras, tmp_path):
    """Cancelar no meio da montagem (SIGTERM) nao deixa pasta temporaria."""
    with client(srv) as c:
        slug = _criar(c)
        d = srv.app.projects.path(slug)
        pesado = tmp_path / "pesado.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=1920x1080:rate=30:duration=40", "-c:v", "libx264",
                        "-preset", "ultrafast", str(pesado)], check=True, capture_output=True)
        for i in range(3):
            assert _enviar(c, slug, pesado.read_bytes(), f"p{i}.mp4").status == 200
        r = _juntar(c, slug)
        assert r.status == 202
        jid = r.json()["job_id"]
        fim = time.time() + 30
        while time.time() < fim and not list(d.glob(".juntar-*")):
            time.sleep(0.05)
        assert list(d.glob(".juntar-*")), "a montagem deveria estar em andamento"
        assert c.request("POST", f"/api/jobs/{jid}/cancelar", body={}).json() == {"ok": True}
        assert _fim(c, jid, 30)["estado"] == "cancelado"
        assert not list(d.glob(".juntar-*")) and not (d / "entrada.mp4").exists()
