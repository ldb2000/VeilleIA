import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, reddit
from app.database import SessionLocal

NOW = datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc)
NOW_TS = NOW.timestamp()
HOUR = 3600


def post(**overrides):
    data = {
        "title": "Nouveau modèle open-weight",
        "subreddit": "LocalLLaMA",
        "score": 500,
        "num_comments": 120,
        "permalink": "/r/LocalLLaMA/comments/abc/nouveau_modele/",
        "url": "https://huggingface.co/org/model",
        "created_utc": NOW_TS - 2 * HOUR,
        "link_flair_text": "New Model",
        "stickied": False,
        "over_18": False,
        "is_self": False,
    }
    data.update(overrides)
    return {"kind": "t3", "data": data}


def listing(*children):
    return {"kind": "Listing", "data": {"children": list(children)}}


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def reddit_env(monkeypatch):
    for name in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_SUBREDDITS", "REDDIT_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REDDIT_ENABLED", "false")
    monkeypatch.setenv("REDDIT_MIN_SCORE", "50")
    monkeypatch.setenv("REDDIT_MAX_POSTS", "15")
    reddit.reset_token_cache()
    yield
    reddit.reset_token_cache()


@pytest.fixture
def no_network(monkeypatch):
    """Tout client httpx créé par reddit.py répond via ce handler (aucune vraie requête)."""
    calls = []
    state = {"handler": lambda request: httpx.Response(200, json=listing())}

    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("follow_redirects", None)
        kwargs["transport"] = httpx.MockTransport(lambda request: (calls.append(request), state["handler"](request))[1])
        return real_client(*args, **kwargs)

    monkeypatch.setattr(reddit.httpx, "Client", fake_client)
    return calls, state


# --- Parsing ---------------------------------------------------------------------------


def test_parse_listing_extracts_fields():
    posts = reddit.parse_listing(
        listing(
            post(),
            post(title="Question", is_self=True, url="https://www.reddit.com/r/LocalLLaMA/comments/def/q/", permalink="/r/LocalLLaMA/comments/def/q/"),
            {"kind": "t1", "data": {"body": "commentaire"}},
        )
    )
    assert len(posts) == 2
    first = posts[0]
    assert first["title"] == "Nouveau modèle open-weight"
    assert first["subreddit"] == "LocalLLaMA"
    assert first["score"] == 500
    assert first["num_comments"] == 120
    assert first["permalink"] == "https://www.reddit.com/r/LocalLLaMA/comments/abc/nouveau_modele/"
    assert first["external_url"] == "https://huggingface.co/org/model"
    assert first["created_at"].startswith("2026-10-25T06:00:00")
    assert posts[1]["external_url"] is None  # post texte : pas d'URL externe


def test_fetch_uses_public_json_with_user_agent():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=listing(post()))

    posts = reddit.fetch_subreddit_posts("LocalLLaMA", "day", client=mock_client(handler))
    assert len(posts) == 1
    request = seen[0]
    assert request.url.host == "www.reddit.com"
    assert request.url.path == "/r/LocalLLaMA/top.json"
    assert request.url.params["t"] == "day"
    assert request.headers["User-Agent"] == reddit.DEFAULT_USER_AGENT
    assert "Authorization" not in request.headers


def test_fetch_uses_oauth_when_configured(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/api/v1/access_token":
            assert b"grant_type=client_credentials" in request.content
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json=listing(post()))

    client = mock_client(handler)
    assert len(reddit.fetch_subreddit_posts("OpenAI", "day", client=client)) == 1
    assert len(reddit.fetch_subreddit_posts("ClaudeAI", "day", client=client)) == 1
    token_calls = [r for r in seen if r.url.path == "/api/v1/access_token"]
    assert len(token_calls) == 1  # jeton mis en cache
    api_call = seen[-1]
    assert api_call.url.host == "oauth.reddit.com"
    assert api_call.url.path == "/r/ClaudeAI/top"
    assert api_call.headers["Authorization"] == "Bearer tok"


def test_oauth_failure_falls_back_to_public_json(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "bad")

    def handler(request):
        if request.url.path == "/api/v1/access_token":
            return httpx.Response(401, json={"error": "invalid_grant"})
        return httpx.Response(200, json=listing(post()))

    seen_hosts = []

    def recording(request):
        seen_hosts.append(request.url.host)
        return handler(request)

    assert len(reddit.fetch_subreddit_posts("OpenAI", "day", client=mock_client(recording))) == 1
    assert seen_hosts[-1] == "www.reddit.com"


# --- Erreurs : liste vide ----------------------------------------------------------------


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(429, json={"message": "Too Many Requests"}),
        lambda request: httpx.Response(503, text="maintenance"),
        lambda request: httpx.Response(200, text="<html>pas du json</html>"),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout", request=request)),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("dns", request=request)),
    ],
    ids=["429", "503", "invalid-json", "timeout", "connect-error"],
)
def test_fetch_errors_return_empty_list(handler):
    errors = []
    assert reddit.fetch_subreddit_posts("OpenAI", "day", client=mock_client(handler), errors=errors) == []
    assert len(errors) == 1 and "r/OpenAI" in errors[0]


def test_fetch_rejects_invalid_subreddit_without_request():
    def handler(request):
        raise AssertionError("aucune requête attendue")

    assert reddit.fetch_subreddit_posts("../etc", "day", client=mock_client(handler)) == []


def test_collect_survives_one_failing_subreddit():
    def handler(request):
        if "/r/OpenAI/" in request.url.path:
            return httpx.Response(429)
        return httpx.Response(200, json=listing(post()))

    errors = []
    posts = reddit.collect_reddit_posts(["OpenAI", "LocalLLaMA"], now=NOW, client=mock_client(handler), errors=errors)
    assert [p["subreddit"] for p in posts] == ["LocalLLaMA"]
    assert errors and "429" in errors[0]


# --- Filtres -----------------------------------------------------------------------------


def normalized(*children):
    return reddit.parse_listing(listing(*children))


def test_filter_score_window_stickied_nsfw_meme():
    posts = normalized(
        post(title="garde", permalink="/r/a/1/"),
        post(title="score trop bas", score=10, permalink="/r/a/2/"),
        post(title="trop ancien", created_utc=NOW_TS - 30 * HOUR, permalink="/r/a/3/"),
        post(title="épinglé", stickied=True, permalink="/r/a/4/"),
        post(title="nsfw", over_18=True, permalink="/r/a/5/"),
        post(title="mème", link_flair_text="Funny", permalink="/r/a/6/"),
        post(title="mème 2", link_flair_text="Meme", permalink="/r/a/7/"),
    )
    kept = reddit.filter_posts(posts, now=NOW)
    assert [p["title"] for p in kept] == ["garde"]


def test_filter_week_period_widens_window():
    posts = normalized(post(title="il y a 3 jours", created_utc=NOW_TS - 72 * HOUR))
    assert reddit.filter_posts(posts, now=NOW, period="day") == []
    assert len(reddit.filter_posts(posts, now=NOW, period="week")) == 1


def test_filter_deduplicates_external_url_across_subreddits_keeping_best_score():
    posts = normalized(
        post(subreddit="OpenAI", score=200, url="https://openai.com/index/annonce?utm_source=reddit", permalink="/r/OpenAI/1/"),
        post(subreddit="singularity", score=900, url="https://www.openai.com/index/annonce/", permalink="/r/singularity/2/"),
        post(subreddit="LocalLLaMA", title="post texte", is_self=True, url="", permalink="/r/LocalLLaMA/3/"),
        post(subreddit="ClaudeAI", title="autre texte", is_self=True, url="", permalink="/r/ClaudeAI/4/"),
    )
    kept = reddit.filter_posts(posts, now=NOW)
    assert [p["subreddit"] for p in kept] == ["singularity", "LocalLLaMA", "ClaudeAI"]


def test_filter_respects_min_score_and_max_posts_env(monkeypatch):
    monkeypatch.setenv("REDDIT_MIN_SCORE", "300")
    monkeypatch.setenv("REDDIT_MAX_POSTS", "2")
    posts = normalized(
        *[post(title=f"p{i}", score=250 + i * 100, url=f"https://ex.com/{i}", permalink=f"/r/a/{i}/") for i in range(5)]
    )
    kept = reddit.filter_posts(posts, now=NOW)
    assert [p["title"] for p in kept] == ["p4", "p3"]


def test_configured_subreddits(monkeypatch):
    assert reddit.configured_subreddits() == list(reddit.DEFAULT_SUBREDDITS)
    monkeypatch.setenv("REDDIT_SUBREDDITS", " LocalLLaMA, r/mlops ,bad name!,")
    assert reddit.configured_subreddits() == ["LocalLLaMA", "mlops"]


# --- Prompt de veille --------------------------------------------------------------------


def watch_prompt(**kwargs):
    db = SessionLocal()
    try:
        return main.build_technical_prompt(db, now=datetime(2026, 10, 25, 8, 0), **kwargs)
    finally:
        db.close()


def test_prompt_without_reddit_when_disabled(no_network):
    calls, _ = no_network
    prompt = watch_prompt()
    assert "Signaux communautaires Reddit" not in prompt
    assert calls == []  # REDDIT_ENABLED=false : aucune requête


def test_prompt_contains_reddit_section_when_enabled(monkeypatch, no_network):
    calls, state = no_network
    monkeypatch.setenv("REDDIT_ENABLED", "true")
    monkeypatch.setenv("REDDIT_SUBREDDITS", "LocalLLaMA")
    fresh = datetime.now(timezone.utc).timestamp() - HOUR
    state["handler"] = lambda request: httpx.Response(200, json=listing(post(created_utc=fresh)))
    prompt = watch_prompt()
    assert "# Signaux communautaires Reddit" in prompt
    assert "source primaire" in prompt
    assert (
        "- Nouveau modèle open-weight — r/LocalLLaMA, score 500, 120 commentaires — "
        "thread : https://www.reddit.com/r/LocalLLaMA/comments/abc/nouveau_modele/"
    ) in prompt
    assert len(calls) == 1


def test_prompt_unchanged_when_reddit_unavailable(monkeypatch, no_network):
    _, state = no_network
    baseline = watch_prompt()
    monkeypatch.setenv("REDDIT_ENABLED", "true")
    state["handler"] = lambda request: httpx.Response(429)
    assert watch_prompt() == baseline


def test_reddit_section_adds_no_report_heading():
    section = reddit.build_reddit_prompt_section(normalized(post()))
    assert not any(line.startswith("## ") for line in section.splitlines())
    output_format = main.TECHNICAL_PROMPT.split("# Format de sortie obligatoire", 1)[1]
    headings = {line for line in output_format.splitlines() if line.startswith("## ")}
    assert headings == {
        "## TL;DR",
        "## Radar décisionnel",
        "## Nouveautés détaillées",
        "## Sécurité & gouvernance",
        "## Signaux faibles & recherche",
        "## Note de méthode",
    }
    signals = main.TECHNICAL_PROMPT.split("## Signaux faibles & recherche", 1)[1].split("## Note de méthode")[0]
    assert "Reddit" in signals and "lien du thread" in signals


def test_generate_watch_report_works_when_reddit_down(monkeypatch, no_network):
    _, state = no_network
    monkeypatch.setenv("REDDIT_ENABLED", "true")
    state["handler"] = lambda request: (_ for _ in ()).throw(httpx.ConnectError("down", request=request))
    sent = {}
    monkeypatch.setattr(main, "ensure_llm_ready", lambda: None)
    monkeypatch.setattr(main, "llm_supports_web_search", lambda: True)
    monkeypatch.setattr(
        main,
        "generate_llm_content",
        lambda prompt, timeout_seconds, web_search=False: sent.setdefault("prompt", prompt) and "## TL;DR\n- ok\n",
    )
    db = SessionLocal()
    try:
        report = main.generate_watch_report(db)
        assert report.content.startswith("## TL;DR")
        db.delete(report)
        db.commit()
    finally:
        db.close()
    assert "Signaux communautaires Reddit" not in sent["prompt"]


# --- GET /reddit/preview -----------------------------------------------------------------


def test_preview_returns_filtered_posts_without_llm(monkeypatch, no_network):
    calls, state = no_network
    fresh = datetime.now(timezone.utc).timestamp() - HOUR
    state["handler"] = lambda request: httpx.Response(
        200,
        json=listing(post(created_utc=fresh), post(title="épinglé", stickied=True, created_utc=fresh, permalink="/r/x/9/")),
    )
    monkeypatch.setattr(main, "generate_llm_content", lambda *a, **k: pytest.fail("le LLM ne doit pas être appelé"))
    response = TestClient(main.app).get("/reddit/preview", params={"subreddit": "LocalLLaMA", "period": "day"})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["subreddits"] == ["LocalLLaMA"]
    assert [p["title"] for p in body["posts"]] == ["Nouveau modèle open-weight"]
    assert body["errors"] == []
    assert calls[0].url.path == "/r/LocalLLaMA/top.json"


def test_preview_defaults_to_configured_subreddits_and_reports_errors(monkeypatch, no_network):
    _, state = no_network
    monkeypatch.setenv("REDDIT_SUBREDDITS", "OpenAI,ClaudeAI")
    state["handler"] = lambda request: httpx.Response(429)
    body = TestClient(main.app).get("/reddit/preview?subreddit=&period=").json()
    assert body["subreddits"] == ["OpenAI", "ClaudeAI"]
    assert body["period"] == "day"
    assert body["posts"] == []
    assert len(body["errors"]) == 2


def test_preview_validates_parameters(no_network):
    client = TestClient(main.app)
    assert client.get("/reddit/preview", params={"period": "decade"}).status_code == 400
    assert client.get("/reddit/preview", params={"subreddit": "bad name"}).status_code == 400


def test_preview_requires_token_when_api_token_set(monkeypatch, no_network):
    monkeypatch.setattr(main, "API_TOKEN", "secret")
    client = TestClient(main.app)
    assert client.get("/reddit/preview").status_code == 401
    assert client.get("/reddit/preview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/reddit/preview", headers={"Authorization": "Bearer secret"}).status_code == 200
