import json
import os

import pytest

from conftest_app import repo_root  # noqa: F401  (poe app/ no sys.path)
from projects import Projects, ProjectsError, slugify


@pytest.fixture
def projs(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    return Projects(root)


def test_slugify_accents_and_symbols():
    assert slugify("Isenção de IR — 3 mitos!") == "isencao-de-ir-3-mitos"


def test_slugify_empty_raises():
    for bad in ("", "   ", "!!! ---", "—"):
        with pytest.raises(ProjectsError, match="nome inválido: use letras ou números"):
            slugify(bad)


def test_slugify_limits_and_trim():
    s = slugify("a" * 39 + " bbb")
    assert len(s) <= 40 and not s.endswith("-") and "--" not in s
    assert slugify("--Olá,   Mundo--") == "ola-mundo"


def test_create_stores_name_and_returns_dict(projs):
    p = projs.create("Isenção de IR")
    assert p["slug"] == "isencao-de-ir" and p["nome"] == "Isenção de IR" and p["criado"]
    meta = json.loads((projs.root / "isencao-de-ir" / "projeto.json").read_text("utf-8"))
    assert meta == {"nome": "Isenção de IR", "criado": p["criado"]}


def test_create_duplicate_gets_suffix(projs):
    assert projs.create("Meu vídeo")["slug"] == "meu-video"
    assert projs.create("Meu video")["slug"] == "meu-video-2"
    assert projs.create("meu vídeo")["slug"] == "meu-video-3"
    long = "x" * 40
    assert projs.create(long)["slug"] == long
    s2 = projs.create(long)["slug"]
    assert s2.endswith("-2") and len(s2) <= 40


def test_list_most_recent_first(projs):
    a = projs.create("Um")
    b = projs.create("Dois")
    meta = projs.root / a["slug"] / "projeto.json"
    meta.write_text(json.dumps({"nome": "Um", "criado": "2020-01-01T00:00:00"}), "utf-8")
    lst = projs.list()
    assert [p["slug"] for p in lst] == [b["slug"], a["slug"]]
    assert set(lst[0]) == {"slug", "nome", "criado"}
    (projs.root / "sem-meta").mkdir()  # pasta sem projeto.json: usa o slug como nome
    assert "sem-meta" in [p["slug"] for p in projs.list()]


def test_path_rejects_bad_slug(projs):
    projs.create("ok")
    assert projs.path("ok") == projs.root / "ok"
    for bad in ("../x", "A_b", "a" * 41, "a\\b", "", "-a", "a-", "a--b", "a/b", "a\x00b"):
        with pytest.raises(ProjectsError):
            projs.path(bad)
    with pytest.raises(ProjectsError, match="não existe"):
        projs.path("inexistente")


def _touch(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_resolve_file_allowlist(projs):
    d = projs.root / projs.create("p")["slug"]
    _touch(d / "entrada.mp4")
    _touch(d / "saida" / "preview.mp4")
    _touch(d / "capa" / "capa.png")
    _touch(d / "materiais" / "a.png")
    _touch(d / "quadros" / "q1.jpg")
    _touch(d / "transcricao.json")
    _touch(d / "projeto.json")
    _touch(d / "saida" / ".tarefa-x.json")
    for rel in ("entrada.mp4", "saida/preview.mp4", "capa/capa.png", "materiais/a.png", "quadros/q1.jpg"):
        assert projs.resolve_file("p", rel) == (d / rel).resolve()
    for rel in ("transcricao.json", "projeto.json", "saida/.tarefa-x.json", "saida", "outro/x.png",
                "entrada.mp4/x", "entradas.mp4", "/etc/passwd", "saida\\preview.mp4", "saida/a\x00",
                "saida/a/b/c/d", "", "saida/nao-existe.mp4"):
        with pytest.raises(ProjectsError):
            projs.resolve_file("p", rel)


def test_resolve_file_rejects_traversal_and_symlink_out(projs, tmp_path):
    d = projs.root / projs.create("p")["slug"]
    _touch(d / "saida" / "preview.mp4")
    outside = _touch(tmp_path / "segredo.txt")
    (d / "capa").mkdir()
    (d / "capa" / "fora.png").symlink_to(outside)
    (d / "capa" / "dentro.png").symlink_to(d / "saida" / "preview.mp4")
    os.symlink(tmp_path, d / "materiais")  # pasta inteira apontando para fora
    for rel in ("saida/../transcricao.json", "../p2/entrada.mp4", "capa/../../x", "capa/fora.png",
                "materiais/segredo.txt", "capa/.."):
        with pytest.raises(ProjectsError):
            projs.resolve_file("p", rel)
    assert projs.resolve_file("p", "capa/dentro.png") == (d / "saida" / "preview.mp4").resolve()


def test_state_steps_follow_files(projs):
    d = projs.root / projs.create("Meu Reel")["slug"]
    st = projs.state("meu-reel")
    assert st["slug"] == "meu-reel" and st["nome"] == "Meu Reel" and st["duracao"] is None
    assert list(st["etapas"]) == ["video", "transcricao", "cortes", "legendas", "estilo",
                                  "preview", "graficos", "capa", "final"]
    assert set(st["etapas"].values()) == {"pendente"}

    _touch(d / "entrada.mov")
    _touch(d / "transcricao.json", json.dumps({"duration": 12.5}).encode())
    _touch(d / "cortes.json", b"{}")
    _touch(d / "estilo.json", b"{}")
    _touch(d / "graficos.json", b"{}")
    _touch(d / "capa" / "capa.png")
    st = projs.state("meu-reel")
    assert st["duracao"] == 12.5
    pronto = {k for k, v in st["etapas"].items() if v == "pronto"}
    assert pronto == {"video", "transcricao", "cortes", "estilo", "graficos", "capa"}
    assert st["arquivos"]["entrada"] == "entrada.mov"

    _touch(d / "etapas.json", json.dumps({"legendas": True}).encode())
    assert projs.state("meu-reel")["etapas"]["legendas"] == "pronto"
    (d / "etapas.json").write_text(json.dumps({"legendas": False}))
    assert projs.state("meu-reel")["etapas"]["legendas"] == "pendente"
    _touch(d / "legendas.json", b"{}")
    assert projs.state("meu-reel")["etapas"]["legendas"] == "pronto"

    _touch(d / "saida" / "preview.mp4")
    _touch(d / "saida" / "final.mp4")
    st = projs.state("meu-reel")
    assert st["etapas"]["preview"] == st["etapas"]["final"] == "pronto"
    assert st["arquivos"]["final"] == "saida/final.mp4"


def test_state_tolerates_corrupt_json(projs):
    d = projs.root / projs.create("x")["slug"]
    _touch(d / "transcricao.json", b"{nao e json")
    _touch(d / "etapas.json", b"[1]")
    st = projs.state("x")
    assert st["duracao"] is None and st["etapas"]["transcricao"] == "pronto"


def test_resolve_file_long_names_and_broken_links(projs):
    d = projs.root / projs.create("p")["slug"]
    for rel in ("saida/" + "x" * 300, "capa/" + "x" * 256, "materiais/" + "é" * 200,
                "quadros/" + "x" * 5000, "entrada." + "x" * 300):
        with pytest.raises(ProjectsError):
            projs.resolve_file("p", rel)
    (d / "saida").mkdir()
    (d / "saida" / "a.mp4").symlink_to(d / "saida" / "b.mp4")
    (d / "saida" / "b.mp4").symlink_to(d / "saida" / "a.mp4")  # laco
    (d / "saida" / "solto.mp4").symlink_to(d / "saida" / "nao-existe.mp4")  # pendurado
    for rel in ("saida/a.mp4", "saida/solto.mp4"):
        with pytest.raises(ProjectsError):
            projs.resolve_file("p", rel)


@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-Infinity", "1e999", "-5", '"12"', "true", "null"])
def test_state_duracao_only_finite_nonnegative(projs, valor):
    d = projs.root / projs.create("p")["slug"]
    (d / "transcricao.json").write_text('{"duration": %s}' % valor, encoding="utf-8")
    assert projs.state("p")["duracao"] is None


def test_symlinked_project_folder_rejected(projs, tmp_path):
    fora = tmp_path / "fora"
    (fora / "saida").mkdir(parents=True)
    (fora / "saida" / "x.mp4").write_bytes(b"x")
    (projs.root / "lnk").symlink_to(fora, target_is_directory=True)
    projs.create("ok")
    with pytest.raises(ProjectsError, match="projeto inválido"):
        projs.path("lnk")
    with pytest.raises(ProjectsError):
        projs.resolve_file("lnk", "saida/x.mp4")
    with pytest.raises(ProjectsError):
        projs.state("lnk")
    assert [p["slug"] for p in projs.list()] == ["ok"]
