from datetime import datetime, timedelta, timezone
from html import escape

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, reddit
from app.database import SessionLocal

NOW = datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def entry(
    title="Nouveau modèle open-weight publié",
    subreddit="LocalLLaMA",
    post_id="abc",
    link="https://huggingface.co/org/model",
    published=None,
    selftext=None,
    author="/u/someone",
):
    """Entrée Atom au format du flux RSS de Reddit (contenu HTML échappé, liens [link] / [comments])."""
    permalink = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/slug/"
    published = (published or NOW - 2 * HOUR).isoformat()
    body = f'<!-- SC_OFF --><div class="md"><p>{selftext}</p></div><!-- SC_ON -->' if selftext else ""
    shared = link or permalink
    content = (
        f"{body} &#32; submitted by &#32; <a href=\"https://www.reddit.com/user/x\"> {author} </a>"
        f" &#32; to &#32; <a href=\"https://www.reddit.com/r/{subreddit}/\"> r/{subreddit} </a> <br/>"
        f" <span><a href=\"{escape(shared)}\">[link]</a></span> &#32; <span><a href=\"{permalink}\">[comments]</a></span>"
    )
    return (
        f"<entry><author><name>{author}</name><uri>https://www.reddit.com/user/x</uri></author>"
        f'<category term="{subreddit}" label="r/{subreddit}"/>'
        f'<content type="html">{escape(content)}</content><id>t3_{post_id}</id>'
        f'<link href="{permalink}" /><updated>{published}</updated><published>{published}</published>'
        f"<title>{escape(title)}</title></entry>"
    )


def feed(*entries):
    return (
        '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:media="http://search.yahoo.com/mrss/"><title>top</title>' + "".join(entries) + "</feed>"
    )


def atom(*entries, status=200, headers=None):
    return httpx.Response(status, text=feed(*entries), headers={"content-type": "application/atom+xml", **(headers or {})})


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def no_sleep(seconds):
    raise AssertionError("aucune attente attendue")


@pytest.fixture(autouse=True)
def reddit_env(monkeypatch):
    for name in ("REDDIT_SUBREDDITS", "REDDIT_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REDDIT_ENABLED", "false")
    monkeypatch.setenv("REDDIT_MAX_POSTS", "15")
    monkeypatch.setenv("REDDIT_MAX_POSTS_PER_SUB", "5")


@pytest.fixture
def no_network(monkeypatch):
    """Tout client httpx créé par reddit.py répond via ce handler (aucune vraie requête)."""
    calls = []
    state = {"handler": lambda request: atom()}
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("follow_redirects", None)
        kwargs["transport"] = httpx.MockTransport(lambda request: (calls.append(request), state["handler"](request))[1])
        return real_client(*args, **kwargs)

    monkeypatch.setattr(reddit.httpx, "Client", fake_client)
    monkeypatch.setattr(reddit.time, "sleep", lambda seconds: None)
    return calls, state


# --- Parsing ---------------------------------------------------------------------------


def test_parse_feed_extracts_fields():
    posts = reddit.parse_feed(
        feed(
            entry(),
            entry(
                title="Retour d'expérience &amp; question",
                post_id="def",
                link=None,
                selftext="J'ai testé <b>vLLM</b> sur 2 GPU &amp; voici les chiffres.",
            ),
        )
    )
    assert len(posts) == 2
    first = posts[0]
    assert first["title"] == "Nouveau modèle open-weight publié"
    assert first["subreddit"] == "LocalLLaMA"
    assert first["rank"] == 1
    assert first["author"] == "/u/someone"
    assert first["permalink"] == "https://www.reddit.com/r/LocalLLaMA/comments/abc/slug/"
    assert first["external_url"] == "https://huggingface.co/org/model"
    assert first["created_at"].startswith("2026-10-25T06:00:00")
    second = posts[1]
    assert second["rank"] == 2
    assert second["title"] == "Retour d'expérience & question"
    assert second["external_url"] is None  # post texte : pas d'URL externe
    assert second["excerpt"] == "J'ai testé vLLM sur 2 GPU & voici les chiffres."


def test_parse_feed_marks_media_and_truncates_excerpt():
    long_text = "mot " * 200
    posts = reddit.parse_feed(feed(entry(link="https://i.redd.it/x.png"), entry(post_id="b", link=None, selftext=long_text)))
    assert posts[0]["external_url"] is None and posts[0]["media"] is True
    assert len(posts[1]["excerpt"]) <= reddit.EXCERPT_MAX_CHARS and posts[1]["excerpt"].endswith("…")


def test_fetch_reads_combined_rss_in_one_request():
    seen = []

    def handler(request):
        seen.append(request)
        return atom(entry(), entry(subreddit="ClaudeAI", post_id="c"))

    posts = reddit.fetch_subreddit_posts("LocalLLaMA+ClaudeAI", "day", client=mock_client(handler), sleep=no_sleep)
    assert [p["subreddit"] for p in posts] == ["LocalLLaMA", "ClaudeAI"]
    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == "www.reddit.com"
    assert request.url.path == "/r/LocalLLaMA+ClaudeAI/top/.rss"
    assert request.url.params["t"] == "day"
    assert request.url.params["limit"] == "100"
    assert request.headers["User-Agent"] == reddit.DEFAULT_USER_AGENT
    assert "Authorization" not in request.headers


def test_collect_uses_a_single_request_for_all_subreddits():
    seen = []

    def handler(request):
        seen.append(request)
        return atom(entry(published=NOW - HOUR))

    reddit.collect_reddit_posts(["LocalLLaMA", "OpenAI", "ClaudeAI"], now=NOW, client=mock_client(handler), sleep=no_sleep)
    assert [r.url.path for r in seen] == ["/r/LocalLLaMA+OpenAI+ClaudeAI/top/.rss"]


# --- 429 et erreurs : liste vide ---------------------------------------------------------


def test_429_retries_once_after_announced_delay():
    responses = [atom(status=429, headers={"x-ratelimit-reset": "30"}), atom(entry())]
    waits = []
    posts = reddit.fetch_subreddit_posts(
        "OpenAI", "day", client=mock_client(lambda request: responses.pop(0)), sleep=waits.append
    )
    assert len(posts) == 1
    assert waits == [31.0]


def test_429_with_long_delay_gives_up_without_waiting():
    errors = []
    handler = lambda request: atom(status=429, headers={"x-ratelimit-reset": "600"})
    assert reddit.fetch_subreddit_posts("OpenAI", "day", client=mock_client(handler), errors=errors, sleep=no_sleep) == []
    assert "429" in errors[0]


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: atom(status=429, headers={"x-ratelimit-reset": "5"}),  # 429 deux fois
        lambda request: httpx.Response(403, text="blocked"),
        lambda request: httpx.Response(503, text="maintenance"),
        lambda request: httpx.Response(200, text="<html><body>pas un flux"),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout", request=request)),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("dns", request=request)),
    ],
    ids=["429-twice", "403", "503", "invalid-xml", "timeout", "connect-error"],
)
def test_fetch_errors_return_empty_list(handler):
    errors = []
    assert reddit.fetch_subreddit_posts("OpenAI", "day", client=mock_client(handler), errors=errors, sleep=lambda s: None) == []
    assert len(errors) == 1 and "r/OpenAI" in errors[0]


def test_fetch_rejects_invalid_subreddit_without_request():
    def handler(request):
        raise AssertionError("aucune requête attendue")

    assert reddit.fetch_subreddit_posts("../etc", "day", client=mock_client(handler)) == []
    assert reddit.fetch_subreddit_posts("OpenAI+bad name", "day", client=mock_client(handler)) == []
    assert reddit.fetch_subreddit_posts("OpenAI", "decade", client=mock_client(handler)) == []


# --- Filtres -----------------------------------------------------------------------------


def parsed(*entries):
    return reddit.parse_feed(feed(*entries))


def test_filter_window_and_memes():
    posts = parsed(
        entry(title="Sortie de vLLM 1.0 avec un nouveau scheduler", post_id="1", link="https://ex.com/1"),
        entry(title="Ancien sujet sur les agents de code", post_id="2", published=NOW - 30 * HOUR, link="https://ex.com/2"),
        entry(title="Best meme of the week about GPUs", post_id="3", link="https://ex.com/3"),
        entry(title="Uh oh", post_id="4", link="https://i.redd.it/x.png"),
        entry(title="Capture du nouveau tableau de bord Claude Code", post_id="5", link="https://i.redd.it/y.png"),
    )
    kept = reddit.filter_posts(posts, now=NOW)
    assert [p["title"] for p in kept] == [
        "Sortie de vLLM 1.0 avec un nouveau scheduler",
        "Capture du nouveau tableau de bord Claude Code",  # image avec un vrai titre : gardée
    ]


def test_filter_week_period_widens_window():
    posts = parsed(entry(published=NOW - 72 * HOUR))
    assert reddit.filter_posts(posts, now=NOW, period="day") == []
    assert len(reddit.filter_posts(posts, now=NOW, period="week")) == 1


def test_filter_deduplicates_external_url_keeping_best_rank():
    posts = parsed(
        entry(subreddit="singularity", post_id="1", link="https://www.openai.com/index/annonce/"),
        entry(subreddit="OpenAI", post_id="2", link="https://openai.com/index/annonce?utm_source=reddit"),
        entry(subreddit="LocalLLaMA", post_id="3", link=None, selftext="texte"),
        entry(subreddit="ClaudeAI", post_id="4", link=None, selftext="autre"),
    )
    kept = reddit.filter_posts(posts, now=NOW)
    assert [p["subreddit"] for p in kept] == ["singularity", "LocalLLaMA", "ClaudeAI"]


def test_filter_caps_per_subreddit_and_total(monkeypatch):
    monkeypatch.setenv("REDDIT_MAX_POSTS", "4")
    monkeypatch.setenv("REDDIT_MAX_POSTS_PER_SUB", "2")
    posts = parsed(
        *[entry(subreddit="singularity", post_id=f"s{i}", link=f"https://ex.com/s{i}") for i in range(4)],
        *[entry(subreddit="ChatGPTCoding", post_id=f"c{i}", link=f"https://ex.com/c{i}") for i in range(3)],
    )
    kept = reddit.filter_posts(posts, now=NOW)
    assert [(p["subreddit"], p["rank"]) for p in kept] == [
        ("singularity", 1),
        ("singularity", 2),
        ("ChatGPTCoding", 5),
        ("ChatGPTCoding", 6),
    ]


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


def fresh_entry(**kwargs):
    return entry(published=datetime.now(timezone.utc) - HOUR, **kwargs)


def test_prompt_without_reddit_when_disabled(no_network):
    calls, _ = no_network
    prompt = watch_prompt()
    assert "Signaux communautaires Reddit" not in prompt
    assert calls == []  # REDDIT_ENABLED=false : aucune requête


def test_prompt_contains_reddit_section_when_enabled(monkeypatch, no_network):
    calls, state = no_network
    monkeypatch.setenv("REDDIT_ENABLED", "true")
    monkeypatch.setenv("REDDIT_SUBREDDITS", "LocalLLaMA,ClaudeAI")
    state["handler"] = lambda request: atom(
        fresh_entry(), fresh_entry(subreddit="ClaudeAI", post_id="q", link=None, selftext="Astuce sur les hooks")
    )
    prompt = watch_prompt()
    assert "# Signaux communautaires Reddit" in prompt
    assert "source primaire" in prompt
    assert (
        "- Nouveau modèle open-weight publié — r/LocalLLaMA, rang 1 — "
        "thread : https://www.reddit.com/r/LocalLLaMA/comments/abc/slug/ — lien partagé : https://huggingface.co/org/model"
    ) in prompt
    assert "r/ClaudeAI, rang 2" in prompt and "extrait : « Astuce sur les hooks »" in prompt
    assert [r.url.path for r in calls] == ["/r/LocalLLaMA+ClaudeAI/top/.rss"]


def test_prompt_unchanged_when_reddit_unavailable(monkeypatch, no_network):
    _, state = no_network
    baseline = watch_prompt()
    monkeypatch.setenv("REDDIT_ENABLED", "true")
    state["handler"] = lambda request: httpx.Response(403, text="blocked")
    assert watch_prompt() == baseline


def test_reddit_section_adds_no_report_heading():
    section = reddit.build_reddit_prompt_section(parsed(entry()))
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
    state["handler"] = lambda request: atom(fresh_entry(), fresh_entry(title="Uh oh", post_id="m", link="https://i.redd.it/m.png"))
    monkeypatch.setattr(main, "generate_llm_content", lambda *a, **k: pytest.fail("le LLM ne doit pas être appelé"))
    response = TestClient(main.app).get("/reddit/preview", params={"subreddit": "LocalLLaMA", "period": "day"})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["subreddits"] == ["LocalLLaMA"]
    assert body["max_posts_per_sub"] == 5
    assert [p["title"] for p in body["posts"]] == ["Nouveau modèle open-weight publié"]
    assert body["posts"][0]["rank"] == 1
    assert body["errors"] == []
    assert calls[0].url.path == "/r/LocalLLaMA/top/.rss"


def test_preview_defaults_to_configured_subreddits_and_reports_errors(monkeypatch, no_network):
    calls, state = no_network
    monkeypatch.setenv("REDDIT_SUBREDDITS", "OpenAI,ClaudeAI")
    state["handler"] = lambda request: httpx.Response(403, text="blocked")
    body = TestClient(main.app).get("/reddit/preview?subreddit=&period=").json()
    assert body["subreddits"] == ["OpenAI", "ClaudeAI"]
    assert body["period"] == "day"
    assert body["posts"] == []
    assert body["errors"] == ["r/OpenAI+ClaudeAI indisponible (HTTP 403)"]
    assert len(calls) == 1


def test_preview_validates_parameters(no_network):
    client = TestClient(main.app)
    assert client.get("/reddit/preview", params={"period": "decade"}).status_code == 400
    assert client.get("/reddit/preview", params={"subreddit": "bad name"}).status_code == 400
    assert client.get("/reddit/preview", params={"subreddit": "a+b"}).status_code == 400


def test_preview_requires_token_when_api_token_set(monkeypatch, no_network):
    monkeypatch.setattr(main, "API_TOKEN", "secret")
    client = TestClient(main.app)
    assert client.get("/reddit/preview").status_code == 401
    assert client.get("/reddit/preview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/reddit/preview", headers={"Authorization": "Bearer secret"}).status_code == 200
