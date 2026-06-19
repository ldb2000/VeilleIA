import os
import sys

# Isoler la base SQLite des tests AVANT d'importer app.main (qui crée le schéma à l'import).
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_app.db")

# Permettre "from app.main import ..." comme en exécution (uvicorn app.main:app lancé depuis backend/).
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
