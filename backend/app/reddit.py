"""Lecture de subreddits pour enrichir la veille (signaux communautaires).

Reddit n'accorde pas d'application (pas d'OAuth) et refuse son API JSON sans compte
(403) : on lit donc le flux RSS public, la seule page accessible sans authentification.
Module autonome (pas de dépendance à l'application) :
- fetch_subreddit_posts() lit le top RSS d'un ou plusieurs subreddits en UNE requête
  (`/r/A+B+C/top/.rss`), car Reddit limite les accès anonymes à environ une requête par minute ;
- filter_posts() applique fenêtre temporelle, exclusions, dédoublonnage et plafonds ;
- collect_reddit_posts() enchaîne les deux sur les subreddits configurés ;
- build_reddit_prompt_section() formate les posts pour le prompt de veille.

Le RSS ne donne ni score, ni nombre de commentaires, ni indicateurs épinglé / NSFW / flair :
le rang dans le top (trié par score par Reddit) remplace le score.

Reddit ne doit jamais faire échouer la veille : toute erreur (HTTP, 429, délai, XML
invalide) est journalisée et donne une liste vide.
"""

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

DEFAULT_SUBREDDITS = ("LocalLLaMA", "ClaudeAI", "OpenAI", "ChatGPTCoding", "MachineLearning", "singularity")
# Reddit accepte un User-Agent descriptif sur le RSS (un User-Agent de navigateur est davantage limité).
DEFAULT_USER_AGENT = "linux:veille-ia:1.0 (veille technique IA interne)"
BASE_URL = "https://www.reddit.com"
FETCH_LIMIT = 100  # maximum accepté par Reddit pour un flux
RATE_LIMIT_MAX_WAIT_SECONDS = 65  # attente maximale avant l'unique nouvel essai après un 429
EXCERPT_MAX_CHARS = 280

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
# Fenêtre de filtrage associée à chaque période Reddit (None : pas de limite).
PERIOD_HOURS = {"hour": 1, "day": 24, "week": 24 * 7, "month": 24 * 31, "year": 24 * 366, "all": None}
SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")
MEME_TITLE_RE = re.compile(r"\b(meme|memes|shitpost|humou?r|funny|joke|satire)\b|\[(humou?r|meme|funny)\]", re.IGNORECASE)
MEDIA_HOSTS = ("i.redd.it", "v.redd.it", "preview.redd.it", "i.imgur.com", "imgur.com")
MEDIA_SHORT_TITLE_WORDS = 5  # image / vidéo dont le titre fait moins de 5 mots : traité comme mème
TRACKING_PARAM_PREFIXES = ("utm_", "ref", "fbclid", "gclid")
LINK_RE = re.compile(r'<a href="([^"]+)">\s*\[link\]\s*</a>')
SELFTEXT_RE = re.compile(r'<div class="md">(.*?)</div>', re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


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


def max_posts() -> int:
    return max(0, _env_int("REDDIT_MAX_POSTS", 15))


def max_posts_per_sub() -> int:
    return max(0, _env_int("REDDIT_MAX_POSTS_PER_SUB", 5))


def timeout_seconds() -> float:
    try:
        return float(os.getenv("REDDIT_TIMEOUT_SECONDS", "").strip() or 10)
    except ValueError:
        return 10.0


def user_agent() -> str:
    return os.getenv("REDDIT_USER_AGENT", "").strip() or DEFAULT_USER_AGENT


def is_valid_subreddit(name: str) -> bool:
    return bool(SUBREDDIT_RE.match(name or ""))


# --- Lecture et parsing du flux Atom -------------------------------------------------------


def describe_error(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            return "429 limite de requêtes atteinte"
        return f"HTTP {status}"
    if isinstance(error, httpx.TimeoutException):
        return "délai dépassé"
    if isinstance(error, ET.ParseError):
        return f"flux RSS invalide ({error})"
    return f"{type(error).__name__}: {error}"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _is_reddit_url(url: str) -> bool:
    host = _host(url)
    return host == "redd.it" or host.endswith(".redd.it") or host == "reddit.com" or host.endswith(".reddit.com")


def _is_media_url(url: Optional[str]) -> bool:
    return bool(url) and _host(url) in MEDIA_HOSTS


def _text(element: Optional[ET.Element]) -> str:
    return (element.text or "").strip() if element is not None else ""


def _clean_excerpt(html: str) -> Optional[str]:
    match = SELFTEXT_RE.search(html)
    if not match:
        return None
    text = re.sub(r"\s+", " ", unescape(TAG_RE.sub(" ", match.group(1)))).strip()
    if not text:
        return None
    return text if len(text) <= EXCERPT_MAX_CHARS else text[: EXCERPT_MAX_CHARS - 1].rstrip() + "…"


def _parse_date(value: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_entry(entry: ET.Element, rank: int) -> Optional[dict]:
    """Champs utiles d'une entrée Atom. None si inexploitable."""
    title = unescape(_text(entry.find("a:title", ATOM_NS)))
    link = entry.find("a:link", ATOM_NS)
    permalink = (link.get("href") or "").strip() if link is not None else ""
    created_utc = _parse_date(_text(entry.find("a:published", ATOM_NS)) or _text(entry.find("a:updated", ATOM_NS)))
    if not title or not permalink or created_utc is None:
        return None
    category = entry.find("a:category", ATOM_NS)
    subreddit = (category.get("term") or "").strip() if category is not None else ""
    if not subreddit:
        match = re.search(r"/r/([^/]+)/", permalink)
        subreddit = match.group(1) if match else ""
    content = _text(entry.find("a:content", ATOM_NS))
    link_match = LINK_RE.search(content)
    shared = unescape(link_match.group(1)).strip() if link_match else ""
    return {
        "title": title,
        "subreddit": subreddit,
        "rank": rank,
        "author": _text(entry.find("a:author/a:name", ATOM_NS)) or None,
        "permalink": permalink,
        "external_url": shared if shared and not _is_reddit_url(shared) else None,
        "media": _is_media_url(shared),
        "excerpt": _clean_excerpt(content),
        "created_utc": created_utc,
        "created_at": datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat(),
    }


def parse_feed(xml_text: str) -> list[dict]:
    """Posts d'un flux Atom Reddit, rang 1 = premier du top. Lève ET.ParseError si le XML est invalide."""
    root = ET.fromstring(xml_text)
    posts = []
    for entry in root.findall("a:entry", ATOM_NS):
        post = parse_entry(entry, rank=len(posts) + 1)
        if post:
            posts.append(post)
    return posts


def _retry_delay(response: httpx.Response) -> Optional[float]:
    for header in ("retry-after", "x-ratelimit-reset"):
        try:
            value = float(response.headers.get(header, ""))
        except ValueError:
            continue
        return value if 0 <= value <= RATE_LIMIT_MAX_WAIT_SECONDS else None
    return None


def fetch_subreddit_posts(
    subreddit: str,
    period: str = "day",
    client: Optional[httpx.Client] = None,
    errors: Optional[list] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """Top RSS d'un subreddit, ou de plusieurs joints par « + » (une seule requête), normalisé et
    non filtré. Après un 429, un seul nouvel essai si Reddit annonce une attente courte.
    Liste vide en cas d'erreur."""
    names = [name for name in (subreddit or "").split("+") if name]
    label = "r/" + "+".join(names)
    if not names or not all(is_valid_subreddit(name) for name in names) or period not in PERIOD_HOURS:
        message = f"{label or 'r/?'} : subreddit ou période invalide ({period})"
        print(f"Reddit : {message}")
        if errors is not None:
            errors.append(message)
        return []
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=timeout_seconds(), follow_redirects=True)
    try:
        url = f"{BASE_URL}/r/{'+'.join(names)}/top/.rss"
        params = {"t": period, "limit": FETCH_LIMIT}
        headers = {"User-Agent": user_agent(), "Accept": "application/atom+xml"}
        response = client.get(url, params=params, headers=headers)
        if response.status_code == 429:
            delay = _retry_delay(response)
            if delay is not None:
                print(f"Reddit : 429 sur {label}, nouvel essai dans {delay:.0f} s")
                sleep(delay + 1)
                response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return parse_feed(response.text)
    except Exception as e:
        message = f"{label} indisponible ({describe_error(e)})"
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


def is_meme(post: dict) -> bool:
    """Heuristique (le RSS n'a pas de flair) : mot-clé de mème dans le titre, ou image / vidéo
    avec un titre très court (« Uh oh », « lol »…)."""
    if MEME_TITLE_RE.search(post["title"]):
        return True
    return bool(post.get("media")) and len(post["title"].split()) < MEDIA_SHORT_TITLE_WORDS


def filter_posts(
    posts: list[dict],
    now: Optional[datetime] = None,
    period: str = "day",
    limit: Optional[int] = None,
    per_sub_limit: Optional[int] = None,
) -> list[dict]:
    """Fenêtre de la période (24 h pour `day`), sans mèmes, dédoublonnés par permalink et par
    URL externe (le mieux classé gagne), au plus `per_sub_limit` par subreddit pour que les gros
    subreddits n'écrasent pas les autres, `limit` au total, dans l'ordre du top."""
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    hours = PERIOD_HOURS.get(period, 24)
    cap = max_posts() if limit is None else limit
    per_sub = max_posts_per_sub() if per_sub_limit is None else per_sub_limit

    seen_urls: set[str] = set()
    seen_permalinks: set[str] = set()
    per_sub_count: dict[str, int] = {}
    kept = []
    for post in sorted(posts, key=lambda p: p["rank"]):
        if hours is not None and not (now_ts - hours * 3600 <= post["created_utc"] <= now_ts + 300):
            continue
        if is_meme(post) or post["permalink"] in seen_permalinks:
            continue
        key = canonical_url(post["external_url"]) if post["external_url"] else None
        if key and key in seen_urls:
            continue
        sub = post["subreddit"].lower()
        if per_sub_count.get(sub, 0) >= per_sub:
            continue
        per_sub_count[sub] = per_sub_count.get(sub, 0) + 1
        seen_permalinks.add(post["permalink"])
        if key:
            seen_urls.add(key)
        kept.append(post)
        if len(kept) >= cap:
            break
    return kept


def collect_reddit_posts(
    subreddits: Optional[list[str]] = None,
    period: str = "day",
    now: Optional[datetime] = None,
    client: Optional[httpx.Client] = None,
    errors: Optional[list] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """Posts filtrés de tous les subreddits (configurés par défaut), lus en une requête.
    Ne lève jamais d'exception."""
    try:
        names = subreddits or configured_subreddits()
        posts = fetch_subreddit_posts("+".join(names), period, client=client, errors=errors, sleep=sleep)
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
        "Discussions les plus votées des dernières 24h sur les subreddits suivis (rang dans le top du jour, "
        "1 = la plus votée). Ce sont des pistes, pas des sources : vérifie chaque fait sur une source primaire "
        "(annonce officielle, documentation, dépôt, article) avant de l'utiliser, cite cette source primaire, "
        "et ignore ce qui n'est pas confirmé. Ne crée pas de section dédiée à Reddit : une discussion marquante "
        "sans source primaire va au plus dans « Signaux faibles & recherche » (lien du thread + apport pratique), "
        "et se liste dans la « Note de méthode ».",
    ]
    for post in posts:
        line = f"- {post['title']} — r/{post['subreddit']}, rang {post['rank']} — thread : {post['permalink']}"
        if post.get("external_url"):
            line += f" — lien partagé : {post['external_url']}"
        if post.get("excerpt"):
            line += f" — extrait : « {post['excerpt']} »"
        lines.append(line)
    return "\n".join(lines) + "\n"
