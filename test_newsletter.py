"""Newsletter HTML (contraintes clients mail) et route cron."""
import re

from fastapi.testclient import TestClient

from app import main, models
from app.database import SessionLocal
from app.main import app
from app.newsletter import detect_actor, render_newsletter

REPORT = """## TL;DR
- **OpenAI** sort GPT-X en GA, prix d’entrée divisé par deux.
- Faille critique dans un serveur MCP populaire.

## Radar décisionnel

### À tester maintenant
- GPT-X via l’API Responses

### À surveiller
- Claude Agent SDK 2 (bêta)

### À ignorer
- Annonce marketing sans disponibilité

## Nouveautés détaillées

### OpenAI publie GPT-X
- **Ce qui sort** : nouveau modèle, contexte 1M tokens.
- **Pourquoi c’est important** : coût réduit de 50 %.
- **Type** : nouveau modèle
- **Maturité** : GA
- **Action recommandée** : tester sur le RAG sinistres.
- **Source** : [Changelog OpenAI](https://platform.openai.com/docs/changelog) — publié le 2026-10-23

### Claude Agent SDK 2
- **Ce qui sort** : orchestration multi-agents.
- **Type** : agents
- **Maturité** : bêta
- **Action recommandée** : surveiller.

## Sécurité & gouvernance
- CVE-2026-1234 sur un serveur MCP : exécution de code à distance, mettre à jour.

## Signaux faibles & recherche
- Repo « tiny-agents » en forte hausse

## Note de méthode
- Fenêtre : du 2026-10-23 08:00 au 2026-10-24 08:00.
"""


def test_newsletter_respects_mail_constraints():
    html = render_newsletter(REPORT, "2026-10-24")
    assert html.startswith("<table")
    for forbidden in ("<!DOCTYPE", "<html", "<head", "<body", "<style", "<div", "<strong", "<em>", "class=", "border-left", "background:"):
        assert forbidden.lower() not in html.lower(), forbidden
    assert all(ord(char) < 128 for char in html), "caractères non ASCII restants"
    # Chaque bgcolor est doublé par un background-color identique.
    for color in re.findall(r'bgcolor="(#[0-9a-fA-F]{6})"', html):
        assert f"background-color:{color}" in html
    assert 'width="720"' in html


def test_newsletter_content_and_charte():
    html = render_newsletter(REPORT, "2026-10-24")
    assert "#0f2740" in html and "#eef4f9" in html and "#fdf5f4" in html and "#c0392b" in html
    assert "#10a37f" in html  # barre OpenAI
    assert "#d97757" in html  # barre Anthropic
    assert "Tableau de synth&egrave;se" in html
    assert "Executive summary" in html
    assert 'href="https://platform.openai.com/docs/changelog"' in html
    assert "<b>OpenAI</b>" in html
    assert "s&eacute;curit&eacute;" in html.lower()
    assert "24/10/2026" in html


def test_detect_actor():
    assert detect_actor("Claude Agent SDK 2")[0] == "Anthropic"
    assert detect_actor("Azure AI Foundry")[0] == "Microsoft"
    assert detect_actor("Qwen 4")[0] == "Autres"


def test_newsletter_route_and_daily_cron(monkeypatch):
    monkeypatch.setattr(main, "ensure_llm_ready", lambda: None)
    calls = []

    def fake_generate(prompt, timeout_seconds=0, web_search=False):
        calls.append(web_search)
        return REPORT

    monkeypatch.setattr(main, "generate_llm_content", fake_generate)
    monkeypatch.setattr(main, "today_paris", lambda: "2099-01-01")
    client = TestClient(app)

    first = client.post("/cron/daily").json()
    assert first["created"] is True and first["date"] == "2099-01-01"
    second = client.post("/cron/daily").json()
    assert second["created"] is False and second["report_id"] == first["report_id"]
    forced = client.post("/cron/daily", params={"force": True}).json()
    assert forced["created"] is True and forced["report_id"] != first["report_id"]
    assert calls == [True, True]

    response = client.get(first["newsletter_url"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.startswith("<table")
    assert client.get("/reports/999999/newsletter").status_code == 404

    # Verrou : une génération en cours renvoie 409.
    assert main.WATCH_GENERATION_LOCK.acquire(blocking=False)
    try:
        assert client.post("/cron/daily", params={"force": True}).status_code == 409
        assert client.post("/reports/trigger").status_code == 409
    finally:
        main.WATCH_GENERATION_LOCK.release()

    for report_id in {first["report_id"], forced["report_id"]}:
        client.delete(f"/reports/{report_id}")
