import os
import sys

# Isoler la base SQLite des tests AVANT d'importer app.main (qui crée le schéma à l'import).
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_app.db")
# Aucun accès réseau pendant les tests : Reddit désactivé même si backend/.env l'active
# (load_dotenv n'écrase pas une variable déjà définie). test_reddit.py le réactive au cas par cas.
os.environ["REDDIT_ENABLED"] = "false"
# Jamais d'envoi de mail réel : config SMTP vide (prioritaire sur backend/.env), envoi auto coupé.
# test_mailer.py fournit sa propre config et un faux smtplib.SMTP.
for _name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM", "MAIL_TO"):
    os.environ[_name] = ""
os.environ["MAIL_AUTO_SEND"] = "false"

# Permettre "from app.main import ..." comme en exécution (uvicorn app.main:app lancé depuis backend/).
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
