from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class ReportBase(BaseModel):
    date: str
    report_type: str
    content: str

class ReportCreate(ReportBase):
    pass

class Report(ReportBase):
    id: int
    created_at: datetime
    newsletter_sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatHistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    report_ids: Optional[List[int]] = None
    history: Optional[List[ChatHistoryMessage]] = None
    web_search: bool = False
    # False pour les appels techniques (synthèse projet) qui ne doivent pas apparaître dans l'historique.
    persist: bool = True


class LLMInfo(BaseModel):
    provider: str
    web_search: bool
    backend: str


class ChatResponse(BaseModel):
    answer: str


class ReportDetailResponse(BaseModel):
    detail: str


class ReportDefinitionResponse(BaseModel):
    definition: str


class ReportSummaryResponse(BaseModel):
    report_id: int
    summary: str
    updated_at: datetime

    class Config:
        from_attributes = True


class NoteCreate(BaseModel):
    kind: str
    source_text: str
    content: str


class Note(BaseModel):
    id: int
    report_id: int
    kind: str
    source_text: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessage(BaseModel):
    id: int
    role: str
    content: str
    report_ids: Optional[List[int]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NewsItem(BaseModel):
    id: int
    report_id: Optional[int] = None
    position: int
    title: str
    maturity: Optional[str] = None
    content: str
    saved: bool
    saved_at: Optional[datetime] = None
    created_at: datetime
    report_date: Optional[str] = None

    class Config:
        from_attributes = True


class NewsItemUpdate(BaseModel):
    saved: bool


class DailyRunResponse(BaseModel):
    report_id: int
    date: str
    created: bool
    newsletter_url: str
    mail_sent: bool = False
    mail_error: Optional[str] = None


class RedditPost(BaseModel):
    title: str
    subreddit: str
    rank: int
    author: Optional[str] = None
    permalink: str
    external_url: Optional[str] = None
    excerpt: Optional[str] = None
    created_utc: float
    created_at: str


class RedditPreview(BaseModel):
    enabled: bool
    period: str
    subreddits: List[str]
    max_posts: int
    max_posts_per_sub: int
    posts: List[RedditPost]
    errors: List[str]


class MailInfo(BaseModel):
    configured: bool
    missing: List[str]
    host: Optional[str] = None
    port: int
    security: str
    authenticated: bool
    sender: Optional[str] = None
    recipients_count: int
    auto_send: bool


class SendNewsletterResponse(BaseModel):
    report_id: int
    subject: str
    recipients_count: int
    newsletter_sent_at: Optional[datetime] = None
