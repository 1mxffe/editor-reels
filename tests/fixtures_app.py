"""Projeto sintetico para os testes da API de revisao (mesmos dados de test_review_apply)."""
import json

WORDS = [
    ("O", 0.50, 0.70), ("prazo", 0.70, 1.10), ("para", 1.10, 1.30), ("recorrer", 1.30, 1.70),
    ("conta", 1.70, 1.95), ("dias", 1.95, 2.15), ("úteis.", 2.15, 2.40),
    ("Leia", 3.80, 4.10), ("a", 4.10, 4.20), ("intimação", 4.20, 4.70), ("com", 4.70, 4.90),
    ("calma.", 4.90, 5.30),
]
CUTS = [{"id": "c1", "start": 0.0, "end": 0.45, "kind": "silence"},
        {"id": "c2", "start": 2.6, "end": 3.4, "kind": "silence"}]


def montar_projeto(d, com_transcricao=True):
    """Preenche a pasta `d` (ja criada por Projects.create): entrada falsa (o motor da
    revisao so confirma que existe), transcricao fixa e cortes.json."""
    (d / "entrada.mp4").write_bytes(b"nao e video")
    if com_transcricao:
        (d / "transcricao.json").write_text(json.dumps({"duration": 6.0, "words": [
            {"w": w, "start": s, "end": e} for w, s, e in WORDS]}, ensure_ascii=False), "utf-8")
        (d / "cortes.json").write_text(json.dumps({"cuts": CUTS}), "utf-8")
    return d
