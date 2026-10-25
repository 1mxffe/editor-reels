"""Os dez efeitos do banco (banco/efeitos/) e o renderizador generico de efeitos.

Testes com navegador/ffmpeg reais sao pulados (com motivo) quando node,
playwright/Chromium ou o libvpx-vp9 do ffmpeg nao existem. Um navegador por chamada:
cada efeito abre o Chromium poucas vezes (clipe, quadros medidos, texto com marcacao).
"""
import io
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

import banco
import graphics

REPO = Path(__file__).resolve().parent.parent
BANCO = REPO / "banco"
BRAND = json.loads((REPO / "brand" / "brand.json").read_text("utf-8"))
GOLDEN = Path(__file__).resolve().parent / "golden"
IDS = ["card-destaque", "numero-grande", "pilula-destaque", "selos", "polaroides",
       "circulo-a-mao", "seta-a-mao", "calendario", "linha-do-tempo", "palavra-destaque"]
TOPO, BASE = 250, 1580
LIMITE_S = 5.0
CLIPE = (270, 480)


def _need_renderer():
    reason = graphics.renderer_status()
    if reason:
        pytest.skip(f"renderizador de graficos indisponivel: {reason}")


def _item(eid):
    return graphics.efeitos()[eid]


def _png(path: Path, size=(64, 48), color=(168, 200, 240, 255)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path)
    return path


def _video(out: Path, cores=("red", "blue"), dur=1.0, size="540x960"):
    """Video com uma cor por trecho de ``dur`` s (vermelho e depois azul)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg ausente")
    args, filtro = [], ""
    for i, c in enumerate(cores):
        args += ["-f", "lavfi", "-i", f"color=c={c}:size={size}:rate=30:duration={dur}"]
        filtro += f"[{i}:v]"
    filtro += f"concat=n={len(cores)}:v=1:a=0[v]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, "-filter_complex", filtro,
                    "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
                   check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def projeto(tmp_path_factory):
    """Projeto com video (para quadro:<s>) e uma foto em materiais/."""
    p = tmp_path_factory.mktemp("proj")
    _png(p / "materiais" / "foto.png", size=(300, 300), color=(40, 160, 90, 255))
    if shutil.which("ffmpeg") is not None:
        _video(p / "entrada.mp4")
    return p


def _campos(eid):
    c = dict(_item(eid)["dados"].get("exemplo") or {})
    if eid == "polaroides":
        c["imagens"] = ["quadro:0.5", "materiais/foto.png"]
    if eid == "card-destaque":
        c["imagem"] = "materiais/foto.png"
    return c


LARGO = "WÃMÉWÔQ"  # letras largas e acentuadas: pior caso de largura


def _largo(n: int) -> str:
    return (LARGO * n)[:n]


def _mes_de_seis_semanas():
    """(mes, ano) cujo dia 1 cai num sabado e que tem 31 dias: a folha mais alta."""
    import datetime
    nomes = _item("calendario")["campos"][0]["opcoes"]
    for ano in range(2026, 2040):
        for m in (1, 3, 5, 7, 8, 10, 12):
            if datetime.date(ano, m, 1).weekday() == 5:
                return nomes[m - 1], ano
    raise AssertionError("sem mes de 6 semanas")


def _pior(eid):
    """Campos no pior caso permitido pelo manifesto: todo texto no ``max`` com letras
    largas, toda lista no maximo de itens, as escolhas que mais ocupam espaco."""
    c = {}
    for f in _item(eid)["campos"]:
        n = f["itens"]["max"] if "itens" in f else None
        if f["tipo"] == "texto":
            v = _largo(int(f.get("max", graphics.TEXTO_MAX)))
            c[f["id"]] = [v] * n if n else v
        elif f["tipo"] == "imagem":
            fotos = ["quadro:0.5", "materiais/foto.png", "quadro:1.5"]
            c[f["id"]] = (fotos * 2)[:n] if n else "materiais/foto.png"
        elif f["tipo"] == "numero":
            mx = f.get("max", 100)
            c[f["id"]] = [int(mx) - i for i in range(n)] if n else mx
        elif f["tipo"] == "escolha":
            c[f["id"]] = max(f["opcoes"], key=len)
    if eid == "calendario":
        c["mes"], c["ano"] = _mes_de_seis_semanas()
    if eid == "pilula-destaque":
        c["altura"] = "embaixo"
    if eid == "circulo-a-mao":
        c["tamanho"] = "grande"
    return c


def _dur(eid):
    d = _item(eid)["duracao"]
    return min(max(d["min"], 1.2), d["max"])


def _corte(eid):
    return _item(eid)["dados"].get("transicao") == "corte"


def _alpha_sum(im: Image.Image) -> int:
    hist = im.getchannel("A").histogram()
    return sum(i * n for i, n in enumerate(hist))


# ---------------------------------------------------------------- banco

def test_bank_has_the_ten_effects_and_they_draw():
    _need_renderer()
    t0 = time.monotonic()
    b = banco.carregar(BANCO, verificar_efeitos=True)
    assert time.monotonic() - t0 < 30
    assert b.erros == []
    assert sorted(i["id"] for i in b.itens("efeito")) == sorted(IDS)
    for it in b.itens("efeito"):
        assert it["dados"]["area_segura"] is True
        assert it["nome"] and it["descricao"]


@pytest.mark.parametrize("eid", IDS)
def test_effect_html_is_self_contained(eid):
    html = (BANCO / "efeitos" / eid / "efeito.html").read_text("utf-8")
    assert "default-src 'none'" in html and "font-src data:" in html
    assert "img-src data: blob:" in html
    for proibido in ("http://", "https://", "Date.now", "Math.random", "requestAnimationFrame",
                     "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                     "setTimeout", "setInterval", "file:"):
        assert proibido not in html.replace("http://www.w3.org/2000/svg", ""), proibido  # so o namespace SVG
    assert "window.setup" in html and "window.setTime" in html and "textContent" in html


def test_bank_validates_list_fields_and_effect_dados(tmp_path):
    ef = {"nome": "E", "descricao": "E.", "tipo": "efeito", "duracao": {"padrao": 2, "min": 1, "max": 3}}
    casos = {
        "sem-area-segura": {**ef, "campos": [], "dados": {}},
        "pesos-ruins": {**ef, "campos": [], "dados": {"area_segura": True, "pesos": [450]}},
        "transicao-ruim": {**ef, "campos": [], "dados": {"area_segura": True, "transicao": "pisca"}},
        "itens-em-cor": {**ef, "dados": {"area_segura": True},
                         "campos": [{"id": "a", "rotulo": "A", "tipo": "cor", "itens": {"min": 1, "max": 2}}]},
        "itens-incoerente": {**ef, "dados": {"area_segura": True},
                             "campos": [{"id": "a", "rotulo": "A", "tipo": "texto", "itens": {"min": 3, "max": 2}}]},
        "inteiro-em-texto": {**ef, "dados": {"area_segura": True},
                             "campos": [{"id": "a", "rotulo": "A", "tipo": "texto", "inteiro": True}]},
        "mesmo-tamanho-ruim": {**ef, "campos": [{"id": "a", "rotulo": "A", "tipo": "texto"}],
                               "dados": {"area_segura": True, "mesmo_tamanho": [["a", "b"]]}},
    }
    ok = {**ef, "dados": {"area_segura": True, "pesos": [400, 800], "transicao": "corte"},
          "campos": [{"id": "a", "rotulo": "A", "tipo": "texto", "max": 9, "itens": {"min": 1, "max": 3}},
                     {"id": "n", "rotulo": "N", "tipo": "numero", "inteiro": True}]}
    for nome, m in {**casos, "bom": ok}.items():
        d = tmp_path / "efeitos" / nome
        d.mkdir(parents=True)
        (d / "manifesto.json").write_text(json.dumps(m), "utf-8")
        (d / "efeito.html").write_text("<html></html>", "utf-8")
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("efeito")] == ["bom"]
    assert {Path(e["pasta"]).name for e in b.erros} == set(casos)
    assert b.item("efeito", "bom")["campos"][0]["itens"] == {"min": 1, "max": 3}


# ---------------------------------------------------------------- validacao (sem navegador)

@pytest.fixture
def no_tools(monkeypatch):
    def boom(*a, **k):
        raise AssertionError(f"nao deveria executar nada: {a!r}")
    monkeypatch.setattr(graphics.subprocess, "run", boom)
    monkeypatch.setattr(graphics.subprocess, "Popen", boom)


def _spec(eid, campos, **kw):
    s = {"id": "e1", "efeito": eid, "campos": campos, "at": 0.5, "dur": _item(eid)["duracao"]["padrao"]}
    s.update(kw)
    return s


def _violacoes(c):
    """Valores que precisam ser recusados para o campo ``c`` do manifesto."""
    lista = "itens" in c
    um = []
    if c["tipo"] == "texto":
        um += ["x" * (int(c.get("max", graphics.TEXTO_MAX)) + 1), "sino\x07", "zero​width", 7]
    elif c["tipo"] == "numero":
        um += ["3", True, float("nan")]
        if "max" in c:
            um.append(c["max"] + 1)
        if "min" in c:
            um.append(c["min"] - 1)
        if c.get("inteiro"):
            um.append(c.get("min", 1) + 0.5)
    elif c["tipo"] == "escolha":
        um += ["nao-existe", 1]
    elif c["tipo"] == "imagem":
        um += ["../fora.png", "/etc/passwd", "materiais/sumiu.png", "quadro:abc", "http://x/y.png"]
    out = [[v] if lista else v for v in um]
    if lista:
        base = {"texto": "ok", "numero": c.get("min", 1), "imagem": "materiais/foto.png"}[c["tipo"]]
        out += [[base] * (c["itens"]["max"] + 1), "nao-lista", [base, ""]]
    return out


@pytest.mark.parametrize("eid", IDS)
def test_effect_field_limits_enforced(tmp_path, no_tools, eid):
    _png(tmp_path / "materiais" / "foto.png")
    _png(tmp_path.parent / "fora.png")
    item = _item(eid)
    base = _campos(eid)
    if eid == "polaroides":
        base["imagens"] = ["materiais/foto.png"]
    ok = graphics.validate(_spec(eid, base), tmp_path)
    assert ok["efeito"] == eid and ok["title"]
    for c in item["campos"]:
        for ruim in _violacoes(c):
            with pytest.raises(graphics.GraphicsError):
                graphics.validate(_spec(eid, {**base, c["id"]: ruim}), tmp_path)
        if c["obrigatorio"]:
            sem = {k: v for k, v in base.items() if k != c["id"]}
            with pytest.raises(graphics.GraphicsError, match="obrigatório|pelo menos"):
                graphics.validate(_spec(eid, sem), tmp_path)
    with pytest.raises(graphics.GraphicsError, match="campo desconhecido"):
        graphics.validate(_spec(eid, {**base, "cor_extra": "x"}), tmp_path)
    d = item["duracao"]
    for dur in (d["min"] - 0.1, d["max"] + 0.1, "2", None):
        with pytest.raises(graphics.GraphicsError, match="dur"):
            graphics.validate(_spec(eid, base, dur=dur), tmp_path)
    with pytest.raises(graphics.GraphicsError, match="chaves desconhecidas"):
        graphics.validate({**_spec(eid, base), "title": "misturado"}, tmp_path)


def test_unknown_effect_is_error_in_portuguese(tmp_path, no_tools):
    with pytest.raises(graphics.GraphicsError, match="efeito desconhecido 'fogos'.*card-destaque"):
        graphics.validate({"id": "e", "efeito": "fogos", "campos": {"titulo": "x"}, "at": 0, "dur": 2}, tmp_path)
    with pytest.raises(graphics.GraphicsError, match="efeito desconhecido"):
        graphics.validate({"id": "e", "efeito": None, "campos": {}, "at": 0, "dur": 2}, tmp_path)
    doc = tmp_path / "graficos.json"
    doc.write_text(json.dumps({"cards": [_spec("selos", {"selos": ["a", "b"]}, id="a"),
                                         {"id": "b", "efeito": "fogos", "campos": {}, "at": 0,
                                          "dur": 2}]}), "utf-8")
    with pytest.raises(graphics.GraphicsError, match="card 1.*desconhecido"):
        graphics.load_cards(tmp_path)


def test_mixed_graficos_json_and_review_label(tmp_path, no_tools):
    import review_apply as ra
    (tmp_path / "graficos.json").write_text(json.dumps({"cards": [
        {"id": "a", "title": "Antigo", "body": None, "at": 0.5, "dur": 2, "material": None},
        _spec("numero-grande", {"destaque": "60 dias", "frase": "de prazo"}, id="b", at=3.0),
        _spec("circulo-a-mao", {"x": 10}, id="c", at=5.0),
    ]}), "utf-8")
    cards = graphics.load_cards(tmp_path)
    assert [c["title"] for c in cards] == ["Antigo", "60 dias", "Círculo à mão"]
    assert cards[1]["campos"] == {"destaque": "60 dias", "frase": "de prazo"}
    assert cards[2]["campos"] == {"x": 10.0, "y": None, "tamanho": None}
    (tmp_path / "transcricao.json").write_text(json.dumps({"duration": 9, "words": [
        {"w": "oi", "start": 0.1, "end": 0.4}]}), "utf-8")
    (tmp_path / "cortes.json").write_text('{"cuts": []}', "utf-8")
    (tmp_path / "entrada.mp4").write_bytes(b"nao e video")
    assert [c["title"] for c in ra.build_review(tmp_path)["cards"]] == ["Antigo", "60 dias", "Círculo à mão"]


def test_legacy_card_format_still_valid(tmp_path, no_tools):
    _png(tmp_path / "materiais" / "foto.png")
    legado = {"id": "k1", "title": " Prazo em\ndias úteis ", "body": "Conte só os úteis.",
              "at": 1, "dur": 3, "material": "materiais/foto.png"}
    c = graphics.validate(legado, tmp_path)
    foto = (tmp_path / "materiais" / "foto.png").resolve()
    assert c["efeito"] == "card-destaque"
    assert c["campos"] == {"titulo": "Prazo em\ndias úteis", "texto": "Conte só os úteis.", "imagem": foto}
    assert (c["title"], c["body"], c["material"]) == ("Prazo em\ndias úteis", "Conte só os úteis.", foto)
    novo = graphics.validate(_spec("card-destaque", {"titulo": "Prazo em\ndias úteis",
                                                      "texto": "Conte só os úteis.",
                                                      "imagem": "materiais/foto.png"},
                                   id="k1", at=1, dur=3), tmp_path)
    assert {k: novo[k] for k in c} == c
    with pytest.raises(graphics.GraphicsError, match="controle"):
        graphics.validate({**legado, "title": "a\x1bb"}, tmp_path)


def test_palavra_destaque_max_duration(tmp_path, no_tools):
    assert _item("palavra-destaque")["duracao"]["max"] == 2
    ok = graphics.validate(_spec("palavra-destaque", {"palavra": "ISENTO"}, dur=2), tmp_path)
    assert ok["dur"] == 2.0
    with pytest.raises(graphics.GraphicsError, match="máximo do efeito Palavra em destaque: 2 s"):
        graphics.validate(_spec("palavra-destaque", {"palavra": "ISENTO"}, dur=2.1), tmp_path)
    with pytest.raises(graphics.GraphicsError, match="dur"):
        graphics.inspect_effect("palavra-destaque", {"palavra": "ISENTO"}, BRAND, dur=2.5)
    assert _item("palavra-destaque")["dados"]["transicao"] == "corte"


# ---------------------------------------------------------------- navegador real

@pytest.fixture(scope="module", params=IDS)
def clipe(request, tmp_path_factory, projeto):
    """Clipe pequeno (270x480, rapido) de cada efeito (duracao curta) e os quadros decodificados com alfa."""
    _need_renderer()
    eid = request.param
    d = tmp_path_factory.mktemp(f"clipe-{eid}")
    dur = _dur(eid)
    out = graphics.render_card(_spec(eid, _campos(eid), dur=dur), BRAND, d / "e.webm",
                               project=projeto, size=CLIPE)
    frames = d / "frames"
    frames.mkdir()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-c:v", "libvpx-vp9", "-i", str(out),
                    "-pix_fmt", "rgba", str(frames / "f%03d.png")], check=True)
    return eid, dur, out, sorted(frames.glob("f*.png"))


def test_effect_renders_clip_with_alpha_and_duration(clipe):
    eid, dur, out, frames = clipe
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,pix_fmt:"
         "stream_tags=alpha_mode", "-of", "json", str(out)],
        check=True, capture_output=True, text=True).stdout)
    assert abs(float(probe["format"]["duration"]) - dur) <= 1 / 30 + 1e-6
    st = probe["streams"][0]
    assert st["codec_name"] == "vp9" and (st["width"], st["height"]) == CLIPE
    assert st["pix_fmt"] == "yuva420p" or st.get("tags", {}).get("alpha_mode") == "1"
    assert len(frames) == graphics.frame_count(dur)
    meio = Image.open(frames[len(frames) // 2])
    lo, hi = meio.getchannel("A").getextrema()
    assert lo == 0 and hi == 255  # fundo transparente e efeito opaco


@pytest.fixture(scope="module", params=IDS)
def quadros(request, projeto):
    """Quadros 1080x1920 medidos em t = 0, meio da entrada, fim da entrada, meio, saida, fim,
    com os campos no PIOR CASO que o manifesto permite (texto no max, listas cheias)."""
    _need_renderer()
    eid = request.param
    dur = _dur(eid)
    last = (graphics.frame_count(dur) - 1) / graphics.FPS
    ts = [0.0, graphics.ENTER_S / 2, graphics.ENTER_S, (graphics.ENTER_S + last - graphics.EXIT_S) / 2,
          last - graphics.EXIT_S / 2, last]
    t0 = time.monotonic()
    res = graphics.inspect_effect(eid, _pior(eid), BRAND, project=projeto, dur=dur, ts=ts)
    assert time.monotonic() - t0 < LIMITE_S + 3  # Chromium + quadro do video
    return eid, res["quadros"]


def test_effect_respects_safe_areas(quadros):
    """Pior caso: nada acima de y=250 nem dentro da faixa da legenda (y > 1580)."""
    eid, qs = quadros
    for q in qs:
        assert q["pageErrors"] == []
        assert q["caixas"], f"{eid}: nada medido em t={q['t']}"
        for c in q["caixas"]:
            assert c["top"] >= TOPO - 0.5 and c["bottom"] <= BASE + 0.5, (eid, q["t"], c)
        im = Image.open(io.BytesIO(q["png"]))
        assert im.size == (1080, 1920)
        bbox = im.getchannel("A").getbbox()
        if bbox:
            assert bbox[1] >= TOPO and bbox[3] <= BASE, (eid, q["t"], bbox)


def test_effect_worst_case_stays_inside_horizontally(quadros):
    """Pior caso: nada sai pela esquerda/direita e nenhum texto fica cortado por uma
    caixa (texto que nao cabe quebra a linha ou termina em reticencias)."""
    eid, qs = quadros
    for q in qs[2:4]:  # cheio (fim da entrada e meio)
        for c in q["caixas"]:
            assert c["left"] >= -0.5 and c["right"] <= 1080.5, (eid, q["t"], c)
        assert q["cortados"] == [], (eid, q["cortados"])
        l, _, r, _ = Image.open(io.BytesIO(q["png"])).getchannel("A").getbbox()
        assert l >= 0 and r <= 1080
        assert len(q["textos"]) == sum(len(v) if isinstance(v, list) else 1
                                       for k, v in _pior(eid).items()
                                       if _campo(eid, k)["tipo"] == "texto")


def _campo(eid, cid):
    return next(c for c in _item(eid)["campos"] if c["id"] == cid)


def test_effect_entrance_and_exit_frames(quadros):
    eid, qs = quadros
    op = [q["opacidade"] for q in qs]
    if _corte(eid):  # corte seco: igual do primeiro ao ultimo quadro
        assert op == [1, 1, 1, 1, 1, 1]
    else:
        assert op[0] <= 0.001                 # comeca invisivel
        assert 0.3 < op[1] < 0.999            # entrando (ease-out: ja passou da metade)
        assert op[2] >= 0.999 and op[3] >= 0.999  # cheio em 350 ms e parado
        assert 0.001 < op[4] < 0.999          # saindo
        assert op[5] <= 0.001                 # termina invisivel


def test_effect_clip_fades_in_and_out(clipe):
    eid, _, _, frames = clipe
    a = [_alpha_sum(Image.open(f)) for f in frames]
    hold = a[len(a) // 2]
    assert hold > 0
    if _corte(eid):
        assert all(abs(x - hold) <= hold * 0.01 for x in a)
    else:
        # invisivel no primeiro e no ultimo quadro (sobra so ruido do VP9 no clipe pequeno)
        assert a[0] <= hold * 0.01 and a[-1] <= hold * 0.01
        assert a[math.ceil(graphics.ENTER_S * 30)] >= hold * 0.3


def _marcacao(c):
    payload = '<img src=x onerror="window.__xss=1">'
    mx = int(c.get("max", graphics.TEXTO_MAX))
    return payload if len(payload) <= mx else "<b>&amp;</b>"[:mx]


@pytest.mark.parametrize("eid", [e for e in IDS if e not in ("circulo-a-mao", "seta-a-mao")])
def test_effect_text_inert_with_markup(eid, projeto):
    _need_renderer()
    item = _item(eid)
    campos = _campos(eid)
    esperados = []
    for c in item["campos"]:
        if c["tipo"] != "texto":
            continue
        v = _marcacao(c)
        if "itens" in c:
            n = max(c["itens"]["min"], len(campos.get(c["id"]) or []))
            campos[c["id"]] = [v] * n
            esperados += [v] * n
        else:
            campos[c["id"]] = v
            esperados.append(v)
    assert esperados, eid
    t0 = time.monotonic()
    q = graphics.inspect_effect(eid, campos, BRAND, project=projeto, size=(540, 960))
    assert time.monotonic() - t0 < LIMITE_S + 3
    assert q["xss"] is None and q["pageErrors"] == []
    for v in esperados:
        assert v in q["textos"]
    n_img = len(campos.get("imagens") or []) + (1 if campos.get("imagem") else 0)
    assert q["imgCount"] == n_img


@pytest.mark.parametrize("eid", ["circulo-a-mao", "seta-a-mao"])
@pytest.mark.parametrize("canto", [(0, 0), (100, 100)])
def test_hand_drawn_stays_inside_at_extreme_positions(eid, canto):
    _need_renderer()
    campos = {"x": canto[0], "y": canto[1]}
    if eid == "circulo-a-mao":
        campos["tamanho"] = "grande"
    else:
        campos["direcao"] = "para cima" if canto[1] == 0 else "para a direita"
    q = graphics.inspect_effect(eid, campos, BRAND)
    l, t, r, b = Image.open(io.BytesIO(q["png"])).getchannel("A").getbbox()
    assert t >= TOPO and b <= BASE and l >= 0 and r <= 1080


def test_hand_drawn_stroke_draws_progressively():
    _need_renderer()
    res = graphics.inspect_effect("circulo-a-mao", {"x": 50, "y": 50}, BRAND, dur=2,
                                  size=(540, 960), ts=[0.1, 0.3, 0.9])
    soma = [_alpha_sum(Image.open(io.BytesIO(q["png"]))) for q in res["quadros"]]
    assert 0 < soma[0] < soma[1] < soma[2]   # o traco cresce (stroke-dashoffset)


def test_polaroid_uses_video_frames(tmp_path, monkeypatch):
    _need_renderer()
    proj = tmp_path / "p"
    proj.mkdir()
    _video(proj / "entrada.mp4", size="1080x1920")  # 0-1 s vermelho, 1-2 s azul
    (proj / "transcricao.json").write_text(json.dumps({"duration": 4.0, "words": [
        {"w": "oi", "start": 1.0, "end": 1.5}]}), "utf-8")
    # corte de 0 a 0.9 s: na linha do tempo cortada, 0.05 s = 0.95 s do bruto (vermelho)
    # e 0.5 s = 1.4 s do bruto (azul)
    (proj / "cortes.json").write_text(json.dumps({"cuts": [
        {"id": "c1", "start": 0.0, "end": 0.9, "kind": "silencio"}]}), "utf-8")
    c = graphics.validate(_spec("polaroides", {"imagens": ["quadro:0.05", "quadro:0.5"]}, at=0, dur=3), proj)
    assert [x["quadro"] for x in c["campos"]["imagens"]] == [0.95, 1.4]
    with pytest.raises(graphics.GraphicsError, match="fim do vídeo cortado"):
        graphics.validate(_spec("polaroides", {"imagens": ["quadro:5"]}), proj)
    with pytest.raises(graphics.GraphicsError, match="entrada"):
        graphics.validate(_spec("polaroides", {"imagens": ["quadro:0.5"]}), tmp_path / "vazio")

    chamadas = []
    real = graphics.subprocess.run

    def espia(cmd, *a, **k):
        if cmd and cmd[0] == "ffmpeg":
            chamadas.append((cmd, k))
        return real(cmd, *a, **k)
    monkeypatch.setattr(graphics.subprocess, "run", espia)
    q = graphics.inspect_effect("polaroides", {"imagens": ["quadro:0.05", "quadro:0.5"]}, BRAND,
                                project=proj)
    assert len(chamadas) == 2
    for cmd, k in chamadas:
        assert isinstance(cmd, list) and not k.get("shell") and k.get("timeout")
        assert str((proj / "entrada.mp4").resolve()) in cmd
    assert q["imgCount"] == 2 and q["imgLoaded"] is True
    im = Image.open(io.BytesIO(q["png"])).convert("RGB")

    def cor(x, y):
        r, g, b = im.crop((x - 20, y - 20, x + 20, y + 20)).resize((1, 1)).getpixel((0, 0))
        return r, g, b
    r1, _, b1 = cor(392, 787)   # centro da foto 1 (arranjo de 2 polaroides)
    r2, _, b2 = cor(690, 957)   # centro da foto 2
    assert r1 > 180 and b1 < 80, (r1, b1)
    assert b2 > 180 and r2 < 80, (r2, b2)


def test_legacy_card_clip_matches_golden(tmp_path):
    """Regressao: o card antigo, agora desenhado pelo efeito card-destaque do banco,
    gera o mesmo clipe (duracao, alfa quadro a quadro) e o mesmo quadro de antes."""
    _need_renderer()
    gold = json.loads((GOLDEN / "card-destaque-legado-alfa.json").read_text("utf-8"))
    spec = {"id": "k1", "title": "Prazo em dias úteis", "body": "Conte só os dias úteis.",
            "at": 0.5, "dur": gold["dur"], "material": None}
    out = graphics.render_card(spec, BRAND, tmp_path / "c.webm", project=tmp_path, size=(540, 960))
    frames = tmp_path / "f"
    frames.mkdir()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-c:v", "libvpx-vp9", "-i", str(out),
                    "-pix_fmt", "rgba", str(frames / "f%03d.png")], check=True)
    a = [_alpha_sum(Image.open(f)) for f in sorted(frames.glob("f*.png"))]
    assert len(a) == len(gold["alfa"])
    hold = max(gold["alfa"])
    assert all(abs(x - y) <= hold * 0.01 for x, y in zip(a, gold["alfa"]))
    shot = tmp_path / "shot.png"
    info = graphics.inspect_card({**spec, "dur": 1.5}, BRAND, project=tmp_path, size=(540, 960), shot=shot)
    assert info["card"]["top"] == 320 and info["titleWeight"] == "800"
    novo = Image.open(shot).convert("RGBA")
    velho = Image.open(GOLDEN / "card-destaque-legado-540.png").convert("RGBA")
    assert novo.size == velho.size
    dif = sum(abs(p - q) for p, q in zip(novo.tobytes(), velho.tobytes())) / len(novo.tobytes())
    assert dif < 1.0, dif


def _quebra(raiz: Path, nome: str, troca: tuple[str, str] | None = None, sem_csp=False):
    d = raiz / "efeitos" / nome
    shutil.copytree(BANCO / "efeitos" / "numero-grande", d)
    html = (d / "efeito.html").read_text("utf-8")
    if troca:
        assert troca[0] in html
        html = html.replace(troca[0], troca[1], 1)
    if sem_csp:
        html = html.replace('http-equiv="Content-Security-Policy"', 'name="x"')
    (d / "efeito.html").write_text(html, "utf-8")


def test_broken_effect_html_excluded_with_reason(tmp_path):
    _need_renderer()
    shutil.copytree(BANCO / "efeitos" / "numero-grande", tmp_path / "efeitos" / "numero-grande")
    _quebra(tmp_path, "settime-quebrado", ("window.setTime = (t) => {",
                                           "window.setTime = (t) => { if (t > 0.5) throw new Error('quebrei');"))
    _quebra(tmp_path, "setup-quebrado", ("window.setup = async (d) => {",
                                         "window.setup = async (d) => { throw new Error('sem setup');"))
    _quebra(tmp_path, "sem-csp", sem_csp=True)
    _quebra(tmp_path, "sem-settime", ("window.setTime = (t) =>", "window.outraCoisa = (t) =>"))
    leve = banco.carregar(tmp_path)  # sem verificacao: so JSON, nada de navegador
    assert len(leve.itens("efeito")) == 5 and leve.erros == []
    t0 = time.monotonic()
    b = banco.carregar(tmp_path, verificar_efeitos=True)
    assert time.monotonic() - t0 < 4 * LIMITE_S
    assert [i["id"] for i in b.itens("efeito")] == ["numero-grande"]
    m = {Path(e["pasta"]).name: e["motivo"] for e in b.erros}
    assert set(m) == {"settime-quebrado", "setup-quebrado", "sem-csp", "sem-settime"}
    assert "setTime" in m["settime-quebrado"] and "quebrei" in m["settime-quebrado"]
    assert "setup" in m["setup-quebrado"] and "sem setup" in m["setup-quebrado"]
    assert "Content-Security-Policy" in m["sem-csp"]
    assert "setTime" in m["sem-settime"]
    assert all(v.startswith("o efeito não desenha") for v in m.values())
    assert banco.verificar_efeito(leve.item("efeito", "numero-grande")) is None
    r = subprocess.run([sys.executable, "-I", str(REPO / "scripts" / "banco.py"), "validar", "--efeitos",
                        "--raiz", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 1 and "settime-quebrado" in r.stderr and "Traceback" not in r.stderr


def test_driver_refuses_html_outside_bank(tmp_path):
    _need_renderer()
    fora = tmp_path / "x" / "efeito.html"
    fora.parent.mkdir()
    shutil.copy(BANCO / "efeitos" / "numero-grande" / "efeito.html", fora)
    job = {"html": str(fora), "banco": str(BANCO), "width": 540, "height": 960, "fps": 30,
           "data": {}, "inspect": {"ts": [0.0]}}
    with pytest.raises(graphics.GraphicsError, match="fora do banco"):
        graphics._drive(job, tmp_path, "teste")


# ---------------------------------------------------------------- fim do video e teto de duracao

def _proj_video(root: Path, transcricao: float | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _video(root / "entrada.mp4")  # 2 s
    if transcricao is not None:
        (root / "transcricao.json").write_text(json.dumps({"duration": transcricao, "words": [
            {"w": "oi", "start": 0.1, "end": 0.4}]}), "utf-8")
        (root / "cortes.json").write_text('{"cuts": []}', "utf-8")
    return root


def test_quadro_beyond_video_rejected_on_validate(tmp_path):
    # sem transcricao/cortes: a duracao vem do proprio video (ffprobe)
    proj = _proj_video(tmp_path / "p")
    ok = graphics.validate(_spec("polaroides", {"imagens": ["quadro:1.5"]}), proj)
    assert ok["campos"]["imagens"][0]["quadro"] == 1.5
    with pytest.raises(graphics.GraphicsError, match="o segundo 5 está depois do fim do vídeo"):
        graphics.validate(_spec("polaroides", {"imagens": ["quadro:5"]}), proj)


def test_quadro_beyond_end_fails_clearly_at_render(tmp_path, monkeypatch):
    _need_renderer()
    proj = _proj_video(tmp_path / "p")
    monkeypatch.setattr(graphics, "_duracao_video", lambda video: None)  # duracao desconhecida
    c = graphics.validate(_spec("polaroides", {"imagens": ["quadro:9"]}), proj)
    with pytest.raises(graphics.GraphicsError, match="o segundo 9 está depois do fim do vídeo") as e:
        graphics.render_clip(c, BRAND, tmp_path / "o.webm", size=(270, 480))
    assert "sem quadro" not in str(e.value)
    assert not (tmp_path / "o.webm").exists()


def test_effect_ending_after_video_is_error_when_known(tmp_path, no_tools):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "transcricao.json").write_text(json.dumps({"duration": 3.0, "words": []}), "utf-8")
    (proj / "cortes.json").write_text('{"cuts": []}', "utf-8")
    campos = {"destaque": "60 dias"}
    assert graphics.validate(_spec("numero-grande", campos, at=0.5, dur=2.5), proj)["dur"] == 2.5
    with pytest.raises(graphics.GraphicsError, match="depois do fim do vídeo"):
        graphics.validate(_spec("numero-grande", campos, at=2.0, dur=2.0), proj)
    # sem transcricao a duracao nao e conhecida: aceita (o render encurta)
    assert graphics.validate(_spec("numero-grande", campos, at=50, dur=2.0), tmp_path)["at"] == 50
    # formato antigo continua sendo encurtado/ignorado pelo render (comportamento de sempre)
    legado = {"id": "k", "title": "t", "body": None, "at": 2.0, "dur": 2.0, "material": None}
    assert graphics.validate(legado, proj)["dur"] == 2.0


def test_effect_duration_ceiling(tmp_path, no_tools, monkeypatch):
    ef = {"nome": "E", "descricao": "E.", "tipo": "efeito", "campos": [],
          "dados": {"area_segura": True}}
    for nome, mx in (("trinta", 30), ("longo", 31)):
        d = tmp_path / "efeitos" / nome
        d.mkdir(parents=True)
        (d / "manifesto.json").write_text(json.dumps({**ef, "duracao": {"padrao": 3, "min": 1, "max": mx}}),
                                          "utf-8")
        (d / "efeito.html").write_text("<html></html>", "utf-8")
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("efeito")] == ["trinta"]
    assert "30" in b.erros[0]["motivo"]
    item = {**_item("numero-grande"), "duracao": {"padrao": 3, "min": 1, "max": 600}}
    monkeypatch.setattr(graphics, "item_efeito", lambda *a, **k: item)
    with pytest.raises(graphics.GraphicsError, match="30 s"):
        graphics.validate(_spec("numero-grande", {"destaque": "1"}, dur=31), tmp_path)
