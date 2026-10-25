"""Fluxo completo na tela (projeto novo -> video -> fala -> cortes -> legendas -> preview ->
estilo -> capa -> final) por Chromium, com conferencia dos arquivos gerados, sem erros no
console e sem nenhuma requisicao fora de 127.0.0.1; mais uma segunda aba no mesmo projeto.
Sem node/Chromium/ffmpeg os testes sao pulados."""
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

import test_app_ui_shell as shell

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "js" / "app_full_flow.mjs"


def _wh(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    return s["width"], s["height"]


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    missing = shell._requirements()
    if missing:
        pytest.skip(f"fluxo completo nao testado: {missing}")
    tmp = tmp_path_factory.mktemp("app_full_flow")
    video = tmp / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=720x1280:rate=30:duration=6",
                    "-c:v", "libvpx-vp9", "-b:v", "300k", "-an", str(video)],
                   check=True, capture_output=True)
    marca = json.loads((REPO / "brand" / "brand.json").read_text("utf-8"))
    brand = tmp / "brand.json"
    brand.write_text(json.dumps({**marca, "handles": ["@gutmannesilva"]}), "utf-8")
    cfg = {"tmp": str(tmp), "video": str(video), "brand": str(brand)}
    (tmp / "cfg.json").write_text(json.dumps(cfg), "utf-8")
    r = subprocess.run(["node", str(DRIVER), str(tmp / "cfg.json")], capture_output=True,
                       text=True, env=shell._node_env(), timeout=1500)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    out["_dir"] = str(tmp / "projects" / out["slug"]) if out.get("slug") else None
    return out


def _ok(results):
    assert "error" not in results, results.get("error")
    return results


def test_full_flow_in_the_screen_produces_final_files(results):
    r = _ok(results)
    assert r["cortou"] is True
    d = Path(r["_dir"])
    assert _wh(d / "saida" / "final.mp4") == (1080, 1920)
    assert Image.open(d / "capa" / "capa.png").size == (1080, 1920)
    estilo = r["estilo"]  # lido antes de a segunda parte do teste mexer nos efeitos
    assert json.loads((d / "estilo.json").read_text("utf-8")) == estilo
    assert estilo["paleta"] == "grafite"
    assert estilo["legenda"] == {"estilo": "faixa-azul", "posicao": "meio", "tamanho": "G"}
    efeitos = [c for c in r["graficos"]["cards"] if c.get("efeito") == "palavra-destaque"]
    assert len(efeitos) == 1 and "PRAZO" in json.dumps(efeitos[0], ensure_ascii=False)
    assert all(p["estado"] == "pronto" for k, p in r["passos"].items() if k in ("video", "cortes", "legendas", "capa", "final"))


def test_full_flow_has_no_console_errors_and_no_external_requests(results):
    r = _ok(results)
    assert r["errosAba1"] == [], r["errosAba1"]
    assert r["errosAba2"] == [] and r["errosAba1Final"] == []
    assert r["externas"] == [], r["externas"]


def test_second_browser_tab_same_project_consistent(results):
    r = _ok(results)
    assert r["passos2"] == r["passos"], "a segunda aba ve o mesmo andamento"
    assert r["estado2"] == r["estado1"]
    assert r["arquivosFinal2"] == r["arquivosFinal"], "e os mesmos arquivos finais"
    assert r["efeitos2Antes"] == 1
    assert r["efeitos2Depois"] == 0, "a acao da primeira aba aparece ao recarregar a segunda"
