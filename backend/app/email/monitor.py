"""Email status monitoring (spec §12.2-12.3). Stores only extracted fields, never full bodies."""
import re

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..applications import apply_email_event
from ..audit import audit, notify
from ..llm import get_llm
from ..llm.prompts import EMAIL_SYSTEM
from ..models import Application, EmailConnection, EmailEvent, Job, now
from ..providers.base import NormalizedJob, html_to_text
from ..textutil import jaccard, norm, slug
from . import clients

LINK_THRESHOLD = 0.75
ASK_THRESHOLD = 0.4

KEYWORDS = re.compile(r"applica|appl(y|ied)|interview|assessment|offer|candida|position|role|recruit|job|hiring|"
                      r"thank you for (your )?interest|regret|unfortunately|next steps|opportunit", re.I)
ATS_SENDERS = ("greenhouse", "lever.co", "ashbyhq", "workday", "smartrecruiters", "icims", "taleo", "successfactors",
               "mycareersfuture", "linkedin", "indeed", "jobstreet", "recruitee", "bamboohr", "jobvite", "workable")


class AlertJob(BaseModel):
    title: str
    company: str = ""
    location: str = ""
    url: str = ""


class EmailClass(BaseModel):
    event_type: str = Field(description="confirmation|acknowledgement|interview|assessment|info_request|rejection|offer|closed|job_alert|other")
    company: str = ""
    role: str = ""
    requisition_id: str = ""
    confidence: float = Field(0.5, description="0-1 confidence in event_type")
    jobs: list[AlertJob] = Field(default_factory=list)


def prefilter(m: clients.Msg) -> bool:
    s = f"{m.sender} {m.subject}".lower()
    return bool(KEYWORDS.search(m.subject) or KEYWORDS.search(m.snippet[:300])) or any(a in s for a in ATS_SENDERS)


def _domain(sender: str) -> str:
    m = re.search(r"@([\w.-]+)", sender)
    return m.group(1).lower() if m else ""


def match_application(s: Session, ev: EmailEvent) -> tuple[Application | None, float, list[tuple[Application, float]]]:
    apps = s.exec(select(Application)).all()
    scored = []
    dom = _domain(ev.sender)
    for a in apps:
        job = s.get(Job, a.job_id)
        if not job:
            continue
        sc = 0.0
        comp = norm(job.company)
        if comp and ev.company and (comp in norm(ev.company) or norm(ev.company) in comp):
            sc += 0.45
        elif comp and (comp in norm(ev.subject) or comp in norm(ev.sender)):
            sc += 0.4
        elif comp and slug(job.company).replace("-", "") in dom.replace("-", ""):
            sc += 0.35
        role_sim = max(jaccard(job.title, ev.role or ""), jaccard(job.title, ev.subject))
        sc += 0.35 * min(1.0, role_sim * 1.6)
        req = str(job.requirements.get("_requisition_id") or job.external_id or "")
        if ev.requisition_id and req and norm(ev.requisition_id) == norm(req):
            sc += 0.5
        if a.submitted_at:
            sc += 0.1
        scored.append((a, min(1.0, sc)))
    scored.sort(key=lambda x: -x[1])
    best = scored[0] if scored else (None, 0.0)
    # ambiguity: two candidates close together → ask the user
    if len(scored) > 1 and best[1] - scored[1][1] < 0.1:
        return None, best[1], scored[:5]
    return best[0], best[1], scored[:5]


def _import_alert_jobs(s: Session, conn: EmailConnection, ev: EmailEvent, cls: EmailClass) -> int:
    from ..jobs.service import upsert_job
    from ..providers.url_import import NeedsPaste, import_url
    n = 0
    for j in cls.jobs[:25]:
        nj = None
        if j.url:
            try:
                nj = import_url(j.url)
            except (NeedsPaste, Exception):  # noqa: BLE001 — alert sites often block fetch; keep title-only lead
                nj = None
        if nj is None:
            nj = NormalizedJob(provider="email_alert", external_id=j.url or f"{ev.message_id}:{j.title}",
                               title=j.title, company=j.company, location=j.location, url=j.url, apply_url=j.url,
                               description=f"(From job alert email: {ev.subject}. Open the link and paste the full "
                                           f"description to match and tailor.)")
        _, created = upsert_job(s, nj)
        n += int(created)
    return n


def poll(s: Session, conn_id: int) -> dict:
    conn = s.get(EmailConnection, conn_id)
    if not conn or conn.status == "disconnected":
        return {"skipped": True}
    try:
        msgs, new_tok = clients.fetch(conn.provider, conn.token_enc, clients.default_since(conn.last_polled_at))
    except clients.EmailAuthError as e:
        conn.status, conn.last_error = "reauth_required", str(e)
        s.add(conn)
        s.commit()
        notify(s, "email_auth", f"Reconnect {conn.provider.title()} mailbox", str(e), "/connections", important=True)
        raise PermissionError(str(e)) from e
    conn.token_enc = new_tok
    seen = set(s.exec(select(EmailEvent.message_id).where(EmailEvent.connection_id == conn.id)).all())
    llm = get_llm()
    stats = {"fetched": len(msgs), "classified": 0, "linked": 0, "needs_confirmation": 0, "alert_jobs": 0}
    for m in msgs:
        if m.id in seen or not prefilter(m):
            continue
        cls = llm.generate_structured(f"FROM: {m.sender}\nSUBJECT: {m.subject}\nSNIPPET: {m.snippet[:600]}",
                                      EmailClass, system=EMAIL_SYSTEM, fast=True, temperature=0)
        stats["classified"] += 1
        ev = EmailEvent(connection_id=conn.id, message_id=m.id, received_at=m.received_at, sender=m.sender[:200],
                        subject=m.subject[:300], event_type=cls.event_type, company=cls.company, role=cls.role,
                        requisition_id=cls.requisition_id, confidence=cls.confidence)
        s.add(ev)
        s.flush()
        if cls.event_type == "job_alert":
            # body is processed in memory to extract job links, then discarded
            raw_body = clients.body(conn.provider, conn.token_enc, m.id)
            text = html_to_text(raw_body)[:12000]
            links = list(dict.fromkeys(re.findall(r"https?://[^\s\"'<>)]+", raw_body)))[:80]
            del raw_body
            full = llm.generate_structured(f"SUBJECT: {m.subject}\n\nBODY:\n{text}\n\nLINKS:\n" + "\n".join(links),
                                           EmailClass, system=EMAIL_SYSTEM, fast=True, temperature=0)
            stats["alert_jobs"] += _import_alert_jobs(s, conn, ev, full)
            ev.link_status = "alert_imported"
        elif cls.event_type == "other":
            ev.link_status = "ignored"
        else:
            app, conf, _ = match_application(s, ev)
            total = conf * (0.5 + 0.5 * cls.confidence)
            if app and total >= LINK_THRESHOLD:
                ev.application_id, ev.link_status, ev.confidence = app.id, "linked", round(total, 2)
                s.add(ev)
                s.commit()
                apply_email_event(s, app, cls.event_type, m.subject, ev.id)
                stats["linked"] += 1
            elif conf >= ASK_THRESHOLD or cls.event_type in ("interview", "offer", "info_request"):
                ev.link_status, ev.confidence = "needs_confirmation", round(total, 2)
                if app:
                    ev.application_id = app.id  # suggestion only
                stats["needs_confirmation"] += 1
                notify(s, "email_confirm", f"Confirm email match: {m.subject[:80]}",
                       f"Detected '{cls.event_type}' from {cls.company or m.sender}. Link it to an application.",
                       "/inbox", important=cls.event_type in ("interview", "offer"), commit=False)
            else:
                ev.link_status = "ignored"
        s.add(ev)
        s.commit()
    conn.last_polled_at, conn.status, conn.last_error = now(), "connected", ""
    s.add(conn)
    s.commit()
    audit(s, "system", "email.polled", "email_connection", conn.id, **stats)
    return stats


def confirm(s: Session, ev: EmailEvent, application_id: int | None) -> None:
    if application_id is None:
        ev.link_status = "ignored"
        s.add(ev)
        s.commit()
        return
    app = s.get(Application, application_id)
    if not app:
        raise ValueError("application not found")
    ev.application_id, ev.link_status = app.id, "linked"
    s.add(ev)
    s.commit()
    apply_email_event(s, app, ev.event_type, ev.subject, ev.id)
    audit(s, "user", "email.match.confirmed", "email_event", ev.id, application_id=app.id)
