"""Tela "Juntar vários trechos" (passo Vídeo) dirigida por Chromium headless.

O driver (tests/js/app_flow_d.mjs) sobe o app/server.py REAL em modo de teste e usa os
scripts de verdade (juntar.py com ffmpeg). Sem node/Chromium/ffmpeg os testes sao pulados.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import test_app_ui_shell as shell
from projects import Projects

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "js" / "app_flow_d.mjs"
SCREENS = REPO / ".superpowers" / "sdd" / "2026-10-23-interface-web" / "screens-clipes"
NOMES = ["Trecho um - vermelho", "Trecho dois - verde", "Trecho três - azul"]


def _gerar(destino, cor, tam, fps, dur, audio):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={cor}:s={tam}:r={fps}:d={dur}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={dur}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else [])
    subprocess.run(cmd + [str(destino)], check=True, capture_output=True)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    missing = shell._requirements()
    if missing:
        pytest.skip(f"tela de juntar trechos nao testada: {missing}")
    tmp = tmp_path_factory.mktemp("app_flow_d")
    clipes = tmp / "clipes"
    clipes.mkdir()
    a, b, c = (clipes / f"{n}.mp4" for n in NOMES)
    _gerar(a, "red", "640x360", 25, 2, False)
    _gerar(b, "lime", "360x640", 30, 3, True)
    _gerar(c, "blue", "500x500", 24, 1, True)
    lixo, texto = clipes / "lixo.mp4", clipes / "notas.txt"
    lixo.write_bytes(b"isto nao e um video" * 100)
    texto.write_text("so texto")
    root = tmp / "projects"
    root.mkdir()
    proj = Projects(root)
    slugs = {k: proj.create(n)["slug"] for k, n in (
        ("principal", "Reel principal"), ("cancelar", "Reel cancelar"), ("ruins", "Reel ruins"),
        ("confirmar", "Reel confirmar"), ("trocaA", "Reel A lento"), ("trocaB", "Reel B"),
        ("estreito", "Reel estreito"))}
    d = root / slugs["confirmar"]  # ja tem video e tudo o que depende dele
    shutil.copy(a, d / "entrada.mp4")
    (d / "transcricao.json").write_text('{"duration": 2.0, "words": []}')
    (d / "cortes.json").write_text('{"cuts": []}')
    (d / "legendas.json").write_text('{"edits": []}')
    (d / "graficos.json").write_text('{"cards": []}')
    (d / "saida").mkdir()
    (d / "saida" / "preview.mp4").write_bytes(b"p")
    (d / "estilo.json").write_text("{}")
    marca = json.loads((REPO / "brand" / "brand.json").read_text("utf-8"))
    brand = tmp / "brand.json"
    brand.write_text(json.dumps({**marca, "handles": ["@gutmannesilva"]}), "utf-8")
    cfg = {"tmp": str(tmp), "screens": str(SCREENS), "root": str(root), "brand": str(brand), "slugs": slugs,
           "clipes": {"a": str(a), "b": str(b), "c": str(c), "lixo": str(lixo), "texto": str(texto)}}
    (tmp / "cfg.json").write_text(json.dumps(cfg), "utf-8")
    r = subprocess.run(["node", str(DRIVER), str(tmp / "cfg.json")], capture_output=True,
                       text=True, env=shell._node_env(), timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    out["_root"] = root
    out["_slugs"] = slugs
    return out


def _ok(results, name):
    res = results[name]
    assert "error" not in res, res.get("error")
    assert not res.get("erros"), res.get("erros")
    return res


def _sonda(caminho):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                          "-of", "json", str(caminho)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"]


# ------------------------------------------------------------------ envio
def test_choose_mode_and_send_three_clips_with_progress(results):
    r = _ok(results, "enviar")
    assert r["modosAntes"] == [["Um vídeo só", "true"], ["Juntar vários trechos", "false"]]
    assert r["modosDepois"] == [["Um vídeo só", "false"], ["Juntar vários trechos", "true"]]
    assert "Nenhum trecho ainda" in r["listaVaziaTexto"] and r["montarDesligado"] is True
    assert r["inputMultiplo"] is True
    e = r["envio"]
    assert "Enviando o trecho 1 de 3" in e["texto"] or "Conferindo o trecho 1 de 3" in e["texto"], e["texto"]
    assert e["barras"] == ["clipes-barra-arquivo", "clipes-barra-geral"]
    assert e["cancelar"] is True and e["zonaDesligada"] is True and e["montarDesligado"] is True
    assert r["depoisDoEnvio"] == NOMES, "a ordem de envio e a da lista"
    assert len(r["metas"]) == 3 and all("0:0" in m and "MB" in m for m in r["metas"]), r["metas"]
    assert r["total"].startswith("3 trechos") and "0:06" in r["total"], r["total"]
    assert r["avisosVisiveis"] is False
    assert r["estadoApi"] == 3


def test_reorder_by_keyboard_buttons_and_drag_then_remove(results):
    r = _ok(results, "ordem")
    assert r["modoAoAbrir"] == "true", "com trechos na lista a tela abre no modo de juntar"
    assert r["antes"] == NOMES
    assert r["subirDoPrimeiro"] is True and r["descerDoUltimo"] is True
    assert r["rotuloBotao"] == f"Descer o trecho 1, {NOMES[0]}"
    assert r["depoisDescer"] == [NOMES[1], NOMES[0], NOMES[2]]
    assert r["focoNoMovido"] is True and r["focoDepoisDescer"]["acao"] == "descer", "o foco acompanha o trecho"
    assert r["focoShiftTab"] == "subir"
    assert r["depoisSubir"] == NOMES
    assert r["focoDepoisSubir"]["arquivo"], "o foco continua num botao do trecho movido"
    assert r["ordemNoServidor"] == NOMES
    assert r["depoisArrastar"] == [NOMES[2], NOMES[0], NOMES[1]]
    assert r["ordemNoServidorDepoisArrastar"] == r["depoisArrastar"]
    assert r["situacaoAntes"] is False, "nada de aviso de montagem antes de montar"
    assert r["depoisRemover"] == [NOMES[2], NOMES[1]]
    assert r["focoDepoisRemover"]["arquivo"], "depois de remover o foco vai para outro trecho"
    assert r["totalDepois"].startswith("2 trechos")
    assert r["final"] == [NOMES[2], NOMES[1], NOMES[0]], "o reenviado vai para o fim"


def test_assemble_shows_video_in_player_and_unlocks_cuts(results):
    r = _ok(results, "montar")
    assert r["cortesBloqueado"] == "true"
    assert "Montando o vídeo com os trechos" in r["progresso"]
    assert r["detalhesFechados"] is True and r["cancelavel"] is True
    assert r["montarEscondido"] is True and r["botoesDuranteDesligados"] is True and r["zonaDesligada"] is True
    assert r["tituloInfo"] == "Vídeo montado"
    assert r["cortesLiberado"] == "false" and r["videoPronto"] == "pronto"
    assert "/arquivos/entrada.mp4" in r["playerSrc"] and "v=" in r["playerSrc"]
    assert r["playerRotulo"] == "Vídeo montado com os trechos"
    assert "foi montado com estes trechos" in r["situacao"]
    assert r["tarefaEscondida"] is True
    assert r["irParaCortes"].startswith("Ir para Cortes")
    assert r["estado"]["video_montado_de_clipes"] is True and r["estado"]["clipes"] == 3
    assert "mudou depois da última montagem" in r["situacaoDesatualizada"]
    assert r["passoSeguinte"] == "cortes"
    d = results["_root"] / results["_slugs"]["principal"]
    streams = _sonda(d / "entrada.mp4")
    video = next(s for s in streams if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in streams)


def test_cancel_upload_keeps_what_arrived(results):
    r = _ok(results, "cancelar")
    assert "cancelado" in r["aviso"].lower()
    assert r["envioEscondido"] is True and r["montarDesligado"] is (r["lista"] == 0)
    assert r["lista"] == r["noServidor"]
    assert r["avisoFechado"] is True


def test_bad_files_are_explained_and_hostile_names_are_text(results):
    r = _ok(results, "ruins")
    aviso = r["aviso"]
    assert "lixo.mp4" in aviso and "Não consegui ler este vídeo" in aviso
    assert "notas.txt" in aviso and "não é aceito" in aviso
    assert "sem.extensao" in aviso and "vazio.mp4" in aviso and "vazio" in aviso
    assert "chegou" in aviso, "um trecho bom chegou junto com os ruins"
    assert len(r["lista"]) == 1 and r["noServidor"] == 1
    assert r["pwn"] is True and r["imgsNaLista"] == 0
    assert "solto-na-area" in r["depoisDoDrop"] and len(r["depoisDoDrop"]) == 2


# ------------------------------------------------------------ confirmacao
def test_confirmation_lists_what_will_be_lost_and_changes_nothing_until_yes(results):
    r = _ok(results, "confirmar")
    assert "já tem um vídeo" in r["situacaoAntes"]
    assert r["itens"] == ["cortes", "legendas", "gráficos", "vídeos gerados"]
    assert r["botao"] == "Entendi, montar e recomeçar os cortes"
    assert "apaga" in r["titulo"]
    assert r["focoNaConfirmacao"] == "clipes-confirmar-sim"
    assert r["tarefaIniciada"] is False
    assert r["estadoSemConfirmar"]["cortes"] == "pronto" and r["estadoSemConfirmar"]["preview"] == "pronto"
    assert r["confirmacaoFechou"] is True and r["focoVoltou"] == "clipes-montar"
    assert r["estadoDepoisDeVoltar"]["cortes"] == "pronto"
    assert r["estadoDepois"]["cortes"] == "pendente" and r["estadoDepois"]["preview"] == "pendente"
    assert r["estadoDepois"]["estilo"] == "pronto", "o estilo continua"
    assert r["estadoDepois"]["video"] == "pronto"
    assert r["rolagem375"]["scrollWidth"] <= r["rolagem375"]["clientWidth"], r["rolagem375"]
    assert not r["rolagem375"]["estouram"], r["rolagem375"]


# ----------------------------------------------------- troca de Reel e 375 px
def test_switching_reel_during_upload_ignores_old_responses(results):
    r = _ok(results, "troca")
    assert "Reel B" in r["cabecalho"] and "Reel A" not in r["cabecalho"]
    assert r["listaB"] == 0 and r["envioVisivelNoB"] is False and r["avisosNoB"] is False
    assert r["noServidorA"] == 2 and r["noServidorB"] == 0, "o envio terminou no Reel certo"
    assert any("trechos chegaram" in t for t in r["toasts"]), r["toasts"]
    assert r["listaAVoltando"] == 2


def test_narrow_screen_has_no_horizontal_scroll(results):
    r = _ok(results, "estreito")
    for chave in ("rolagemLista", "rolagemEnvio"):
        s = r[chave]
        assert s["scrollWidth"] <= s["clientWidth"] and s["bodyScroll"] <= s["clientWidth"], (chave, s)
        assert not s["estouram"], (chave, s)
    assert all(h >= 36 for h in r["botoesAltura"]), r["botoesAltura"]


def test_juntar_screens_have_no_jargon(results):
    _ok(results, "enviar")
    for tela, texto in results["visivel"].items():
        achados = sorted({m.group(0) for m in shell.PROIBIDOS.finditer(texto)})
        assert not achados, (tela, achados)
        for termo in [t for t in shell.JARGAO if t != "ASS"]:
            assert termo.lower() not in texto.lower(), (tela, termo)
