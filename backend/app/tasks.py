"""Task handlers + periodic schedulers."""
from datetime import timedelta

from sqlmodel import Session, select

from .audit import audit, notify
from .db import session_scope
from .models import Application, EmailConnection, Job, JobMatch, JobSourceConnection, now
from .worker import enqueue, handler


@handler("resume.parse")
def h_parse(s: Session, p: dict):
    from .ingest.pipeline import parse_resume
    return {"facts": parse_resume(s, p["resume_id"])}


@handler("resume.tailor")
def h_tailor(s: Session, p: dict):
    from .applications import create_for_tailoring
    from .tailoring.engine import tailor
    tl = tailor(s, p["tailoring_id"])
    app = create_for_tailoring(s, tl, actor="user")
    return {"qa": tl.qa_status, "application_id": app.id}


@handler("job.match")
def h_match(s: Session, p: dict):
    from .matching import match_job
    job = s.get(Job, p["job_id"])
    if not job:
        return {"skipped": True}
    m = match_job(s, job)
    return {"score": m.score, "eligible": m.eligible}


def prescreen(s: Session, job: Job) -> bool:
    """Cheap deterministic screen before spending LLM calls on scoring."""
    from .matching import hard_and_soft_checks
    from .prefs import load_prefs
    from .textutil import jaccard, norm
    prefs = load_prefs(s)
    hard, _, _ = hard_and_soft_checks(job, None, prefs)
    if hard:
        m = s.exec(select(JobMatch).where(JobMatch.job_id == job.id)).first() or JobMatch(job_id=job.id)
        m.eligible, m.hard_failures, m.score = False, hard, 0
        m.explanation, m.recommended_action = "Excluded by hard requirement before scoring.", "Excluded by hard requirement"
        s.add(m)
        s.commit()
        return False
    titles = prefs["titles"]["value"] or []
    if titles and job.title:
        jt = norm(job.title)
        if not any(jaccard(job.title, t) >= 0.2 or any(w in jt for w in norm(t).split() if len(w) > 3) for t in titles):
            return False
    return True


@handler("source.poll")
def h_poll_source(s: Session, p: dict):
    from .jobs.service import upsert_job
    from .ledger import active_facts
    from .providers.registry import get_provider
    conn = s.get(JobSourceConnection, p["connection_id"])
    if not conn or not conn.enabled:
        return {"skipped": True}
    prov = get_provider(conn.provider)
    cursor, pages, new = None, 0, []
    try:
        while pages < 5:
            jobs, cursor = prov.search_jobs(conn.config, cursor)
            pages += 1
            for nj in jobs:
                job, created = upsert_job(s, nj, conn.id)
                if created:
                    new.append(job)
            if cursor is None:
                break
    except Exception as e:
        conn.status, conn.last_error = "error", str(e)[:500]
        s.add(conn)
        s.commit()
        raise
    conn.status, conn.last_error, conn.last_run_at = "ok", "", now()
    s.add(conn)
    s.commit()
    has_profile = bool(active_facts(s))
    queued = 0
    for job in new:
        if job.duplicate_of is None and has_profile and prescreen(s, job):
            enqueue(s, "job.match", {"job_id": job.id}, dedupe_key=f"match:{job.id}")
            queued += 1
    audit(s, "system", "job.search.completed", "source", conn.id, new=len(new), queued_for_match=queued)
    if new:
        notify(s, "jobs", f"{len(new)} new jobs from {conn.label or conn.provider}",
               f"{queued} passed your filters and are being scored.", "/discover")
    return {"new": len(new), "queued": queued}


@handler("email.poll")
def h_poll_email(s: Session, p: dict):
    from .email.monitor import poll
    return poll(s, p["connection_id"])


@handler("autopilot.run")
def h_autopilot(s: Session, p: dict):
    from .autopilot import run
    return run(s)


@handler("digest")
def h_digest(s: Session, p: dict):
    since = now() - timedelta(days=1)
    jobs = len(s.exec(select(Job).where(Job.discovered_at >= since)).all())
    good = len(s.exec(select(JobMatch).where(JobMatch.created_at >= since, JobMatch.eligible == True,  # noqa: E712
                                             JobMatch.score >= 70)).all())
    review = len(s.exec(select(Application).where(Application.status == "READY_FOR_REVIEW")).all())
    ready = len(s.exec(select(Application).where(Application.status == "APPROVED")).all())
    follow = s.exec(select(Application).where(Application.follow_up_at != None, Application.follow_up_at <= now(),  # noqa: E711
                                              Application.status.in_(["SUBMITTED", "ACKNOWLEDGED"]))).all()
    body = (f"New jobs: {jobs}. Strong matches: {good}. Awaiting your review: {review}. "
            f"Approved, ready to submit: {ready}. Follow-ups due: {len(follow)}.")
    notify(s, "digest", "Daily job search summary", body, "/")
    return {"jobs": jobs}


# ---- periodic schedulers (called by APScheduler) ----

def schedule_source_polls():
    with session_scope() as s:
        for c in s.exec(select(JobSourceConnection).where(JobSourceConnection.enabled == True)).all():  # noqa: E712
            enqueue(s, "source.poll", {"connection_id": c.id}, dedupe_key=f"source:{c.id}")


def schedule_email_polls():
    with session_scope() as s:
        for c in s.exec(select(EmailConnection).where(EmailConnection.status == "connected")).all():
            enqueue(s, "email.poll", {"connection_id": c.id}, dedupe_key=f"email:{c.id}", max_attempts=2)


def schedule_autopilot():
    from .autopilot import get_policy
    with session_scope() as s:
        p = get_policy(s)
        if p.enabled and not p.paused:
            enqueue(s, "autopilot.run", {}, dedupe_key="autopilot", max_attempts=1)


def schedule_digest():
    with session_scope() as s:
        enqueue(s, "digest", {}, dedupe_key=f"digest:{now().date()}")
