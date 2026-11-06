"""Application state machine, idempotency, submission controls (spec §11)."""
import hashlib
from datetime import timedelta

from sqlmodel import Session, select

from .audit import audit, notify
from .jobs.service import requisition_id
from .models import Application, ApplicationEvent, Job, Tailoring, now

PIPELINE = ["DISCOVERED", "MATCHED", "READY_FOR_REVIEW", "APPROVED", "SUBMITTING", "SUBMITTED", "ACKNOWLEDGED",
            "IN_REVIEW", "INTERVIEW", "OFFER"]
EXCEPTIONS = ["REJECTED", "WITHDRAWN", "CLOSED", "FAILED", "ACTION_REQUIRED", "UNKNOWN"]
ALL_STATES = PIPELINE + EXCEPTIONS
TERMINAL = {"OFFER", "REJECTED", "WITHDRAWN", "CLOSED"}

# provider/email vocabulary → internal state (original kept in provider_status)
EVENT_TO_STATE = {"confirmation": "ACKNOWLEDGED", "acknowledgement": "ACKNOWLEDGED", "assessment": "IN_REVIEW",
                  "info_request": "ACTION_REQUIRED", "interview": "INTERVIEW", "offer": "OFFER",
                  "rejection": "REJECTED", "closed": "CLOSED"}
IMPORTANT_EVENTS = {"interview", "offer", "info_request", "assessment"}


class ApplyError(ValueError):
    pass


def idem_key(job: Job) -> str:
    raw = f"{job.provider}|{requisition_id(job) or job.dedupe_key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def find_existing(s: Session, job: Job) -> Application | None:
    app = s.exec(select(Application).where(Application.idempotency_key == idem_key(job))).first()
    if app:
        return app
    # same role found through another source
    same = s.exec(select(Job.id).where(Job.dedupe_key == job.dedupe_key)).all()
    if same:
        return s.exec(select(Application).where(Application.job_id.in_(same))).first()
    return None


def _event(s: Session, app: Application, event_type: str, frm: str, to: str, source: str, **detail):
    s.add(ApplicationEvent(application_id=app.id, event_type=event_type, from_status=frm, to_status=to,
                           source=source, detail=detail))


def transition(s: Session, app: Application, to: str, source: str, event_type: str = "status_changed",
               force: bool = False, provider_status: str = "", **detail) -> bool:
    """Automated sources can only move forward along the pipeline; manual (force) can set anything."""
    if to not in ALL_STATES:
        raise ApplyError(f"Unknown status {to}")
    frm = app.status
    if frm == to:
        _event(s, app, event_type, frm, to, source, **detail)
        s.commit()
        return False
    if not force:
        if frm in TERMINAL:
            _event(s, app, event_type, frm, frm, source, ignored_target=to, **detail)
            s.commit()
            return False
        if to in PIPELINE and frm in PIPELINE and PIPELINE.index(to) < PIPELINE.index(frm):
            _event(s, app, event_type, frm, frm, source, ignored_target=to, **detail)
            s.commit()
            return False
    app.status, app.updated_at = to, now()
    if provider_status:
        app.provider_status = provider_status
    if to == "SUBMITTED" and not app.submitted_at:
        app.submitted_at = now()
        app.follow_up_at = now() + timedelta(days=10)
    s.add(app)
    _event(s, app, event_type, frm, to, source, **detail)
    s.commit()
    audit(s, "user" if source == "manual" else source, "application.status.changed", "application", app.id,
          frm=frm, to=to)
    return True


def create_for_tailoring(s: Session, tl: Tailoring, actor: str = "user") -> Application:
    job = s.get(Job, tl.job_id)
    existing = find_existing(s, job)
    if existing:
        if existing.status in ("READY_FOR_REVIEW", "MATCHED", "DISCOVERED", "FAILED") and existing.job_id == job.id:
            existing.tailoring_id = tl.id
            s.add(existing)
            s.commit()
        return existing
    app = Application(job_id=job.id, tailoring_id=tl.id, idempotency_key=idem_key(job), status="READY_FOR_REVIEW",
                      approved_by="")
    s.add(app)
    s.commit()
    s.refresh(app)
    _event(s, app, "created", "", "READY_FOR_REVIEW", actor, tailoring_id=tl.id)
    s.commit()
    audit(s, actor, "application.created", "application", app.id, job_id=job.id)
    return app


def preflight(s: Session, app: Application) -> list[str]:
    """Spec §11.2 validation. Returns blocking problems."""
    problems = []
    job = s.get(Job, app.job_id)
    if app.submitted_at or app.status in ("SUBMITTED", "ACKNOWLEDGED", "IN_REVIEW", "INTERVIEW", "OFFER"):
        problems.append("Already submitted.")
    other = find_existing(s, job)
    if other and other.id != app.id and other.submitted_at:
        problems.append(f"You already applied to this role (application #{other.id}).")
    tl = s.get(Tailoring, app.tailoring_id) if app.tailoring_id else None
    if not tl or tl.status not in ("draft", "approved"):
        problems.append("No tailored resume ready.")
    elif tl.qa_status == "fail":
        problems.append("Tailored resume failed factuality checks — fix before submitting.")
    if job.provider == "mycareersfuture":
        from .providers.registry import get_provider
        try:
            if get_provider("mycareersfuture").is_open(job.external_id) is False:
                problems.append("Job is no longer open.")
        except Exception:  # noqa: BLE001  network issue shouldn't hard-block a manual handoff
            pass
    return problems


def approve(s: Session, app: Application, actor: str = "user") -> Application:
    tl = s.get(Tailoring, app.tailoring_id) if app.tailoring_id else None
    if not tl:
        raise ApplyError("No tailored resume attached.")
    if tl.qa_status == "fail":
        raise ApplyError("Cannot approve: factuality checks failed.")
    tl.status = "approved"
    s.add(tl)
    app.user_approved = actor == "user"
    app.approved_by = actor
    s.add(app)
    s.commit()
    transition(s, app, "APPROVED", actor, "approved")
    return app


def handoff(s: Session, app: Application) -> dict:
    """No candidate-side submit API exists for current providers → open the official application page."""
    problems = preflight(s, app)
    if problems:
        raise ApplyError(" ".join(problems))
    job = s.get(Job, app.job_id)
    from .providers.registry import get_provider
    try:
        url = get_provider(job.provider).get_application_url(job)  # type: ignore[arg-type]
    except KeyError:
        url = job.apply_url or job.url
    if not url:
        raise ApplyError("This job has no application link. Apply via the employer and mark it submitted.")
    app.method = "handoff"
    s.add(app)
    s.commit()
    _event(s, app, "handoff_opened", app.status, app.status, "manual", url=url)
    s.commit()
    return {"url": url, "tailoring_id": app.tailoring_id}


def mark_submitted(s: Session, app: Application, confirmation_id: str = "", answers: dict | None = None) -> Application:
    if app.submitted_at:
        return app  # idempotent
    if not app.user_approved and app.approved_by != "autopilot":
        approve(s, app, "user")
    app.confirmation_id = confirmation_id
    if answers:
        app.answers = answers
    s.add(app)
    s.commit()
    transition(s, app, "SUBMITTED", "manual", "submitted", method=app.method, confirmation_id=confirmation_id,
               user_approved=app.user_approved)
    tl = s.get(Tailoring, app.tailoring_id) if app.tailoring_id else None
    audit(s, "user", "application.submitted", "application", app.id, method=app.method,
          docs={"resume_pdf": tl.pdf_path if tl else "", "resume_docx": tl.docx_path if tl else "",
                "cover": tl.cover_docx_path if tl else ""})
    return app


def apply_email_event(s: Session, app: Application, event_type: str, subject: str, email_event_id: int) -> None:
    to = EVENT_TO_STATE.get(event_type)
    if not to:
        return
    changed = transition(s, app, to, "email", f"email_{event_type}", provider_status=event_type,
                         subject=subject, email_event_id=email_event_id)
    job = s.get(Job, app.job_id)
    if changed and (event_type in IMPORTANT_EVENTS or to == "REJECTED"):
        notify(s, f"application_{event_type}", f"{event_type.replace('_', ' ').title()}: {job.title} at {job.company}",
               subject, f"/applications/{app.id}", important=event_type in IMPORTANT_EVENTS)
