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


# --------------------------------------------------------------------------
# Transcricao falsa para os testes de tela (no lugar do Whisper).
#
# O servidor so a usa com make_server(..., test_mode=True) E a variavel
# REEL_APP_FAKE_TRANSCRIBE=1 (ver server.transcricao_falsa); fora disso a tarefa
# "transcrever" roda o scripts/transcribe.py de verdade.
# Uso pelo servidor: python3 -I tests/fixtures_app.py transcrever <video> <saida.json>
# REEL_APP_FAKE_TRANSCRIBE_ESPERA=<segundos> deixa a tarefa lenta (cancelar/recarregar).

# fala de ~5,6 s para um video de 6 s: uma muleta ("né"), uma pausa longa
# (2,95-4,00) e uma palavra repetida ("a a") -> cut.py detect acha 3 cortes
FALA = [
    ("O", 0.40, 0.60), ("prazo", 0.60, 1.00), ("para", 1.00, 1.20), ("recorrer", 1.20, 1.65),
    ("né", 1.70, 1.95), ("conta", 2.00, 2.30), ("dias", 2.30, 2.55), ("úteis.", 2.55, 2.95),
    ("Leia", 4.00, 4.30), ("a", 4.30, 4.40), ("a", 4.40, 4.50), ("intimação", 4.50, 5.00),
    ("com", 5.00, 5.20), ("calma.", 5.20, 5.60),
]


def _duracao(video):
    import subprocess
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", str(video)],
                             capture_output=True, text=True, timeout=30).stdout
        return float(out.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 6.0


def fake_transcribe_script(video, saida, espera=0.0):
    """Grava em `saida` uma transcricao fixa (FALA) com a duracao real de `video`;
    com `espera` > 0 imprime progresso por esse tempo antes de gravar."""
    import os
    import time
    from pathlib import Path
    passos = max(1, int(espera / 0.2)) if espera > 0 else 1
    for i in range(passos):
        print(f"ouvindo o vídeo… {int(100 * i / passos)}%", flush=True)
        if espera > 0:
            time.sleep(espera / passos)
    dur = _duracao(video)
    words = [{"w": w, "start": s, "end": e} for w, s, e in FALA if e <= dur]
    saida = Path(saida)
    tmp = saida.with_name(f".{saida.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"duration": dur, "words": words}, ensure_ascii=False), "utf-8")
    os.replace(tmp, saida)
    print(f"{len(words)} palavras, {dur:.2f}s", flush=True)


if __name__ == "__main__":
    import os
    import sys
    if len(sys.argv) != 4 or sys.argv[1] != "transcrever":
        print("erro: uso: fixtures_app.py transcrever <video> <saida.json>", file=sys.stderr)
        sys.exit(1)
    fake_transcribe_script(sys.argv[2], sys.argv[3],
                           float(os.environ.get("REEL_APP_FAKE_TRANSCRIBE_ESPERA") or 0))
