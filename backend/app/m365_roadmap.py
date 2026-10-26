"""Microsoft 365 Roadmap : éléments Copilot récents, pour la veille Microsoft Copilot.

Microsoft publie la Roadmap sous forme d'API JSON publique, sans authentification :
https://www.microsoft.com/releasecommunications/api/v1/m365 (environ 2 200 éléments, ~3 Mo).
Module autonome (pas de dépendance à l'application) :
- fetch_roadmap_items() télécharge la liste complète ;
- filter_copilot_items() garde le périmètre Copilot (Microsoft 365 Copilot, Copilot Studio,
  Work IQ, Copilot Cowork) créé ou modifié dans la fenêtre ;
- build_roadmap_prompt_section() formate la liste pour le prompt.

La Roadmap ne doit jamais faire échouer la veille : toute erreur (HTTP, délai, JSON invalide)
est journalisée et donne une liste vide ; le LLM s'appuie alors sur sa recherche web.
"""

import os
import re
from datetime import datetime, timezone
from html import unescape
from typing import Optional

import httpx

ROADMAP_API_URL = "https://www.microsoft.com/releasecommunications/api/v1/m365"
ROADMAP_ITEM_URL = "https://www.microsoft.com/microsoft-365/roadmap?id={id}"
USER_AGENT = "veille-ia/1.0 (veille technique interne)"
DESCRIPTION_MAX_CHARS = 300

# Produits (tagsContainer.products) du périmètre, et mots-clés de titre qui y font entrer un élément.
COPILOT_PRODUCTS = {"Microsoft Copilot (Microsoft 365)", "Microsoft Copilot Studio", "Work IQ"}
KEYWORD_RE = re.compile(r"cowork|work iq|copilot studio", re.IGNORECASE)
# Applications métier taguées « Copilot » mais hors périmètre (Dynamics, Power Platform),
# sauf si elles mentionnent explicitement Cowork / Work IQ / Copilot Studio.
NOISE_TITLE_RE = re.compile(r"^(Dynamics 365|Power (Apps|Pages|Automate|BI)|Microsoft Dataverse)", re.IGNORECASE)
WORLDWIDE = "Worldwide (Standard Multi-Tenant)"
TAG_RE = re.compile(r"<[^>]+>")


def roadmap_enabled() -> bool:
    value = (os.getenv("COPILOT_ROADMAP_ENABLED") or "").strip().lower()
    return value not in ("0", "false", "no", "off")  # activé par défaut


def max_items() -> int:
    try:
        return max(0, int((os.getenv("COPILOT_ROADMAP_MAX_ITEMS") or "").strip() or 40))
    except ValueError:
        return 40


def timeout_seconds() -> float:
    try:
        return float((os.getenv("COPILOT_ROADMAP_TIMEOUT_SECONDS") or "").strip() or 30)
    except ValueError:
        return 30.0


def describe_error(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    if isinstance(error, httpx.TimeoutException):
        return "délai dépassé"
    return f"{type(error).__name__}: {error}"


def fetch_roadmap_items(client: Optional[httpx.Client] = None, errors: Optional[list] = None) -> list[dict]:
    """Liste brute des éléments de la Roadmap. Liste vide en cas d'erreur."""
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=timeout_seconds(), follow_redirects=True)
    try:
        response = client.get(ROADMAP_API_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("réponse inattendue (liste attendue)")
        return [item for item in payload if isinstance(item, dict)]
    except Exception as e:
        message = f"Microsoft 365 Roadmap indisponible ({describe_error(e)})"
        print(f"Roadmap : {message}")
        if errors is not None:
            errors.append(message)
        return []
    finally:
        if own_client:
            client.close()


def _tags(item: dict, kind: str) -> list[str]:
    container = item.get("tagsContainer") or {}
    return [tag.get("tagName", "") for tag in container.get(kind) or [] if isinstance(tag, dict)]


def _parse_date(value) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)  # dates de l'API en UTC


def in_copilot_scope(item: dict) -> bool:
    title = item.get("title") or ""
    if WORLDWIDE not in _tags(item, "cloudInstances"):
        return False  # éléments réservés aux clouds gouvernementaux américains
    if not (set(_tags(item, "products")) & COPILOT_PRODUCTS or KEYWORD_RE.search(title)):
        return False
    if NOISE_TITLE_RE.match(title) and not KEYWORD_RE.search(title):
        return False
    return True


def _excerpt(html: str) -> str:
    text = (html or "").split("<h3>Availability</h3>")[0]
    text = re.sub(r"\s+", " ", unescape(TAG_RE.sub(" ", text))).strip()
    return text if len(text) <= DESCRIPTION_MAX_CHARS else text[: DESCRIPTION_MAX_CHARS - 1].rstrip() + "…"


def normalize_item(item: dict, start: datetime) -> Optional[dict]:
    created = _parse_date(item.get("created"))
    modified = _parse_date(item.get("modified")) or created
    if item.get("id") is None or not item.get("title") or modified is None:
        return None
    return {
        "id": item["id"],
        "title": re.sub(r"\s+", " ", item["title"]).strip(),
        "status": item.get("status") or "",
        "change": "nouvel élément" if created is not None and created >= start else "mis à jour",
        "products": _tags(item, "products"),
        "release_phases": _tags(item, "releasePhase"),
        "target": item.get("publicDisclosureAvailabilityDate") or "",
        "preview": item.get("publicPreviewDate") or "",
        "created": created.date().isoformat() if created else "",
        "modified": modified.date().isoformat(),
        "modified_at": modified,
        "description": _excerpt(item.get("description") or ""),
        "url": ROADMAP_ITEM_URL.format(id=item["id"]),
    }


def filter_copilot_items(
    items: list[dict], start: datetime, end: datetime, limit: Optional[int] = None
) -> list[dict]:
    """Éléments du périmètre créés ou modifiés entre start et end, nouveaux d'abord, puis du plus
    récent au plus ancien."""
    start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    cap = max_items() if limit is None else limit
    kept = []
    for raw in items:
        if not in_copilot_scope(raw):
            continue
        item = normalize_item(raw, start)
        if item and start <= item["modified_at"] <= end:
            kept.append(item)
    kept.sort(key=lambda i: (i["change"] != "nouvel élément", -i["modified_at"].timestamp()))
    return kept[:cap]


def collect_copilot_roadmap(start: datetime, end: datetime, client: Optional[httpx.Client] = None,
                            errors: Optional[list] = None) -> list[dict]:
    """Éléments Copilot de la fenêtre ; liste vide si désactivé ou en cas d'erreur. Ne lève jamais."""
    if not roadmap_enabled():
        return []
    try:
        return filter_copilot_items(fetch_roadmap_items(client=client, errors=errors), start, end)
    except Exception as e:
        print(f"Roadmap : lecture abandonnée ({describe_error(e)})")
        return []


def build_roadmap_prompt_section(items: list[dict]) -> str:
    """Section ajoutée au prompt de la veille Copilot ; chaîne vide sans éléments."""
    if not items:
        return ""
    lines = [
        "",
        "# Éléments du Microsoft 365 Roadmap créés ou modifiés pendant la période",
        "Extraits automatiquement de l'API publique de la Roadmap (source primaire). Utilise-les comme point de départ : "
        "ouvre la page de chaque élément important, recoupe avec les notes de version et le blog, et reprends "
        "l'identifiant Roadmap, le statut et la date prévue dans l'item. Un élément « mis à jour » peut n'avoir changé "
        "que de date ou de statut : ne le retiens que si le changement compte (passage en Rolling out ou Launched, "
        "report, annulation, nouvelle portée). Ignore ce qui ne concerne pas Microsoft 365 Copilot, Copilot Studio, "
        "Work IQ ou Copilot Cowork.",
    ]
    for item in items:
        details = [
            f"ID {item['id']}",
            item["change"],
            f"statut {item['status']}" if item["status"] else "",
            f"phase {' / '.join(item['release_phases'])}" if item["release_phases"] else "",
            f"date prévue {item['target']}" if item["target"] else "",
            f"modifié le {item['modified']}",
            item["url"],
        ]
        line = f"- {item['title']} — " + ", ".join(d for d in details if d)
        if item["description"]:
            line += f" — « {item['description']} »"
        lines.append(line)
    return "\n".join(lines) + "\n"
