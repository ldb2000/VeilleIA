"""Lecture de subreddits pour enrichir la veille (signaux communautaires).

Module autonome (pas de dépendance à l'application) :
- fetch_subreddit_posts() lit le top d'un subreddit (OAuth « application-only » si
  REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET sont définis, sinon JSON public) ;
- filter_posts() applique fenêtre temporelle, score minimal, exclusions et dédoublonnage ;
- collect_reddit_posts() enchaîne les deux sur les subreddits configurés ;
- build_reddit_prompt_section() formate les posts pour le prompt de veille.

Reddit ne doit jamais faire échouer la veille : toute erreur (HTTP, 429, délai, JSON
invalide) est journalisée et donne une liste vide.
"""

import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

DEFAULT_SUBREDDITS = ("LocalLLaMA", "ClaudeAI", "OpenAI", "ChatGPTCoding", "MachineLearning", "singularity")
DEFAULT_USER_AGENT = "linux:veille-ia:1.0 (veille technique IA interne)"
PUBLIC_BASE_URL = "https://www.reddit.com"
OAUTH_BASE_URL = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
FETCH_LIMIT = 25

# Fenêtre de filtrage associée à chaque période Reddit (None : pas de limite).
PERIOD_HOURS = {"hour": 1, "day": 24, "week": 24 * 7, "month": 24 * 31, "year": 24 * 366, "all": None}
SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")
MEME_FLAIR_RE = re.compile(r"meme|humou?r|funny|joke|shitpost|satire", re.IGNORECASE)
TRACKING_PARAM_PREFIXES = ("utm_", "ref", "fbclid", "gclid")


# --- Configuration (lue à chaque appel) -------------------------------------------------


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        print(f"Reddit : valeur invalide pour {name}, défaut {default} utilisé")
        return default


def reddit_enabled() -> bool:
    return _env_flag("REDDIT_ENABLED", False)


def configured_subreddits() -> list[str]:
    raw = os.getenv("REDDIT_SUBREDDITS", "")
    names = [name.strip().removeprefix("r/") for name in raw.split(",") if name.strip()]
    valid = [name for name in names if SUBREDDIT_RE.match(name)]
    for name in names:
        if name not in valid:
            print(f"Reddit : subreddit ignoré (nom invalide) : {name!r}")
    return valid or list(DEFAULT_SUBREDDITS)


def min_score() -> int:
    return _env_int("REDDIT_MIN_SCORE", 50)


def max_posts() -> int:
    return max(0, _env_int("REDDIT_MAX_POSTS", 15))


def timeout_seconds() -> float:
    try:
        return float(os.getenv("REDDIT_TIMEOUT_SECONDS", "").strip() or 10)
    except ValueError:
        return 10.0


def user_agent() -> str:
    return os.getenv("REDDIT_USER_AGENT", "").strip() or DEFAULT_USER_AGENT


def oauth_configured() -> bool:
    return bool(os.getenv("REDDIT_CLIENT_ID", "").strip() and os.getenv("REDDIT_CLIENT_SECRET", "").strip())


def is_valid_subreddit(name: str) -> bool:
    return bool(SUBREDDIT_RE.match(name or ""))


# --- OAuth « application-only » -----------------------------------------------------------

_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict = {"token": None, "expires_at": 0.0}


def reset_token_cache() -> None:
    with _TOKEN_LOCK:
        _TOKEN_CACHE["token"] = None
        _TOKEN_CACHE["expires_at"] = 0.0


def get_app_token(client: httpx.Client) -> Optional[str]:
    """Jeton client_credentials (mis en cache jusqu'à 60 s avant expiration). None en cas d'échec."""
    if not oauth_configured():
        return None
    with _TOKEN_LOCK:
        if _TOKEN_CACHE["token"] and time.time() < _TOKEN_CACHE["expires_at"]:
            return _TOKEN_CACHE["token"]
        try:
            response = client.post(
                TOKEN_URL,
                auth=(os.getenv("REDDIT_CLIENT_ID", "").strip(), os.getenv("REDDIT_CLIENT_SECRET", "").strip()),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": user_agent()},
            )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token")
            if not token:
                raise ValueError(payload.get("error") or "réponse sans access_token")
        except Exception as e:  # repli sur le JSON public
            print(f"Reddit : échec de l'authentification OAuth ({describe_error(e)}), repli sur le JSON public")
            return None
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires_at"] = time.time() + max(0, float(payload.get("expires_in", 3600)) - 60)
        return token


# --- Lecture et normalisation --------------------------------------------------------------


def describe_error(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            return "429 limite de requêtes atteinte"
        return f"HTTP {status}"
    if isinstance(error, httpx.TimeoutException):
        return "délai dépassé"
    return f"{type(error).__name__}: {error}"


def _is_reddit_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "redd.it" or host.endswith(".redd.it") or host == "reddit.com" or host.endswith(".reddit.com")


def normalize_post(data: dict) -> Optional[dict]:
    """Champs utiles d'un post (objet `data` d'un enfant `t3`). None si inexploitable."""
    title = (data.get("title") or "").strip()
    permalink = data.get("permalink") or ""
    created = data.get("created_utc")
    if not title or not permalink or created is None:
        return None
    url = (data.get("url_overridden_by_dest") or data.get("url") or "").strip()
    external_url = None if data.get("is_self") or not url or _is_reddit_url(url) else url
    created_utc = float(created)
    return {
        "title": title,
        "subreddit": data.get("subreddit") or "",
        "score": int(data.get("score") or 0),
        "num_comments": int(data.get("num_comments") or 0),
        "permalink": PUBLIC_BASE_URL + permalink if permalink.startswith("/") else permalink,
        "external_url": external_url,
        "created_utc": created_utc,
        "created_at": datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat(),
        "flair": (data.get("link_flair_text") or "").strip() or None,
        "stickied": bool(data.get("stickied")),
        "nsfw": bool(data.get("over_18")),
    }


def parse_listing(payload: dict) -> list[dict]:
    children = ((payload or {}).get("data") or {}).get("children") or []
    posts = []
    for child in children:
        if child.get("kind") != "t3":
            continue
        post = normalize_post(child.get("data") or {})
        if post:
            posts.append(post)
    return posts


def fetch_subreddit_posts(
    subreddit: str,
    period: str = "day",
    client: Optional[httpx.Client] = None,
    errors: Optional[list] = None,
) -> list[dict]:
    """Top du subreddit sur la période, normalisé et non filtré. Liste vide en cas d'erreur."""
    if not is_valid_subreddit(subreddit) or period not in PERIOD_HOURS:
        message = f"r/{subreddit} : subreddit ou période invalide ({period})"
        print(f"Reddit : {message}")
        if errors is not None:
            errors.append(message)
        return []
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=timeout_seconds(), follow_redirects=True)
    try:
        params = {"t": period, "limit": FETCH_LIMIT, "raw_json": 1}
        headers = {"User-Agent": user_agent()}
        token = get_app_token(client)
        if token:
            url = f"{OAUTH_BASE_URL}/r/{subreddit}/top"
            headers["Authorization"] = f"Bearer {token}"
        else:
            url = f"{PUBLIC_BASE_URL}/r/{subreddit}/top.json"
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return parse_listing(response.json())
    except Exception as e:
        message = f"r/{subreddit} indisponible ({describe_error(e)})"
        print(f"Reddit : {message}")
        if errors is not None:
            errors.append(message)
        return []
    finally:
        if own_client:
            client.close()


# --- Filtrage ------------------------------------------------------------------------------


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(TRACKING_PARAM_PREFIXES)]
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return urlunsplit(("", host, path, urlencode(query), ""))


def filter_posts(
    posts: list[dict],
    now: Optional[datetime] = None,
    period: str = "day",
    score_threshold: Optional[int] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """Fenêtre de la période (24 h pour `day`), score minimal, sans épinglés / NSFW / mèmes,
    dédoublonnés par URL externe (le mieux noté gagne), triés par score décroissant."""
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    hours = PERIOD_HOURS.get(period, 24)
    threshold = min_score() if score_threshold is None else score_threshold
    cap = max_posts() if limit is None else limit

    kept = []
    for post in posts:
        if post["stickied"] or post["nsfw"]:
            continue
        if post["flair"] and MEME_FLAIR_RE.search(post["flair"]):
            continue
        if post["score"] < threshold:
            continue
        if hours is not None and not (now_ts - hours * 3600 <= post["created_utc"] <= now_ts + 300):
            continue
        kept.append(post)

    kept.sort(key=lambda p: (p["score"], p["num_comments"]), reverse=True)
    seen_urls: set[str] = set()
    seen_permalinks: set[str] = set()
    unique = []
    for post in kept:
        if post["permalink"] in seen_permalinks:
            continue
        if post["external_url"]:
            key = canonical_url(post["external_url"])
            if key in seen_urls:
                continue
            seen_urls.add(key)
        seen_permalinks.add(post["permalink"])
        unique.append(post)
    return unique[:cap]


def collect_reddit_posts(
    subreddits: Optional[list[str]] = None,
    period: str = "day",
    now: Optional[datetime] = None,
    client: Optional[httpx.Client] = None,
    errors: Optional[list] = None,
) -> list[dict]:
    """Posts filtrés de tous les subreddits (configurés par défaut). Ne lève jamais d'exception."""
    try:
        names = subreddits or configured_subreddits()
        own_client = client is None
        if own_client:
            client = httpx.Client(timeout=timeout_seconds(), follow_redirects=True)
        try:
            posts: list[dict] = []
            for name in names:
                posts.extend(fetch_subreddit_posts(name, period, client=client, errors=errors))
        finally:
            if own_client:
                client.close()
        return filter_posts(posts, now=now, period=period)
    except Exception as e:
        print(f"Reddit : collecte abandonnée ({describe_error(e)})")
        if errors is not None:
            errors.append(f"collecte abandonnée ({describe_error(e)})")
        return []


def build_reddit_prompt_section(posts: list[dict]) -> str:
    """Section ajoutée au prompt de veille ; chaîne vide sans posts."""
    if not posts:
        return ""
    lines = [
        "",
        "# Signaux communautaires Reddit",
        "Discussions les plus votées des dernières 24h sur les subreddits suivis. Ce sont des pistes, pas des sources : "
        "vérifie chaque fait sur une source primaire (annonce officielle, documentation, dépôt, article) avant de l'utiliser, "
        "cite cette source primaire, et ignore ce qui n'est pas confirmé. Ne crée pas de section dédiée à Reddit : "
        "une discussion marquante sans source primaire va au plus dans « Signaux faibles & recherche » "
        "(lien du thread + apport pratique), et se liste dans la « Note de méthode ».",
    ]
    for post in posts:
        line = (
            f"- {post['title']} — r/{post['subreddit']}, score {post['score']}, "
            f"{post['num_comments']} commentaires — thread : {post['permalink']}"
        )
        if post.get("external_url"):
            line += f" — lien partagé : {post['external_url']}"
        lines.append(line)
    return "\n".join(lines) + "\n"
