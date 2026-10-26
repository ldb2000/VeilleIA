from sqlalchemy import Boolean, Column, Integer, String, DateTime, Text
from datetime import datetime
from .database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, index=True)
    report_type = Column(String, default="technical_watch", index=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    newsletter_sent_at = Column(DateTime, nullable=True)


class ReportSummary(Base):
    __tablename__ = "report_summaries"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, index=True, unique=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, index=True)
    kind = Column(String, default="note", index=True)
    source_text = Column(Text)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String, index=True)
    content = Column(Text)
    report_ids = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class NewsItem(Base):
    """Une nouveauté extraite de la section « Nouveautés détaillées » d'un rapport."""

    __tablename__ = "news_items"

    id = Column(Integer, primary_key=True, index=True)
    # NULL quand le rapport d'origine a été supprimé (news sauvegardée conservée).
    report_id = Column(Integer, index=True, nullable=True)
    source_report_date = Column(String, nullable=True)
    position = Column(Integer, default=0)
    title = Column(String)
    maturity = Column(String, nullable=True)
    content = Column(Text)
    saved = Column(Boolean, default=False, index=True)
    saved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
