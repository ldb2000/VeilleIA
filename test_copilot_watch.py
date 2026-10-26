import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import m365_roadmap, main, models
from app.database import SessionLocal

NOW = datetime(2026, 10, 26, 8, 0)
UTC_NOW = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)

COPILOT_REPORT = """## TL;DR
- Work IQ gagne la validation humaine des actions d’agents.

## Radar décisionnel

### À tester maintenant
- Références CSV dans Copilot Notebooks

### À surveiller
- Work IQ : Human in the loop

### À ignorer
- Annonce marketing sans date

## Nouveautés détaillées

### Work IQ : validation humaine des actions d’agents
- **Ce qui sort** : les agents demandent une validation avant d’agir.
- **Produit** : Work IQ
- **Identifiant Roadmap** : 570672
- **Statut** : In development
- **Maturité** : bêta
- **Licence requise** : Microsoft 365 Copilot
- **Disponibilité UE / tenant FR** : non précisé
- **Impact admin M365** : nouveau contrôle dans le centre d’administration
- **Action recommandée** : suivre le déploiement
- **Source** : [Microsoft 365 Roadmap](https://www.microsoft.com/microsoft-365/roadmap?id=570672) — publié le 2026-10-19

### DLP Purview pour Copilot Cowork
- **Ce qui sort** : la DLP s’applique aux tâches Cowork.
- **Produit** : Copilot Cowork
- **Statut** : Rolling out
- **Maturité** : GA
- **Source** : [Microsoft 365 Roadmap](https://www.microsoft.com/microsoft-365/roadmap?id=570845) — publié le 2026-10-19

## Sécurité & gouvernance
- DLP Cowork : vérifier les stratégies Purview existantes.

## Signaux faibles & recherche
- Agent Policy Governance prévu en janvier 2027.

## Note de méthode
- Fenêtre : du 2026-10-19 au 2026-10-26.
"""


def roadmap_item(item_id, title, products, created, modified=None, status="In development", clouds=None):
    return {
        "id": item_id,
        "title": title,
        "description": "<p>Description <b>courte</b> &amp; utile.</p><h3>Availability</h3><table><tr><td>x</td></tr></table>",
        "publicDisclosureAvailabilityDate": "January CY2027",
        "publicPreviewDate": "",
        "created": created,
        "modified": modified or created,
        "status": status,
        "tagsContainer": {
            "products": [{"tagName": p} for p in products],
            "cloudInstances": [{"tagName": c} for c in (clouds or ["Worldwide (Standard Multi-Tenant)"])],
            "releasePhase": [{"tagName": "Preview"}],
        },
    }


ROADMAP = [
    roadmap_item(570672, "Work IQ: Human in the loop", ["Work IQ"], "2026-10-19T10:00:00"),
    roadmap_item(570845, "Microsoft Purview: Data Loss Prevention for Microsoft Cowork", ["Microsoft Purview"],
                 "2026-09-08T10:00:00", "2026-10-20T10:00:00", status="Rolling out"),
    roadmap_item(571305, "Microsoft Copilot Studio: Support for sensitive documents", ["Microsoft Copilot Studio"],
                 "2026-10-22T10:00:00"),
    roadmap_item(1, "Dynamics 365 Sales: Lead management - agents", ["Microsoft Copilot (Microsoft 365)", "Dynamics 365 Sales"],
                 "2026-10-23T10:00:00"),
    roadmap_item(2, "Microsoft Copilot (Microsoft 365): Old item", ["Microsoft Copilot (Microsoft 365)"],
                 "2026-01-10T10:00:00", "2026-09-01T10:00:00"),
    roadmap_item(3, "Microsoft Copilot (Microsoft 365): GCC only", ["Microsoft Copilot (Microsoft 365)"],
                 "2026-10-23T10:00:00", clouds=["GCC"]),
    roadmap_item(4, "Excel: Pivot tables", ["Excel"], "2026-10-23T10:00:00"),
]


def cleanup_reports(report_type):
    db = SessionLocal()
    ids = [row[0] for row in db.query(models.Report.id).filter(models.Report.report_type == report_type).all()]
    db.close()
    client = TestClient(main.app)
    for report_id in ids:  # route API : supprime aussi les news extraites
        client.delete(f"/reports/{report_id}")


@pytest.fixture
def copilot_env(monkeypatch):
    """LLM simulé, Roadmap simulée (aucun réseau), date figée, base nettoyée."""
    cleanup_reports("copilot_watch")
    prompts = []

    def fake_generate(prompt, timeout_seconds=0, web_search=False):
        prompts.append((prompt, web_search))
        return COPILOT_REPORT

    monkeypatch.setattr(main, "ensure_llm_ready", lambda: None)
    monkeypatch.setattr(main, "generate_llm_content", fake_generate)
    monkeypatch.setattr(main, "today_paris", lambda: "2099-05-10")
    monkeypatch.setattr(m365_roadmap, "fetch_roadmap_items", lambda client=None, errors=None: list(ROADMAP))
    yield prompts
    cleanup_reports("copilot_watch")


def copilot_prompt(**kwargs):
    db = SessionLocal()
    try:
        return main.build_copilot_prompt(db, now=NOW, **kwargs)
    finally:
        db.close()


# --- Prompt ------------------------------------------------------------------------------


def test_copilot_prompt_window_and_sources():
    prompt = copilot_prompt(roadmap_items=[])
    assert prompt.startswith("Date du jour : 2026-10-26.")
    assert "du 2026-10-19 08:00 au 2026-10-26 08:00" in prompt
    for source in (
        "microsoft-365/roadmap",
        "learn.microsoft.com/microsoft-365/copilot/release-notes",
        "learn.microsoft.com/microsoft-copilot-studio/whats-new",
        "microsoft.com/microsoft-365/blog",
        "techcommunity.microsoft.com",
        "learn.microsoft.com/microsoft-iq",
        "learn.microsoft.com/microsoft-365/copilot/cowork",
    ):
        assert source in prompt, source
    for product in ("Microsoft 365 Copilot", "Copilot Studio", "Work IQ", "Copilot Cowork"):
        assert product in prompt
    for field in ("**Identifiant Roadmap**", "**Statut**", "**Licence requise**", "**Disponibilité UE / tenant FR**",
                  "**Impact admin M365**", "**Maturité**", "**Source**"):
        assert field in prompt
    assert "Éléments du Microsoft 365 Roadmap" not in prompt


def test_copilot_prompt_keeps_report_structure():
    output_format = main.COPILOT_WATCH_PROMPT.split("# Format de sortie obligatoire", 1)[1]
    headings = [line for line in output_format.splitlines() if line.startswith("## ")]
    technical = [
        line for line in main.TECHNICAL_PROMPT.split("# Format de sortie obligatoire", 1)[1].splitlines()
        if line.startswith("## ")
    ]
    assert headings == technical  # même structure : vue structurée, news, newsletter et PDF s'appliquent
    assert "### À tester maintenant" in output_format and "### <Titre court de la nouveauté>" in output_format


def test_daily_prompt_is_unchanged():
    db = SessionLocal()
    try:
        prompt = main.build_technical_prompt(db, now=NOW, reddit_posts=[])
    finally:
        db.close()
    assert prompt.startswith("Date du jour : 2026-10-26. Période couverte : du 2026-10-25 08:00 au 2026-10-26 08:00")
    assert "Microsoft 365 Roadmap" not in prompt and "COPILOT" not in prompt


def test_already_covered_is_filtered_by_report_type(copilot_env):
    db = SessionLocal()
    try:
        daily = models.Report(date="2099-05-01", report_type="technical_watch",
                              content="## Nouveautés détaillées\n### Sujet de la veille quotidienne\n- **Maturité** : GA\n")
        copilot = models.Report(date="2099-05-01", report_type="copilot_watch", content=COPILOT_REPORT)
        db.add_all([daily, copilot])
        db.commit()
        main.sync_news_items(db, daily)
        main.sync_news_items(db, copilot)
        daily_id = daily.id
        prompt = main.build_copilot_prompt(db, now=NOW, roadmap_items=[])
        technical = main.build_technical_prompt(db, now=NOW, reddit_posts=[])
    finally:
        db.close()
        TestClient(main.app).delete(f"/reports/{daily_id}")
    covered = prompt.split("# Déjà couvert dans les rapports précédents", 1)[1]
    assert "Work IQ : validation humaine des actions d’agents (2099-05-01)" in covered
    assert "Sujet de la veille quotidienne" not in prompt
    assert "Work IQ : validation humaine" not in technical


# --- Roadmap -----------------------------------------------------------------------------


def test_roadmap_filter_keeps_copilot_scope_in_window():
    items = m365_roadmap.filter_copilot_items(ROADMAP, UTC_NOW - timedelta(days=7), UTC_NOW)
    assert [i["id"] for i in items] == [571305, 570672, 570845]  # nouveaux d'abord, puis mis à jour
    first = items[0]
    assert first["change"] == "nouvel élément" and items[2]["change"] == "mis à jour"
    assert first["url"] == "https://www.microsoft.com/microsoft-365/roadmap?id=571305"
    assert first["description"] == "Description courte & utile."


def test_roadmap_section_in_prompt():
    items = m365_roadmap.filter_copilot_items(ROADMAP, UTC_NOW - timedelta(days=7), UTC_NOW)
    prompt = copilot_prompt(roadmap_items=items)
    section = prompt.split("# Éléments du Microsoft 365 Roadmap créés ou modifiés pendant la période", 1)[1]
    assert "- Work IQ: Human in the loop — ID 570672, nouvel élément, statut In development, phase Preview, " \
           "date prévue January CY2027, modifié le 2026-10-19, https://www.microsoft.com/microsoft-365/roadmap?id=570672" in section
    assert not any(line.startswith("## ") for line in section.splitlines())


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(503),
        lambda request: httpx.Response(200, text="<html>pas du json"),
        lambda request: httpx.Response(200, json={"error": "inattendu"}),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout", request=request)),
    ],
    ids=["503", "invalid-json", "not-a-list", "timeout"],
)
def test_roadmap_errors_return_empty_list(handler):
    errors = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert m365_roadmap.fetch_roadmap_items(client=client, errors=errors) == []
    assert errors and "Roadmap indisponible" in errors[0]


def test_roadmap_can_be_disabled(monkeypatch):
    monkeypatch.setenv("COPILOT_ROADMAP_ENABLED", "false")
    monkeypatch.setattr(m365_roadmap, "fetch_roadmap_items", lambda **kw: pytest.fail("aucune requête attendue"))
    assert m365_roadmap.collect_copilot_roadmap(UTC_NOW - timedelta(days=7), UTC_NOW) == []


# --- Génération, endpoints, cron ---------------------------------------------------------


def test_trigger_creates_copilot_watch_with_news(copilot_env):
    client = TestClient(main.app)
    response = client.post("/reports/copilot/trigger")
    assert response.status_code == 200
    report = response.json()
    assert report["report_type"] == "copilot_watch" and report["date"] == "2099-05-10"

    prompt, web_search = copilot_env[0]
    assert web_search is True
    assert "Microsoft 365 Roadmap créés ou modifiés" in prompt  # Roadmap simulée injectée

    news = client.get(f"/reports/{report['id']}/news").json()
    assert [n["title"] for n in news] == ["Work IQ : validation humaine des actions d’agents", "DLP Purview pour Copilot Cowork"]
    assert news[0]["maturity"] == "bêta"


def test_trigger_returns_409_when_generation_running(copilot_env):
    assert main.WATCH_GENERATION_LOCK.acquire(blocking=False)
    try:
        assert TestClient(main.app).post("/reports/copilot/trigger").status_code == 409
        assert TestClient(main.app).post("/cron/copilot-weekly").status_code == 409
    finally:
        main.WATCH_GENERATION_LOCK.release()
    assert copilot_env == []


def test_weekly_cron_does_not_regenerate_within_7_days(copilot_env, monkeypatch):
    client = TestClient(main.app)
    first = client.post("/cron/copilot-weekly").json()
    assert first["created"] is True and first["newsletter_url"] == f"/reports/{first['report_id']}/newsletter"

    monkeypatch.setattr(main, "today_paris", lambda: "2099-05-16")  # J+6 : encore dans la semaine
    second = client.post("/cron/copilot-weekly").json()
    assert second["created"] is False and second["report_id"] == first["report_id"]

    monkeypatch.setattr(main, "today_paris", lambda: "2099-05-17")  # J+7 : nouvelle semaine
    third = client.post("/cron/copilot-weekly").json()
    assert third["created"] is True and third["report_id"] != first["report_id"]

    forced = client.post("/cron/copilot-weekly", params={"force": True}).json()
    assert forced["created"] is True
    assert len(copilot_env) == 3

    # La veille quotidienne n'est pas concernée : /cron/daily ignore les copilot_watch.
    monkeypatch.setattr(main, "generate_llm_content", lambda prompt, timeout_seconds=0, web_search=False: "## TL;DR\n- ok\n")
    daily = client.post("/cron/daily").json()
    assert daily["created"] is True
    client.delete(f"/reports/{daily['report_id']}")


# --- Exports et chat ---------------------------------------------------------------------


def test_pdf_newsletter_and_chat_work_on_copilot_report(copilot_env, monkeypatch):
    client = TestClient(main.app)
    report = client.post("/reports/copilot/trigger").json()

    pdf = client.get(f"/reports/{report['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert b"Veille Microsoft Copilot" in pdf.content  # titre du document

    newsletter = client.get(f"/reports/{report['id']}/newsletter")
    assert newsletter.status_code == 200
    assert "Veille Microsoft Copilot" in newsletter.text

    captured = {}

    def fake_chat(prompt, timeout_seconds=0, web_search=False):
        captured["prompt"] = prompt
        return "Réponse (Rapport 1 · Nouveautés détaillées)"

    monkeypatch.setattr(main, "generate_llm_content", fake_chat)
    answer = client.post("/chat", json={"question": "Quoi de neuf sur Work IQ ?", "report_ids": [report["id"]], "persist": False})
    assert answer.status_code == 200
    assert f"## Rapport {report['id']} · Veille Microsoft Copilot du 2099-05-10" in captured["prompt"]
    assert "Work IQ : validation humaine" in captured["prompt"]


def test_newsletter_mail_constraints_on_copilot_report():
    """Mêmes contraintes que test_newsletter.py, appliquées au rendu d'un rapport copilot_watch."""
    report = models.Report(date="2099-05-10", report_type="copilot_watch", content=COPILOT_REPORT)
    html = main.render_report_newsletter(report)
    assert html.startswith("<table")
    for forbidden in ("<!DOCTYPE", "<html", "<head", "<body", "<style", "<div", "<strong", "<em>", "class=", "border-left", "background:"):
        assert forbidden.lower() not in html.lower(), forbidden
    assert all(ord(char) < 128 for char in html), "caractères non ASCII restants"
    for color in re.findall(r'bgcolor="(#[0-9a-fA-F]{6})"', html):
        assert f"background-color:{color}" in html
    assert 'width="720"' in html
    assert "La veille Microsoft Copilot" in html
    assert "DLP Purview pour Copilot Cowork" in html
    assert "Work IQ" in html
