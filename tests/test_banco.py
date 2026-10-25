import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import banco

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "banco.py"

PALETA = {"fundo": "#001931", "texto": "#ddebf5", "destaque": "#a8c8f0", "apoio": "#566a7a"}
LEGENDA = {"estilo": "faixa", "posicao_padrao": "baixo", "tamanho_padrao": "M"}


def manifesto(tipo="paleta", dados=None, **extra):
    m = {"nome": "Item", "descricao": "Um item de teste.", "tipo": tipo, "campos": [],
         "dados": dict(PALETA if tipo == "paleta" else LEGENDA) if dados is None else dados}
    m.update(extra)
    return m


def escreve(raiz, plural, pasta, m):
    d = raiz / plural / pasta
    d.mkdir(parents=True, exist_ok=True)
    if isinstance(m, str):
        (d / "manifesto.json").write_text(m, encoding="utf-8")
    else:
        (d / "manifesto.json").write_text(json.dumps(m), encoding="utf-8")
    return d


def motivos(b):
    return {Path(e["pasta"]).name: e["motivo"] for e in b.erros}


def run_cli(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


def test_loads_four_palettes_and_four_caption_styles():
    b = banco.carregar(REPO / "banco")
    assert b.erros == []
    assert sorted(i["id"] for i in b.itens("paleta")) == [
        "gelo-claro", "grafite", "marca", "marinho-profundo"]
    assert sorted(i["id"] for i in b.itens("legenda")) == [
        "duas-linhas-grandes", "faixa-azul", "pequena-baixa-esquerda", "pilula-escura"]
    faixa = b.item("legenda", "faixa-azul")
    assert faixa["dados"] == LEGENDA and faixa["tipo"] == "legenda"
    assert faixa["pasta"] == REPO / "banco" / "legendas" / "faixa-azul"
    assert {i["dados"]["estilo"] for i in b.itens("legenda")} == {
        "faixa", "pilula", "duas-linhas", "pequena"}
    with pytest.raises(banco.BancoError):
        b.item("paleta", "nao-existe")
    with pytest.raises(banco.BancoError):
        b.itens("tipo-torto")


def test_invalid_manifest_excluded_and_reported(tmp_path):
    escreve(tmp_path, "paletas", "boa", manifesto())
    escreve(tmp_path, "paletas", "json-quebrado", "{nao e json")
    escreve(tmp_path, "paletas", "cor-ruim", manifesto(dados={**PALETA, "fundo": "#fff"}))
    escreve(tmp_path, "paletas", "tipo-estranho", manifesto(tipo="paleta") | {"tipo": "banana"})
    escreve(tmp_path, "paletas", "tipo-errado-pasta", manifesto(tipo="legenda"))
    escreve(tmp_path, "paletas", "max-negativo", manifesto(campos=[
        {"id": "t", "rotulo": "T", "tipo": "texto", "max": -5}]))
    escreve(tmp_path, "paletas", "outro-id", manifesto(id="x"))
    escreve(tmp_path, "paletas", "a..b", manifesto())
    escreve(tmp_path, "paletas", "chave-extra", manifesto(extra=1))
    escreve(tmp_path, "paletas", "nan", '{"nome":"a","descricao":"b","tipo":"paleta","campos":[],'
            '"dados":{"fundo":"#001931","texto":"#ddebf5","destaque":"#a8c8f0","apoio":"#566a7a"},'
            '"duracao":{"padrao":NaN,"min":1,"max":2}}')
    grande = escreve(tmp_path, "paletas", "grande", manifesto())
    (grande / "manifesto.json").write_text(
        json.dumps(manifesto(descricao="x" * 70000)), encoding="utf-8")
    real = escreve(tmp_path, "paletas", "real", manifesto())
    os.symlink(real, tmp_path / "paletas" / "link-pasta")
    arq = escreve(tmp_path, "paletas", "link-arquivo", manifesto())
    (arq / "manifesto.json").unlink()
    os.symlink(real / "manifesto.json", arq / "manifesto.json")
    (tmp_path / "paletas" / "sem-manifesto").mkdir()

    b = banco.carregar(tmp_path)
    ids = {i["id"] for i in b.itens("paleta")}
    assert ids == {"boa", "real"}
    m = motivos(b)
    assert set(m) == {"json-quebrado", "cor-ruim", "tipo-estranho", "tipo-errado-pasta",
                      "max-negativo", "outro-id", "a..b", "chave-extra", "nan", "grande",
                      "link-pasta", "link-arquivo", "sem-manifesto"}
    assert all(v and isinstance(v, str) for v in m.values())
    assert "JSON" in m["json-quebrado"]
    assert "fundo" in m["cor-ruim"]
    assert "64" in m["grande"]
    assert "link" in m["link-pasta"].lower()


def test_field_types_validation(tmp_path):
    def campos(*cs):
        return manifesto(campos=list(cs))
    ok = [
        {"id": "titulo", "rotulo": "Título", "tipo": "texto", "max": 60, "obrigatorio": True},
        {"id": "qtd", "rotulo": "Quantidade", "tipo": "numero", "min": 0, "max": 10},
        {"id": "foto", "rotulo": "Foto", "tipo": "imagem"},
        {"id": "cor", "rotulo": "Cor", "tipo": "cor"},
        {"id": "lado", "rotulo": "Lado", "tipo": "escolha", "opcoes": ["esquerda", "direita"]},
    ]
    escreve(tmp_path, "paletas", "ok", campos(*ok))
    bad = {
        "tipo-invalido": [{"id": "a", "rotulo": "A", "tipo": "video"}],
        "id-duplicado": [{"id": "a", "rotulo": "A", "tipo": "texto"},
                         {"id": "a", "rotulo": "B", "tipo": "texto"}],
        "min-maior": [{"id": "a", "rotulo": "A", "tipo": "numero", "min": 5, "max": 2}],
        "min-negativo": [{"id": "a", "rotulo": "A", "tipo": "numero", "min": -1}],
        "max-infinito": [{"id": "a", "rotulo": "A", "tipo": "numero", "max": float("inf")}],
        "max-texto": [{"id": "a", "rotulo": "A", "tipo": "texto", "max": "10"}],
        "max-bool": [{"id": "a", "rotulo": "A", "tipo": "texto", "max": True}],
        "escolha-sem-opcoes": [{"id": "a", "rotulo": "A", "tipo": "escolha"}],
        "escolha-vazia": [{"id": "a", "rotulo": "A", "tipo": "escolha", "opcoes": []}],
        "opcoes-nao-string": [{"id": "a", "rotulo": "A", "tipo": "escolha", "opcoes": [1]}],
        "opcoes-demais": [{"id": "a", "rotulo": "A", "tipo": "escolha",
                           "opcoes": [f"o{i}" for i in range(21)]}],
        "opcoes-em-texto": [{"id": "a", "rotulo": "A", "tipo": "texto", "opcoes": ["x"]}],
        "sem-rotulo": [{"id": "a", "tipo": "texto"}],
        "campo-chave-extra": [{"id": "a", "rotulo": "A", "tipo": "texto", "x": 1}],
        "obrigatorio-nao-bool": [{"id": "a", "rotulo": "A", "tipo": "texto", "obrigatorio": "sim"}],
        "campos-nao-lista": {"a": 1},
    }
    for nome, cs in bad.items():
        m = manifesto()
        m["campos"] = cs
        d = escreve(tmp_path, "paletas", nome, "x")
        (d / "manifesto.json").write_text(json.dumps(m), encoding="utf-8")  # inf vira Infinity
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("paleta")] == ["ok"]
    assert set(motivos(b)) == set(bad)
    item = b.item("paleta", "ok")
    assert [c["id"] for c in item["campos"]] == ["titulo", "qtd", "foto", "cor", "lado"]
    assert item["campos"][0]["obrigatorio"] is True
    assert item["campos"][2]["obrigatorio"] is False


def test_duracao_and_effect_rules(tmp_path):
    ef = {"nome": "Efeito", "descricao": "Efeito.", "tipo": "efeito", "campos": [], "dados": {"area_segura": True},
          "duracao": {"padrao": 3, "min": 1, "max": 6}}
    d = escreve(tmp_path, "efeitos", "bom", ef)
    (d / "efeito.html").write_text("<html></html>", encoding="utf-8")
    escreve(tmp_path, "efeitos", "sem-html", ef)
    d = escreve(tmp_path, "efeitos", "sem-duracao", {k: v for k, v in ef.items() if k != "duracao"})
    (d / "efeito.html").write_text("x", encoding="utf-8")
    d = escreve(tmp_path, "efeitos", "duracao-incoerente", {**ef, "duracao": {"padrao": 9, "min": 1, "max": 6}})
    (d / "efeito.html").write_text("x", encoding="utf-8")
    d = escreve(tmp_path, "efeitos", "html-link", ef)
    os.symlink(d.parent / "bom" / "efeito.html", d / "efeito.html")
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("efeito")] == ["bom"]
    assert b.item("efeito", "bom")["duracao"] == {"padrao": 3, "min": 1, "max": 6}
    assert set(motivos(b)) == {"sem-html", "sem-duracao", "duracao-incoerente", "html-link"}


def test_legenda_dados_enums(tmp_path):
    escreve(tmp_path, "legendas", "ok", manifesto("legenda"))
    for nome, dados in {
        "estilo-ruim": {**LEGENDA, "estilo": "neon"},
        "posicao-ruim": {**LEGENDA, "posicao_padrao": "topo"},
        "tamanho-ruim": {**LEGENDA, "tamanho_padrao": "GG"},
        "falta-chave": {"estilo": "faixa"},
        "chave-extra": {**LEGENDA, "x": 1},
    }.items():
        escreve(tmp_path, "legendas", nome, manifesto("legenda", dados=dados))
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("legenda")] == ["ok"]
    assert len(b.erros) == 5


def test_text_limits_and_control_chars(tmp_path):
    escreve(tmp_path, "paletas", "ok", manifesto(nome="a" * 60, descricao="d" * 300))
    escreve(tmp_path, "paletas", "nome-longo", manifesto(nome="a" * 61))
    escreve(tmp_path, "paletas", "desc-longa", manifesto(descricao="d" * 301))
    escreve(tmp_path, "paletas", "nome-vazio", manifesto(nome="  "))
    escreve(tmp_path, "paletas", "nome-ctrl", manifesto(nome="a\u0007b"))
    escreve(tmp_path, "paletas", "nome-numero", manifesto(nome=3))
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("paleta")] == ["ok"]
    assert len(b.erros) == 5


def test_brand_palette_matches_brand_json_seed():
    brand = json.loads((REPO / "brand" / "brand.json").read_text(encoding="utf-8"))
    d = banco.carregar(REPO / "banco").item("paleta", "marca")["dados"]
    assert d == {"fundo": brand["bg"], "texto": brand["fg"],
                 "destaque": brand["accent"], "apoio": brand["muted"]}
    assert d == {"fundo": "#001931", "texto": "#ddebf5", "destaque": "#a8c8f0", "apoio": "#566a7a"}


def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contraste(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_palette_contrast_wcag():
    b = banco.carregar(REPO / "banco")
    for p in b.itens("paleta"):
        d = p["dados"]
        assert contraste(d["fundo"], d["texto"]) >= 4.5, p["id"]
        assert contraste(d["fundo"], d["destaque"]) >= 4.5, p["id"]
    claro = b.item("paleta", "gelo-claro")["dados"]
    assert claro["fundo"] == "#f3f8fb" and _lum(claro["fundo"]) > _lum(claro["texto"])
    # azul-marinho dominante: as escuras partem de fundos azul-marinho/grafite escuros
    for pid in ("marca", "marinho-profundo"):
        d = b.item("paleta", pid)["dados"]
        r, g, bl = (int(d["fundo"][i:i + 2], 16) for i in (1, 3, 5))
        assert bl > r and bl > g and bl < 0x40


def test_cli_validar_exit_codes(tmp_path):
    ok = run_cli("validar")
    assert ok.returncode == 0 and "Traceback" not in ok.stderr
    escreve(tmp_path, "paletas", "quebrada", "{")
    r = run_cli("validar", "--raiz", str(tmp_path))
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert "erro:" in r.stderr and "quebrada" in r.stderr
    r = run_cli("validar", "--raiz", str(tmp_path / "nao-existe"))
    assert r.returncode == 1 and "erro:" in r.stderr
    r = run_cli("banana")
    assert r.returncode == 1 and "Traceback" not in r.stderr and "erro:" in r.stderr
    r = run_cli()
    assert r.returncode == 1 and "Traceback" not in r.stderr


def test_cli_listar_json_valid_and_stable(tmp_path):
    a = run_cli("listar", "--json")
    b = run_cli("listar", "--json")
    assert a.returncode == 0 and a.stdout == b.stdout
    data = json.loads(a.stdout)
    assert data["erros"] == []
    chaves = [(i["tipo"], i["id"]) for i in data["itens"]]
    assert chaves == sorted(chaves, key=lambda k: (["paleta", "legenda", "efeito", "material"].index(k[0]), k[1]))
    assert len(chaves) == 18  # 4 paletas, 4 legendas, 10 efeitos
    assert all(i["pasta"] == f"{ {'paleta': 'paletas', 'legenda': 'legendas', 'efeito': 'efeitos'}[i['tipo']] }/{i['id']}"
               for i in data["itens"])
    texto = run_cli("listar")
    assert texto.returncode == 0 and "faixa-azul" in texto.stdout and "Faixa azul" in texto.stdout


def test_missing_root_is_empty_bank(tmp_path):
    b = banco.carregar(tmp_path / "nada")
    assert b.erros == []
    assert all(b.itens(t) == [] for t in ("paleta", "legenda", "efeito", "material"))


def test_id_is_folder_name_slug(tmp_path):
    escreve(tmp_path, "paletas", "meu-estilo-2", manifesto())
    for nome in ("Maiusculas", "com_underline", "-comeca", "termina-", "dois--hifens",
                 "a" * 41, "com espaco", "açai"):
        try:
            escreve(tmp_path, "paletas", nome, manifesto())
        except OSError:
            pass
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("paleta")] == ["meu-estilo-2"]
    assert len(b.erros) >= 7
    ids = [i["id"] for t in ("paleta", "legenda") for i in banco.carregar(REPO / "banco").itens(t)]
    assert len(ids) == len(set(ids))


def test_unknown_entries_reported(tmp_path):
    (tmp_path / "paletas").mkdir()
    (tmp_path / "paletas" / "solto.txt").write_text("x", encoding="utf-8")
    (tmp_path / "estranha").mkdir()
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    b = banco.carregar(tmp_path)
    assert {Path(e["pasta"]).name for e in b.erros} == {"solto.txt", "estranha"}


# ---- rodada de correcao 1 ----

def _escreve_bruto(raiz, nome, texto, plural="paletas"):
    d = raiz / plural / nome
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifesto.json").write_text(texto, encoding="utf-8")
    return d


def test_deeply_nested_json_is_invalid_item_not_crash(tmp_path):
    escreve(tmp_path, "paletas", "boa", manifesto())
    fundo = "[" * 30000 + "]" * 30000
    _escreve_bruto(tmp_path, "aninhada", '{"nome":"a","descricao":"b","tipo":"paleta","campos":'
                   + fundo + ',"dados":{}}')
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("paleta")] == ["boa"]
    assert "aninhad" in motivos(b)["aninhada"].lower() or "JSON" in motivos(b)["aninhada"]
    r = run_cli("validar", "--raiz", str(tmp_path))
    assert r.returncode == 1 and "Traceback" not in r.stderr and "erro:" in r.stderr
    r = run_cli("listar", "--json", "--raiz", str(tmp_path))
    assert r.returncode == 0 and json.loads(r.stdout)["erros"]


def test_huge_integers_are_invalid_not_crash(tmp_path):
    escreve(tmp_path, "paletas", "boa", manifesto())
    gigante = "9" * 4000
    base = ('{"nome":"a","descricao":"b","tipo":"paleta","campos":%s,"dados":'
            '{"fundo":"#001931","texto":"#ddebf5","destaque":"#a8c8f0","apoio":"#566a7a"}%s}')
    _escreve_bruto(tmp_path, "max-gigante", base % (
        '[{"id":"a","rotulo":"A","tipo":"numero","max":%s}]' % gigante, ""))
    _escreve_bruto(tmp_path, "min-gigante", base % (
        '[{"id":"a","rotulo":"A","tipo":"numero","min":-%s}]' % gigante, ""))
    _escreve_bruto(tmp_path, "duracao-gigante", base % (
        "[]", ',"duracao":{"padrao":%s,"min":1,"max":%s}' % (gigante, gigante)))
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("paleta")] == ["boa"]
    assert set(motivos(b)) == {"max-gigante", "min-gigante", "duracao-gigante"}
    assert run_cli("validar", "--raiz", str(tmp_path)).stderr.count("Traceback") == 0


def test_duplicate_json_keys_invalid(tmp_path):
    _escreve_bruto(tmp_path, "dup", '{"nome":"a","nome":"b","descricao":"d","tipo":"paleta",'
                   '"campos":[],"dados":{"fundo":"#001931","texto":"#ddebf5",'
                   '"destaque":"#a8c8f0","apoio":"#566a7a"}}')
    b = banco.carregar(tmp_path)
    assert b.itens("paleta") == []
    assert "repetid" in motivos(b)["dup"] and "nome" in motivos(b)["dup"]


@pytest.mark.parametrize("ch", ["‮", "​", " ", " ", "﻿", "‍"])
def test_invisible_unicode_rejected(tmp_path, ch):
    escreve(tmp_path, "paletas", "nome", manifesto(nome=f"ab{ch}cd"))
    escreve(tmp_path, "paletas", "desc", manifesto(descricao=f"ab{ch}cd"))
    escreve(tmp_path, "paletas", "rotulo", manifesto(campos=[
        {"id": "a", "rotulo": f"x{ch}y", "tipo": "texto"}]))
    escreve(tmp_path, "paletas", "opcao", manifesto(campos=[
        {"id": "a", "rotulo": "A", "tipo": "escolha", "opcoes": [f"x{ch}y"]}]))
    b = banco.carregar(tmp_path)
    assert b.itens("paleta") == [] and len(b.erros) == 4


def test_accented_portuguese_text_still_ok(tmp_path):
    escreve(tmp_path, "paletas", "ok", manifesto(nome="Pílula à esquerda", descricao="Ação, coração."))
    assert len(banco.carregar(tmp_path).itens("paleta")) == 1


def test_ceilings(tmp_path):
    def num(**kw):
        return manifesto(campos=[{"id": "a", "rotulo": "A", "tipo": "numero", **kw}])
    ef = {"nome": "E", "descricao": "E.", "tipo": "efeito", "campos": [], "dados": {"area_segura": True}}
    casos = {
        "dur-max-601": {**ef, "duracao": {"padrao": 3, "min": 1, "max": 601}},
        "campo-max-grande": num(max=1000001),
        "campo-min-grande": num(min=1000001),
        "opcao-longa": manifesto(campos=[{"id": "a", "rotulo": "A", "tipo": "escolha",
                                          "opcoes": ["x" * 61]}]),
    }
    for nome, m in casos.items():
        d = escreve(tmp_path, "efeitos" if nome.startswith("dur") else "paletas", nome, m)
        (d / "efeito.html").write_text("x", encoding="utf-8")
    ok = escreve(tmp_path, "efeitos", "dur-30", {**ef, "duracao": {"padrao": 3, "min": 1, "max": 30}})
    (ok / "efeito.html").write_text("x", encoding="utf-8")
    escreve(tmp_path, "paletas", "campo-ok", num(min=0, max=1000000))
    escreve(tmp_path, "paletas", "opcao-60", manifesto(campos=[
        {"id": "a", "rotulo": "A", "tipo": "escolha", "opcoes": ["x" * 60]}]))
    b = banco.carregar(tmp_path)
    assert {i["id"] for i in b.itens("efeito")} == {"dur-30"}  # efeito: teto de 30 s
    assert {i["id"] for i in b.itens("paleta")} == {"campo-ok", "opcao-60"}
    assert set(motivos(b)) == set(casos)


def test_efeito_html_size_and_special_files(tmp_path):
    ef = {"nome": "E", "descricao": "E.", "tipo": "efeito", "campos": [], "dados": {"area_segura": True},
          "duracao": {"padrao": 3, "min": 1, "max": 6}}
    d = escreve(tmp_path, "efeitos", "grande", ef)
    (d / "efeito.html").write_bytes(b"x" * (1024 * 1024 + 1))
    d = escreve(tmp_path, "efeitos", "um-mib", ef)
    (d / "efeito.html").write_bytes(b"x" * (1024 * 1024))
    d = escreve(tmp_path, "efeitos", "fifo", ef)
    os.mkfifo(d / "efeito.html")
    d = escreve(tmp_path, "efeitos", "pasta", ef)
    (d / "efeito.html").mkdir()
    b = banco.carregar(tmp_path)
    assert [i["id"] for i in b.itens("efeito")] == ["um-mib"]
    m = motivos(b)
    assert "grande demais" in m["grande"]
    assert "arquivo comum" in m["fifo"] and "arquivo comum" in m["pasta"]


def test_validar_missing_root_is_error(tmp_path):
    r = run_cli("validar", "--raiz", str(tmp_path / "nao-existe"))
    assert r.returncode == 1 and r.stderr.startswith("erro:") and "Traceback" not in r.stderr


def test_faixa_azul_matches_captions_defaults():
    import captions
    brand = json.loads((REPO / "brand" / "brand.json").read_text(encoding="utf-8"))
    ass = captions.to_ass([], brand)
    # Faixa azul = estilo atual: fonte 64, caixa (BorderStyle 3), outline 14, base-centro, margem 340
    assert "Style: Legenda,Poppins,64," in ass
    assert ",3,14,0,2,72,72,340,1" in ass
    d = banco.carregar(REPO / "banco").item("legenda", "faixa-azul")["dados"]
    assert d == {"estilo": "faixa", "posicao_padrao": "baixo", "tamanho_padrao": "M"}


def test_readme_documents_dot_folders_and_empty_campos():
    t = (REPO / "banco" / "README.md").read_text(encoding="utf-8")
    assert "ponto" in t and "[]" in t
