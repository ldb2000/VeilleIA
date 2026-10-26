"""Envoi d'emails HTML par SMTP (newsletter de veille).

Module autonome (pas de dépendance à l'application). La configuration est lue dans
l'environnement à chaque appel :
SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_STARTTLS (true),
SMTP_SSL (true si le port vaut 465), SMTP_TIMEOUT_SECONDS (30),
MAIL_FROM (défaut : SMTP_USER), MAIL_TO (adresses séparées par des virgules).

Le mot de passe n'est jamais renvoyé (describe_mail_config) ni écrit dans les logs.
"""

import os
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from html import unescape
from typing import Optional


class MailNotConfigured(RuntimeError):
    """Configuration SMTP absente ou incomplète."""


class MailSendError(RuntimeError):
    """Échec de l'envoi (connexion, authentification, refus du serveur…)."""


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _env_flag(name: str, default: bool) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def parse_recipients(raw: str) -> list[str]:
    recipients = []
    for item in (raw or "").split(","):
        address = parseaddr(item.strip())[1]
        if address and "@" in address and address not in recipients:
            recipients.append(address)
    return recipients


@dataclass
class MailConfig:
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = field(default="", repr=False)  # jamais affiché, même dans un repr
    starttls: bool = True
    use_ssl: bool = False
    timeout: float = 30.0
    sender: str = ""
    recipients: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        missing = []
        if not self.host:
            missing.append("SMTP_HOST")
        if not self.sender:
            missing.append("MAIL_FROM")
        if not self.recipients:
            missing.append("MAIL_TO")
        if self.user and not self.password:
            missing.append("SMTP_PASSWORD")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing


def load_mail_config() -> MailConfig:
    try:
        port = int(_env("SMTP_PORT") or 587)
    except ValueError:
        print("Mail : SMTP_PORT invalide, 587 utilisé")
        port = 587
    try:
        timeout = float(_env("SMTP_TIMEOUT_SECONDS") or 30)
    except ValueError:
        timeout = 30.0
    user = _env("SMTP_USER")
    return MailConfig(
        host=_env("SMTP_HOST"),
        port=port,
        user=user,
        password=os.getenv("SMTP_PASSWORD") or "",
        starttls=_env_flag("SMTP_STARTTLS", True),
        use_ssl=_env_flag("SMTP_SSL", port == 465),
        timeout=timeout,
        sender=_env("MAIL_FROM") or user,
        recipients=parse_recipients(_env("MAIL_TO")),
    )


def mail_auto_send() -> bool:
    return _env_flag("MAIL_AUTO_SEND", False)


def describe_mail_config(config: Optional[MailConfig] = None) -> dict:
    """État de la configuration, sans le mot de passe ni la liste des destinataires."""
    config = config or load_mail_config()
    return {
        "configured": config.configured,
        "missing": config.missing,
        "host": config.host or None,
        "port": config.port,
        "security": "ssl" if config.use_ssl else ("starttls" if config.starttls else "none"),
        "authenticated": bool(config.user),
        "sender": config.sender or None,
        "recipients_count": len(config.recipients),
        "auto_send": mail_auto_send(),
    }


def html_to_text(html: str) -> str:
    """Version texte de secours d'un HTML (pour les clients qui n'affichent pas le HTML)."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|h[1-6]|li|table)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def build_message(subject: str, html: str, recipients: list[str], sender: str, text: Optional[str] = None) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Date"] = formatdate(localtime=True)
    domain = parseaddr(sender)[1].rpartition("@")[2] or None
    message["Message-ID"] = make_msgid(domain=domain)
    # multipart/alternative : texte brut d'abord, HTML ensuite (préféré par les clients).
    message.set_content(text or html_to_text(html), subtype="plain", charset="utf-8")
    message.add_alternative(html, subtype="html", charset="utf-8")
    return message


def send_html_email(
    subject: str,
    html: str,
    recipients: Optional[list[str]] = None,
    text: Optional[str] = None,
    config: Optional[MailConfig] = None,
) -> list[str]:
    """Envoie un email multipart/alternative (texte + HTML). Renvoie les destinataires.
    Lève MailNotConfigured si la configuration est incomplète, MailSendError si l'envoi échoue."""
    config = config or load_mail_config()
    if recipients is not None:
        config.recipients = parse_recipients(",".join(recipients))
    if not config.configured:
        raise MailNotConfigured("Envoi de mail non configuré : variable(s) manquante(s) " + ", ".join(config.missing) + ".")

    message = build_message(subject, html, config.recipients, config.sender, text)
    context = ssl.create_default_context()
    try:
        if config.use_ssl:
            server = smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout, context=context)
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
        with server:
            if not config.use_ssl and config.starttls:
                server.starttls(context=context)
            if config.user:
                server.login(config.user, config.password)
            refused = server.send_message(message, from_addr=parseaddr(config.sender)[1], to_addrs=config.recipients)
    except smtplib.SMTPAuthenticationError as e:
        raise MailSendError(f"Authentification SMTP refusée pour {config.user} (code {e.smtp_code}).") from None
    except (smtplib.SMTPException, OSError) as e:
        # Le message de ces exceptions ne contient jamais le mot de passe (seulement hôte / réponse serveur).
        raise MailSendError(f"Échec de l'envoi via {config.host}:{config.port} : {type(e).__name__}: {e}") from None

    delivered = [address for address in config.recipients if address not in (refused or {})]
    if not delivered:
        raise MailSendError("Tous les destinataires ont été refusés par le serveur SMTP.")
    print(f"Mail « {subject} » envoyé via {config.host}:{config.port} à {len(delivered)} destinataire(s)")
    return delivered
