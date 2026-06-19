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

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    question: str
    report_ids: Optional[List[int]] = None


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
