"""Data model (spec §15). Local single-user build: no user_id columns."""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(timezone.utc)


def JSONCol(default=None):
    return Field(default_factory=(lambda: default() if callable(default) else default), sa_column=Column(JSON))


def TextCol():
    return Field(default="", sa_column=Column(Text))


class Resume(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    sha256: str = Field(index=True)
    format: str  # pdf | docx
    file_path: str  # immutable original
    is_master: bool = False
    raw_text: str = TextCol()
    parse_status: str = "pending"  # pending | parsing | parsed | failed
    parse_error: str = ""
    created_at: datetime = Field(default_factory=now)


class CandidateFact(SQLModel, table=True):
    """Canonical fact ledger (spec §5.3)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str = Field(index=True)  # contact|summary|employment|education|skill|certification|project|achievement|language|award|publication
    text: str = TextCol()  # human-readable canonical value
    data: dict = JSONCol(dict)  # structured fields (employer, title, start, end, ...)
    parent_id: Optional[int] = Field(default=None, index=True)  # achievement -> employment/project
    source_resume_id: Optional[int] = None
    source_excerpt: str = TextCol()
    confidence: float = 1.0
    verified: bool = False
    verified_at: Optional[datetime] = None
    notes: str = ""
    active: bool = True
    version: int = 1
    sort_order: int = 0
    updated_at: datetime = Field(default_factory=now)


class FactRevision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    fact_id: int = Field(index=True)
    version: int
    text: str = TextCol()
    data: dict = JSONCol(dict)
    changed_at: datetime = Field(default_factory=now)


class JobPreference(SQLModel, table=True):
    """Spec §6. criterion examples: titles, locations, work_arrangement, salary_min, seniority,
    employment_type, excluded_companies, preferred_companies, required_skills, preferred_skills,
    excluded_keywords, industries, max_posting_age_days."""
    id: Optional[int] = Field(default=None, primary_key=True)
    criterion: str = Field(index=True, unique=True)
    rule_type: str = "soft"  # hard | soft | info
    value: Any = JSONCol(lambda: None)


class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: Any = JSONCol(lambda: None)


class JobSourceConnection(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str  # greenhouse | lever | ashby | mycareersfuture
    label: str = ""
    config: dict = JSONCol(dict)  # {"board": "stripe"} or {"search": "...", "limit": 50}
    enabled: bool = True
    autopilot_enabled: bool = False
    status: str = "ok"
    last_run_at: Optional[datetime] = None
    last_error: str = ""
    created_at: datetime = Field(default_factory=now)


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str = Field(index=True)
    external_id: str = Field(default="", index=True)
    dedupe_key: str = Field(index=True)
    url: str = ""
    apply_url: str = ""
    title: str
    company: str = ""
    location: str = ""
    work_arrangement: str = ""  # onsite | hybrid | remote | ""
    employment_type: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = ""
    salary_period: str = ""
    description: str = TextCol()
    requirements: dict = JSONCol(dict)  # extracted by LLM
    posted_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=now)
    retrieved_at: datetime = Field(default_factory=now)
    duplicate_of: Optional[int] = None
    saved: bool = False
    dismissed: bool = False
    source_connection_id: Optional[int] = None


class JobMatch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(index=True, unique=True)
    score: float = 0
    eligible: bool = True
    hard_failures: list = JSONCol(list)
    breakdown: dict = JSONCol(dict)
    strong_matches: list = JSONCol(list)
    gaps: list = JSONCol(list)
    explanation: str = TextCol()
    recommended_action: str = ""
    created_at: datetime = Field(default_factory=now)


class Tailoring(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(index=True)
    options: dict = JSONCol(dict)
    content: dict = JSONCol(dict)  # structured tailored resume with fact citations
    qa: dict = JSONCol(dict)
    qa_status: str = "pending"  # pending | pass | warn | fail
    change_report: dict = JSONCol(dict)
    cover_letter: str = TextCol()
    docx_path: str = ""
    pdf_path: str = ""
    cover_docx_path: str = ""
    model: str = ""
    prompt_version: str = ""
    status: str = "generating"  # generating | draft | approved | rejected | failed
    error: str = ""
    created_at: datetime = Field(default_factory=now)


class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(index=True)
    tailoring_id: Optional[int] = None
    idempotency_key: str = Field(unique=True, index=True)
    status: str = "READY_FOR_REVIEW"
    provider_status: str = ""
    method: str = "handoff"  # handoff | api
    user_approved: bool = False
    approved_by: str = ""  # user | autopilot
    submitted_at: Optional[datetime] = None
    confirmation_id: str = ""
    answers: dict = JSONCol(dict)
    follow_up_at: Optional[datetime] = None
    notes: str = TextCol()
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class ApplicationEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(index=True)
    event_type: str
    from_status: str = ""
    to_status: str = ""
    source: str = "system"  # manual | email | provider | system | autopilot
    detail: dict = JSONCol(dict)
    occurred_at: datetime = Field(default_factory=now)


class EmailConnection(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str  # gmail | outlook
    account: str = ""
    token_enc: str = TextCol()
    scopes: list = JSONCol(list)
    status: str = "connected"
    last_polled_at: Optional[datetime] = None
    last_error: str = ""
    created_at: datetime = Field(default_factory=now)


class EmailEvent(SQLModel, table=True):
    """Only extracted fields are stored — never full bodies (spec §15.2)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    connection_id: int = Field(index=True)
    message_id: str = Field(unique=True, index=True)
    received_at: Optional[datetime] = None
    sender: str = ""
    subject: str = ""
    event_type: str = ""  # confirmation|acknowledgement|interview|assessment|info_request|rejection|offer|closed|job_alert|other
    company: str = ""
    role: str = ""
    requisition_id: str = ""
    confidence: float = 0
    application_id: Optional[int] = None
    link_status: str = "pending"  # linked | needs_confirmation | ignored | alert_imported
    created_at: datetime = Field(default_factory=now)


class Notification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str
    title: str
    body: str = TextCol()
    link: str = ""
    important: bool = False
    read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now)


class ConsentRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    purpose: str
    scope: str = ""
    granted_at: datetime = Field(default_factory=now)
    revoked_at: Optional[datetime] = None


class AuditEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    actor: str  # user | autopilot | system
    action: str
    entity: str = ""
    entity_id: Optional[int] = None
    meta: dict = JSONCol(dict)
    ts: datetime = Field(default_factory=now, index=True)


class QuestionAnswer(SQLModel, table=True):
    """User-supplied answers to application questions. Sensitive ones are never AI-generated."""
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(unique=True)  # e.g. work_authorisation, notice_period
    question: str = ""
    category: str = "standard"  # standard | sensitive
    answer: str = TextCol()
    confirmed: bool = False
    updated_at: datetime = Field(default_factory=now)


class Task(SQLModel, table=True):
    """DB-backed work queue with retries + backoff (spec §17)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    payload: dict = JSONCol(dict)
    status: str = Field(default="queued", index=True)  # queued | running | done | failed | dead
    attempts: int = 0
    max_attempts: int = 4
    next_run_at: datetime = Field(default_factory=now, index=True)
    last_error: str = TextCol()
    correlation_id: str = ""
    dedupe_key: Optional[str] = Field(default=None, unique=True)
    result: dict = JSONCol(dict)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
