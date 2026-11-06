"""Autopilot (spec §4.2, Appendix B). Off by default. Policy is stored as validated DB settings.
Because no connected provider offers a candidate-side submission API, autopilot prepares
applications (match → tailor → QA) and queues them for one-click handoff; it never fills
third-party forms or bypasses CAPTCHA/MFA."""
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .applications import create_for_tailoring, find_existing, approve
from .audit import audit, notify
from .db import get_setting, put_setting
from .ledger import active_facts
from .matching import match_job
from .models import Application, AuditEvent, ConsentRecord, Job, JobMatch, JobSourceConnection, Tailoring, now
from .providers.registry import get_provider

SENSITIVE_DEFAULT = ["salary_expectations", "work_authorisation", "security_clearance", "legal_declarations",
                     "demographic_questions", "disability_questions", "conflict_of_interest", "criminal_history"]


class AutoSubmit(BaseModel):
    enabled: bool = False
    supported_providers_only: bool = True  # always enforced
    pause_on_captcha_or_mfa: bool = True  # always enforced
    pause_on_sensitive_questions: bool = True  # always enforced
    pause_on_unknown_questions: bool = True


class AutopilotPolicy(BaseModel):
    enabled: bool = False
    paused: bool = False
    minimum_match_score: int = Field(82, ge=0, le=100)
    max_applications_per_day: int = Field(3, ge=0, le=50)
    max_applications_per_week: int = Field(10, ge=0, le=200)
    require_job_open_check: bool = True
    require_verified_candidate_facts: bool = True
    require_qa_pass: bool = True
    generate_cover_letter: bool = False
    tailoring_tone: str = "balanced"
    tailoring_length: str = "two_page"
    max_job_age_days: int = 14
    auto_submit: AutoSubmit = Field(default_factory=AutoSubmit)
    excluded_employers: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    require_user_approval_for: list[str] = Field(default_factory=lambda: list(SENSITIVE_DEFAULT))


def get_policy(s: Session) -> AutopilotPolicy:
    return AutopilotPolicy.model_validate(get_setting(s, "autopilot", {}) or {})


def save_policy(s: Session, p: AutopilotPolicy, actor: str = "user") -> AutopilotPolicy:
    old = get_policy(s)
    # safety invariants cannot be switched off
    p.auto_submit.supported_providers_only = True
    p.auto_submit.pause_on_captcha_or_mfa = True
    p.auto_submit.pause_on_sensitive_questions = True
    for k in SENSITIVE_DEFAULT:
        if k not in p.require_user_approval_for:
            p.require_user_approval_for.append(k)
    if p.enabled and not old.enabled:
        s.add(ConsentRecord(purpose="autopilot", scope="prepare applications automatically"))
    if not p.enabled and old.enabled:
        for c in s.exec(select(ConsentRecord).where(ConsentRecord.purpose == "autopilot",
                                                    ConsentRecord.revoked_at == None)).all():  # noqa: E711
            c.revoked_at = now()
            s.add(c)
    if p.auto_submit.enabled and not old.auto_submit.enabled:
        s.add(ConsentRecord(purpose="autopilot_auto_submit", scope="submit via officially supported provider APIs only"))
    put_setting(s, "autopilot", p.model_dump())
    audit(s, actor, "autopilot.settings.changed", "autopilot", None, enabled=p.enabled, paused=p.paused)
    return p


def set_paused(s: Session, paused: bool) -> AutopilotPolicy:
    p = get_policy(s)
    p.paused = paused
    put_setting(s, "autopilot", p.model_dump())
    audit(s, "user", "autopilot.paused" if paused else "autopilot.resumed", "autopilot")
    return p


def _count_since(s: Session, since: datetime) -> int:
    return len(s.exec(select(Application).where(Application.approved_by == "autopilot",
                                                Application.created_at >= since)).all())


def caps_remaining(s: Session, p: AutopilotPolicy) -> int:
    t = datetime.now(timezone.utc)
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    week = day - timedelta(days=day.weekday())
    return max(0, min(p.max_applications_per_day - _count_since(s, day),
                      p.max_applications_per_week - _count_since(s, week)))


def _exception(s: Session, job: Job, reason: str):
    audit(s, "autopilot", "autopilot.exception", "job", job.id, reason=reason, title=job.title, company=job.company)


def run(s: Session) -> dict:
    from .tailoring.engine import tailor
    from .tailoring.schema import TailorOptions

    p = get_policy(s)
    stats = {"considered": 0, "prepared": 0, "skipped": 0, "exceptions": 0}
    if not p.enabled or p.paused:
        return {"skipped": "disabled" if not p.enabled else "paused"}
    if p.require_verified_candidate_facts and not any(f.type == "employment" for f in active_facts(s, True)):
        notify(s, "autopilot", "Autopilot waiting", "Verify your profile facts so autopilot can tailor resumes.",
               "/profile", important=True)
        return {"skipped": "no_verified_facts"}
    sources = [c.id for c in s.exec(select(JobSourceConnection).where(JobSourceConnection.autopilot_enabled == True,  # noqa: E712
                                                                      JobSourceConnection.enabled == True)).all()]  # noqa: E712
    if not sources:
        return {"skipped": "no_sources_enabled"}
    cutoff = now() - timedelta(days=p.max_job_age_days)
    jobs = s.exec(select(Job).where(Job.source_connection_id.in_(sources), Job.dismissed == False,  # noqa: E712
                                    Job.duplicate_of == None, Job.discovered_at >= cutoff)  # noqa: E711
                  .order_by(Job.discovered_at.desc()).limit(200)).all()
    remaining = caps_remaining(s, p)
    for job in jobs:
        if remaining <= 0:
            break
        if get_policy(s).paused:  # honour pause immediately
            break
        if find_existing(s, job):
            continue
        stats["considered"] += 1
        text = f"{job.title} {job.company} {job.description}".lower()
        if any(e.lower() in job.company.lower() for e in p.excluded_employers if e) or \
                any(k.lower() in text for k in p.excluded_keywords if k):
            stats["skipped"] += 1
            continue
        m = s.exec(select(JobMatch).where(JobMatch.job_id == job.id)).first() or match_job(s, job)
        if not m.eligible or m.score < p.minimum_match_score:
            stats["skipped"] += 1
            continue
        if p.require_job_open_check and job.provider == "mycareersfuture":
            if get_provider("mycareersfuture").is_open(job.external_id) is False:
                stats["skipped"] += 1
                continue
        reqs = job.requirements.get("sensitive_requirements") or []
        opts = TailorOptions(tone=p.tailoring_tone, length=p.tailoring_length, cover_letter=p.generate_cover_letter)
        tl = Tailoring(job_id=job.id, options={**opts.model_dump(), "_actor": "autopilot"}, status="generating")
        s.add(tl)
        s.commit()
        s.refresh(tl)
        try:
            tl = tailor(s, tl.id)
        except Exception as e:  # noqa: BLE001
            _exception(s, job, f"Tailoring failed: {e}")
            stats["exceptions"] += 1
            continue
        if tl.qa_status == "fail" or (p.require_qa_pass and tl.qa_status != "pass"):
            _exception(s, job, f"Tailored resume QA status '{tl.qa_status}' — needs your review")
            create_for_tailoring(s, tl, actor="autopilot")
            stats["exceptions"] += 1
            continue
        app = create_for_tailoring(s, tl, actor="autopilot")
        app.approved_by = "autopilot"
        s.add(app)
        s.commit()
        approve(s, app, actor="autopilot")
        remaining -= 1
        stats["prepared"] += 1
        # Auto-submit hook: only for providers declaring capabilities.submit (none today) — handoff otherwise.
        note = (" Sensitive requirements detected: " + "; ".join(reqs)) if reqs else ""
        notify(s, "autopilot", f"Ready to submit: {job.title} at {job.company}",
               f"Match {m.score:.0f}. Tailored resume passed QA. Open the official application page to submit.{note}",
               f"/applications/{app.id}", important=bool(reqs))
    audit(s, "autopilot", "autopilot.run", "autopilot", None, **stats)
    return stats


def recent_actions(s: Session, limit: int = 50) -> list[AuditEvent]:
    return list(s.exec(select(AuditEvent).where(AuditEvent.actor == "autopilot")
                       .order_by(AuditEvent.ts.desc()).limit(limit)).all())
