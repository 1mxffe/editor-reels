"""Ajuda para os testes do app/: poe `<repo>/app` no sys.path (app/ nao e pacote)."""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "app"))
