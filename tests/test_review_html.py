"""Pagina de revisao (review/review.html) dirigida por Chromium headless.

O driver e Node + Playwright (tests/js/review_driver.cjs); Python playwright nao
e dependencia. Um unico processo node roda todos os cenarios (um navegador, varios
contextos em paralelo) e devolve as observacoes em JSON; cada teste afirma sobre
o seu cenario. As fixtures saem do ``review_apply.build_review`` real.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import review_apply as ra

REPO = Path(__file__).resolve().parent.parent
HTML = REPO / "review" / "review.html"
DRIVER = REPO / "tests" / "js" / "review_driver.cjs"
BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

WORDS = [
    ("O", 0.50, 0.70), ("prazo", 0.70, 1.10), ("para", 1.10, 1.30), ("recorrer", 1.30, 1.70),
    ("conta", 1.70, 1.95), ("dias", 1.95, 2.15), ("úteis.", 2.15, 2.40),
    ("Leia", 3.80, 4.10), ("a", 4.10, 4.20), ("intimação", 4.20, 4.70), ("com", 4.70, 4.90),
    ("calma.", 4.90, 5.30),
]
CUTS = [{"id": "c1", "start": 0.0, "end": 0.45, "kind": "silence"},
        {"id": "c2", "start": 2.6, "end": 3.4, "kind": "silence"},
        {"id": "c3", "start": 4.7, "end": 4.9, "kind": "filler"}]
XSS = '<img src=x onerror="window.__xss=1">'


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
    if shutil.which("node") is None:
        return "node ausente"
    if shutil.which("ffmpeg") is None:
        return "ffmpeg ausente"
    env = _node_env()
    probe = subprocess.run(
        ["node", "-e", "const {chromium}=require('playwright');"
                       "process.stdout.write(require('fs').existsSync(chromium.executablePath())?'ok':'no')"],
        capture_output=True, text=True, env=env, timeout=30)
    if probe.returncode != 0:
        return "playwright (node) ausente"
    if probe.stdout != "ok":
        return f"Chromium do Playwright ausente em {BROWSERS}"
    return None


def _jw(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def _project(root: Path, words, cuts, extra=None) -> Path:
    root.mkdir(parents=True)
    (root / "entrada.mp4").write_bytes(b"nao e video")
    _jw(root / "transcricao.json", {"duration": 6.0, "words": [
        {"w": w, "start": s, "end": e} for w, s, e in words]})
    _jw(root / "cortes.json", {"cuts": cuts})
    for name, data in (extra or {}).items():
        _jw(root / name, data)
    review = ra.build_review(root)
    _jw(root / "review.json", review)
    return root


def _fixture_dir(base: Path) -> Path:
    fx = base / "fx"
    main = _project(fx / "main", WORDS, CUTS,
                    {"revisao.json": {"removed_cuts": [], "graphics": {"g1": "keep"}, "notes": []}})
    kept = json.loads((main / "review.json").read_text("utf-8"))["kept_duration"]
    (main / "saida").mkdir()
    # VP9 em MP4: o Chromium do Playwright nao tem H.264; o player e o mesmo.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"testsrc2=size=108x192:rate=15:duration={kept}",
                    "-c:v", "libvpx-vp9", "-b:v", "50k", "-an", str(main / "saida" / "preview.mp4")],
                   check=True, capture_output=True)
    applied = fx / "main_applied"
    shutil.copytree(main, applied)
    ra.apply(applied, {"cuts_added": [{"start": 4.9, "end": 5.3}], "notes": [{"t": 1, "text": "nota salva"}]})
    _jw(applied / "review.json", ra.build_review(applied))
    _project(fx / "stale", WORDS, CUTS[:2], {"legendas.json": {"edits": [
        {"idx": 0, "base_text": "texto automático antigo", "text": "Legenda antiga"},
        {"idx": 99, "base_text": "frase que sumiu", "text": "Órfã"}]}})
    _project(fx / "cards", WORDS, CUTS, {
        "graficos.json": {"cards": [
            {"id": "k2", "title": "Segundo card", "body": None, "at": 3.0, "dur": 1.5, "material": None},
            {"id": "k1", "title": XSS, "body": None, "at": 1.0, "dur": 2.0, "material": None}]},
        "revisao.json": {"removed_cuts": [], "graphics": {"k2": "drop"}, "notes": []}})
    xss_words = [("Cuidado", 0.5, 0.9), (XSS, 0.9, 1.4), ("aqui.", 1.4, 1.8)]
    x = _project(fx / "xss", xss_words, [])
    _jw(x / "materiais.json", {"items": [
        {"id": "m1", "kind": "inspiracao", "name": XSS, "url": "https://example.com/x", "note": XSS}]})
    return fx


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    missing = _requirements()
    if missing:
        pytest.skip(f"pagina de revisao nao testada: {missing}")
    assert HTML.is_file(), f"{HTML} nao existe"
    fx = _fixture_dir(tmp_path_factory.mktemp("review_html"))
    r = subprocess.run(["node", str(DRIVER), str(HTML), str(fx)], capture_output=True, text=True,
                       env=_node_env(), timeout=150)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _ok(results, name):
    res = results[name]
    assert "error" not in res, res.get("error")
    return res


def test_tabs_render(results):
    r = _ok(results, "tabs")
    assert r["title"] == "Revisão do Reel" and r["lang"] == "pt-BR"
    assert r["tablists"] == 1 and r["landmarks"] == {"main": True, "header": True}
    tabs = {t["id"]: t for t in r["tabs"]}
    assert set(tabs) == {"tab-revisao", "tab-materiais"}
    assert tabs["tab-revisao"]["selected"] == "true" and tabs["tab-materiais"]["selected"] == "false"
    assert all(t["panelRole"] == "tabpanel" for t in tabs.values())
    assert tabs["tab-materiais"]["panelHidden"] is True and tabs["tab-revisao"]["panelHidden"] is False
    assert "opcional" in tabs["tab-materiais"]["text"].lower()
    a = r["after"]  # seta para a direita leva a Materiais
    assert a["focused"] == "tab-materiais" and a["selected"] == "true"
    assert a["revisaoHidden"] is True and a["materiaisHidden"] is False
    assert a["emptyVisible"] and "Opcional" in a["emptyText"]
    assert r["back"] == "tab-revisao"
    assert r["errors"] == []


def test_empty_materials_is_valid(results):
    r = _ok(results, "empty_materials")
    for case in ("absent", "empty"):
        c = r[case]
        assert c["emptyVisible"] and c["items"] == 0, case
        assert c["errorText"] == [] and c["errors"] == [], case
        assert c["materiaisWrites"] == 0, case  # abrir nao grava nada


def test_word_click_toggles_cut(results):
    r = _ok(results, "word_click")
    assert r["nWords"] == len(WORDS)
    assert r["d1"]["cuts_added"] == [{"start": 4.9, "end": 5.3}] and r["d1"]["cuts_removed"] == []
    assert r["calmaState"] == "cut"
    assert r["d2"]["cuts_added"] == []
    assert r["comBefore"] == "cut" and r["comAfter"] == "kept"
    assert r["d3"]["cuts_removed"] == ["c3"] and r["d3"]["cuts_added"] == []
    assert r["d4"]["cuts_removed"] == []
    assert set(r["d4"]) == ra.DECISION_KEYS
    assert r["seek"] == pytest.approx(3.80 - 0.45 - 0.8, abs=0.02)
    assert "Salvo às" in r["status"] and r["hint"]
    assert r["errors"] == []


def test_no_horizontal_scroll_375px(results):
    r = results["no_hscroll"]
    assert isinstance(r, list), r
    assert len(r) == 6
    for row in r:
        assert row["scrollWidth"] <= row["innerWidth"], row
        if "bodyContrast" in row:
            assert row["bodyContrast"] >= 4.5 and row["mutedContrast"] >= 4.5, row
        else:
            assert row["toggleChanged"], row


def test_caption_edit_and_revert(results):
    r = _ok(results, "caption_edit")
    # a pagina manda o texto automatico que o revisor viu (base_text): o apply confere
    assert r["d1"]["caption_edits"] == {"0": {"text": "Novo texto da legenda", "base_text": r["original"]}}
    assert r["edited"] == "true"
    assert "0" not in r["d2"]["caption_edits"]
    assert r["shownAfterBlank"] == r["original"]  # vazio volta ao automatico
    assert r["d3"]["graphics"] == {"g1": "drop"}
    assert "0:00" in r["times"]
    assert r["errors"] == []


def test_notes_roundtrip(results):
    r = _ok(results, "notes")
    # preview em 2.0 s = 2.45 s do original (antes dele so o corte c1, 0.45 s)
    assert r["d1"]["notes"] == [{"t": pytest.approx(2.45, abs=0.01), "text": "Ajustar a luz aqui"}]
    assert r["d2"]["notes"][0]["text"] == "Ajustar a luz aqui, mais quente"
    assert r["d3"]["notes"] == []
    assert "0:02" in r["label"]
    assert r["errors"] == []


def test_original_to_cut_time(results):
    r = _ok(results, "mapping")
    assert r["a"] == pytest.approx(0.0)        # dentro do 1o corte: inicio dele
    assert r["b"] == pytest.approx(0.55)
    assert r["c"] == pytest.approx(2.15)       # dentro de cortes sobrepostos
    assert r["d"] == pytest.approx(4.0 - 0.45 - 1.0)  # sobreposicao contada uma vez
    assert r["e"] == pytest.approx(1.0)
    assert r["inv"] == pytest.approx(4.0) and r["inv2"] == pytest.approx(0.45)


def test_stale_warning_shown(results):
    r = _ok(results, "stale")
    assert r["hidden"] is False and r["items"] >= 2
    assert "edição de legenda antiga" in r["text"] and "Órfã" in r["text"]
    assert r["errors"] == []


def test_materials_write(results):
    r = _ok(results, "materials_write")
    items = r["mj1"]["items"]
    files = [i["file"] for i in items if "file" in i]
    assert files == ["fo-to-1.png", "fo-to-1-2.png", "seta.svg"]
    for f in files:
        assert "/" not in f and "\\" not in f and not any(ord(ch) < 32 for ch in f)
        assert f.endswith((".png", ".svg"))
        assert "materiais/" + f in r["files1"]
    kinds = [i["kind"] for i in items]
    assert kinds == ["foto", "foto", "icone", "inspiracao"]
    assert items[3]["url"] == "https://example.com/referencia" and "file" not in items[3]
    assert items[0]["note"] == "usar no gancho"
    assert all(set(i) <= {"id", "kind", "name", "file", "url", "note"} for i in items)
    assert len({i["id"] for i in items}) == 4
    assert r["itemsAfterBad"] == 3 and "http" in r["urlError"]
    assert r["link"]["rel"] == "noopener noreferrer" and r["link"]["target"] == "_blank"
    assert r["iframes"] == 0
    assert [i["id"] for i in r["mj2"]["items"]] == [items[0]["id"], items[2]["id"], items[3]["id"]]
    assert "materiais/" + files[1] not in r["files2"]
    san = r["san"]
    assert "/" not in san[0] and "\\" not in san[0] and "\x00" not in san[0] and san[0].endswith(".JPG")
    assert san[1] and san[1] not in (".", "..", "...")
    assert san[2] == "x-3.png"
    assert san[3:] == [True, False, False]
    assert r["errors"] == []


def test_xss_text_is_inert(results):
    r = _ok(results, "xss")
    assert r["fired"] is False and r["evilImgs"] == 0
    assert r["wordText"] == XSS
    assert XSS in r["phraseText"]
    assert XSS in r["matText"]
    assert "Nenhum gráfico nesta versão" in r["graphicsEmpty"]


def test_decisions_restored_and_reload_drops_applied(results):
    r = _ok(results, "reload")
    assert r["restored"] == {"state": "cut", "pending": "true", "notes": 1, "writes": 0}
    # depois de apply + build, o corte ja esta no review.json: a pendencia some
    assert r["d"]["cuts_added"] == [] and r["d"]["notes"] == [{"t": 1, "text": "nota salva"}]
    assert r["after"]["state"] == "cut" and r["after"]["pending"] == "false"
    assert r["errors"] == []


def test_fallback_download_buttons(results):
    r = _ok(results, "fallback")
    assert r["fsaHidden"]
    assert r["dlName"] == "decisions.json"
    assert r["decisions"]["cuts_added"] == [{"start": 4.9, "end": 5.3}]
    assert set(r["decisions"]) == ra.DECISION_KEYS
    assert r["notice"]["hidden"] is False and "não" in r["notice"]["text"].lower()
    assert r["materiais"] == {"items": [
        {"id": r["materiais"]["items"][0]["id"], "kind": "inspiracao", "name": "https://example.com/a",
         "url": "https://example.com/a", "note": ""}]}
    assert r["errors"] == []


def test_graphics_list_shows_card_titles(results):
    r = _ok(results, "cards")
    assert r["labels"] == [XSS, "Segundo card"]  # ordem por instante; titulo como texto
    assert r["fired"] is False
    assert r["checked"] == {"k1": "true", "k2": "false"}
    assert r["d"]["graphics"] == {"k1": "drop"}
    assert r["errors"] == []


def test_page_caption_edit_pinned_to_base_text(results, tmp_path):
    d1 = _ok(results, "caption_edit")["d1"]
    proj = _project(tmp_path / "p", WORDS, CUTS)
    ra.apply(proj, d1)  # mesmos cortes: aplica
    assert json.loads((proj / "legendas.json").read_text("utf-8"))["edits"][0]["text"] == "Novo texto da legenda"
    changed = _project(tmp_path / "q", WORDS, CUTS)
    _jw(changed / "cortes.json", {"cuts": CUTS + [{"id": "c4", "start": 0.7, "end": 1.1, "kind": "manual"}]})
    with pytest.raises(ra.ReviewError, match="frase 0.*mudou"):
        ra.apply(changed, d1)  # cortes mudaram depois de salvar: nao cai em outra frase
    assert not (changed / "legendas.json").exists()


def test_caption_drafts_restored_only_for_same_base(results):
    r = _ok(results, "caption_restore")
    assert r["field0"] == "Restaurada" and r["edited0"] == "true"
    assert r["field1"] == r["base1"]  # rascunho de outra versao da frase: descartado
    assert r["d"]["caption_edits"] == {"0": {"text": "Restaurada", "base_text": r["base0"]}}
    assert r["errors"] == []


def test_csp_blocks_network(results):
    r = _ok(results, "csp")
    assert r["meta"] and "default-src 'none'" in r["meta"] and "connect-src 'none'" in r["meta"]
    assert r["fetched"] == "blocked" and r["img"] == "blocked"
    assert r["requests"] == [] and r["cspErrors"] >= 1, (r["requests"], r["failures"], r["cspErrors"])  # recusado pela CSP, antes da rede


def test_csp_meta_is_first_in_head():
    html = HTML.read_text("utf-8")
    head = html[:html.index("<style>")]
    assert '<meta http-equiv="Content-Security-Policy"' in head
    for directive in ("script-src 'unsafe-inline'", "style-src 'unsafe-inline'", "media-src blob:",
                      "img-src blob: data:", "form-action 'none'", "base-uri 'none'", "object-src 'none'"):
        assert directive in head, directive
