"""Prompt de veille quotidienne et endpoint /chat, sans appel LLM réel."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import main, models
from app.database import SessionLocal
from app.main import app, build_technical_prompt, sync_news_items

REPORT = """## TL;DR
- ok

## Nouveautés détaillées

### Outil Z passe en GA
- **Maturité** : GA
- **Source** : [Changelog](https://example.com/z) — publié le 2026-10-23

## Signaux faibles & recherche
- rien
"""


def make_report(content=REPORT, date="2026-10-23"):
    db = SessionLocal()
    try:
        report = models.Report(date=date, report_type="technical_watch", content=content)
        db.add(report)
        db.commit()
        db.refresh(report)
        sync_news_items(db, report)
        return report.id
    finally:
        db.close()


def test_technical_prompt_has_date_method_and_already_covered():
    report_id = make_report()
    db = SessionLocal()
    try:
        prompt = build_technical_prompt(db, now=datetime(2026, 10, 24, 8, 0))
    finally:
        db.close()
    assert prompt.startswith("Date du jour : 2026-10-24.")
    assert "du 2026-10-23 08:00 au 2026-10-24 08:00" in prompt
    assert "Méthode de recherche" in prompt
    assert "**Source**" in prompt
    assert "Déjà couvert" in prompt
    assert "Outil Z passe en GA (2026-10-23)" in prompt
    TestClient(app).delete(f"/reports/{report_id}")


def test_extract_news_items_reads_labelled_maturity():
    items = main.extract_news_items(REPORT)
    assert items[0]["maturity"] == "GA"


def test_chat_sends_full_report_history_and_persists_on_success(monkeypatch):
    long_tail = "\n".join(f"- ligne {i}" for i in range(600))
    report_id = make_report(REPORT + "\n" + long_tail + "\n- MARQUEUR_FIN")
    captured = {}

    def fake_generate(prompt, timeout_seconds=0, web_search=False):
        captured.update(prompt=prompt, web_search=web_search)
        return "Réponse (Rapport %d · Nouveautés détaillées)" % report_id

    monkeypatch.setattr(main, "generate_llm_content", fake_generate)
    monkeypatch.setattr(main, "ensure_llm_ready", lambda: None)
    client = TestClient(app)
    before = len(client.get("/chat/messages").json())

    response = client.post(
        "/chat",
        json={
            "question": "Et pour Azure ?",
            "report_ids": [report_id],
            "history": [
                {"role": "user", "content": "Quoi de neuf sur Z ?"},
                {"role": "assistant", "content": "Z passe en GA."},
            ],
        },
    )
    assert response.status_code == 200
    assert "MARQUEUR_FIN" in captured["prompt"]  # plus de troncature à 3 500 caractères
    assert "Utilisateur : Quoi de neuf sur Z ?" in captured["prompt"]
    assert "(Rapport <id> · <section>)" in captured["prompt"]
    assert captured["web_search"] is False
    messages = client.get("/chat/messages").json()
    assert len(messages) == before + 2
    assert messages[-1]["report_ids"] == [report_id]

    # persist=False : n'apparaît pas dans l'historique (synthèses du tableau de bord).
    client.post("/chat", json={"question": "Synthèse", "report_ids": [report_id], "persist": False})
    assert len(client.get("/chat/messages").json()) == before + 2

    # Échec du LLM : rien n'est enregistré.
    def boom(*args, **kwargs):
        raise RuntimeError("panne")

    monkeypatch.setattr(main, "generate_llm_content", boom)
    assert client.post("/chat", json={"question": "x", "report_ids": [report_id]}).status_code == 500
    assert len(client.get("/chat/messages").json()) == before + 2
    client.delete(f"/reports/{report_id}")


def test_chat_web_search_requires_capable_provider(monkeypatch):
    report_id = make_report()
    monkeypatch.setattr(main, "ensure_llm_ready", lambda: None)
    captured = {}

    def fake_generate(prompt, timeout_seconds=0, web_search=False):
        captured.update(prompt=prompt, web_search=web_search)
        return "ok"

    monkeypatch.setattr(main, "generate_llm_content", fake_generate)
    client = TestClient(app)

    monkeypatch.setattr(main, "llm_supports_web_search", lambda: False)
    payload = {"question": "Alertes ?", "report_ids": [report_id], "web_search": True, "persist": False}
    assert client.post("/chat", json=payload).status_code == 400

    monkeypatch.setattr(main, "llm_supports_web_search", lambda: True)
    assert client.post("/chat", json=payload).status_code == 200
    assert captured["web_search"] is True
    assert "Sur le web" in captured["prompt"]
    client.delete(f"/reports/{report_id}")


def test_llm_info_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_WEB_SEARCH", "false")
    info = TestClient(app).get("/llm/info").json()
    assert info["provider"] == "openrouter"
    assert info["web_search"] is False



def test_trigger_and_codir_run_as_background_jobs(monkeypatch, wait_job):
    monkeypatch.setattr(main, "ensure_llm_ready", lambda: None)
    monkeypatch.setattr(main, "generate_llm_content", lambda prompt, timeout_seconds=0, web_search=False: REPORT)
    client = TestClient(app)

    response = client.post("/reports/trigger")
    assert response.status_code == 202 and response.json()["kind"] == "technical_watch"
    watch = wait_job(client, response.json())
    assert watch["status"] == "done"
    assert client.get(f"/reports/{watch['report_id']}").json()["report_type"] == "technical_watch"
    # Le verrou est libéré à la fin de la tâche.
    assert main.WATCH_GENERATION_LOCK.acquire(blocking=False)
    main.WATCH_GENERATION_LOCK.release()

    assert client.post("/reports/999999/codir").status_code == 404
    codir = wait_job(client, client.post(f"/reports/{watch['report_id']}/codir").json())
    assert codir["status"] == "done"

    def boom(*args, **kwargs):
        raise RuntimeError("LLM indisponible")

    monkeypatch.setattr(main, "generate_llm_content", boom)
    failed = wait_job(client, client.post("/reports/trigger").json())
    assert failed["status"] == "error" and "LLM indisponible" in failed["error"]
    assert client.get("/jobs/inconnu").status_code == 404

    for report_id in (watch["report_id"], codir["report_id"]):
        client.delete(f"/reports/{report_id}")
