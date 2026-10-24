"""Rendu d'un rapport de veille en newsletter HTML compatible clients mail (Gmail, Outlook).

Contraintes (cf. tâche Cowork d'origine) :
- pas de <!DOCTYPE>, <html>, <head>, <body> ni <style> : le HTML commence par <table> ;
- mise en page 100 % en tables, styles inline uniquement, aucune classe CSS ;
- toute couleur de fond doublée : attribut bgcolor ET style background-color ;
- barres latérales en cellule dédiée de 4px, jamais border-left ;
- caractères non ASCII convertis en entités HTML ;
- <b> / <i> plutôt que <strong> / <em> ; largeur fixe 720px.

Le rendu est déterministe (pas de LLM) : il part du markdown produit par TECHNICAL_PROMPT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from html.entities import codepoint2name
from typing import Optional

# ---------------------------------------------------------------------------
# Charte
# ---------------------------------------------------------------------------

FONT = "Arial,Helvetica,sans-serif"
OUTER_BG = "#f4f6f8"
INNER_BG = "#ffffff"
HEADER_BG = "#0f2740"
HEADER_KICKER = "#7fd1ff"
HEADER_SUBTITLE = "#9fb4c7"
SUMMARY_BG = "#eef4f9"
SECTION_RULE = "#2f8fd6"
SECURITY_BG = "#fdf5f4"
SECURITY_BAR = "#c0392b"
SECURITY_TITLE = "#8e2b21"
TABLE_ALT_BG = "#f7fafc"
TEXT = "#1f2d3a"
MUTED = "#5b6b7a"
BORDER = "#e3e8ee"
LINK = "#1a6fb5"

RADAR_COLORS = {
    "tester": "#1e8e3e",
    "surveiller": "#d98200",
    "ignorer": "#8a96a3",
}

# (nom affiché, couleur, motifs de détection)
ACTORS: list[tuple[str, str, tuple[str, ...]]] = [
    ("OpenAI", "#10a37f", ("openai", "chatgpt", "gpt-", "codex", "sora")),
    ("Anthropic", "#d97757", ("anthropic", "claude")),
    ("Google", "#4285f4", ("google", "gemini", "deepmind", "vertex", "gemma")),
    ("Mistral", "#fa520f", ("mistral", "codestral", "le chat")),
    ("NVIDIA", "#76b900", ("nvidia", "nemotron", "nim ")),
    ("AWS", "#ff9900", ("aws", "amazon", "bedrock", "nova ")),
    ("Microsoft", "#0078d4", ("microsoft", "azure", "copilot", "phi-", "github")),
]
OTHER_ACTOR = ("Autres", "#6b7785")


def detect_actor(*texts: str) -> tuple[str, str]:
    """Acteur principal d'une nouveauté : le premier repéré dans le titre, sinon dans le corps."""
    for text in texts:
        haystack = f" {text.lower()} "
        best: Optional[tuple[int, str, str]] = None
        for name, color, patterns in ACTORS:
            for pattern in patterns:
                index = haystack.find(pattern)
                if index >= 0 and (best is None or index < best[0]):
                    best = (index, name, color)
        if best:
            return best[1], best[2]
    return OTHER_ACTOR


# ---------------------------------------------------------------------------
# Encodage et markdown inline
# ---------------------------------------------------------------------------

def to_entities(text: str) -> str:
    """Remplace tout caractère non ASCII par une entité HTML (nommée si possible)."""
    out = []
    for char in text:
        code = ord(char)
        if code < 128:
            out.append(char)
        elif code in codepoint2name:
            out.append(f"&{codepoint2name[code]};")
        else:
            out.append(f"&#{code};")
    return "".join(out)


LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
BARE_URL_RE = re.compile(r"(?<![\"'=>])(https?://[^\s<)]+)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
ITALIC_RE = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
CODE_RE = re.compile(r"`([^`]+)`")


def inline(text: str) -> str:
    """Markdown inline (gras, italique, liens, code) vers HTML mail, échappé."""
    placeholders: list[str] = []

    def keep(html: str) -> str:
        placeholders.append(html)
        return f"\x00{len(placeholders) - 1}\x00"

    def link(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        return keep(
            f'<a href="{escape(url, quote=True)}" style="color:{LINK};text-decoration:underline;">'
            f"{escape(label)}</a>"
        )

    text = LINK_RE.sub(link, text)
    text = BARE_URL_RE.sub(
        lambda m: keep(
            f'<a href="{escape(m.group(1), quote=True)}" style="color:{LINK};text-decoration:underline;">'
            f"{escape(m.group(1))}</a>"
        ),
        text,
    )
    text = escape(text, quote=False)
    text = CODE_RE.sub(lambda m: f'<span style="font-family:Consolas,monospace;">{m.group(1)}</span>', text)
    text = BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = ITALIC_RE.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)


def plain(text: str) -> str:
    text = LINK_RE.sub(lambda m: m.group(1), text)
    return re.sub(r"(\*\*|__|\*|`)", "", text).strip()


# ---------------------------------------------------------------------------
# Parsing du rapport
# ---------------------------------------------------------------------------

@dataclass
class Subsection:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class Section:
    title: str
    lines: list[str] = field(default_factory=list)
    subsections: list[Subsection] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.title.lower()


def parse_sections(content: str) -> list[Section]:
    sections: list[Section] = []
    current: Optional[Section] = None
    sub: Optional[Subsection] = None
    for raw in (content or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            current = Section(title=plain(stripped[3:]))
            sections.append(current)
            sub = None
            continue
        if stripped.startswith("### "):
            if current is None:
                current = Section(title="")
                sections.append(current)
            sub = Subsection(title=plain(stripped[4:]))
            current.subsections.append(sub)
            continue
        if current is None:
            continue
        (sub.lines if sub else current.lines).append(line)
    return sections


def bullets(lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            items.append(stripped[2:].strip())
        elif stripped and items and not stripped.startswith("|"):
            items[-1] += " " + stripped
    return items


def paragraphs(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith(("- ", "* ", "|"))]


def table_rows(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
            continue
        rows.append(cells)
    return rows


FIELD_RE = re.compile(r"^\*{0,2}([^:*\[\]()]{2,48}?)\*{0,2}\s*[:：](?!//)\s*(.+)$")


def split_field(text: str) -> tuple[Optional[str], str]:
    match = FIELD_RE.match(text)
    if not match:
        return None, text
    return plain(match.group(1)), match.group(2).strip()


def find_section(sections: list[Section], *prefixes: str) -> Optional[Section]:
    for section in sections:
        if any(section.key.startswith(prefix) for prefix in prefixes):
            return section
    return None


# ---------------------------------------------------------------------------
# Briques HTML
# ---------------------------------------------------------------------------

def bg(color: str) -> str:
    return f'bgcolor="{color}" style="background-color:{color};'


def section_title(title: str, color: str = HEADER_BG, rule: str = SECTION_RULE) -> str:
    return (
        '<tr><td style="padding:28px 32px 8px 32px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="font-family:{FONT};font-size:19px;line-height:26px;font-weight:bold;color:{color};'
        f'padding-bottom:8px;">{escape(title)}</td></tr>'
        f'<tr><td height="3" {bg(rule)}height:3px;font-size:1px;line-height:1px;">&nbsp;</td></tr>'
        "</table></td></tr>"
    )


def bullet_rows(items: list[str], dot_color: str = SECTION_RULE, size: int = 14) -> str:
    rows = []
    for item in items:
        rows.append(
            "<tr>"
            f'<td width="18" valign="top" style="font-family:{FONT};font-size:{size}px;line-height:22px;'
            f'color:{dot_color};font-weight:bold;">&bull;</td>'
            f'<td style="font-family:{FONT};font-size:{size}px;line-height:22px;color:{TEXT};padding-bottom:6px;">'
            f"{inline(item)}</td></tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + "".join(rows)
        + "</table>"
    )


def body_cell(inner: str, padding: str = "8px 32px 0 32px") -> str:
    return f'<tr><td style="padding:{padding};">{inner}</td></tr>'


def render_header(report_date: str, kicker: str, title: str) -> str:
    try:
        date_label = datetime.strptime(report_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        date_label = report_date
    return (
        f'<tr><td {bg(HEADER_BG)}padding:28px 32px 26px 32px;">'
        f'<div style="font-family:{FONT};font-size:12px;letter-spacing:2px;text-transform:uppercase;'
        f'color:{HEADER_KICKER};font-weight:bold;">{escape(kicker)}</div>'
        f'<div style="font-family:{FONT};font-size:26px;line-height:32px;color:#ffffff;font-weight:bold;'
        f'padding-top:6px;">{escape(title)}</div>'
        f'<div style="font-family:{FONT};font-size:14px;color:{HEADER_SUBTITLE};padding-top:6px;">'
        f"Lecture technique &middot; {escape(date_label)} &middot; derni&egrave;res 24h</div>"
        "</td></tr>"
    )


def render_summary(items: list[str]) -> str:
    if not items:
        return ""
    return (
        '<tr><td style="padding:24px 32px 0 32px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td {bg(SUMMARY_BG)}padding:18px 20px 12px 20px;">'
        f'<div style="font-family:{FONT};font-size:13px;letter-spacing:1px;text-transform:uppercase;'
        f'font-weight:bold;color:{HEADER_BG};padding-bottom:10px;">Executive summary</div>'
        f"{bullet_rows(items, dot_color=HEADER_BG, size=15)}</td></tr>"
        f'<tr><td height="3" {bg(HEADER_BG)}height:3px;font-size:1px;line-height:1px;">&nbsp;</td></tr>'
        "</table></td></tr>"
    )


def radar_tone(title: str) -> str:
    lowered = title.lower()
    if "tester" in lowered:
        return RADAR_COLORS["tester"]
    if "surveiller" in lowered:
        return RADAR_COLORS["surveiller"]
    if "ignorer" in lowered:
        return RADAR_COLORS["ignorer"]
    return SECTION_RULE


def render_radar(section: Section) -> str:
    blocks = []
    for sub in section.subsections:
        items = bullets(sub.lines)
        if not items:
            continue
        color = radar_tone(sub.title)
        blocks.append(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="margin-bottom:12px;">'
            "<tr>"
            f'<td width="4" {bg(color)}width:4px;font-size:1px;">&nbsp;</td>'
            f'<td style="padding:4px 0 4px 14px;">'
            f'<div style="font-family:{FONT};font-size:14px;font-weight:bold;color:{color};padding-bottom:6px;">'
            f"{escape(sub.title)}</div>{bullet_rows(items, dot_color=color)}</td>"
            "</tr></table>"
        )
    if not blocks:
        return ""
    return section_title(section.title) + body_cell("".join(blocks), "14px 32px 0 32px")


@dataclass
class NewsCard:
    title: str
    actor: str
    color: str
    fields: list[tuple[Optional[str], str]]

    def field(self, *labels: str) -> str:
        for label, value in self.fields:
            if label and any(label.lower().startswith(wanted) for wanted in labels):
                return value
        return ""


def build_news_cards(section: Section) -> list[NewsCard]:
    cards = []
    for sub in section.subsections:
        items = bullets(sub.lines) + paragraphs(sub.lines)
        fields = [split_field(item) for item in items]
        actor, color = detect_actor(sub.title, " ".join(items))
        cards.append(NewsCard(title=sub.title, actor=actor, color=color, fields=fields))
    return cards


def render_news_card(card: NewsCard) -> str:
    rows = []
    for label, value in card.fields:
        if label:
            rows.append(
                f'<tr><td style="font-family:{FONT};font-size:14px;line-height:21px;color:{TEXT};padding-bottom:6px;">'
                f'<b style="color:{HEADER_BG};">{escape(label)}</b> &mdash; {inline(value)}</td></tr>'
            )
        else:
            rows.append(
                f'<tr><td style="font-family:{FONT};font-size:14px;line-height:21px;color:{TEXT};padding-bottom:6px;">'
                f"{inline(value)}</td></tr>"
            )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin-bottom:16px;border:1px solid {BORDER};">'
        "<tr>"
        f'<td width="4" {bg(card.color)}width:4px;font-size:1px;">&nbsp;</td>'
        '<td style="padding:14px 18px 10px 16px;">'
        f'<div style="font-family:{FONT};font-size:11px;letter-spacing:1px;text-transform:uppercase;'
        f'font-weight:bold;color:{card.color};">{escape(card.actor)}</div>'
        f'<div style="font-family:{FONT};font-size:17px;line-height:23px;font-weight:bold;color:{HEADER_BG};'
        f'padding:4px 0 10px 0;">{escape(card.title)}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + "".join(rows)
        + "</table></td></tr></table>"
    )


def render_news(section: Section, cards: list[NewsCard]) -> str:
    if not cards:
        return ""
    return section_title(section.title) + body_cell(
        "".join(render_news_card(card) for card in cards), "16px 32px 0 32px"
    )


def truncate(text: str, limit: int) -> str:
    text = plain(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_synthesis_table(cards: list[NewsCard]) -> str:
    if not cards:
        return ""
    headers = ["Acteur", "Nouveaut&eacute;", "Type", "Impact", "Maturit&eacute;", "Action"]
    head = "".join(
        f'<td {bg(HEADER_BG)}font-family:{FONT};font-size:12px;font-weight:bold;color:#ffffff;'
        f'padding:8px 8px;">{label}</td>'
        for label in headers
    )
    body = []
    for index, card in enumerate(cards):
        row_bg = TABLE_ALT_BG if index % 2 else INNER_BG
        cells = [
            f'<b style="color:{card.color};">{escape(card.actor)}</b>',
            escape(truncate(card.title, 70)),
            escape(truncate(card.field("type"), 30)),
            escape(truncate(card.field("pourquoi", "impact", "pour qui"), 110)),
            escape(truncate(card.field("maturit"), 30)),
            escape(truncate(card.field("action"), 110)),
        ]
        body.append(
            f'<tr {bg(row_bg)}">'
            + "".join(
                f'<td valign="top" style="font-family:{FONT};font-size:12px;line-height:17px;color:{TEXT};'
                f'padding:8px 8px;border-bottom:1px solid {BORDER};">{cell}</td>'
                for cell in cells
            )
            + "</tr>"
        )
    table = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border:1px solid {BORDER};"><tr>{head}</tr>' + "".join(body) + "</table>"
    )
    return section_title("Tableau de synthèse") + body_cell(table, "14px 32px 0 32px")


def render_security(section: Section) -> str:
    items = bullets(section.lines) + [
        f"**{sub.title}** : {' '.join(bullets(sub.lines) or paragraphs(sub.lines))}" for sub in section.subsections
    ]
    intro = [p for p in paragraphs(section.lines)]
    if not items and not intro:
        items = ["Rien de notable dans la période."]
    inner = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        "<tr>"
        f'<td width="4" {bg(SECURITY_BAR)}width:4px;font-size:1px;">&nbsp;</td>'
        f'<td {bg(SECURITY_BG)}padding:16px 18px 10px 16px;">'
        f'<div style="font-family:{FONT};font-size:18px;font-weight:bold;color:{SECURITY_TITLE};padding-bottom:10px;">'
        f"{escape(section.title)}</div>"
        + "".join(
            f'<div style="font-family:{FONT};font-size:14px;line-height:21px;color:{TEXT};padding-bottom:8px;">'
            f"{inline(p)}</div>"
            for p in intro
            if not items
        )
        + (bullet_rows(items, dot_color=SECURITY_BAR) if items else "")
        + "</td></tr></table>"
    )
    return body_cell(inner, "28px 32px 0 32px")


def render_generic(section: Section, muted: bool = False) -> str:
    parts = []
    for text in paragraphs(section.lines):
        parts.append(
            f'<div style="font-family:{FONT};font-size:14px;line-height:21px;color:{MUTED if muted else TEXT};'
            f'padding-bottom:8px;">{inline(text)}</div>'
        )
    items = bullets(section.lines)
    if items:
        parts.append(bullet_rows(items, dot_color=MUTED if muted else SECTION_RULE, size=13 if muted else 14))
    rows = table_rows(section.lines)
    if rows:
        header, *rest = rows
        html_rows = [
            "<tr>"
            + "".join(
                f'<td {bg(HEADER_BG)}font-family:{FONT};font-size:12px;font-weight:bold;color:#ffffff;padding:8px;">'
                f"{inline(cell)}</td>"
                for cell in header
            )
            + "</tr>"
        ]
        for index, row in enumerate(rest):
            row_bg = TABLE_ALT_BG if index % 2 else INNER_BG
            html_rows.append(
                f'<tr {bg(row_bg)}">'
                + "".join(
                    f'<td valign="top" style="font-family:{FONT};font-size:12px;color:{TEXT};padding:8px;">'
                    f"{inline(cell)}</td>"
                    for cell in row
                )
                + "</tr>"
            )
        parts.append(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            + "".join(html_rows)
            + "</table>"
        )
    for sub in section.subsections:
        parts.append(
            f'<div style="font-family:{FONT};font-size:15px;font-weight:bold;color:{HEADER_BG};padding:10px 0 6px 0;">'
            f"{escape(sub.title)}</div>"
        )
        sub_items = bullets(sub.lines)
        if sub_items:
            parts.append(bullet_rows(sub_items))
    if not parts:
        return ""
    title_color = MUTED if muted else HEADER_BG
    return section_title(section.title, color=title_color, rule=BORDER if muted else SECTION_RULE) + body_cell(
        "".join(parts), "12px 32px 0 32px"
    )


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def render_newsletter(
    content: str,
    report_date: str,
    kicker: str = "Veille IA · STTI APRIL",
    title: str = "La newsletter technique IA",
) -> str:
    """HTML d'email (corps seul, commence par <table>) pour un rapport de veille."""
    sections = parse_sections(content)
    tldr = find_section(sections, "tl;dr", "tldr", "l’essentiel", "l'essentiel", "executive")
    radar = find_section(sections, "radar")
    news = find_section(sections, "nouveautés", "nouveautes")
    security = find_section(sections, "sécurité", "securite")
    method = find_section(sections, "note de méthode", "note de methode", "méthode")
    handled = {id(s) for s in (tldr, radar, news, security, method) if s}

    cards = build_news_cards(news) if news else []
    blocks = [render_header(report_date, kicker, title)]
    blocks.append(render_summary(bullets(tldr.lines) + paragraphs(tldr.lines) if tldr else []))
    if radar:
        blocks.append(render_radar(radar))
    if news:
        blocks.append(render_news(news, cards))
    if security:
        blocks.append(render_security(security))
    blocks.append(render_synthesis_table(cards))
    for section in sections:
        if id(section) in handled or not section.title:
            continue
        blocks.append(render_generic(section))
    if method:
        blocks.append(render_generic(method, muted=True))
    blocks.append(
        f'<tr><td {bg(OUTER_BG)}padding:18px 32px;font-family:{FONT};font-size:11px;line-height:16px;'
        f'color:{MUTED};text-align:center;">'
        "Newsletter g&eacute;n&eacute;r&eacute;e automatiquement par Veille IA &middot; "
        "les &eacute;l&eacute;ments b&ecirc;ta / preview ne sont pas disponibles en production."
        "</td></tr>"
    )

    html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'{bg(OUTER_BG)}">'
        '<tr><td align="center" style="padding:24px 12px;">'
        f'<table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" '
        f'{bg(INNER_BG)}width:720px;max-width:720px;">'
        + "".join(block for block in blocks if block)
        + "</table></td></tr></table>"
    )
    return to_entities(html.replace("<div", "<p").replace("</div>", "</p>").replace('<p style="', '<p style="margin:0;'))
