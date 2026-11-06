"""DB-backed task queue + in-process scheduler (spec §17).
- idempotent enqueue via dedupe_key
- retries with exponential backoff, dead-letter after max_attempts
- failures are never silently dropped: dead tasks raise a notification"""
import logging
import threading
import traceback
import uuid
from datetime import timedelta
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .audit import notify
from .db import get_engine
from .models import Task, now

log = logging.getLogger("jobpilot.worker")
HANDLERS: dict[str, Callable[[Session, dict], dict | None]] = {}
_lock = threading.Lock()


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


def enqueue(s: Session, kind: str, payload: dict | None = None, *, dedupe_key: str | None = None,
            correlation_id: str = "", delay_s: float = 0, max_attempts: int = 4) -> Task | None:
    if dedupe_key:
        existing = s.exec(select(Task).where(Task.dedupe_key == dedupe_key)).first()
        if existing:
            if existing.status in ("done", "dead", "failed"):
                # allow re-run of finished work: free the key
                existing.dedupe_key = None
                s.add(existing)
                s.commit()
            else:
                return existing
    t = Task(kind=kind, payload=payload or {}, dedupe_key=dedupe_key, max_attempts=max_attempts,
             correlation_id=correlation_id or uuid.uuid4().hex[:12],
             next_run_at=now() + timedelta(seconds=delay_s))
    s.add(t)
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        return s.exec(select(Task).where(Task.dedupe_key == dedupe_key)).first()
    s.refresh(t)
    return t


def _due(s: Session, limit: int) -> list[Task]:
    rows = s.exec(select(Task).where(Task.status == "queued").order_by(Task.next_run_at).limit(limit * 3)).all()
    n = now()
    out = []
    for t in rows:
        nra = t.next_run_at if t.next_run_at.tzinfo else t.next_run_at.replace(tzinfo=n.tzinfo)
        if nra <= n:
            out.append(t)
    return out[:limit]


def run_task(s: Session, t: Task) -> None:
    fn = HANDLERS.get(t.kind)
    t.status, t.attempts, t.updated_at = "running", t.attempts + 1, now()
    s.add(t)
    s.commit()
    try:
        if fn is None:
            raise RuntimeError(f"no handler for task kind {t.kind}")
        res = fn(s, t.payload)
        s.refresh(t)
        t.status, t.result, t.last_error, t.dedupe_key = "done", res or {}, "", None
    except Exception as e:  # noqa: BLE001
        s.rollback()
        s.refresh(t)
        t.last_error = f"{e}\n{traceback.format_exc()[-1500:]}"
        if t.attempts >= t.max_attempts or isinstance(e, (ValueError, PermissionError)):
            t.status, t.dedupe_key = "dead", None
            notify(s, "task_failed", f"Background task failed: {t.kind}", str(e)[:500], "/settings", important=True,
                   commit=False)
            log.error("task %s dead: %s", t.id, e)
        else:
            t.status = "queued"
            t.next_run_at = now() + timedelta(seconds=30 * 2 ** (t.attempts - 1))
            log.warning("task %s retry %s: %s", t.id, t.attempts, e)
    t.updated_at = now()
    s.add(t)
    s.commit()


def run_due_tasks(limit: int = 4) -> int:
    if not _lock.acquire(blocking=False):
        return 0
    try:
        with Session(get_engine()) as s:
            tasks = _due(s, limit)
            for t in tasks:
                run_task(s, t)
            return len(tasks)
    finally:
        _lock.release()


def recover_stuck() -> None:
    with Session(get_engine()) as s:
        for t in s.exec(select(Task).where(Task.status == "running")).all():
            t.status = "queued"
            s.add(t)
        s.commit()


_scheduler = None


def start_scheduler() -> None:
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    from . import tasks  # noqa: F401  registers handlers
    from .config import get_settings

    cfg = get_settings()
    recover_stuck()
    sch = BackgroundScheduler(daemon=True)
    sch.add_job(run_due_tasks, "interval", seconds=3, max_instances=1, coalesce=True, id="tasks")
    sch.add_job(tasks.schedule_source_polls, "interval", minutes=cfg.job_poll_minutes, id="sources",
                next_run_time=None)
    sch.add_job(tasks.schedule_email_polls, "interval", minutes=cfg.email_poll_minutes, id="email")
    sch.add_job(tasks.schedule_autopilot, "interval", minutes=30, id="autopilot")
    sch.add_job(tasks.schedule_digest, "cron", hour=8, minute=0, id="digest")
    sch.start()
    _scheduler = sch


def stop_scheduler() -> None:
    if _scheduler:
        _scheduler.shutdown(wait=False)
