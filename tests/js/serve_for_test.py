"""Sobe o servidor real do app em porta efemera para os testes de tela (tests/js/).

Uso: python3 -I tests/js/serve_for_test.py <config.json>

config: {"root": dir dos projetos, "brand": caminho de um brand.json de teste,
         "max_upload": bytes, "doctor": {"estado": "...", "itens": [itens crus do doctor]},
         "test_mode": bool (padrao false; liga os dublês de teste do servidor, como a
         transcricao falsa de REEL_APP_FAKE_TRANSCRIBE=1 e o "Abrir pasta" que so registra)}
Imprime UMA linha JSON {"base", "url", "token", "port"} e serve ate receber SIGTERM
ou fechar o stdin. O doctor e substituido pelo resultado fixo do config (o real
depende da maquina); a marca aponta para um arquivo de teste, nunca para brand/brand.json.
"""
from __future__ import annotations

import json
import secrets
import signal
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "app"))

import server  # noqa: E402


def main() -> None:
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    doctor = cfg.get("doctor")
    if doctor is not None:
        server._doctor_check = lambda: (doctor["estado"], doctor["itens"])
    token = secrets.token_urlsafe(24)
    srv = server.make_server(Path(cfg["root"]), token,
                             max_upload=int(cfg.get("max_upload", 4 * 1024 ** 3)),
                             test_mode=bool(cfg.get("test_mode", False)))
    if cfg.get("brand"):
        srv.app.brand_path = Path(cfg["brand"])
    porta = srv.server_address[1]
    base = f"http://127.0.0.1:{porta}"
    print(json.dumps({"base": base, "url": f"{base}/?t={token}", "token": token,
                      "port": porta}), flush=True)

    def parar(*_):
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, parar)
    # o processo pai morreu (stdin fechou): encerra tambem
    threading.Thread(target=lambda: (sys.stdin.read(), parar()), daemon=True).start()
    try:
        srv.serve_forever()
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
