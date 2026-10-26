import smtplib

import pytest
from fastapi.testclient import TestClient

from app import mailer, main, models
from app.database import SessionLocal

PASSWORD = "s3cr3t-Pa55word!"
REPORT = """## TL;DR
- Un modèle sort

## Nouveautés détaillées
### OpenAI publie un modèle
- **Ce qui sort** : un modèle
- **Maturité** : GA
"""


class FakeSMTP:
    """Remplace smtplib.SMTP / SMTP_SSL : enregistre les appels, n'ouvre aucune connexion."""

    instances: list = []
    fail_with: Exception | None = None
    refuse: dict = {}

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.ssl = context is not None
        self.calls = []
        self.messages = []
        FakeSMTP.instances.append(self)
        if FakeSMTP.fail_with is not None and isinstance(FakeSMTP.fail_with, OSError):
            raise FakeSMTP.fail_with

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if isinstance(FakeSMTP.fail_with, smtplib.SMTPAuthenticationError):
            raise FakeSMTP.fail_with

    def send_message(self, message, from_addr=None, to_addrs=None):
        if isinstance(FakeSMTP.fail_with, smtplib.SMTPException) and not isinstance(
            FakeSMTP.fail_with, smtplib.SMTPAuthenticationError
        ):
            raise FakeSMTP.fail_with
        self.calls.append(("send", from_addr, tuple(to_addrs)))
        self.messages.append(message)
        return dict(FakeSMTP.refuse)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.fail_with = None
    FakeSMTP.refuse = {}
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def mail_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "veille@example.org")
    monkeypatch.setenv("SMTP_PASSWORD", PASSWORD)
    monkeypatch.setenv("SMTP_STARTTLS", "true")
    monkeypatch.delenv("SMTP_SSL", raising=False)
    monkeypatch.setenv("MAIL_FROM", "Veille IA <veille@example.org>")
    monkeypatch.setenv("MAIL_TO", "alice@example.org, Bob <bob@example.org>,alice@example.org, pas-une-adresse")
    monkeypatch.setenv("MAIL_AUTO_SEND", "false")


@pytest.fixture
def report():
    db = SessionLocal()
    item = models.Report(date="2099-02-03", report_type="technical_watch", content=REPORT)
    db.add(item)
    db.commit()
    db.refresh(item)
    report_id = item.id
    db.close()
    yield report_id
    TestClient(main.app).delete(f"/reports/{report_id}")  # route API : nettoie aussi news et notes


def sent_at(report_id):
    db = SessionLocal()
    try:
        return db.query(models.Report).filter(models.Report.id == report_id).first().newsletter_sent_at
    finally:
        db.close()


# --- mailer ------------------------------------------------------------------------------


def test_config_from_env(mail_env):
    config = mailer.load_mail_config()
    assert config.configured
    assert config.host == "smtp.example.org" and config.port == 587
    assert config.starttls and not config.use_ssl
    assert config.recipients == ["alice@example.org", "bob@example.org"]
    assert PASSWORD not in repr(config)


def test_config_missing_fields(monkeypatch):
    # conftest vide déjà SMTP_HOST, MAIL_FROM, MAIL_TO.
    config = mailer.load_mail_config()
    assert not config.configured
    assert config.missing == ["SMTP_HOST", "MAIL_FROM", "MAIL_TO"]
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP_USER", "u@example.org")
    monkeypatch.setenv("MAIL_TO", "a@example.org")
    config = mailer.load_mail_config()
    assert config.sender == "u@example.org"  # MAIL_FROM par défaut : SMTP_USER
    assert config.missing == ["SMTP_PASSWORD"]


def test_port_465_uses_implicit_ssl(mail_env, monkeypatch, smtp):
    monkeypatch.setenv("SMTP_PORT", "465")
    mailer.send_html_email("Sujet", "<table><tr><td>x</td></tr></table>")
    server = smtp.instances[0]
    assert server.ssl and server.port == 465
    assert "starttls" not in server.calls


def test_send_builds_multipart_alternative(mail_env, smtp):
    delivered = mailer.send_html_email(
        "Veille IA – 2099-02-03", "<table><tr><td>Caf&eacute; &amp; IA</td></tr></table>"
    )
    assert delivered == ["alice@example.org", "bob@example.org"]
    server = smtp.instances[0]
    assert (server.host, server.port, server.timeout) == ("smtp.example.org", 587, 30.0)
    assert server.calls[0] == "starttls"
    assert server.calls[1] == ("login", "veille@example.org", PASSWORD)
    assert server.calls[2] == ("send", "veille@example.org", ("alice@example.org", "bob@example.org"))

    message = server.messages[0]
    assert message["Subject"] == "Veille IA – 2099-02-03"
    assert message["From"] == "Veille IA <veille@example.org>"
    assert message["To"] == "alice@example.org, bob@example.org"
    assert message.get_content_type() == "multipart/alternative"
    parts = list(message.iter_parts())
    assert [part.get_content_type() for part in parts] == ["text/plain", "text/html"]
    assert parts[0].get_content().strip() == "Café & IA"
    assert "<table>" in parts[1].get_content()
    assert PASSWORD not in message.as_string()


def test_send_without_config_raises_clear_error(smtp):
    with pytest.raises(mailer.MailNotConfigured, match="SMTP_HOST, MAIL_FROM, MAIL_TO"):
        mailer.send_html_email("s", "<table></table>")
    assert smtp.instances == []


@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials"),
        smtplib.SMTPRecipientsRefused({"alice@example.org": (550, b"no")}),
        ConnectionRefusedError(111, "Connection refused"),
        TimeoutError("timed out"),
    ],
    ids=["auth", "refused", "connection", "timeout"],
)
def test_send_errors_never_leak_password(mail_env, smtp, capsys, error):
    smtp.fail_with = error
    with pytest.raises(mailer.MailSendError) as info:
        mailer.send_html_email("s", "<table></table>")
    assert PASSWORD not in str(info.value)
    assert PASSWORD not in capsys.readouterr().out


# --- API ---------------------------------------------------------------------------------


def test_mail_info_never_returns_password_or_addresses(mail_env):
    body = TestClient(main.app).get("/mail/info").json()
    assert body["configured"] is True
    assert body["sender"] == "Veille IA <veille@example.org>"
    assert body["recipients_count"] == 2
    assert body["security"] == "starttls" and body["authenticated"] is True
    raw = str(body)
    assert PASSWORD not in raw and "alice@" not in raw


def test_mail_info_unconfigured():
    body = TestClient(main.app).get("/mail/info").json()
    assert body["configured"] is False
    assert body["missing"] == ["SMTP_HOST", "MAIL_FROM", "MAIL_TO"]


def test_mail_endpoints_require_token(monkeypatch, report):
    monkeypatch.setattr(main, "API_TOKEN", "secret")
    client = TestClient(main.app)
    assert client.get("/mail/info").status_code == 401
    assert client.post(f"/reports/{report}/send").status_code == 401
    assert client.get("/mail/info", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_send_endpoint_sends_newsletter_and_marks_report(mail_env, smtp, report, capsys):
    response = TestClient(main.app).post(f"/reports/{report}/send")
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "Veille IA – 2099-02-03"
    assert body["recipients_count"] == 2
    assert body["newsletter_sent_at"]
    assert sent_at(report) is not None

    message = smtp.instances[0].messages[0]
    html = message.get_body(("html",)).get_content()
    assert html.startswith("<!doctype html>") and "<table" in html
    assert "OpenAI publie un modèle" in message.get_body(("plain",)).get_content()  # texte = markdown du rapport
    assert PASSWORD not in capsys.readouterr().out

    listed = TestClient(main.app).get(f"/reports/{report}").json()
    assert listed["newsletter_sent_at"]


def test_send_endpoint_errors(smtp, report, mail_env, monkeypatch):
    client = TestClient(main.app)
    assert client.post("/reports/999999/send").status_code == 404
    smtp.fail_with = smtplib.SMTPAuthenticationError(535, b"bad")
    failed = client.post(f"/reports/{report}/send")
    assert failed.status_code == 502 and PASSWORD not in failed.text
    assert sent_at(report) is None
    smtp.fail_with = None
    monkeypatch.setenv("SMTP_HOST", "")
    unconfigured = client.post(f"/reports/{report}/send")
    assert unconfigured.status_code == 503
    assert "SMTP_HOST" in unconfigured.json()["detail"]


# --- Cron --------------------------------------------------------------------------------


@pytest.fixture
def cron_env(monkeypatch):
    monkeypatch.setattr(main, "ensure_llm_ready", lambda: None)
    monkeypatch.setattr(main, "generate_llm_content", lambda prompt, timeout_seconds=0, web_search=False: REPORT)
    monkeypatch.setattr(main, "today_paris", lambda: "2099-03-04")
    yield
    db = SessionLocal()
    ids = [row[0] for row in db.query(models.Report.id).filter(models.Report.date == "2099-03-04").all()]
    db.close()
    client = TestClient(main.app)
    for report_id in ids:  # route API : supprime aussi les news extraites du rapport
        client.delete(f"/reports/{report_id}")


def test_cron_auto_send_only_once(mail_env, smtp, cron_env, monkeypatch):
    monkeypatch.setenv("MAIL_AUTO_SEND", "true")
    client = TestClient(main.app)
    first = client.post("/cron/daily").json()
    assert first["created"] is True and first["mail_sent"] is True and first["mail_error"] is None
    second = client.post("/cron/daily").json()
    assert second["created"] is False and second["mail_sent"] is False and second["mail_error"] is None
    assert len(smtp.instances) == 1
    assert sent_at(first["report_id"]) is not None


def test_cron_retries_send_after_failure(mail_env, smtp, cron_env, monkeypatch):
    monkeypatch.setenv("MAIL_AUTO_SEND", "true")
    smtp.fail_with = ConnectionRefusedError(111, "Connection refused")
    client = TestClient(main.app)
    first = client.post("/cron/daily").json()
    assert first["created"] is True and first["mail_sent"] is False
    assert "Connection refused" in first["mail_error"] and PASSWORD not in first["mail_error"]
    smtp.fail_with = None
    second = client.post("/cron/daily").json()  # rappel du cron : la veille existe, l'envoi est retenté
    assert second["created"] is False and second["mail_sent"] is True


def test_cron_without_auto_send_or_config(smtp, cron_env, monkeypatch):
    client = TestClient(main.app)
    first = client.post("/cron/daily").json()  # MAIL_AUTO_SEND=false (conftest)
    assert first["mail_sent"] is False and first["mail_error"] is None
    monkeypatch.setenv("MAIL_AUTO_SEND", "true")  # mais pas de config SMTP
    second = client.post("/cron/daily").json()
    assert second["mail_sent"] is False and "SMTP_HOST" in second["mail_error"]
    assert smtp.instances == []
