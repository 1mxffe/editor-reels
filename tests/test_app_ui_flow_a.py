"""Telas Cortes, Legendas, Preview e Final (entrega A) dirigidas por Chromium headless.

O driver (tests/js/app_flow_a.mjs) sobe o app/server.py REAL em modo de teste com a
transcricao falsa (tests/fixtures_app.py::fake_transcribe_script, ligada por
REEL_APP_FAKE_TRANSCRIBE=1) e percorre: reconhecer a fala -> cortes -> palavras ->
legendas -> preview -> final, alem de cancelar e recarregar com tarefa rodando.
Cortes, legendas, preview e final usam os scripts de verdade (cut.py, review_apply.py,
render.py). Sem node/Chromium/ffmpeg os testes de tela sao pulados; os do servidor
rodam sempre.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

import test_app_ui_shell as shell
from conftest_app import client
import server
import tarefas
from server import make_server

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "js" / "app_flow_a.mjs"
SCREENS = REPO / ".superpowers" / "sdd" / "2026-10-23-interface-web" / "screens-t7"
NOVOS = ["cortes", "legendas", "preview", "final"]


def _ffprobe_wh(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    return s["width"], s["height"]


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    missing = shell._requirements()
    if missing:
        pytest.skip(f"telas da entrega A nao testadas: {missing}")
    tmp = tmp_path_factory.mktemp("app_flow_a")
    video = tmp / "video.mp4"
    # VP9 em MP4 (o Chromium do Playwright nao tem H.264), 6 s como a fala falsa
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=360x640:rate=30:duration=6",
                    "-c:v", "libvpx-vp9", "-b:v", "300k", "-an", str(video)],
                   check=True, capture_output=True)
    cfg = {"tmp": str(tmp), "video": str(video), "screens": str(SCREENS),
           "review_html": str(REPO / "review" / "review.html"),
           "tempo_js": str(REPO / "app" / "web" / "tempo.js")}
    (tmp / "cfg.json").write_text(json.dumps(cfg), "utf-8")
    r = subprocess.run(["node", str(DRIVER), str(tmp / "cfg.json")], capture_output=True,
                       text=True, env=shell._node_env(), timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _ok(results, name):
    res = results[name]
    assert "error" not in res, res.get("error")
    assert not res.get("erros"), res.get("erros")
    return res


# ------------------------------------------------------------------ cortes
def test_cuts_flow_toggle_and_time_saved(results):
    r = _ok(results, "cortes")
    assert "primeira vez" in r["avisoModelo"].lower() and "modelo de voz" in r["avisoModelo"]
    assert r["tarefas"][:2] == ["transcrever", "cortes"], "reconhecer a fala e depois procurar cortes"
    assert r["estado"]["etapas"]["transcricao"] == "pronto"
    assert r["estado"]["etapas"]["cortes"] == "pronto"
    kinds = [c["kind"] for c in r["cortesApi"]]
    assert kinds == ["filler", "silence", "repeat"], kinds
    assert [c["id"] for c in r["lista"]] == ["c1", "c2", "c3"]
    assert all(c["ligado"] == "true" for c in r["lista"])
    # tempo economizado = duracao - kept_duration, em segundos com virgula
    economia = r["duracao"] - r["kept"]
    assert economia == pytest.approx(0.25 + 0.75 + 0.10, abs=0.01)
    assert f"{economia:.1f}".replace(".", ",") in r["economia"], r["economia"]
    # desligar um corte: o servidor deixa de aplicar e o tempo economizado cai
    assert r["desligado"]["ligado"] == "false"
    assert r["desligado"]["ativoNoServidor"] is False
    assert f"{economia - 0.75:.1f}".replace(".", ",") in r["desligado"]["economia"]
    # ligar de novo: o trecho volta a ser cortado no servidor
    assert r["religado"]["ligado"] == "true"
    assert r["religado"]["cobertoNoServidor"] is True
    assert r["idAntes"] == "c2"
    assert r["religado"]["texto"].startswith("Pausa"), "ligado de novo continua sendo a mesma pausa"
    assert f"{economia:.1f}".replace(".", ",") in r["religado"]["economia"]
    assert r["playerOriginal"].endswith("entrada.mp4") or "/arquivos/entrada.mp4" in r["playerOriginal"]
    assert r["detalhes"] == {"resumo": "Detalhes", "aberto": False}


def test_word_click_cut_and_restore(results):
    r = _ok(results, "palavras")
    # palavra mantida -> corta (corte manual no servidor) e o player pula para ela
    assert r["antes"] == "mantida"
    assert r["cortada"] == "cortada"
    assert r["manualNoServidor"] is True
    assert r["playerEm"] == pytest.approx(r["inicioPalavra"], abs=0.3)
    # clicar de novo -> volta
    assert r["restaurada"] == "mantida"
    assert r["manualDepois"] is False
    # palavra dentro de corte automatico ("né") -> restaura (o corte sai)
    assert r["muletaAntes"] == "cortada"
    assert r["muletaDepois"] == "mantida"
    assert r["muletaAtivaNoServidor"] is False


def test_original_to_cut_time_parity_with_review_html(results):
    r = _ok(results, "paridade")
    assert len(r["pontos"]) >= 20
    for a, b, p in zip(r["review"], r["novo"], r["pontos"]):
        assert a["o2c"] == pytest.approx(b["o2c"], abs=1e-9), p
        assert a["c2o"] == pytest.approx(b["c2o"], abs=1e-9), p
    assert r["mergeIgual"] is True


# ----------------------------------------------------------------- legendas
def test_caption_edit_pinned_and_error_shown(results):
    r = _ok(results, "legendas")
    assert r["frases"] >= 1
    assert r["previewBloqueadoAntes"] is True, "Preview so abre com as legendas confirmadas"
    edits = r["legendasJson"]["edits"]
    e0 = [e for e in edits if e["idx"] == 0]
    assert e0 and e0[0]["text"] == "O prazo para recorrer é curto"
    assert e0[0]["base_text"] == r["base0"], "edicao presa ao texto automatico"
    assert r["tagEditada"] == "Editada"
    assert "chaves" in r["erroChaves"] and "{" in r["erroChaves"], r["erroChaves"]
    assert r["erroChaves"].startswith(f"Na frase {r['frases']}"), "mensagem traduzida, frase numerada a partir de 1"
    assert "não mostra" in r["erroChaves"], "com acento"
    assert "2 linhas" in r["erroLinhas"]
    assert r["textoAposErro"] == "texto {ruim}", "o texto digitado nao some no erro"
    assert r["confirmado"] is True
    assert r["passoApos"] == "preview"
    passos = {p["id"]: p for p in r["passosApos"]}
    assert passos["legendas"]["estado"] == "pronto"
    assert passos["preview"]["bloqueado"] is False


# ------------------------------------------------------------------ preview
def test_preview_generates_and_player_loads_it(results):
    """Gera saida/preview.mp4 (540x960 via ffprobe) e o player passa a apontar para ele.
    Nao confere a reproducao: o Chromium do Playwright nao toca H.264."""
    r = _ok(results, "preview")
    assert r["tarefas"] == ["preview"]
    arq = Path(r["root"]) / r["slug"] / "saida" / "preview.mp4"
    assert _ffprobe_wh(arq) == (540, 960)
    assert "/arquivos/saida/preview.mp4" in r["src"]
    assert r["rotuloPlayer"] == "Preview"
    assert r["notas"] and r["notas"][0]["text"] == "Trocar o começo"
    assert isinstance(r["notas"][0]["t"], (int, float)) and r["notas"][0]["t"] >= 0
    assert r["tempoNota"].count(":") == 1
    assert r["finalLiberado"] is True, "preview gerado libera o Final"


def test_final_1080x1920(results):
    r = _ok(results, "final")
    arq = Path(r["root"]) / r["slug"] / "saida" / "final.mp4"
    assert _ffprobe_wh(arq) == (1080, 1920)
    assert r["estado"]["etapas"]["final"] == "pronto"
    assert "/arquivos/saida/final.mp4" in r["src"]
    nomes = [a["texto"] for a in r["arquivos"]]
    assert any("Versão final" in n for n in nomes) and any("Preview" in n for n in nomes)
    assert all("/arquivos/saida/" in a["href"] and a["download"] for a in r["arquivos"])
    reg = [json.loads(x) for x in (Path(r["root"]) / ".abrir-pasta.log").read_text().splitlines()]
    assert reg[-1]["argv"][1] == str(Path(r["root"]) / r["slug"] / "saida")
    assert reg[-1]["argv"][0] in ("open", "xdg-open")
    assert "Pedi ao computador para abrir a pasta" in r["toast"], "so afirma o que sabe"


# --------------------------------------------------- cancelar e recarregar
def test_cancel_running_job_ui(results):
    r = _ok(results, "cancelar")
    assert "Reconhecendo a fala" in r["rodando"]
    assert r["botaoCancelar"] == 1
    assert "Cancelado" in r["depois"]
    assert r["job"]["estado"] == "cancelado"
    assert r["transcricao"] is False
    assert r["botaoDeNovo"] == 1, "da para tentar de novo"


def test_reload_keeps_running_job(results):
    r = _ok(results, "recarregar")
    assert "Reconhecendo a fala" in r["antes"]
    assert "Reconhecendo a fala" in r["depoisF5"], "depois do F5 continua mostrando a tarefa"
    assert r["cancelarDepoisF5"] == 1
    assert r["mesmoJob"] is True
    assert r["cortesNoFim"] >= 1, "acompanhamento retomado e cortes encadeados"


# ---------------------------------------------------------- texto e layout
def test_new_screens_have_no_jargon(results):
    telas = _ok(results, "visivel")["telas"]
    assert set(NOVOS) <= set(telas)
    for tela, texto in telas.items():
        achados = sorted({m.group(0) for m in shell.PROIBIDOS.finditer(texto)})
        assert not achados, (tela, achados)
        assert "transcri" not in texto.lower(), tela
        assert not re.search(r"\b(null|undefined|NaN)\b", texto), (tela, "valor vazio aparecendo como texto")


def test_new_screens_no_horizontal_scroll_375(results):
    r = _ok(results, "scroll375")
    assert set(NOVOS) <= set(r["medidas"])
    for tela, m in r["medidas"].items():
        assert m["scrollWidth"] <= m["clientWidth"], (tela, m)
        assert m["bodyScroll"] <= m["clientWidth"], (tela, m)
    pequenos = [a for a in r["alvos"] if a["h"] < 44 or a["w"] < 44]
    assert not pequenos, pequenos


def test_screenshots_written(results):
    _ok(results, "scroll375")
    for tela in NOVOS:
        for largura in (1280, 375):
            assert (SCREENS / f"{tela}-{largura}-claro.png").is_file(), (tela, largura)


# --------------------------------------------------------------- servidor
TOKEN = "tok-fluxo-a"


@pytest.fixture
def root(tmp_path):
    d = tmp_path / "projects"
    d.mkdir()
    return d


def _projeto(c, srv, nome="Fluxo"):
    slug = c.request("POST", "/api/projects", body={"nome": nome}).json()["slug"]
    (srv.app.root / slug / "entrada.mp4").write_bytes(b"nao e video")
    return slug


def _esperar_job(c, job_id, prazo=30):
    fim = time.monotonic() + prazo
    while time.monotonic() < fim:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["estado"] != "rodando":
            return job
        time.sleep(0.05)
    raise AssertionError("tarefa nao terminou")


def test_fake_transcribe_ignored_outside_test_mode(root, monkeypatch):
    monkeypatch.setenv("REEL_APP_FAKE_TRANSCRIBE", "1")
    real = make_server(root, TOKEN)
    assert server.transcricao_falsa(real) is False
    d = root / "x"
    d.mkdir()
    (d / "entrada.mp4").write_bytes(b"x")
    argv = tarefas.argv("transcrever", d, falso=server.transcricao_falsa(real))
    assert argv[-3].endswith("transcribe.py") and "fixtures_app" not in " ".join(argv)
    with client(real) as c:
        slug = _projeto(c, real)
        r = c.request("POST", f"/api/projects/{slug}/jobs/transcrever", body={})
        assert r.status == 202
        job = _esperar_job(c, r.json()["job_id"], prazo=120)
        assert job["estado"] == "erro", job
        assert not (root / slug / "transcricao.json").exists(), "a transcricao falsa nao pode rodar"
    teste = make_server(root, TOKEN, test_mode=True)
    try:
        assert server.transcricao_falsa(teste) is True
        assert "fixtures_app.py" in " ".join(tarefas.argv("transcrever", d, falso=True))
        monkeypatch.setenv("REEL_APP_FAKE_TRANSCRIBE", "0")
        assert server.transcricao_falsa(teste) is False
    finally:
        teste.server_close()


def test_fake_transcribe_in_test_mode_writes_fixed_words(root, monkeypatch):
    monkeypatch.setenv("REEL_APP_FAKE_TRANSCRIBE", "1")
    srv = make_server(root, TOKEN, test_mode=True)
    with client(srv) as c:
        slug = _projeto(c, srv)
        r = c.request("POST", f"/api/projects/{slug}/jobs/transcrever", body={})
        job = _esperar_job(c, r.json()["job_id"])
        assert job["estado"] == "ok", job
        dados = json.loads((root / slug / "transcricao.json").read_text("utf-8"))
        assert [w["w"] for w in dados["words"]][:3] == ["O", "prazo", "para"]


def test_project_jobs_route_lists_active_and_recent(root, monkeypatch):
    monkeypatch.setenv("REEL_APP_FAKE_TRANSCRIBE", "1")
    monkeypatch.setenv("REEL_APP_FAKE_TRANSCRIBE_ESPERA", "20")
    srv = make_server(root, TOKEN, test_mode=True)
    with client(srv) as c:
        slug = _projeto(c, srv)
        r = c.get(f"/api/projects/{slug}/jobs")
        assert r.status == 200 and r.json() == {"ativo": None, "recentes": []}
        job_id = c.request("POST", f"/api/projects/{slug}/jobs/transcrever", body={}).json()["job_id"]
        r = c.get(f"/api/projects/{slug}/jobs").json()
        assert r["ativo"]["id"] == job_id and r["ativo"]["tipo"] == "transcrever"
        assert r["ativo"]["estado"] == "rodando"
        assert [j["id"] for j in r["recentes"]] == [job_id]
        assert "log" not in r["recentes"][0]
        assert c.request("POST", f"/api/jobs/{job_id}/cancelar").json()["ok"] is True
        _esperar_job(c, job_id)
        r = c.get(f"/api/projects/{slug}/jobs").json()
        assert r["ativo"] is None and r["recentes"][0]["estado"] == "cancelado"
        assert c.get("/api/projects/nao-existe/jobs").status == 404
        assert c.get("/api/projects/Inv@lido/jobs").status == 400
        assert c.get(f"/api/projects/{slug}/jobs", token=False).status == 401
        assert c.request("DELETE", f"/api/projects/{slug}/jobs").status == 405


def test_open_folder_uses_double_and_rejects_bad_slug(root, monkeypatch):
    chamados = []
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: chamados.append(a))
    srv = make_server(root, TOKEN, test_mode=True)
    with client(srv) as c:
        slug = _projeto(c, srv)
        url = f"/api/projects/{slug}/abrir-pasta"
        r = c.request("POST", url, body={})
        assert r.status == 409, "sem arquivos prontos ainda"
        (root / slug / "saida").mkdir()
        r = c.request("POST", url, body={})
        assert r.status == 200 and r.json() == {"ok": True}
        reg = [json.loads(x) for x in (root / ".abrir-pasta.log").read_text().splitlines()]
        esperado = "open" if sys.platform == "darwin" else "xdg-open"
        assert reg == [{"argv": [esperado, str(root / slug / "saida")]}]
        assert chamados == [], "em modo de teste nada e executado"
        assert c.get(url).status == 405
        assert c.request("POST", url, body={}, token=False).status == 401
        for ruim in ("..", "Inv@lido", "a%2F..%2F..", "x" * 50):
            assert c.request("POST", f"/api/projects/{ruim}/abrir-pasta", body={}).status in (400, 404), ruim
        assert c.request("POST", "/api/projects/nao-existe/abrir-pasta", body={}).status == 404
        # saida que e link para fora do projeto: recusada
        alvo = root / "fora"
        alvo.mkdir()
        slug2 = _projeto(c, srv, "Link")
        (root / slug2 / "saida").symlink_to(alvo)
        assert c.request("POST", f"/api/projects/{slug2}/abrir-pasta", body={}).status == 409
    assert len((root / ".abrir-pasta.log").read_text().splitlines()) == 1


def test_open_folder_real_mode_runs_without_shell(root, monkeypatch):
    chamados = []

    class Proc:
        def wait(self):
            return 0

    def falso(argv, **kw):
        chamados.append((argv, kw))
        return Proc()

    monkeypatch.setattr(server.subprocess, "Popen", falso)
    srv = make_server(root, TOKEN)
    with client(srv) as c:
        slug = _projeto(c, srv)
        (root / slug / "saida").mkdir()
        assert c.request("POST", f"/api/projects/{slug}/abrir-pasta", body={}).status == 200
    (argv, kw), = chamados
    assert argv == ["open" if sys.platform == "darwin" else "xdg-open", str(root / slug / "saida")]
    assert not kw.get("shell")
    assert not (root / ".abrir-pasta.log").exists()


def test_state_exposes_captions_confirmation(root):
    srv = make_server(root, TOKEN, test_mode=True)
    with client(srv) as c:
        slug = _projeto(c, srv)
        assert c.get(f"/api/projects/{slug}").json()["legendas_confirmadas"] is False
        (root / slug / "legendas.json").write_text('{"edits": []}')
        st = c.get(f"/api/projects/{slug}").json()
        assert st["legendas_confirmadas"] is False, "legendas.json sozinho nao e confirmacao"
        (root / slug / "etapas.json").write_text('{"legendas": true}')
        assert c.get(f"/api/projects/{slug}").json()["legendas_confirmadas"] is True


# --------------------------------------------------------- fix round 1
def test_stale_outputs_warn_and_lock_final_ui(results):
    r = _ok(results, "desatualizado")
    assert r["estado"]["preview_desatualizado"] is True and r["estado"]["final_desatualizado"] is True
    assert r["estado"]["legendas_desatualizado"] is True
    assert "depois de gerar este vídeo" in r["avisoPreview"]
    assert "Gerar de novo" in r["botaoPreview"] and "botao-primario" in r["classeBotaoPreview"]
    assert r["irParaFinal"] == 0
    passos = {p["id"]: p for p in r["passos"]}
    assert passos["legendas"]["estado"] == "pronto", "confirmado de novo"
    assert passos["preview"]["estado"] != "pronto", "preview antigo nao conta como pronto"
    assert passos["final"]["bloqueado"] is True, "video antigo nao libera o Final"
    assert "confirme de novo" in r["avisoLegendas"]
    assert r["depoisConfirmar"] is False, "confirmar de novo limpa o aviso das legendas"


def test_last_word_past_duration_is_clamped(results):
    r = _ok(results, "ultimaPalavra")
    assert r["estado"] == "cortada", r
    assert r["erro"] == ""
    assert r["corte"]["end"] <= r["duracao"] and r["corte"]["start"] < r["corte"]["end"]


def test_confirm_waits_for_pending_caption_save(results):
    r = _ok(results, "confirmarEspera")
    assert r["painel"] == "legendas", "erro tardio segura a confirmacao"
    assert "chaves" in r["erro"]
    assert r["confirmado"] is False


def test_server_messages_translated_without_jargon(results):
    r = _ok(results, "mensagens")
    for bruto, texto in r["pares"]:
        achados = sorted({m.group(0) for m in shell.PROIBIDOS.finditer(texto)})
        assert not achados, (bruto, texto)
        assert not re.search(r"\b(nao|voce|automatico|codigo)\b", texto), (bruto, texto)
        assert "/" not in texto.replace("cortes/legendas", ""), (bruto, texto)
    d = dict(r["pares"])
    assert d["Ffprobe falhou (codigo 1): [mov,mp4 @ 0x55fe] moov atom not found."].startswith("Não consegui ler este vídeo")
    assert "fim do vídeo" in d["corte novo fora do intervalo: 5.9-6.02 (precisa 0 <= start < end <= 6.0)"]
    assert "Recarregue" in d["frase 0: o texto automatico mudou desde a revisao (era 'x', agora 'y'); recarregue a pagina e edite de novo"]
    assert d["Erro estranho: /usr/lib/x.py linha 3"] == r["generica"]


def _fazer_cortes(c, srv, slug):
    import fixtures_app
    d = srv.app.root / slug
    fixtures_app.montar_projeto(d)
    c.request("PUT", f"/api/projects/{slug}/etapas/legendas", body={"confirmado": True})
    return d


def test_fingerprint_marks_outputs_stale(root):
    import os
    import projects
    srv = make_server(root, TOKEN, test_mode=True)
    with client(srv) as c:
        slug = c.request("POST", "/api/projects", body={"nome": "Impressao"}).json()["slug"]
        d = _fazer_cortes(c, srv, slug)
        url = f"/api/projects/{slug}"

        def gerar():
            for tipo in ("preview", "final"):
                projects.registrar_origem(d, tipo)
                arq = d / "saida" / f"{tipo}.mp4"
                arq.write_bytes(b"x")
                t = (d / "saida" / f".origem-{tipo}.json").stat().st_mtime + 1
                os.utime(arq, (t, t))

        gerar()
        st = c.get(url).json()
        assert (st["legendas_desatualizado"], st["preview_desatualizado"], st["final_desatualizado"]) == (False,) * 3
        assert c.request("PUT", url + "/revisao", body={"notes": [{"t": 1, "text": "oi"}]}).status == 200
        st = c.get(url).json()
        assert (st["legendas_desatualizado"], st["preview_desatualizado"], st["final_desatualizado"]) == (False,) * 3
        assert c.request("PUT", url + "/revisao", body={"cuts_added": [{"start": 4.2, "end": 4.6}]}).status == 200
        st = c.get(url).json()
        assert (st["legendas_desatualizado"], st["preview_desatualizado"], st["final_desatualizado"]) == (True,) * 3
        c.request("PUT", url + "/etapas/legendas", body={"confirmado": True})
        gerar()
        st = c.get(url).json()
        assert (st["legendas_desatualizado"], st["preview_desatualizado"], st["final_desatualizado"]) == (False,) * 3
        # legenda editada tambem conta
        c.request("PUT", url + "/revisao", body={"caption_edits": {"0": {
            "text": "Outro texto", "base_text": c.get(url + "/revisao").json()["phrases"][0]["base_text"]}}})
        assert c.get(url).json()["preview_desatualizado"] is True


def test_generation_registers_origin_and_failed_run_stays_stale(root, monkeypatch):
    srv = make_server(root, TOKEN, test_mode=True)
    with client(srv) as c:
        slug = c.request("POST", "/api/projects", body={"nome": "Origem"}).json()["slug"]
        d = _fazer_cortes(c, srv, slug)
        (d / "saida").mkdir(exist_ok=True)
        (d / "saida" / "preview.mp4").write_bytes(b"velho")
        r = c.request("POST", f"/api/projects/{slug}/jobs/preview", body={})
        assert r.status == 202
        assert (d / "saida" / ".origem-preview.json").is_file()
        job = _esperar_job(c, r.json()["job_id"], prazo=60)
        assert job["estado"] == "erro"  # entrada falsa: o render falha
        assert c.get(f"/api/projects/{slug}").json()["preview_desatualizado"] is True, \
            "arquivo mais velho que a geracao registrada e o antigo"


def test_job_log_hides_project_paths(root):
    real = make_server(root, TOKEN)
    with client(real) as c:
        slug = _projeto(c, real)
        job_id = c.request("POST", f"/api/projects/{slug}/jobs/transcrever", body={}).json()["job_id"]
        _esperar_job(c, job_id, prazo=120)
        log = c.get(f"/api/jobs/{job_id}").json()["log"]
        assert log, "o log deveria ter a saida do erro"
        assert not any(str(root) in linha for linha in log), log
