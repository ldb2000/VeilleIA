from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app, extract_news_items, sync_news_items

SAMPLE_REPORT = """## TL;DR
- Point clé

## Radar décisionnel

### À tester maintenant
- Outil A

## Nouveautés détaillées

### **Outil A** passe en GA
- Ce qui sort : la version stable
- **Maturité** : GA
- Action recommandée : tester

### Modèle B open-weight
- Ce qui sort : un modèle
- Maturité – bêta

## Signaux faibles & recherche
- ### pas une nouveauté
"""


def test_extract_news_items_reads_detailed_section_only():
    items = extract_news_items(SAMPLE_REPORT)
    assert [item["title"] for item in items] == ["Outil A passe en GA", "Modèle B open-weight"]
    assert items[0]["maturity"] == "GA"
    assert items[1]["maturity"] == "bêta"
    assert items[0]["position"] == 0 and items[1]["position"] == 1
    assert "Action recommandée" in items[0]["content"]
    assert "Signaux" not in items[1]["content"]


def test_extract_news_items_handles_missing_section():
    assert extract_news_items("## TL;DR\n- rien") == []
    assert extract_news_items("") == []


def test_news_are_saved_and_survive_report_deletion():
    client = TestClient(app)
    db = SessionLocal()
    try:
        report = models.Report(date="2026-10-23", report_type="technical_watch", content=SAMPLE_REPORT)
        db.add(report)
        db.commit()
        db.refresh(report)
        sync_news_items(db, report)
        sync_news_items(db, report)  # idempotent
        report_id = report.id
    finally:
        db.close()

    news = client.get(f"/reports/{report_id}/news").json()
    assert len(news) == 2
    assert news[0]["report_date"] == "2026-10-23"
    assert news[0]["saved"] is False

    saved = client.patch(f"/news/{news[0]['id']}", json={"saved": True}).json()
    assert saved["saved"] is True and saved["saved_at"]

    saved_list = client.get("/news", params={"saved": True}).json()
    assert news[0]["id"] in [item["id"] for item in saved_list]

    assert client.delete(f"/reports/{report_id}").status_code == 204
    remaining = client.get("/news", params={"report_id": report_id}).json()
    assert [item["id"] for item in remaining] == [news[0]["id"]]

    client.patch(f"/news/{news[0]['id']}", json={"saved": False})
    assert client.patch("/news/999999", json={"saved": True}).status_code == 404
