import os
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from html import escape, unescape
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Response, Security
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy import func, inspect, text
from typing import TYPE_CHECKING, List, Optional, Tuple
from datetime import datetime, timedelta
from io import BytesIO

import httpx
from dotenv import load_dotenv
import markdown
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import models, schemas, database
from .newsletter import render_newsletter
from . import reddit
from . import mailer
from . import m365_roadmap

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials


def import_genai():
    """Charge le SDK Gemini à la demande : inutile (et bruyant) avec Codex ou OpenRouter."""
    import google.generativeai as genai

    return genai
from .database import SessionLocal, engine

load_dotenv()

models.Base.metadata.create_all(bind=engine)


def ensure_reports_schema() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("reports")}
    with engine.begin() as connection:
        if "report_type" not in columns:
            connection.execute(
                text("ALTER TABLE reports ADD COLUMN report_type VARCHAR DEFAULT 'technical_watch'")
            )
            connection.execute(
                text("UPDATE reports SET report_type = 'technical_watch' WHERE report_type IS NULL")
            )
        if "newsletter_sent_at" not in columns:
            connection.execute(text("ALTER TABLE reports ADD COLUMN newsletter_sent_at DATETIME"))


ensure_reports_schema()


def ensure_news_items_schema() -> None:
    inspector = inspect(engine)
    if "news_items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("news_items")}
    with engine.begin() as connection:
        if "source_report_date" not in columns:
            connection.execute(text("ALTER TABLE news_items ADD COLUMN source_report_date VARCHAR"))
            connection.execute(
                text(
                    "UPDATE news_items SET source_report_date = "
                    "(SELECT reports.date FROM reports WHERE reports.id = news_items.report_id)"
                )
            )


ensure_news_items_schema()


def serialize_report_ids(report_ids: Optional[list[int]]) -> Optional[str]:
    if not report_ids:
        return None
    return json.dumps(report_ids)


def deserialize_report_ids(report_ids_raw: Optional[str]) -> Optional[list[int]]:
    if not report_ids_raw:
        return None
    try:
        value = json.loads(report_ids_raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, list) else None


# Types de rapports. Les « veilles » (technical_watch, copilot_watch) partagent le même format de sortie :
# extraction des news, vue structurée, newsletter et PDF fonctionnent sur les deux.
WATCH_REPORT_TYPES = ("technical_watch", "copilot_watch")
REPORT_TYPE_LABELS = {
    "technical_watch": "Analyse de veille",
    "copilot_watch": "Veille Microsoft Copilot",
    "codir_note": "Note CODIR",
}


def report_type_label(report_type: Optional[str]) -> str:
    return REPORT_TYPE_LABELS.get(report_type or "technical_watch", "Analyse de veille")


CHAT_REPORT_CONTEXT_MAX_CHARS = int(os.getenv("CHAT_REPORT_CONTEXT_MAX_CHARS", "24000"))
CHAT_HISTORY_MAX_MESSAGES = 6
CHAT_HISTORY_MESSAGE_MAX_CHARS = 2000


def build_report_chat_context(db: Session, report: models.Report) -> str:
    """Rapport complet + résumé + notes, pour que la recherche voie les nouveautés détaillées."""
    parts = [f"## Rapport {report.id} · {report_type_label(report.report_type)} du {report.date}"]

    summary = db.query(models.ReportSummary).filter(models.ReportSummary.report_id == report.id).first()
    if summary and summary.content.strip():
        parts.append(f"### Résumé exécutif\n{summary.content.strip()}")

    content = (report.content or "").strip()
    if len(content) > CHAT_REPORT_CONTEXT_MAX_CHARS:
        content = content[:CHAT_REPORT_CONTEXT_MAX_CHARS].rstrip() + "\n\n[contenu tronqué]"
    parts.append(f"### Contenu du rapport\n{content}")

    notes = (
        db.query(models.Note)
        .filter(models.Note.report_id == report.id)
        .order_by(models.Note.created_at.asc())
        .all()
    )
    note_lines = []
    for note in notes:
        label = {"detail": "Détail", "definition": "Définition"}.get(note.kind, "Note")
        source = (note.source_text or "").strip()
        body = (note.content or "").strip()
        if source and source != body:
            note_lines.append(f"- {label} sur « {source[:200]} » : {body[:1200]}")
        elif body:
            note_lines.append(f"- {label} : {body[:1200]}")
    if note_lines:
        parts.append("### Notes de l'équipe\n" + "\n".join(note_lines))

    return "\n\n".join(parts)


def build_chat_history_text(history: Optional[list]) -> str:
    if not history:
        return ""
    lines = []
    for message in history[-CHAT_HISTORY_MAX_MESSAGES:]:
        role = "Utilisateur" if message.role == "user" else "Assistant"
        content = (message.content or "").strip()
        if len(content) > CHAT_HISTORY_MESSAGE_MAX_CHARS:
            content = content[:CHAT_HISTORY_MESSAGE_MAX_CHARS].rstrip() + " […]"
        if content:
            lines.append(f"{role} : {content}")
    return "\n\n".join(lines)


def build_chat_prompt(question: str, context_text: str, history_text: str, web_search: bool) -> str:
    if web_search:
        web_rules = """- tu peux et dois utiliser la recherche web pour compléter ou mettre à jour les rapports
- structure la réponse en deux parties : « D'après les rapports » puis « Sur le web », et ne mélange pas les deux
- chaque information issue du web doit avoir sa source en lien markdown [titre](url) avec sa date de publication
- privilégie les sources officielles (changelogs, documentation, avis de sécurité, blogs engineering)"""
    else:
        web_rules = """- tu n'as pas accès à internet : ne prétends pas avoir fait une recherche web
- tu peux ajouter du contexte général utile, mais en le signalant explicitement comme « contexte général », distinct des rapports"""

    history_block = (
        f"\nÉchanges précédents de la conversation (pour comprendre les questions de suivi) :\n\n{history_text}\n"
        if history_text
        else ""
    )

    return f"""Tu es l'assistant de veille IA de l'équipe STTI d'APRIL (architecture, plateforme, sécurité, développement). Tu réponds à partir des rapports de veille fournis.
Date du jour : {datetime.now().strftime("%Y-%m-%d")}

Règles :
- priorise les informations présentes dans les rapports fournis
- cite l'origine de chaque information issue des rapports sous la forme (Rapport <id> · <section>), par exemple (Rapport 12 · Nouveautés détaillées)
{web_rules}
- si l'information n'est pas présente, dis-le clairement
- si plusieurs rapports se contredisent ou si le contexte est insuffisant, signale-le
- réponse dense et concrète ; commence par la réponse directe en 2 à 4 lignes, puis les détails en listes courtes si utile
- relie à la stack APRIL (Dagster, Snowflake, Azure, M365) ou à un cas assurance uniquement quand c'est pertinent
- réponds en français, sans blocs de code
{history_block}
Question :
{question}

Rapports de contexte :

{context_text}
"""


DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
DEFAULT_GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "90"))
REPORT_GEMINI_TIMEOUT_SECONDS = float(
    os.getenv("GEMINI_REPORT_TIMEOUT_SECONDS", str(max(DEFAULT_GEMINI_TIMEOUT_SECONDS, 300)))
)
GEMINI_EXECUTOR = ThreadPoolExecutor(max_workers=4)
CLI_MODEL_ALIASES = {
    "gemini-2.0-flash-lite": "auto-gemini-3",
    "gemini-1.5-flash": "auto-gemini-3",
    "gemini-2.0-flash": "auto-gemini-3",
}
MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>.*?)\]\((?P<url>https?://[^\s)]+)\)")
MARKDOWN_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>https?://[^\s)]+)\)")
MARKDOWN_BOLD_RE = re.compile(r"\*\*(?P<text>.+?)\*\*")


def extract_gemini_cli_oauth_client_config() -> Tuple[Optional[str], Optional[str]]:
    gemini_path = shutil.which("gemini")
    if not gemini_path:
        return None, None

    try:
        resolved = Path(gemini_path).resolve()
        candidates = [
            resolved.parent / "node_modules" / "@google" / "gemini-cli-core" / "dist" / "src" / "code_assist" / "oauth2.js",
            resolved.parent.parent / "node_modules" / "@google" / "gemini-cli-core" / "dist" / "src" / "code_assist" / "oauth2.js",
            resolved.parent.parent / "node_modules" / "@google" / "gemini-cli" / "node_modules" / "@google" / "gemini-cli-core" / "dist" / "src" / "code_assist" / "oauth2.js",
        ]
        oauth2_path = next((path for path in candidates if path.exists()), None)
        if oauth2_path is None:
            matches = list(resolved.parent.parent.rglob("oauth2.js"))
            oauth2_path = next((path for path in matches if "code_assist" in str(path)), None)
        if oauth2_path is None:
            return None, None

        content = oauth2_path.read_text()
        client_id_match = re.search(r"(\d+-[a-z0-9]+\.apps\.googleusercontent\.com)", content)
        client_secret_match = re.search(r"(GOCSPX-[A-Za-z0-9_-]+)", content)
        client_id = client_id_match.group(1) if client_id_match else None
        client_secret = client_secret_match.group(1) if client_secret_match else None
        return client_id, client_secret
    except Exception:
        return None, None


def load_oauth_credentials(creds_path: Path) -> "tuple[Credentials, dict]":
    from google.oauth2.credentials import Credentials

    with creds_path.open("r") as f:
        data = json.load(f)

    extracted_client_id, extracted_client_secret = extract_gemini_cli_oauth_client_config()
    client_id = (
        data.get("client_id")
        or os.getenv("GEMINI_OAUTH_CLIENT_ID")
        or extracted_client_id
    )
    client_secret = (
        data.get("client_secret")
        or os.getenv("GEMINI_OAUTH_CLIENT_SECRET")
        or extracted_client_secret
    )
    scopes = data.get("scopes") or data.get("scope")
    if isinstance(scopes, str):
        scopes = scopes.split()

    creds = Credentials(
        token=data.get("access_token") or data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        id_token=data.get("id_token"),
    )

    expiry_date = data.get("expiry_date")
    if expiry_date:
        creds.expiry = datetime.utcfromtimestamp(expiry_date / 1000)

    data["client_id"] = client_id
    data["client_secret"] = client_secret
    return creds, data


def persist_oauth_credentials(creds_path: Path, source_data: dict, creds: "Credentials") -> None:
    updated = dict(source_data)
    updated["access_token"] = creds.token
    if creds.refresh_token:
        updated["refresh_token"] = creds.refresh_token
    if creds.id_token:
        updated["id_token"] = creds.id_token
    if creds.client_id:
        updated["client_id"] = creds.client_id
    if creds.client_secret:
        updated["client_secret"] = creds.client_secret
    if creds.scopes:
        updated["scope"] = " ".join(creds.scopes)
    if creds.expiry:
        updated["expiry_date"] = int(creds.expiry.timestamp() * 1000)

    creds_path.parent.mkdir(parents=True, exist_ok=True)
    with creds_path.open("w") as f:
        json.dump(updated, f, indent=2)
        f.write("\n")


def load_gemini_auth():
    """
    Configures Gemini Developer API auth.
    Prefers ~/.gemini/oauth_creds.json when present, then falls back to GEMINI_API_KEY.
    """
    creds_path = Path.home() / ".gemini" / "oauth_creds.json"
    api_key = os.getenv("GEMINI_API_KEY")

    if creds_path.exists():
        if should_use_gemini_cli_backend():
            print(f"Using Gemini CLI backend with OAuth credentials from {creds_path}")
            return True
        try:
            creds, raw_creds = load_oauth_credentials(creds_path)

            if creds.refresh_token and creds.client_id and creds.client_secret:
                print("Refreshing Gemini OAuth access token")
                from google.auth.transport.requests import Request

                creds.refresh(Request())
                persist_oauth_credentials(creds_path, raw_creds, creds)
            elif not creds.token:
                raise RuntimeError(
                    "Gemini OAuth credentials are missing an access token. "
                    "Set GEMINI_OAUTH_CLIENT_ID and GEMINI_OAUTH_CLIENT_SECRET "
                    "to enable refresh, or re-authenticate with Gemini."
                )
            else:
                print(
                    "OAuth credentials loaded without backend refresh support. "
                    "Set GEMINI_OAUTH_CLIENT_ID and GEMINI_OAUTH_CLIENT_SECRET "
                    "to enable token refresh."
                )

            print(f"Configuring Gemini with OAuth credentials from {creds_path}")
            original_gemini_api_key = os.environ.pop("GEMINI_API_KEY", None)
            original_google_api_key = os.environ.pop("GOOGLE_API_KEY", None)
            try:
                import_genai().configure(credentials=creds)
            finally:
                if original_gemini_api_key is not None:
                    os.environ["GEMINI_API_KEY"] = original_gemini_api_key
                if original_google_api_key is not None:
                    os.environ["GOOGLE_API_KEY"] = original_google_api_key
            return True
        except Exception as e:
            print(f"Failed to load OAuth credentials: {e}")
            raise

    if api_key:
        print("Configuring Gemini with GEMINI_API_KEY")
        import_genai().configure(api_key=api_key)
        return True

    raise RuntimeError(
        "No Gemini authentication configured. Provide ~/.gemini/oauth_creds.json "
        "or set GEMINI_API_KEY."
    )


def get_auth_debug_info() -> dict:
    creds_path = Path.home() / ".gemini" / "oauth_creds.json"
    gemini_cli_path = shutil.which("gemini")
    info = {
        "llm_provider": os.getenv("LLM_PROVIDER", "codex"),
        "codex_path": shutil.which(CODEX_BIN),
        "has_openrouter_api_key": bool(os.getenv("OPENROUTER_API_KEY")),
        "has_oauth_file": creds_path.exists(),
        "oauth_path": str(creds_path),
        "has_gemini_api_key": bool(os.getenv("GEMINI_API_KEY")),
        "has_google_api_key": bool(os.getenv("GOOGLE_API_KEY")),
        "gemini_cli_path": gemini_cli_path,
        "use_cli_backend": bool(creds_path.exists() and gemini_cli_path),
        "model": DEFAULT_GEMINI_MODEL,
        "cli_model": resolve_cli_model_name(),
        "timeout_seconds": DEFAULT_GEMINI_TIMEOUT_SECONDS,
    }

    if creds_path.exists():
        creds, _ = load_oauth_credentials(creds_path)
        info.update(
            {
                "oauth_has_token": bool(creds.token),
                "oauth_has_refresh_token": bool(creds.refresh_token),
                "oauth_has_client_id": bool(creds.client_id),
                "oauth_has_client_secret": bool(creds.client_secret),
                "oauth_scopes": creds.scopes,
                "oauth_expiry": creds.expiry.isoformat() if creds.expiry else None,
                "oauth_valid": creds.valid,
                "oauth_expired": creds.expired,
            }
        )

    return info


def should_use_gemini_cli_backend() -> bool:
    return bool((Path.home() / ".gemini" / "oauth_creds.json").exists() and shutil.which("gemini"))


def resolve_cli_model_name() -> str:
    return os.getenv(
        "GEMINI_CLI_MODEL",
        CLI_MODEL_ALIASES.get(DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_MODEL),
    )


def generate_gemini_content_with_sdk(prompt: str, timeout_seconds: float = DEFAULT_GEMINI_TIMEOUT_SECONDS):
    model = import_genai().GenerativeModel(DEFAULT_GEMINI_MODEL)
    future = GEMINI_EXECUTOR.submit(
        model.generate_content,
        prompt,
        request_options={"timeout": timeout_seconds},
    )
    try:
        return future.result(timeout=timeout_seconds)
    except FuturesTimeoutError as e:
        future.cancel()
        raise TimeoutError(
            f"Gemini call exceeded application timeout of {timeout_seconds}s"
        ) from e


def generate_gemini_content_with_cli(
    prompt: str,
    timeout_seconds: float = DEFAULT_GEMINI_TIMEOUT_SECONDS,
) -> str:
    cli_model = resolve_cli_model_name()
    cmd = [
        "gemini",
        "--model",
        cli_model,
        "--prompt",
        prompt,
        "--output-format",
        "json",
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise TimeoutError(
            f"gemini CLI exceeded timeout of {timeout_seconds}s"
        ) from e
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if completed.returncode != 0:
        raise RuntimeError(
            f"gemini CLI failed with exit code {completed.returncode}: {stderr or stdout or 'no output'}"
        )
    if not stdout:
        raise RuntimeError(f"gemini CLI returned no output. stderr={stderr or '<empty>'}")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"gemini CLI returned non-JSON output: {stdout[:500]}") from e

    if payload.get("error"):
        raise RuntimeError(f"gemini CLI error: {payload['error']}")

    response = payload.get("response")
    if not isinstance(response, str) or not response.strip():
        raise RuntimeError(f"gemini CLI JSON missing 'response': {stdout[:500]}")

    return response


def generate_gemini_content(prompt: str, timeout_seconds: float = DEFAULT_GEMINI_TIMEOUT_SECONDS):
    if should_use_gemini_cli_backend():
        return generate_gemini_content_with_cli(prompt, timeout_seconds=timeout_seconds)
    return generate_gemini_content_with_sdk(prompt, timeout_seconds=timeout_seconds)


# ---------------------------------------------------------------------------
# Fournisseurs LLM : codex (défaut), openrouter, gemini.
# ---------------------------------------------------------------------------

SUPPORTED_LLM_PROVIDERS = ("codex", "openrouter", "gemini")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", str(DEFAULT_GEMINI_TIMEOUT_SECONDS)))
LLM_REPORT_TIMEOUT_SECONDS = float(
    os.getenv("LLM_REPORT_TIMEOUT_SECONDS", str(max(REPORT_GEMINI_TIMEOUT_SECONDS, 600)))
)
CODEX_BIN = os.getenv("CODEX_BIN", "codex")
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "oui"}


def get_llm_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "codex").strip().lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise RuntimeError(
            f"LLM_PROVIDER={provider!r} inconnu. Valeurs possibles : {', '.join(SUPPORTED_LLM_PROVIDERS)}."
        )
    return provider


def describe_llm_backend() -> str:
    provider = get_llm_provider()
    if provider == "codex":
        return f"codex model={os.getenv('CODEX_MODEL') or '<défaut codex>'}"
    if provider == "openrouter":
        return f"openrouter model={os.getenv('OPENROUTER_MODEL', 'openrouter/auto')}"
    backend_kind = "cli" if should_use_gemini_cli_backend() else "sdk"
    model = resolve_cli_model_name() if backend_kind == "cli" else DEFAULT_GEMINI_MODEL
    return f"gemini backend={backend_kind} model={model}"


def llm_supports_web_search() -> bool:
    provider = get_llm_provider()
    if provider == "codex":
        return env_flag("CODEX_WEB_SEARCH", True)
    if provider == "openrouter":
        return env_flag("OPENROUTER_WEB_SEARCH", False)
    # La CLI Gemini embarque la recherche Google ; le SDK non.
    return should_use_gemini_cli_backend()


def ensure_llm_ready() -> None:
    """Vérifie la configuration du fournisseur actif avant un appel."""
    provider = get_llm_provider()
    if provider == "codex":
        if not shutil.which(CODEX_BIN):
            raise RuntimeError(
                f"Binaire Codex introuvable ({CODEX_BIN}). Installez-le avec `npm install -g @openai/codex` "
                "puis connectez-vous avec `codex login`, ou définissez CODEX_BIN."
            )
        return
    if provider == "openrouter":
        if not os.getenv("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY manquant dans backend/.env.")
        return
    load_gemini_auth()


def build_codex_command(output_path: str, web_search: bool) -> list[str]:
    cmd = [
        CODEX_BIN,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-last-message",
        output_path,
        "-c",
        f'web_search="{"live" if web_search else "disabled"}"',
    ]
    model = os.getenv("CODEX_MODEL")
    if model:
        cmd += ["--model", model]
    reasoning_effort = os.getenv("CODEX_REASONING_EFFORT")
    if reasoning_effort:
        cmd += ["-c", f'model_reasoning_effort="{reasoning_effort}"']
    # Le prompt passe par stdin : les rapports dépassent la taille maximale d'un argument.
    cmd.append("-")
    return cmd


def generate_codex_content(prompt: str, timeout_seconds: float, web_search: bool = False) -> str:
    with tempfile.TemporaryDirectory(prefix="veille-codex-") as workdir:
        output_path = os.path.join(workdir, "last_message.md")
        cmd = build_codex_command(output_path, web_search)
        try:
            completed = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                cwd=workdir,
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"codex exec a dépassé le délai de {timeout_seconds}s") from e

        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            raise RuntimeError(
                f"codex exec a échoué (code {completed.returncode}) : {(stderr or completed.stdout or '')[-1500:]}"
            )
        try:
            content = Path(output_path).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            content = ""
        if not content:
            raise RuntimeError(f"codex exec n'a renvoyé aucune réponse. stderr={stderr[-1000:] or '<vide>'}")
        return content


def generate_openrouter_content(prompt: str, timeout_seconds: float, web_search: bool = False) -> str:
    payload: dict = {
        "model": os.getenv("OPENROUTER_MODEL", "openrouter/auto"),
        "messages": [{"role": "user", "content": prompt}],
    }
    if web_search and env_flag("OPENROUTER_WEB_SEARCH", False):
        # Plugin web d'OpenRouter (facturé en plus) : sans lui, pas de recherche internet.
        payload["plugins"] = [{"id": "web"}]
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
        "Content-Type": "application/json",
        "X-Title": "Veille IA",
    }
    response = httpx.post(OPENROUTER_API_URL, json=payload, headers=headers, timeout=timeout_seconds)
    if response.status_code >= 400:
        raise RuntimeError(f"OpenRouter a répondu {response.status_code} : {response.text[:1000]}")
    data = response.json()
    if data.get("error"):
        raise RuntimeError(f"Erreur OpenRouter : {data['error']}")
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Réponse OpenRouter inattendue : {str(data)[:1000]}") from e
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenRouter a renvoyé une réponse vide.")
    return content


def generate_llm_content(
    prompt: str,
    timeout_seconds: float = LLM_TIMEOUT_SECONDS,
    web_search: bool = False,
) -> str:
    """Point d'entrée unique vers le fournisseur LLM configuré (LLM_PROVIDER)."""
    provider = get_llm_provider()
    if provider == "codex":
        return generate_codex_content(prompt, timeout_seconds, web_search=web_search)
    if provider == "openrouter":
        return generate_openrouter_content(prompt, timeout_seconds, web_search=web_search)
    response = generate_gemini_content(prompt, timeout_seconds=timeout_seconds)
    return response if isinstance(response, str) else response.text

app = FastAPI(title="AI Watch API")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


API_TOKEN = os.getenv("API_TOKEN")
security = HTTPBearer(auto_error=False)


def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)):
    if not API_TOKEN:
        return
    if not credentials or credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing token")


TECHNICAL_PROMPT = """Tu produis une veille technique IA quotidienne couvrant les nouveautés publiées dans les dernières 24h (la date du jour et la période exacte sont indiquées en tête de ce message).

# Méthode de recherche (obligatoire)
- Utilise l’outil de recherche web : fais plusieurs recherches ciblées (une par famille du périmètre ci-dessous), ne réponds jamais de mémoire.
- Pour chaque nouveauté retenue, ouvre la source primaire (changelog, release GitHub, documentation, billet officiel) et vérifie sa date de publication.
- Ne retiens que ce qui a été publié dans la période indiquée. Une annonce plus ancienne n’entre que si un fait nouveau est paru dans la période (nouvelle version, disponibilité générale, faille…).
- Si tu ne trouves pas de source vérifiable pour un élément, écarte-le.
- Journée calme : si peu de choses importantes sont sorties, dis-le dans le TL;DR et produis un rapport court. Ne remplis jamais avec des éléments faibles ou anciens.

# Périmètre de recherche

## Labs / model providers
OpenAI, Anthropic, Google, Meta, Mistral, Microsoft, AWS, xAI, Cohere, NVIDIA, DeepSeek, Alibaba (Qwen), et tout autre lab publiant un modèle marquant — y compris les modèles open-weight.

## AI coding / vibe coding / agents dev / open source
Cursor, Claude Code, Gemini CLI, Windsurf, Codeium, Cline, Continue, Aider, OpenHands, OpenCode, Roo Code, Bolt.new, Void, et tout outil coding/agent émergent (CLI, plugin IDE, agent de terminal, assistant self-hosted) qui monte vite, même immature.

## Écosystème connexe
MCP (Model Context Protocol), tool use / function calling, browse / search / computer use, plugins VS Code / JetBrains, local-first, self-hosted, Ollama, OpenRouter, frameworks d’orchestration d’agents, sandboxing / permissions / sécurité des agents, mémoire / long context / retrieval.

## Recherche
Publications de recherche marquantes (arXiv, blogs engineering des labs) ayant un impact pratique, pas seulement les releases produit.

# Axes d’analyse (uniquement)
- actualité des entreprises liée à l’IA (rachats, partenariats, réorganisations ayant un effet technique)
- nouveaux modèles
- changements d’API
- changements tarifaires des modèles, et entreprises qui changent de fournisseur ou d’usage à cause de ces changements
- tool use / search / browse / computer use
- contexte max / tokens / mémoire / long context
- multimodalité
- agents / orchestration
- sécurité / guardrails / gouvernance technique
- dépréciations / breaking changes / migrations
- disponibilité réelle (régions, GA, accès entreprise, Azure / AWS / GCP)

# Objectif
Veille utile pour un profil architecture / plateforme / infra / sécurité / développement. Détecter vite les sorties réellement importantes, y compris l’open source émergent qui change les usages de développement, de prototypage ou de « vibe coding ».

# Consignes anti-bruit (strictes)
- Priorise les sources officielles : changelogs, documentation, releases GitHub, notes de version, billets engineering. Médias généralistes en source secondaire seulement.
- Sépare clairement les faits confirmés des suppositions ou annonces vagues.
- Ne retiens que ce qui a un impact technique réel et une disponibilité réelle (pas seulement annoncé).
- Ce qui est purement marketing : écarte-le en une seule ligne, ne le développe jamais.
- Indique toujours le niveau de maturité réel : prototype / alpha / bêta / GA / production-ready / expérimental.
- Mieux vaut 4 items solides que 12 dilués : le nombre d’items s’adapte à l’actualité du jour, sans plafond fixe.

# Ancrage April (quand c’est pertinent)
Quand une nouveauté touche notre stack (Dagster, Snowflake, Azure, M365) ou un cas d’usage assurance, relie-la explicitement. Ne force pas ce lien quand il n’existe pas.

# Format de sortie obligatoire
N’utilise que ce sous-ensemble markdown : titres `## ` et `### `, puces `- `, tableaux `|`. Pas de listes imbriquées, pas de `####`, pas de blocs de code.

## TL;DR
- 3 puces maximum : l’essentiel du jour, formulé pour décider vite.

## Radar décisionnel

### À tester maintenant
- ce qui est dispo et mérite un essai immédiat (1 ligne par item)

### À surveiller
- ce qui n’est pas encore mûr mais potentiellement structurant

### À ignorer
- ce qui est du bruit / marketing, écarté en une ligne avec la raison

## Nouveautés détaillées
Trie les items par impact réel (pas par catégorie). Un `### ` par nouveauté, puis des puces plates :

### <Titre court de la nouveauté>
- **Ce qui sort** : …
- **Pourquoi c’est important** : … (impact technique)
- **Pour qui** : … (impact architecture / plateforme / sécurité)
- **Type** : nouveau modèle / API / tarification / tool use / long context / multimodal / agents / sécurité / dépréciation / disponibilité / entreprise
- **Maturité** : prototype / alpha / bêta / GA / production-ready
- **Ancrage April** : … (lien stack Dagster / Snowflake / Azure / M365 ou cas assurance ; omets la puce si non pertinent)
- **Action recommandée** : …
- **Source** : [titre de la source](url) — publié le AAAA-MM-JJ

## Sécurité & gouvernance
Section toujours présente. Une puce par sujet : vulnérabilités et CVE touchant modèles, SDK, agents ou serveurs MCP ; incidents ; attaques (prompt injection, exfiltration, supply chain) ; nouveaux guardrails ; évolutions de gouvernance ou de conformité (AI Act, politiques de données). Pour chaque puce : le fait, qui est exposé, l’action recommandée et la source en lien.
- Si rien de notable dans la période : « - Rien de notable dans la période. »

## Signaux faibles & recherche
- repos GitHub qui montent vite (avec lien)
- publications de recherche / blogs engineering marquants (avec l’apport pratique et le lien)
- discussions Reddit marquantes, seulement si des signaux communautaires sont fournis en fin de message (lien du thread + apport pratique ; préciser « retour communautaire, non vérifié » si aucune source primaire ne le confirme)
- sujets à recontrôler dans les prochains jours

## Note de méthode
- Fenêtre couverte (dates et heures).
- Éléments issus de trackers tiers, de médias ou de Reddit plutôt que de sources primaires : liste-les.
- Rappel : les éléments en bêta / preview ne sont pas disponibles en production.
"""

RECENT_NEWS_LOOKBACK_REPORTS = 5
RECENT_NEWS_MAX_TITLES = 60


def recent_news_titles(db: Session, report_type: str = "technical_watch") -> list[str]:
    """Titres des nouveautés des derniers rapports du même type, pour éviter de les répéter."""
    report_ids = [
        row[0]
        for row in db.query(models.Report.id)
        .filter(models.Report.report_type == report_type)
        .order_by(models.Report.created_at.desc())
        .limit(RECENT_NEWS_LOOKBACK_REPORTS)
        .all()
    ]
    if not report_ids:
        return []
    rows = (
        db.query(models.NewsItem.title, models.NewsItem.source_report_date)
        .filter(models.NewsItem.report_id.in_(report_ids))
        .order_by(models.NewsItem.created_at.desc(), models.NewsItem.position.asc())
        .limit(RECENT_NEWS_MAX_TITLES)
        .all()
    )
    return [f"{title} ({date})" if date else title for title, date in rows if title]


def reddit_posts_for_watch(now: Optional[datetime] = None) -> list[dict]:
    """Posts Reddit filtrés pour la veille ; liste vide si REDDIT_ENABLED est faux ou si Reddit échoue."""
    if not reddit.reddit_enabled():
        return []
    try:
        posts = reddit.collect_reddit_posts(period="day", now=now)
    except Exception as e:  # collect_reddit_posts ne lève pas, sécurité supplémentaire
        print(f"Reddit : signaux ignorés ({e})")
        return []
    print(f"Reddit : {len(posts)} signaux communautaires ajoutés au prompt")
    return posts


def now_paris() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:
        return datetime.now()


def build_period_header(now: datetime, days: int) -> str:
    start = now - timedelta(days=days)
    return (
        f"Date du jour : {now.strftime('%Y-%m-%d')}. "
        f"Période couverte : du {start.strftime('%Y-%m-%d %H:%M')} au {now.strftime('%Y-%m-%d %H:%M')} (heure de Paris).\n\n"
    )


def build_already_covered_section(db: Session, report_type: str) -> str:
    titles = recent_news_titles(db, report_type)
    if not titles:
        return ""
    return (
        "\n# Déjà couvert dans les rapports précédents\n"
        "Ne répète pas ces sujets, sauf fait nouveau publié dans la période ; dans ce cas, "
        "commence le titre par « Mise à jour : » et décris uniquement ce qui a changé.\n"
        + "\n".join(f"- {title}" for title in titles)
        + "\n"
    )


def build_technical_prompt(
    db: Session, now: Optional[datetime] = None, reddit_posts: Optional[list[dict]] = None
) -> str:
    if now is None:
        now = now_paris()
    prompt = build_period_header(now, 1) + TECHNICAL_PROMPT
    prompt += build_already_covered_section(db, "technical_watch")
    if reddit_posts is None:
        reddit_posts = reddit_posts_for_watch()
    prompt += reddit.build_reddit_prompt_section(reddit_posts)
    return prompt


COPILOT_WATCH_DAYS = 7

COPILOT_WATCH_PROMPT = """Tu produis une veille hebdomadaire dédiée à l’écosystème Microsoft Copilot, couvrant les nouveautés publiées dans les 7 derniers jours (la date du jour et la période exacte sont indiquées en tête de ce message). Elle complète la veille IA quotidienne, qui ne suit Microsoft que de loin.

# Périmètre
- **Microsoft 365 Copilot** : Copilot Chat, Copilot dans Word / Excel / PowerPoint / Outlook / Teams / Loop / OneNote, Copilot Notebooks, Copilot Search, Memory, agents intégrés (Researcher, Analyst…), licences et tarifs.
- **Copilot Studio** : création d’agents, connecteurs, MCP, actions, computer use, modèles disponibles, gouvernance et facturation (messages, crédits).
- **Work IQ** : couche d’intelligence qui ancre Copilot et les agents dans les données de travail (mails, réunions, fichiers, Teams, personnes), serveur MCP Work IQ, administration dans le centre d’administration Microsoft 365.
- **Copilot Cowork** : agent qui planifie et exécute des tâches de bout en bout dans Microsoft 365, plugins et skills, intégrations (Planner, Purview…).
- Administration et sécurité liées à Copilot : centre d’administration M365, Purview (DLP, étiquettes de sensibilité, audit), Entra, contrôle des agents, résidence des données.
Hors périmètre : GitHub Copilot, Copilot grand public (Windows, Edge, application Copilot personnelle), Dynamics 365 et Power Platform, sauf impact direct sur Microsoft 365 Copilot.

# Méthode de recherche (obligatoire)
Utilise l’outil de recherche web et interroge ces sources primaires une à une, en filtrant sur la période :
1. **Microsoft 365 Roadmap**, filtre Copilot : https://www.microsoft.com/microsoft-365/roadmap?filters=Microsoft%20Copilot%20(Microsoft%20365) (une liste extraite automatiquement de son API peut être fournie en fin de message).
2. **What’s new in Microsoft 365 Copilot** (notes de version, Learn) : https://learn.microsoft.com/microsoft-365/copilot/release-notes
3. **What’s new in Copilot Studio** (Learn) : https://learn.microsoft.com/microsoft-copilot-studio/whats-new
4. **Microsoft 365 Blog** : https://www.microsoft.com/microsoft-365/blog/
5. **Tech Community, blog Microsoft Copilot** : https://techcommunity.microsoft.com/category/microsoft-copilot/blog/microsoft-copilot-blog (dont le billet mensuel « What’s new in Microsoft 365 Copilot »).
6. **Documentation Work IQ** : https://learn.microsoft.com/microsoft-iq/ et https://learn.microsoft.com/microsoft-copilot-studio/agents-experience/add-work-iq
7. **Documentation Copilot Cowork** : https://learn.microsoft.com/microsoft-365/copilot/cowork/
- Pour chaque item, ouvre la source primaire et vérifie la date de publication ou de mise à jour. Ne retiens que ce qui est paru ou a changé de statut dans la période.
- Les sites tiers (miroirs du centre de messages, blogs MVP, médias) servent seulement de pistes : retrouve la source Microsoft, sinon écarte l’item ou signale-le dans la Note de méthode.
- Couvre Microsoft 365 Copilot, Copilot Studio, Work IQ et Copilot Cowork quand il y a de l’actualité ; ne force pas un produit sans nouveauté.
- Semaine calme : dis-le dans le TL;DR et produis un rapport court.

# Questions à traiter pour chaque item
- Identifiant Roadmap s’il existe (ex. « Roadmap 570672 »).
- Statut : In development / Rolling out / Launched (ou Preview / GA selon la source).
- Licence requise : Microsoft 365 Copilot, Copilot Chat (inclus), Copilot Studio (messages / crédits), add-on, programme Frontier…
- Disponibilité en Europe : région UE / EU Data Boundary, tenant français, langue française ; « non précisé » si la source ne dit rien.
- Impact pour l’administration Microsoft 365 : nouveaux contrôles, activation par défaut ou non, gouvernance des données (Purview, étiquettes, DLP, audit, rétention), gestion des agents.

# Consignes anti-bruit (strictes)
- Sources Microsoft officielles uniquement comme preuve ; une source officielle datée par item.
- Sépare l’annoncé (In development, preview) du disponible (Rolling out, Launched, GA).
- Écarte le marketing sans fonctionnalité concrète.
- Mieux vaut 4 items solides que 12 dilués.

# Ancrage April (quand c’est pertinent)
Relie l’item à notre contexte M365 (déploiement de Copilot, gouvernance des données, Teams, SharePoint, Purview) ou à un cas d’usage assurance. Ne force pas ce lien.

# Format de sortie obligatoire
N’utilise que ce sous-ensemble markdown : titres `## ` et `### `, puces `- `, tableaux `|`. Pas de listes imbriquées, pas de `####`, pas de blocs de code.

## TL;DR
- 3 puces maximum : l’essentiel de la semaine côté Copilot, formulé pour décider vite.

## Radar décisionnel

### À tester maintenant
- ce qui est disponible sur notre tenant et mérite un essai (1 ligne par item)

### À surveiller
- annoncé ou en déploiement, potentiellement structurant

### À ignorer
- bruit / marketing, écarté en une ligne avec la raison

## Nouveautés détaillées
Trie les items par impact réel. Un `### ` par nouveauté, puis des puces plates :

### <Titre court de la nouveauté>
- **Ce qui sort** : …
- **Produit** : Microsoft 365 Copilot / Copilot Studio / Work IQ / Copilot Cowork / administration
- **Pourquoi c’est important** : …
- **Pour qui** : utilisateurs / makers / administrateurs M365 / sécurité
- **Identifiant Roadmap** : … (omets la puce s’il n’y en a pas)
- **Statut** : In development / Rolling out / Launched
- **Maturité** : prototype / alpha / bêta / GA / production-ready
- **Licence requise** : …
- **Disponibilité UE / tenant FR** : …
- **Impact admin M365** : contrôles, activation, gouvernance des données
- **Ancrage April** : … (omets la puce si non pertinent)
- **Action recommandée** : …
- **Source** : [titre de la source](url) — publié le AAAA-MM-JJ

## Sécurité & gouvernance
Section toujours présente. Une puce par sujet : nouveaux contrôles d’administration, Purview / DLP / étiquettes, audit, résidence des données, contrôle des agents, incidents ou vulnérabilités touchant Copilot. Pour chaque puce : le fait, qui est concerné, l’action recommandée et la source en lien.
- Si rien de notable dans la période : « - Rien de notable dans la période. »

## Signaux faibles & recherche
- éléments Roadmap annoncés à moyen terme, reports ou annulations, sujets à recontrôler la semaine prochaine (avec lien)

## Note de méthode
- Fenêtre couverte (dates).
- Sources consultées, et éléments issus de sources non officielles : liste-les.
- Rappel : In development / preview ≠ disponible sur le tenant ; le déploiement Microsoft est progressif.
"""


def build_copilot_prompt(
    db: Session, now: Optional[datetime] = None, roadmap_items: Optional[list[dict]] = None
) -> str:
    """Prompt de la veille Microsoft Copilot : fenêtre de 7 jours, « Déjà couvert » des veilles Copilot,
    éléments récents de la Microsoft 365 Roadmap (API publique) quand elle répond."""
    if now is None:
        now = now_paris()
    prompt = build_period_header(now, COPILOT_WATCH_DAYS) + COPILOT_WATCH_PROMPT
    prompt += build_already_covered_section(db, "copilot_watch")
    if roadmap_items is None:
        start = now - timedelta(days=COPILOT_WATCH_DAYS)
        roadmap_items = m365_roadmap.collect_copilot_roadmap(start, now)
        print(f"Roadmap : {len(roadmap_items)} éléments Copilot ajoutés au prompt")
    prompt += m365_roadmap.build_roadmap_prompt_section(roadmap_items)
    return prompt


CODIR_NOTE_PROMPT = """# RÔLE
Tu es Tech Lead à la STTI d'APRIL (assurance, Lyon). Tu produis une note 
hebdomadaire pour le CODIR à partir d'une veille technique IA détaillée.

# AUDIENCE
Directeurs APRIL — non-techniques, pressés, lecture en diagonale. Ils 
décident sur la base : risque / opportunité / coût.

# TÂCHE
À partir du document de veille fourni, produis une note CODIR au format 
Word (.docx), strictement 1 page A4.

# RÈGLES DE TRADUCTION (technique → business)
- **Inverse la pyramide** : impact métier d'abord, techno ensuite.
- **Supprime** : scores benchmarks (SWE-bench…), tailles de modèles 
  (128B, 256k context), noms de frameworks (Temporal, LangChain…), 
  rubriques purement marketing.
- **Traduis les acronymes** : RCE → "exécution de code à distance", 
  MCP → "connecteur universel de l'IA", etc.
- Chaque info doit répondre à : *"qu'est-ce que ça change pour APRIL ? 
  quel bénéfice ? quel risque d'inaction ?"*
- Ajoute une **deadline explicite** sur toute alerte de sécurité.

# STRUCTURE (dans cet ordre, rien de plus)
1. **En-tête** : "NOTE CODIR — VEILLE IA" + date à droite + sous-titre 
   "STTI / Architecture & Gouvernance IA"
2. **Synthèse** : un seul paragraphe, 4 lignes max, mots-clés en gras, 
   alerte sécurité en rouge
3. **Décisions proposées** : tableau de 3 lignes max (colonnes : # / 
   Action / Bénéfice attendu / Validateur). Ligne sécurité en rouge.
4. **Points de vigilance** : 3 bullets, recadrés sur l'impact APRIL 
   (mentionner notre stack quand pertinent : Dagster, Snowflake, Azure, 
   EasyVista, M365…)
5. **Pied de page** : rédacteur + renvoi au rapport complet

# CONTRAINTES VISUELLES
- A4, marges resserrées (haut/bas 0.75", gauche/droite 1")
- Police Calibri, bleu corporate #1F4E79, rouge alerte #C0504D
- Tableau : en-tête bleu plein, alternance gris clair / blanc

# CONTRAINTE DURE
1 page A4 stricte. Si dépassement, sacrifier d'abord les éléments « Signaux faibles & recherche » du rapport,
puis raccourcir la synthèse. Jamais réduire le tableau de décisions.

# FORMAT DE SORTIE
Retourne uniquement le contenu structuré en Markdown simple. N'ajoute pas de bloc de code.
Le document Word sera généré ensuite par l'application.

# DOCUMENT DE VEILLE EN ENTRÉE
{watch_document}
"""


def decode_html_entities(text: str) -> str:
    decoded = text
    for _ in range(3):
        next_decoded = unescape(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    return decoded


def markdown_to_paragraph_markup(text: str) -> str:
    escaped = escape(decode_html_entities(text), quote=False)
    escaped = MARKDOWN_LINK_RE.sub(
        lambda match: (
            f'<link href="{escape(decode_html_entities(match.group("url")), quote=True)}" color="#1d4ed8">'
            f'{escape(decode_html_entities(match.group("label")), quote=False)}</link>'
        ),
        escaped,
    )
    escaped = MARKDOWN_BOLD_RE.sub(
        lambda match: f"<b>{escape(decode_html_entities(match.group('text')), quote=False)}</b>",
        escaped,
    )
    return escaped.replace("\n", "<br/>")


def pdf_text(text: str) -> str:
    return escape(decode_html_entities(text), quote=False)


def build_pdf_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="WatchTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=28,
            textColor=colors.HexColor("#0f172a"),
            alignment=TA_LEFT,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="WatchMeta",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#475569"),
            alignment=TA_LEFT,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="WatchBody",
            parent=styles["Normal"],
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#1e293b"),
            alignment=TA_LEFT,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="WatchBullet",
            parent=styles["Normal"],
            fontSize=10.5,
            leading=15,
            leftIndent=12,
            firstLineIndent=-8,
            bulletIndent=0,
            textColor=colors.HexColor("#1e293b"),
            alignment=TA_LEFT,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="WatchH2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=colors.HexColor("#0f172a"),
            alignment=TA_LEFT,
            spaceBefore=10,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="WatchCaption",
            parent=styles["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#64748b"),
            alignment=TA_LEFT,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="WatchH3",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#334155"),
            alignment=TA_LEFT,
            spaceBefore=8,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="WatchQuote",
            parent=styles["Normal"],
            fontSize=9.5,
            leading=13,
            leftIndent=10,
            rightIndent=6,
            textColor=colors.HexColor("#475569"),
            alignment=TA_LEFT,
            spaceBefore=2,
            spaceAfter=6,
            borderColor=colors.HexColor("#cbd5e1"),
            borderWidth=0.75,
            borderPadding=6,
        )
    )
    return styles


def build_pdf_header(report_date: str, styles, title: str = "AI Technical Watch"):
    header_table = Table(
        [
            [Paragraph(pdf_text(title), styles["WatchTitle"])],
            [Paragraph(report_date, styles["WatchMeta"])],
        ],
        colWidths=[170 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#cbd5e1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return header_table


def fetch_pdf_image(url: str):
    try:
        response = httpx.get(url, timeout=8.0, follow_redirects=True)
        if response.status_code >= 400:
            return None
        content_type = response.headers.get("content-type", "")
        if "image" not in content_type:
            return None
        image = RLImage(BytesIO(response.content))
        image._restrictSize(170 * mm, 90 * mm)
        return image
    except Exception:
        return None


def build_markdown_table(lines: list[str], styles):
    raw_rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        raw_rows.append(cells)

    if len(raw_rows) < 2:
        return []

    header = raw_rows[0]
    data_rows = raw_rows[2:] if len(raw_rows) > 2 else []
    table_data = [[Paragraph(markdown_to_paragraph_markup(cell), styles["WatchBody"]) for cell in header]]
    for row in data_rows:
        normalized = row + [""] * (len(header) - len(row))
        table_data.append(
            [Paragraph(markdown_to_paragraph_markup(cell), styles["WatchBody"]) for cell in normalized[: len(header)]]
        )

    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [table, Spacer(1, 10)]


def append_markdown_pdf_elements(elements, content: str, styles) -> None:
    lines = content.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if stripped.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            elements.extend(build_markdown_table(table_lines, styles))
            continue

        image_match = MARKDOWN_IMAGE_RE.fullmatch(stripped)
        if image_match:
            image = fetch_pdf_image(image_match.group("url"))
            if image is not None:
                elements.append(image)
                caption = image_match.group("alt").strip()
                if caption:
                    elements.append(Paragraph(pdf_text(caption), styles["WatchCaption"]))
            index += 1
            continue

        if stripped.startswith("### "):
            elements.append(Paragraph(pdf_text(stripped[4:]), styles["WatchH3"]))
            index += 1
            continue

        if stripped.startswith("## "):
            elements.append(Paragraph(pdf_text(stripped[3:]), styles["WatchH2"]))
            index += 1
            continue

        if stripped.startswith("- "):
            elements.append(
                Paragraph(markdown_to_paragraph_markup(stripped[2:]), styles["WatchBullet"], bulletText="•")
            )
            index += 1
            continue

        elements.append(Paragraph(markdown_to_paragraph_markup(stripped), styles["WatchBody"]))
        index += 1


def append_note_pdf_elements(elements, note: models.Note, styles) -> None:
    created_at = note.created_at.strftime("%Y-%m-%d %H:%M") if note.created_at else ""
    kind_labels = {
        "detail": "Détail",
        "definition": "Définition",
        "note": "Note",
    }
    title_parts = [f"{kind_labels.get(note.kind, note.kind or 'Note')} #{note.id}"]
    if created_at:
        title_parts.append(created_at)

    elements.append(Paragraph(pdf_text(" - ".join(title_parts)), styles["WatchH3"]))
    if note.source_text and note.source_text.strip():
        elements.append(Paragraph("<b>Extrait :</b>", styles["WatchCaption"]))
        elements.append(Paragraph(markdown_to_paragraph_markup(note.source_text.strip()), styles["WatchQuote"]))
    if note.content and note.content.strip():
        append_markdown_pdf_elements(elements, note.content.strip(), styles)


def build_pdf_story(
    content: str,
    report_date: str,
    summary: Optional[models.ReportSummary] = None,
    notes: Optional[List[models.Note]] = None,
    title: str = "AI Technical Watch",
):
    styles = build_pdf_styles()
    elements = [build_pdf_header(report_date, styles, title), Spacer(1, 12)]

    if summary and summary.content and summary.content.strip():
        elements.append(Paragraph("Résumé exécutif", styles["WatchH2"]))
        append_markdown_pdf_elements(elements, summary.content.strip(), styles)
        elements.append(Spacer(1, 8))

    elements.append(Paragraph("Rapport complet", styles["WatchH2"]))
    append_markdown_pdf_elements(elements, content, styles)

    report_notes = notes or []
    if report_notes:
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("Notes, détails et définitions", styles["WatchH2"]))
        for note in report_notes:
            append_note_pdf_elements(elements, note, styles)

    return elements


def clean_markdown_text(text: str) -> str:
    cleaned = decode_html_entities(text).strip()
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned)
    cleaned = cleaned.replace("**", "")
    cleaned = cleaned.replace("__", "")
    cleaned = cleaned.replace("—", "-")
    return cleaned.strip()


def is_security_text(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "sécurité",
        "securite",
        "alerte",
        "vulnérabilité",
        "vulnerabilite",
        "exécution de code",
        "execution de code",
        "critique",
        "rce",
    ]
    return any(marker in lowered for marker in markers)


def add_markdown_runs(paragraph, text: str, color=None, bold_default: bool = False) -> None:
    parts = re.split(r"(\*\*.*?\*\*)", decode_html_entities(text))
    for part in parts:
        if not part:
            continue
        is_bold = part.startswith("**") and part.endswith("**")
        run_text = part[2:-2] if is_bold else part
        run = paragraph.add_run(run_text)
        run.bold = bold_default or is_bold
        if color is not None:
            run.font.color.rgb = color


def set_docx_cell_shading(cell, fill: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def set_docx_cell_text(cell, text: str, color=None, bold: bool = False) -> None:
    paragraph = cell.paragraphs[0]
    paragraph.text = ""
    run = paragraph.add_run(clean_markdown_text(text))
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def parse_markdown_table(table_lines: List[str]) -> List[List[str]]:
    rows = []
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
            continue
        rows.append(cells)
    return rows


def append_docx_markdown(document, content: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    blue = RGBColor(0x1F, 0x4E, 0x79)
    red = RGBColor(0xC0, 0x50, 0x4D)
    lines = content.splitlines()
    index = 0

    while index < len(lines):
        raw_line = lines[index].rstrip()
        stripped = raw_line.strip()
        if not stripped:
            index += 1
            continue

        if stripped.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            rows = parse_markdown_table(table_lines)
            if rows:
                table = document.add_table(rows=len(rows), cols=max(len(row) for row in rows))
                table.style = "Table Grid"
                for row_index, row in enumerate(rows):
                    for col_index, value in enumerate(row):
                        cell = table.cell(row_index, col_index)
                        if row_index == 0:
                            set_docx_cell_shading(cell, "1F4E79")
                            set_docx_cell_text(cell, value, color=RGBColor(0xFF, 0xFF, 0xFF), bold=True)
                        else:
                            set_docx_cell_shading(cell, "F2F2F2" if row_index % 2 == 1 else "FFFFFF")
                            set_docx_cell_text(cell, value, color=red if is_security_text(" ".join(row)) else None)
                continue

        if stripped.startswith("#"):
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(4)
            paragraph.paragraph_format.space_after = Pt(2)
            add_markdown_runs(paragraph, clean_markdown_text(stripped), color=blue, bold_default=True)
            index += 1
            continue

        if stripped.startswith(("- ", "* ")):
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.paragraph_format.space_after = Pt(1)
            add_markdown_runs(paragraph, stripped[2:], color=red if is_security_text(stripped) else None)
            index += 1
            continue

        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_after = Pt(2)
        add_markdown_runs(paragraph, stripped, color=red if is_security_text(stripped) else None)
        index += 1


def build_codir_docx(report: models.Report) -> bytes:
    try:
        from docx import Document
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches, Pt, RGBColor
    except ImportError as e:
        raise RuntimeError("python-docx is required to export CODIR notes. Run pip install -r requirements.txt") from e

    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.75)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)

    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(8.8)

    blue = RGBColor(0x1F, 0x4E, 0x79)
    red = RGBColor(0xC0, 0x50, 0x4D)

    header_table = document.add_table(rows=2, cols=2)
    header_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    header_table.autofit = True
    title_cell = header_table.cell(0, 0)
    title_run = title_cell.paragraphs[0].add_run("NOTE CODIR - VEILLE IA")
    title_run.bold = True
    title_run.font.size = Pt(14)
    title_run.font.color.rgb = blue

    date_cell = header_table.cell(0, 1)
    date_cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    date_run = date_cell.paragraphs[0].add_run(report.date)
    date_run.bold = True
    date_run.font.color.rgb = blue

    subtitle_cell = header_table.cell(1, 0)
    subtitle_cell.merge(header_table.cell(1, 1))
    subtitle_run = subtitle_cell.paragraphs[0].add_run("STTI / Architecture & Gouvernance IA")
    subtitle_run.font.color.rgb = blue
    subtitle_run.font.size = Pt(9)

    body_content = "\n".join(
        line
        for line in report.content.splitlines()
        if "NOTE CODIR" not in line.upper()
        and "STTI / ARCHITECTURE" not in line.upper()
    )
    append_docx_markdown(document, body_content)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run = footer.add_run("Rédacteur : STTI / Tech Lead - Renvoi au rapport complet de veille IA")
    footer_run.font.size = Pt(8)
    footer_run.font.color.rgb = red if is_security_text(report.content) else blue

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


NEWS_SECTION_PREFIX = "## nouveautés"
MATURITY_LABEL_RE = re.compile(r"^\**\s*maturit[ée]\s*\**\s*[:：\-–—]?\s*", re.IGNORECASE)


def strip_markdown_emphasis(text: str) -> str:
    return re.sub(r"(\*\*|__|\*|_|`)", "", text).strip()


def extract_news_items(content: str) -> list[dict]:
    """Extrait les nouveautés (`### titre` + puces) de la section « Nouveautés détaillées »."""
    if not content:
        return []
    items: list[dict] = []
    in_section = False
    current: Optional[dict] = None

    def flush() -> None:
        if current and current["title"]:
            current["content"] = "\n".join(current["lines"]).strip()
            del current["lines"]
            items.append(current)

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            if in_section:
                break
            in_section = stripped.lower().startswith(NEWS_SECTION_PREFIX)
            continue
        if not in_section:
            continue
        if stripped.startswith("### "):
            flush()
            current = {
                "title": strip_markdown_emphasis(stripped[4:]),
                "maturity": None,
                "lines": [],
            }
            continue
        if current is None:
            continue
        current["lines"].append(line)
        if stripped.startswith("- ") and current["maturity"] is None:
            bullet = strip_markdown_emphasis(stripped[2:])
            if MATURITY_LABEL_RE.match(bullet):
                value = MATURITY_LABEL_RE.sub("", bullet).strip()
                current["maturity"] = value[:80] or None
    flush()
    for index, item in enumerate(items):
        item["position"] = index
    return items


def sync_news_items(db: Session, report: models.Report) -> None:
    """Enregistre les nouveautés d'un rapport de veille si ce n'est pas déjà fait."""
    if report.report_type not in WATCH_REPORT_TYPES:
        return
    exists = db.query(models.NewsItem).filter(models.NewsItem.report_id == report.id).first()
    if exists is not None:
        return
    for item in extract_news_items(report.content or ""):
        db.add(
            models.NewsItem(
                report_id=report.id,
                source_report_date=report.date,
                position=item["position"],
                title=item["title"],
                maturity=item["maturity"],
                content=item["content"],
            )
        )
    db.commit()


def backfill_news_items() -> None:
    db = SessionLocal()
    try:
        known_ids = {row[0] for row in db.query(models.NewsItem.report_id).distinct()}
        reports = (
            db.query(models.Report)
            .filter(models.Report.report_type.in_(WATCH_REPORT_TYPES))
            .all()
        )
        for report in reports:
            if report.id not in known_ids:
                sync_news_items(db, report)
    except Exception as e:
        print(f"News backfill skipped: {e}")
    finally:
        db.close()


backfill_news_items()


def serialize_news_item(item: models.NewsItem, report_dates: dict[int, str]) -> schemas.NewsItem:
    payload = schemas.NewsItem.model_validate(item)
    payload.report_date = report_dates.get(item.report_id) or item.source_report_date
    return payload


def news_report_dates(db: Session, items: list[models.NewsItem]) -> dict[int, str]:
    report_ids = {item.report_id for item in items if item.report_id is not None}
    if not report_ids:
        return {}
    rows = db.query(models.Report.id, models.Report.date).filter(models.Report.id.in_(report_ids)).all()
    return {row[0]: row[1] for row in rows}


@app.get("/news", response_model=List[schemas.NewsItem])
def read_news(
    saved: Optional[bool] = None,
    report_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _=Depends(verify_token),
):
    query = db.query(models.NewsItem)
    if saved is not None:
        query = query.filter(models.NewsItem.saved == saved)
    if report_id is not None:
        query = query.filter(models.NewsItem.report_id == report_id)
    items = query.order_by(
        models.NewsItem.saved_at.desc() if saved else models.NewsItem.created_at.desc(),
        models.NewsItem.position.asc(),
    ).all()
    dates = news_report_dates(db, items)
    return [serialize_news_item(item, dates) for item in items]


@app.get("/reports/{report_id}/news", response_model=List[schemas.NewsItem])
def read_report_news(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    sync_news_items(db, report)
    items = (
        db.query(models.NewsItem)
        .filter(models.NewsItem.report_id == report_id)
        .order_by(models.NewsItem.position.asc())
        .all()
    )
    dates = {report.id: report.date}
    return [serialize_news_item(item, dates) for item in items]


@app.patch("/news/{news_id}", response_model=schemas.NewsItem)
def update_news_item(
    news_id: int,
    payload: schemas.NewsItemUpdate,
    db: Session = Depends(get_db),
    _=Depends(verify_token),
):
    item = db.query(models.NewsItem).filter(models.NewsItem.id == news_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="News not found")
    item.saved = payload.saved
    item.saved_at = datetime.utcnow() if payload.saved else None
    if not payload.saved and item.report_id is None:
        # News orpheline retirée : plus aucune raison de la garder.
        result = serialize_news_item(item, {})
        db.delete(item)
        db.commit()
        return result
    db.commit()
    db.refresh(item)
    return serialize_news_item(item, news_report_dates(db, [item]))


@app.get("/reports", response_model=List[schemas.Report])
def read_reports(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), _=Depends(verify_token)):
    reports = db.query(models.Report).order_by(models.Report.created_at.desc()).offset(skip).limit(limit).all()
    return reports

@app.get("/reports/{report_id}", response_model=schemas.Report)
def read_report(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return db_report


@app.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    db.query(models.ReportSummary).filter(models.ReportSummary.report_id == report_id).delete()
    db.query(models.Note).filter(models.Note.report_id == report_id).delete()
    db.query(models.NewsItem).filter(
        models.NewsItem.report_id == report_id, models.NewsItem.saved.is_(False)
    ).delete(synchronize_session=False)
    # Les news sauvegardées sont détachées : SQLite peut réattribuer cet id au prochain rapport.
    db.query(models.NewsItem).filter(models.NewsItem.report_id == report_id).update(
        {
            models.NewsItem.report_id: None,
            models.NewsItem.source_report_date: func.coalesce(
                models.NewsItem.source_report_date, db_report.date
            ),
        },
        synchronize_session=False,
    )
    db.delete(db_report)
    db.commit()
    return Response(status_code=204)


@app.get("/reports/{report_id}/summary", response_model=schemas.ReportSummaryResponse)
def get_report_summary(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    db_summary = db.query(models.ReportSummary).filter(models.ReportSummary.report_id == report_id).first()
    if db_summary is None:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {
        "report_id": db_summary.report_id,
        "summary": db_summary.content,
        "updated_at": db_summary.updated_at,
    }


@app.post("/reports/{report_id}/summary", response_model=schemas.ReportSummaryResponse)
def summarize_report(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    summary_prompt = f"""Tu reçois un rapport de veille IA déjà rédigé, structuré « décision d'abord » (TL;DR, radar décisionnel, nouveautés détaillées, signaux faibles).

Ta tâche : produire un executive summary court, sans refaire de recherche.

Contraintes :
- utilise uniquement le contenu fourni ci-dessous
- pas de nouvelles affirmations externes
- appuie-toi en priorité sur le TL;DR et le radar décisionnel du rapport
- 5 points maximum
- ton très concret, orienté architecture / plateforme / sécurité / delivery
- termine par une ligne `Décision suggérée : ...`

Rapport :

{db_report.content}
"""

    try:
        ensure_llm_ready()
        response = generate_llm_content(summary_prompt)
        content = response if isinstance(response, str) else response.text
        db_summary = db.query(models.ReportSummary).filter(models.ReportSummary.report_id == report_id).first()
        if db_summary is None:
            db_summary = models.ReportSummary(report_id=report_id, content=content)
            db.add(db_summary)
        else:
            db_summary.content = content
            db_summary.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_summary)
        return {
            "report_id": db_summary.report_id,
            "summary": db_summary.content,
            "updated_at": db_summary.updated_at,
        }
    except Exception as e:
        print(f"Error generating summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reports/{report_id}/detail")
def expand_report_selection(
    report_id: int,
    selected_text: str,
    db: Session = Depends(get_db),
    _=Depends(verify_token),
):
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    detail_prompt = f"""Tu reçois un rapport de veille IA déjà rédigé (structuré « décision d'abord ») et un extrait sélectionné par l'utilisateur.

Ta tâche : expliquer plus en détail cet extrait, sans refaire de recherche.

Contraintes :
- utilise uniquement le rapport ci-dessous
- ne crée pas de nouveaux faits externes
- 6 lignes maximum
- ton concret, technique, utile
- précise si le rapport ne contient pas assez d'information

Extrait sélectionné :
{selected_text}

Rapport complet :
{db_report.content}
"""

    try:
        ensure_llm_ready()
        response = generate_llm_content(detail_prompt)
        content = response if isinstance(response, str) else response.text
        return {"detail": content}
    except Exception as e:
        print(f"Error generating detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reports/{report_id}/definition", response_model=schemas.ReportDefinitionResponse)
def define_report_selection(
    report_id: int,
    selected_text: str,
    db: Session = Depends(get_db),
    _=Depends(verify_token),
):
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    definition_prompt = f"""Tu reçois un rapport de veille IA déjà rédigé (structuré « décision d'abord ») et un terme ou extrait sélectionné par l'utilisateur.

Ta tâche : produire une définition courte, utile et exploitable qui pourra être ajoutée en fin de document.

Contraintes :
- explique le concept en français clair
- commence par une phrase de définition
- ajoute 2 à 3 points maximum : pourquoi c'est important, risque ou usage concret
- traduis les acronymes si nécessaire
- si le rapport ne donne pas assez de contexte, donne une définition générale et indique qu'elle est hors contexte rapport
- ne fais pas de recherche web en direct

Terme ou extrait sélectionné :
{selected_text}

Rapport complet :
{db_report.content}
"""

    try:
        ensure_llm_ready()
        response = generate_llm_content(definition_prompt)
        content = response if isinstance(response, str) else response.text
        return {"definition": content}
    except Exception as e:
        print(f"Error generating definition: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notes", response_model=List[schemas.Note])
def read_notes(db: Session = Depends(get_db), _=Depends(verify_token)):
    return db.query(models.Note).order_by(models.Note.created_at.desc()).all()


@app.post("/reports/{report_id}/notes", response_model=schemas.Note)
def create_note(report_id: int, payload: schemas.NoteCreate, db: Session = Depends(get_db), _=Depends(verify_token)):
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    db_note = models.Note(
        report_id=report_id,
        kind=payload.kind,
        source_text=payload.source_text,
        content=payload.content,
    )
    db.add(db_note)
    db.commit()
    db.refresh(db_note)
    return db_note


@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    db_note = db.query(models.Note).filter(models.Note.id == note_id).first()
    if db_note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(db_note)
    db.commit()
    return Response(status_code=204)


@app.get("/chat/messages", response_model=List[schemas.ChatMessage])
def get_chat_messages(db: Session = Depends(get_db), _=Depends(verify_token)):
    messages = db.query(models.ChatMessage).order_by(models.ChatMessage.created_at.asc()).all()
    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "report_ids": deserialize_report_ids(message.report_ids),
            "created_at": message.created_at,
        }
        for message in messages
    ]


@app.post("/chat", response_model=schemas.ChatResponse)
def chat_with_reports(payload: schemas.ChatRequest, db: Session = Depends(get_db), _=Depends(verify_token)):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    query = db.query(models.Report).order_by(models.Report.created_at.desc())
    if payload.report_ids:
      reports = query.filter(models.Report.id.in_(payload.report_ids)).limit(3).all()
    else:
      reports = query.limit(3).all()

    if not reports:
        raise HTTPException(status_code=404, detail="No reports available")

    # On mémorise les rapports réellement consultés pour afficher les sources.
    used_report_ids = [report.id for report in reports]
    use_web_search = bool(payload.web_search)
    if use_web_search and not llm_supports_web_search():
        raise HTTPException(
            status_code=400,
            detail="Le fournisseur LLM actif n'a pas accès à internet (voir LLM_PROVIDER).",
        )

    context_text = "\n\n---\n\n".join(build_report_chat_context(db, report) for report in reports)
    chat_prompt = build_chat_prompt(
        question,
        context_text,
        build_chat_history_text(payload.history),
        use_web_search,
    )

    try:
        ensure_llm_ready()
        timeout = max(LLM_TIMEOUT_SECONDS, 300) if use_web_search else LLM_TIMEOUT_SECONDS
        content = generate_llm_content(chat_prompt, timeout_seconds=timeout, web_search=use_web_search)
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if payload.persist:
        # Question et réponse sont enregistrées ensemble, seulement en cas de succès.
        serialized_ids = serialize_report_ids(used_report_ids)
        db.add(models.ChatMessage(role="user", content=question, report_ids=serialized_ids))
        db.add(models.ChatMessage(role="assistant", content=content, report_ids=serialized_ids))
        db.commit()
    return {"answer": content}


@app.get("/llm/info", response_model=schemas.LLMInfo)
def get_llm_info(_=Depends(verify_token)):
    try:
        provider = get_llm_provider()
        return {"provider": provider, "web_search": llm_supports_web_search(), "backend": describe_llm_backend()}
    except RuntimeError as e:
        return {"provider": os.getenv("LLM_PROVIDER", ""), "web_search": False, "backend": str(e)}


@app.get("/reddit/preview", response_model=schemas.RedditPreview)
def preview_reddit(
    subreddit: Optional[str] = None,
    period: str = "day",
    _=Depends(verify_token),
):
    """Posts Reddit filtrés tels qu'ils seraient envoyés à la veille, sans appel LLM (flux RSS,
    une requête). Fonctionne même avec REDDIT_ENABLED=false, pour tester la configuration."""
    period = (period or "day").strip()
    if period not in reddit.PERIOD_HOURS:
        raise HTTPException(status_code=400, detail=f"Période invalide : {', '.join(reddit.PERIOD_HOURS)}")
    if subreddit:
        subreddit = subreddit.strip().removeprefix("r/")
        if not reddit.is_valid_subreddit(subreddit):
            raise HTTPException(status_code=400, detail="Nom de subreddit invalide")
    subreddits = [subreddit] if subreddit else reddit.configured_subreddits()
    errors: list[str] = []
    posts = reddit.collect_reddit_posts(subreddits=subreddits, period=period, errors=errors)
    return {
        "enabled": reddit.reddit_enabled(),
        "period": period,
        "subreddits": subreddits,
        "max_posts": reddit.max_posts(),
        "max_posts_per_sub": reddit.max_posts_per_sub(),
        "posts": posts,
        "errors": errors,
    }


# Une seule génération de veille à la fois (bouton de l'interface ou cron).
WATCH_GENERATION_LOCK = threading.Lock()


def today_paris() -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def generate_watch_report(
    db: Session,
    report_type: str = "technical_watch",
    prompt_builder=None,
) -> models.Report:
    """Génère, enregistre et indexe un rapport de veille (quotidienne par défaut, ou copilot_watch avec
    build_copilot_prompt). Appelant : détenir WATCH_GENERATION_LOCK."""
    if report_type not in WATCH_REPORT_TYPES:
        raise ValueError(f"Type de veille inconnu : {report_type}")
    prompt_builder = prompt_builder or build_technical_prompt
    ensure_llm_ready()
    if not llm_supports_web_search():
        print(
            "ATTENTION : le fournisseur LLM actif n'a pas accès à internet ; "
            "la veille reposera sur ses connaissances, sans actualité récente."
        )
    print(f"Sending {report_type} request to {describe_llm_backend()} timeout={LLM_REPORT_TIMEOUT_SECONDS}s")
    start = time.perf_counter()
    content = generate_llm_content(
        prompt_builder(db),
        timeout_seconds=LLM_REPORT_TIMEOUT_SECONDS,
        web_search=True,
    )
    print(f"LLM response received in {time.perf_counter() - start:.2f}s")

    db_report = models.Report(date=today_paris(), report_type=report_type, content=content)
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    sync_news_items(db, db_report)
    return db_report


# Générations longues (veilles, note CODIR) lancées en tâche de fond : le proxy Cloudflare coupe
# toute requête sans réponse après 125 s. Le frontend interroge GET /jobs/{id} jusqu'à la fin.
# Registre en mémoire : suffisant avec un seul worker uvicorn, perdu au redémarrage.
JOBS: dict = {}
JOBS_LOCK = threading.Lock()


def start_report_job(kind: str, work, release_lock: Optional[threading.Lock] = None) -> dict:
    """Exécute `work(db) -> Report` dans un thread et renvoie l'état initial de la tâche."""
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "kind": kind, "status": "running", "report_id": None, "error": None,
           "started_at": datetime.now()}
    with JOBS_LOCK:
        JOBS[job_id] = job

    def run():
        db = SessionLocal()
        try:
            report = work(db)
            job.update(status="done", report_id=report.id)
        except Exception as e:
            print(f"Error in {kind} job: {e}")
            job.update(status="error", error=str(e))
        finally:
            db.close()
            if release_lock is not None:
                release_lock.release()

    threading.Thread(target=run, name=f"job-{kind}-{job_id[:8]}", daemon=True).start()
    return dict(job)


@app.get("/jobs/{job_id}", response_model=schemas.Job)
def get_job(job_id: str, _=Depends(verify_token)):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Tâche inconnue (le serveur a peut-être redémarré).")
    return dict(job)


@app.post("/reports/trigger", response_model=schemas.Job, status_code=202)
def trigger_report(_=Depends(verify_token)):
    if not WATCH_GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Une génération de veille est déjà en cours.")
    return start_report_job("technical_watch", generate_watch_report, release_lock=WATCH_GENERATION_LOCK)


@app.post("/reports/copilot/trigger", response_model=schemas.Job, status_code=202)
def trigger_copilot_report(_=Depends(verify_token)):
    """Veille Microsoft Copilot (7 derniers jours) à la demande. Même verrou que la veille quotidienne."""
    if not WATCH_GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Une génération de veille est déjà en cours.")
    return start_report_job(
        "copilot_watch",
        lambda db: generate_watch_report(db, report_type="copilot_watch", prompt_builder=build_copilot_prompt),
        release_lock=WATCH_GENERATION_LOCK,
    )


# Un envoi de newsletter à la fois : évite un double envoi si le cron et le bouton se croisent.
MAIL_SEND_LOCK = threading.Lock()


def newsletter_subject(report: models.Report) -> str:
    if report.report_type == "copilot_watch":
        return f"Veille Microsoft Copilot – {report.date}"
    return f"Veille IA – {report.date}"


def render_report_newsletter(report: models.Report) -> str:
    if report.report_type == "copilot_watch":
        return render_newsletter(
            report.content or "",
            report.date,
            kicker="Veille Microsoft Copilot · STTI APRIL",
            title="La veille Microsoft Copilot",
        )
    return render_newsletter(report.content or "", report.date)


def build_newsletter_email_html(report: models.Report) -> str:
    """Newsletter dans un document HTML complet (l'endpoint /newsletter renvoie le corps seul)."""
    body = render_report_newsletter(report)
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(newsletter_subject(report))}</title></head>"
        f'<body style="margin:0;padding:0;">{body}</body></html>'
    )


def send_report_newsletter(db: Session, report: models.Report, only_if_unsent: bool = False) -> Optional[list[str]]:
    """Envoie la newsletter du rapport et renseigne newsletter_sent_at.
    Renvoie les destinataires, ou None si only_if_unsent et déjà envoyée.
    Lève mailer.MailNotConfigured / mailer.MailSendError."""
    with MAIL_SEND_LOCK:
        db.refresh(report)
        if only_if_unsent and report.newsletter_sent_at is not None:
            return None
        recipients = mailer.send_html_email(
            newsletter_subject(report),
            build_newsletter_email_html(report),
            text=report.content or None,
        )
        report.newsletter_sent_at = datetime.utcnow()
        db.commit()
        db.refresh(report)
        return recipients


def auto_send_newsletter(db: Session, report: models.Report) -> tuple[bool, Optional[str]]:
    """Envoi automatique du cron : (mail_sent, mail_error). Ne lève jamais."""
    if not mailer.mail_auto_send():
        return False, None
    try:
        return send_report_newsletter(db, report, only_if_unsent=True) is not None, None
    except (mailer.MailNotConfigured, mailer.MailSendError) as e:
        print(f"Mail : envoi automatique de la newsletter {report.id} impossible : {e}")
        return False, str(e)
    except Exception as e:
        print(f"Mail : envoi automatique de la newsletter {report.id} impossible : {type(e).__name__}")
        return False, f"Erreur inattendue : {type(e).__name__}"


def daily_run_response(db: Session, report: models.Report, created: bool) -> dict:
    mail_sent, mail_error = auto_send_newsletter(db, report)
    return {
        "report_id": report.id,
        "date": report.date,
        "created": created,
        "newsletter_url": f"/reports/{report.id}/newsletter",
        "mail_sent": mail_sent,
        "mail_error": mail_error,
    }


@app.post("/cron/daily", response_model=schemas.DailyRunResponse)
def run_daily_watch(force: bool = False, db: Session = Depends(get_db), _=Depends(verify_token)):
    """Route pour le cron : génère la veille du jour si elle n'existe pas encore (force=true pour en refaire une).
    Avec MAIL_AUTO_SEND=true, envoie aussi la newsletter si elle ne l'a pas encore été."""
    today = today_paris()
    if not force:
        existing = (
            db.query(models.Report)
            .filter(models.Report.report_type == "technical_watch", models.Report.date == today)
            .order_by(models.Report.created_at.desc())
            .first()
        )
        if existing is not None:
            return daily_run_response(db, existing, created=False)

    if not WATCH_GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Une génération de veille est déjà en cours.")
    try:
        report = generate_watch_report(db)
    except Exception as e:
        print(f"Error in daily cron run: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        WATCH_GENERATION_LOCK.release()
    return daily_run_response(db, report, created=True)


@app.post("/cron/copilot-weekly", response_model=schemas.DailyRunResponse)
def run_copilot_weekly(force: bool = False, db: Session = Depends(get_db), _=Depends(verify_token)):
    """Route pour le cron hebdomadaire : génère une veille Microsoft Copilot si aucune n'existe sur les
    7 derniers jours (force=true pour en refaire une). Même envoi automatique que /cron/daily."""
    if not force:
        since = (datetime.strptime(today_paris(), "%Y-%m-%d") - timedelta(days=COPILOT_WATCH_DAYS - 1)).strftime("%Y-%m-%d")
        existing = (
            db.query(models.Report)
            .filter(models.Report.report_type == "copilot_watch", models.Report.date >= since)
            .order_by(models.Report.created_at.desc())
            .first()
        )
        if existing is not None:
            return daily_run_response(db, existing, created=False)

    if not WATCH_GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Une génération de veille est déjà en cours.")
    try:
        report = generate_watch_report(db, report_type="copilot_watch", prompt_builder=build_copilot_prompt)
    except Exception as e:
        print(f"Error in Copilot weekly cron run: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        WATCH_GENERATION_LOCK.release()
    return daily_run_response(db, report, created=True)


@app.get("/reports/{report_id}/newsletter", response_class=HTMLResponse)
def get_report_newsletter(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    """Corps d'email HTML (commence par <table>) prêt à coller dans un client mail."""
    report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(render_report_newsletter(report))


@app.get("/mail/info", response_model=schemas.MailInfo)
def get_mail_info(_=Depends(verify_token)):
    """Configuration d'envoi (sans mot de passe ni adresses des destinataires)."""
    return mailer.describe_mail_config()


# Synchrone : l'échange SMTP (plusieurs secondes) tourne dans le pool de threads.
@app.post("/reports/{report_id}/send", response_model=schemas.SendNewsletterResponse)
def send_newsletter(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    """Envoie la newsletter HTML du rapport aux destinataires de MAIL_TO."""
    report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        recipients = send_report_newsletter(db, report)
    except mailer.MailNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except mailer.MailSendError as e:
        print(f"Mail : envoi de la newsletter {report_id} impossible : {e}")
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "report_id": report.id,
        "subject": newsletter_subject(report),
        "recipients_count": len(recipients or []),
        "newsletter_sent_at": report.newsletter_sent_at,
    }


@app.post("/reports/{report_id}/codir", response_model=schemas.Job, status_code=202)
def trigger_codir_note(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    if db.query(models.Report.id).filter(models.Report.id == report_id).first() is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return start_report_job("codir_note", lambda job_db: generate_codir_note(report_id, job_db))


def generate_codir_note(report_id: int, db: Session) -> models.Report:
    source_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if source_report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    source_summary = db.query(models.ReportSummary).filter(models.ReportSummary.report_id == report_id).first()
    source_notes = (
        db.query(models.Note)
        .filter(models.Note.report_id == report_id)
        .order_by(models.Note.created_at.asc())
        .all()
    )

    watch_parts = [f"# Rapport complet - {source_report.date}", source_report.content]
    if source_summary and source_summary.content.strip():
        watch_parts.append(f"# Résumé exécutif enregistré\n{source_summary.content.strip()}")
    if source_notes:
        notes_text = "\n\n".join(
            f"- {note.kind}: {note.content.strip()}" for note in source_notes if note.content and note.content.strip()
        )
        if notes_text:
            watch_parts.append(f"# Notes, détails et définitions enregistrés\n{notes_text}")

    prompt = CODIR_NOTE_PROMPT.format(watch_document="\n\n".join(watch_parts))

    ensure_llm_ready()
    print(f"Sending CODIR note request to {describe_llm_backend()} timeout={LLM_REPORT_TIMEOUT_SECONDS}s")
    response = generate_llm_content(prompt, timeout_seconds=LLM_REPORT_TIMEOUT_SECONDS)
    content = response if isinstance(response, str) else response.text

    db_report = models.Report(
        date=datetime.now().strftime("%Y-%m-%d"),
        report_type="codir_note",
        content=content,
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report


@app.get("/reports/{report_id}/pdf")
def get_report_pdf(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    db_summary = db.query(models.ReportSummary).filter(models.ReportSummary.report_id == report_id).first()
    db_notes = (
        db.query(models.Note)
        .filter(models.Note.report_id == report_id)
        .order_by(models.Note.created_at.asc())
        .all()
    )
    
    pdf_title = "Veille Microsoft Copilot" if db_report.report_type == "copilot_watch" else "AI Technical Watch"
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{pdf_title} - {db_report.date}",
    )
    elements = build_pdf_story(db_report.content, db_report.date, summary=db_summary, notes=db_notes, title=pdf_title)
    doc.build(elements)
    
    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=ai_watch_{db_report.date}.pdf"
        }
    )


@app.get("/reports/{report_id}/docx")
def get_report_docx(report_id: int, db: Session = Depends(get_db), _=Depends(verify_token)):
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if db_report.report_type != "codir_note":
        raise HTTPException(status_code=400, detail="DOCX export is only available for CODIR notes")

    docx_bytes = build_codir_docx(db_report)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=note_codir_veille_ia_{db_report.date}.docx"
        },
    )
