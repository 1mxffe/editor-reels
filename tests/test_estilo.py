"""estilo.json por projeto: carregar, validar contra o banco, salvar e aplicar na marca."""
import copy
import json
from pathlib import Path

import pytest

import banco
import brand
import estilo

REPO = Path(__file__).resolve().parent.parent


def _proj(tmp_path, dados=None, texto=None):
    p = tmp_path / "proj"
    p.mkdir(parents=True)
    if texto is not None:
        (p / "estilo.json").write_text(texto, encoding="utf-8")
    elif dados is not None:
        (p / "estilo.json").write_text(json.dumps(dados), encoding="utf-8")
    return p


def test_default_shape():
    assert estilo.DEFAULT == {"paleta": "marca", "fonte": "Poppins",
                              "legenda": {"estilo": "faixa-azul", "posicao": "baixo", "tamanho": "M"},
                              "cards": {"estilo": "vidro"}}


def test_estilo_missing_file_returns_default(tmp_path):
    p = _proj(tmp_path)
    got = estilo.carregar(p)
    assert got == estilo.DEFAULT
    got["legenda"]["tamanho"] = "G"  # copia: nao muda o DEFAULT
    assert estilo.DEFAULT["legenda"]["tamanho"] == "M"


def test_estilo_invalid_json_message(tmp_path):
    p = _proj(tmp_path, texto="{paleta: marca")
    with pytest.raises(estilo.EstiloError, match="estilo.json não é um JSON válido"):
        estilo.carregar(p)
    p2 = _proj(tmp_path / "b", texto="[1, 2]")
    with pytest.raises(estilo.EstiloError, match="precisa ser um objeto"):
        estilo.carregar(p2)


def test_estilo_unknown_item_rejected(tmp_path):
    casos = [
        ({"paleta": "arco-iris"}, "paleta"),
        ({"legenda": {"estilo": "karaoke"}}, "legenda"),
        ({"legenda": {"estilo": "faixa-azul", "posicao": "topo"}}, "posição"),
        ({"legenda": {"estilo": "faixa-azul", "tamanho": "GG"}}, "tamanho"),
        ({"fonte": "Comic Sans"}, "Poppins"),
        ({"cards": {"estilo": "neon"}}, "vidro"),
        ({"cor": "azul"}, "desconhecida"),
        ({"legenda": {"estilo": "faixa-azul", "animacao": "pop"}}, "desconhecida"),
        ({"cards": {"estilo": "vidro", "x": 1}}, "desconhecida"),
        ({"legenda": "faixa-azul"}, "legenda"),
        ({"paleta": 3}, "paleta"),
    ]
    for i, (dados, trecho) in enumerate(casos):
        p = _proj(tmp_path / str(i), dados)
        with pytest.raises(estilo.EstiloError, match=trecho):
            estilo.carregar(p)


def test_estilo_mensagens_em_portugues_sem_traceback(tmp_path):
    p = _proj(tmp_path, {"fonte": "Arial"})
    with pytest.raises(estilo.EstiloError) as e:
        estilo.carregar(p)
    assert "Poppins" in str(e.value) and "fonte" in str(e.value)
    assert isinstance(e.value, ValueError)


def test_estilo_too_big_rejected(tmp_path):
    p = _proj(tmp_path, texto=json.dumps({"paleta": "marca", "x": "a" * 17000}))
    with pytest.raises(estilo.EstiloError, match="16 KiB"):
        estilo.carregar(p)


def test_estilo_partial_fills_defaults_from_banco(tmp_path):
    p = _proj(tmp_path, {"legenda": {"estilo": "pilula-escura"}})
    got = estilo.carregar(p)
    assert got["paleta"] == "marca" and got["fonte"] == "Poppins"
    # posicao e tamanho vem do padrao do item no banco
    assert got["legenda"] == {"estilo": "pilula-escura", "posicao": "meio", "tamanho": "M"}
    assert got["cards"] == {"estilo": "vidro"}


def test_salvar_valida_e_grava_atomico(tmp_path):
    p = _proj(tmp_path)
    dados = {"paleta": "grafite", "fonte": "Poppins",
             "legenda": {"estilo": "duas-linhas-grandes", "posicao": "meio", "tamanho": "G"},
             "cards": {"estilo": "vidro"}}
    estilo.salvar(p, dados)
    assert json.loads((p / "estilo.json").read_text("utf-8")) == dados
    assert estilo.carregar(p) == dados
    assert [x.name for x in p.iterdir()] == ["estilo.json"]  # sem temporario sobrando
    with pytest.raises(estilo.EstiloError):
        estilo.salvar(p, {**dados, "paleta": "nao-existe"})
    assert estilo.carregar(p) == dados  # o invalido nao foi gravado


def test_aplicar_marca_does_not_write_brand_json(tmp_path):
    arq = tmp_path / "brand.json"
    brand.write_seed(arq)
    antes = arq.read_bytes()
    b = brand.load(arq)
    b_copia = copy.deepcopy(b)
    est = {**estilo.DEFAULT, "paleta": "gelo-claro"}
    efetivo = estilo.aplicar_marca(b, est)
    assert arq.read_bytes() == antes
    assert b == b_copia  # entrada intacta
    pal = banco.carregar().item("paleta", "gelo-claro")["dados"]
    assert efetivo["bg"] == pal["fundo"] and efetivo["fg"] == pal["texto"]
    assert efetivo["accent"] == pal["destaque"] and efetivo["muted"] == pal["apoio"]
    assert efetivo["font_title"] == efetivo["font_body"] == "Poppins"
    assert efetivo["handles"] == b["handles"] and efetivo["handles"] is not b["handles"]
    assert brand.invalid_keys(efetivo) == []


def test_aplicar_marca_paleta_marca_igual_ao_brand():
    b = brand.seed_from_guide()
    assert estilo.aplicar_marca(b, estilo.DEFAULT) == b


def _lum(hexcor):
    def canal(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexcor[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def _mistura(cor, fundo_rgb, opac):
    r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
    m = [round(opac * c + (1 - opac) * f) for c, f in zip((r, g, b), fundo_rgb)]
    return "#" + "".join(f"{c:02x}" for c in m)


def _contraste(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contraste_texto_na_caixa_todas_paletas():
    """Texto vs. fundo da caixa >= 4,5 em toda paleta, nos estilos com caixa.

    Pilula (85 %): pior caso sobre video preto e branco. Faixa: cor cheia da caixa."""
    import captions
    for pal in banco.carregar().itens("paleta"):
        d = pal["dados"]
        assert _contraste(d["texto"], d["fundo"]) >= 4.5, pal["id"]
        for leg in ("pilula-escura", "faixa-azul"):
            est = {**estilo.DEFAULT, "paleta": pal["id"],
                   "legenda": {"estilo": leg, "posicao": "baixo", "tamanho": "M"}}
            ef = estilo.aplicar_marca(brand.seed_from_guide(), est)
            prm = captions.estilo_legenda(est, ef, (1080, 1920))
            assert prm["caixa"] is not None
            if leg == "pilula-escura":
                opac = 1 - prm["alpha"] / 255
                assert abs(opac - 0.85) < 0.01
                for video in ((0, 0, 0), (255, 255, 255)):
                    caixa = _mistura(prm["bg"], video, opac)
                    assert _contraste(prm["fg"], caixa) >= 4.5, (pal["id"], video)
            else:
                assert _contraste(prm["fg"], prm["bg"]) >= 4.5, pal["id"]


def test_cli_graphics_e_capa_estilo_invalido_falham_claro(tmp_path):
    import subprocess
    import sys
    bad = tmp_path / "estilo.json"
    bad.write_text('{"paleta": "arco-iris"}', "utf-8")
    marca = tmp_path / "brand.json"
    brand.write_seed(marca)
    spec = tmp_path / "card.json"
    spec.write_text(json.dumps({"id": "k1", "title": "Prazo", "at": 0, "dur": 2}), "utf-8")
    foto = tmp_path / "foto.png"
    from PIL import Image
    Image.new("RGB", (1080, 1920)).save(foto)
    for cmd in ([str(REPO / "scripts" / "graphics.py"), str(spec), str(marca), str(tmp_path / "o.webm"),
                 "--estilo", str(bad)],
                [str(REPO / "scripts" / "cover_compose.py"), str(foto), str(marca), str(tmp_path / "c.png"),
                 "--hook", "3 MITOS", "--estilo", str(bad)]):
        proc = subprocess.run([sys.executable, "-I", *cmd], capture_output=True, text=True)
        assert proc.returncode == 1, proc.stderr
        assert proc.stderr.startswith("erro:") and "arco-iris" in proc.stderr
        assert "Traceback" not in proc.stderr
    assert not (tmp_path / "o.webm").exists() and not (tmp_path / "c.png").exists()
