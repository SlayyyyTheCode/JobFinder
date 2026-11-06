"""REST API v1 (spec §16)."""
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
from sqlmodel import Session, SQLModel, func, select

from . import applications as A
from . import autopilot as AP
from .audit import audit
from .config import get_settings
from .db import get_session, put_setting
from .ingest.extract import IngestError
from .ingest.pipeline import save_upload, verify_fact
from .ledger import TYPE_ORDER, active_facts, update_fact
from .models import (Application, ApplicationEvent, AuditEvent, CandidateFact, ConsentRecord, EmailConnection,
                     EmailEvent, Job, JobMatch, JobSourceConnection, Notification, QuestionAnswer, Resume,
                     Tailoring, Task, now)
from .prefs import CRITERIA, DEFAULT_WEIGHTS, load_prefs, save_prefs, weights
from .worker import enqueue

r = APIRouter(prefix="/api/v1")
S = Depends(get_session)


def _404(obj, what="Not found"):
    if obj is None:
        raise HTTPException(404, what)
    return obj


def _dump(o: SQLModel | None) -> dict | None:
    if o is None:
        return None
    st = sa_inspect(o, raiseerr=False)
    if st is not None and st.session is not None and st.expired_attributes and not st.deleted:
        st.session.refresh(o)  # model_dump reads __dict__, which is empty after a commit expires the instance
    return o.model_dump(mode="json")


# ---------------------------------------------------------------- status / dashboard

@r.get("/status")
def status(s: Session = S):
    cfg = get_settings()
    return {
        "llm": {"provider": cfg.llm_provider, "model": cfg.llm_model, "fast_model": cfg.llm_fast_model,
                "configured": bool(cfg.gemini_api_key) if cfg.llm_provider == "gemini" else True},
        "gmail_configured": bool(cfg.google_client_secrets_file and Path(cfg.google_client_secrets_file).exists()),
        "outlook_configured": bool(cfg.ms_client_id),
        "has_resume": s.exec(select(Resume)).first() is not None,
        "verified_facts": s.exec(select(func.count()).select_from(CandidateFact).where(
            CandidateFact.active == True, CandidateFact.verified == True)).one(),  # noqa: E712
        "preferences_set": any(bool(v["value"]) for v in load_prefs(s).values() if v["rule_type"] != "info"),
        "sources": s.exec(select(func.count()).select_from(JobSourceConnection)).one(),
        "mailboxes": s.exec(select(func.count()).select_from(EmailConnection)).one(),
    }


@r.get("/dashboard")
def dashboard(s: Session = S):
    def count(model, *where):
        return s.exec(select(func.count()).select_from(model).where(*where)).one()
    by_status = dict(s.exec(select(Application.status, func.count()).group_by(Application.status)).all())
    pol = AP.get_policy(s)
    exceptions = s.exec(select(AuditEvent).where(AuditEvent.action == "autopilot.exception")
                        .order_by(AuditEvent.ts.desc()).limit(5)).all()
    follow = s.exec(select(Application).where(Application.follow_up_at != None, Application.follow_up_at <= now(),  # noqa: E711
                                              Application.status.in_(["SUBMITTED", "ACKNOWLEDGED"]))).all()
    return {
        "jobs_discovered": count(Job, Job.duplicate_of == None),  # noqa: E711
        "jobs_matching": count(JobMatch, JobMatch.eligible == True, JobMatch.score >= 60),  # noqa: E712
        "awaiting_review": by_status.get("READY_FOR_REVIEW", 0),
        "approved": by_status.get("APPROVED", 0),
        "submitted": sum(by_status.get(k, 0) for k in ("SUBMITTED", "ACKNOWLEDGED", "IN_REVIEW", "INTERVIEW", "OFFER", "REJECTED")),
        "interviews": by_status.get("INTERVIEW", 0),
        "offers": by_status.get("OFFER", 0),
        "rejections": by_status.get("REJECTED", 0),
        "action_required": by_status.get("ACTION_REQUIRED", 0),
        "follow_ups_due": [{"id": a.id, "job_id": a.job_id} for a in follow],
        "by_status": by_status,
        "email_to_confirm": count(EmailEvent, EmailEvent.link_status == "needs_confirmation"),
        "autopilot": {"enabled": pol.enabled, "paused": pol.paused, "remaining_today": AP.caps_remaining(s, pol)},
        "autopilot_exceptions": [_dump(e) for e in exceptions],
        "failed_tasks": count(Task, Task.status == "dead"),
    }


class KeyIn(BaseModel):
    api_key: str


@r.put("/settings/gemini-key")
def set_gemini_key(body: KeyIn):
    """Validate with a real call, then store in Windows Credential Manager (never in a file)."""
    from .config import KEYRING_GEMINI, KEYRING_SERVICE, get_settings as gs
    from .llm import LLMError, set_llm
    from .llm.gemini import GeminiProvider
    key = body.api_key.strip()
    if len(key) < 20 or any(c.isspace() for c in key):
        raise HTTPException(400, "That doesn't look like a valid API key.")
    cfg = gs()
    try:
        GeminiProvider(key, cfg.llm_model, cfg.llm_fast_model, cfg.embed_model).generate_text(
            "Reply with OK", fast=True, temperature=0)
    except LLMError as e:
        raise HTTPException(400, f"Gemini rejected the key: {str(e)[:200]}")
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_GEMINI, key)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Could not save the key securely: {e}")
    gs.cache_clear()
    set_llm(None)  # the key value is deliberately never logged or audited
    return {"ok": True}


@r.delete("/settings/gemini-key")
def clear_gemini_key():
    from .config import KEYRING_GEMINI, KEYRING_SERVICE, get_settings as gs
    from .llm import set_llm
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_GEMINI)
    except Exception:  # noqa: BLE001
        pass
    gs.cache_clear()
    set_llm(None)
    return {"ok": True}


# ---------------------------------------------------------------- resumes & profile

@r.post("/resumes")
async def upload_resume(file: UploadFile = File(...), s: Session = S):
    data = await file.read()
    try:
        res = save_upload(s, file.filename or "resume", data)
    except IngestError as e:
        raise HTTPException(400, str(e))
    if res.parse_status in ("pending", "failed"):
        enqueue(s, "resume.parse", {"resume_id": res.id}, dedupe_key=f"parse:{res.id}")
    return _dump(res)


@r.get("/resumes")
def list_resumes(s: Session = S):
    return [_dump(x) | {"raw_text": None} for x in s.exec(select(Resume).order_by(Resume.created_at.desc())).all()]


@r.get("/resumes/{rid}")
def get_resume(rid: int, s: Session = S):
    return _dump(_404(s.get(Resume, rid)))


@r.get("/resumes/{rid}/file")
def resume_file(rid: int, s: Session = S):
    res = _404(s.get(Resume, rid))
    return FileResponse(res.file_path, filename=res.filename)


@r.post("/resumes/{rid}/parse")
def reparse(rid: int, s: Session = S):
    _404(s.get(Resume, rid))
    t = enqueue(s, "resume.parse", {"resume_id": rid}, dedupe_key=f"parse:{rid}")
    return {"task_id": t.id if t else None}


@r.post("/resumes/{rid}/master")
def set_master(rid: int, s: Session = S):
    for x in s.exec(select(Resume)).all():
        x.is_master = x.id == rid
        s.add(x)
    s.commit()
    return {"ok": True}


@r.get("/candidate-profile")
def profile(s: Session = S):
    facts = active_facts(s)
    groups: dict[str, list] = {t: [] for t in TYPE_ORDER}
    for f in facts:
        groups.setdefault(f.type, []).append(_dump(f))
    return {"groups": groups, "total": len(facts), "verified": sum(f.verified for f in facts),
            "low_confidence": sum(1 for f in facts if f.confidence < 0.75 and not f.verified)}


class FactIn(BaseModel):
    type: str
    text: str = ""
    data: dict = {}
    parent_id: Optional[int] = None
    notes: str = ""


class FactPatch(BaseModel):
    text: Optional[str] = None
    data: Optional[dict] = None
    notes: Optional[str] = None


@r.post("/candidate-profile/facts")
def add_fact(body: FactIn, s: Session = S):
    if body.type not in TYPE_ORDER:
        raise HTTPException(400, f"type must be one of {TYPE_ORDER}")
    text = body.text
    if body.type == "employment":
        d = body.data
        text = f"{d.get('title', '')}, {d.get('employer', '')} ({d.get('start') or '?'} – {d.get('end') or '?'})"
    mx = s.exec(select(func.max(CandidateFact.sort_order))).one() or 0
    f = CandidateFact(type=body.type, text=text, data=body.data, parent_id=body.parent_id, notes=body.notes,
                      source_excerpt="(entered by user)", confidence=1.0, verified=True, verified_at=now(),
                      sort_order=mx + 1)
    s.add(f)
    s.commit()
    s.refresh(f)
    audit(s, "user", "fact.created", "fact", f.id, type=f.type)
    return _dump(f)


@r.patch("/candidate-profile/facts/{fid}")
def patch_fact(fid: int, body: FactPatch, s: Session = S):
    f = _404(s.get(CandidateFact, fid))
    f = update_fact(s, f, body.text, body.data, body.notes)
    audit(s, "user", "fact.updated", "fact", fid)
    return _dump(f)


@r.delete("/candidate-profile/facts/{fid}")
def delete_fact(fid: int, s: Session = S):
    f = _404(s.get(CandidateFact, fid))
    f.active = False
    s.add(f)
    for child in s.exec(select(CandidateFact).where(CandidateFact.parent_id == fid)).all():
        child.active = False
        s.add(child)
    s.commit()
    audit(s, "user", "fact.deleted", "fact", fid)
    return {"ok": True}


class VerifyIn(BaseModel):
    verified: bool = True


@r.post("/candidate-profile/facts/{fid}/verify")
def verify(fid: int, body: VerifyIn, s: Session = S):
    try:
        return _dump(verify_fact(s, fid, body.verified))
    except ValueError:
        raise HTTPException(404, "fact not found")


@r.post("/candidate-profile/verify-high-confidence")
def verify_high(s: Session = S):
    n = 0
    for f in active_facts(s):
        if not f.verified and f.confidence >= 0.9:
            f.verified, f.verified_at = True, now()
            s.add(f)
            n += 1
    s.commit()
    audit(s, "user", "fact.bulk_verified", "fact", None, count=n)
    return {"verified": n}


# ---------------------------------------------------------------- preferences

@r.get("/preferences")
def get_prefs(s: Session = S):
    return {"criteria": load_prefs(s), "weights": {**DEFAULT_WEIGHTS, **weights(s)}}


class PrefsIn(BaseModel):
    criteria: dict[str, dict] = {}
    weights: Optional[dict[str, float]] = None


@r.put("/preferences")
def put_prefs(body: PrefsIn, s: Session = S):
    try:
        save_prefs(s, body.criteria)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.weights is not None:
        put_setting(s, "scoring_weights", {k: float(v) for k, v in body.weights.items() if k in DEFAULT_WEIGHTS})
    audit(s, "user", "preferences.updated", "preferences")
    return get_prefs(s)


@r.get("/preferences/criteria")
def criteria_meta():
    return {k: {"default_rule": v[0], "description": v[2]} for k, v in CRITERIA.items()}


# ---------------------------------------------------------------- job sources

@r.get("/providers")
def providers():
    from .providers.registry import all_providers
    return [{"name": p.name, "label": p.label, "config_fields": p.config_fields,
             "capabilities": vars(p.capabilities)} for p in all_providers()]


@r.get("/job-sources")
def list_sources(s: Session = S):
    out = []
    for c in s.exec(select(JobSourceConnection)).all():
        n = s.exec(select(func.count()).select_from(Job).where(Job.source_connection_id == c.id)).one()
        out.append(_dump(c) | {"job_count": n})
    return out


class SourceIn(BaseModel):
    label: str = ""
    config: dict = {}


@r.post("/job-sources/{provider}/connect")
def connect_source(provider: str, body: SourceIn, s: Session = S):
    from .providers.registry import get_provider
    try:
        p = get_provider(provider)
    except KeyError:
        raise HTTPException(404, "unknown provider")
    for f in p.config_fields:
        if not f.get("optional") and not str(body.config.get(f["key"], "")).strip():
            raise HTTPException(400, f"{f['label']} is required")
    try:
        cfg = p.connect(body.config)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not reach {p.label}: {e}")
    c = JobSourceConnection(provider=provider, label=body.label or f"{p.label}: {next(iter(cfg.values()), '')}",
                            config=cfg)
    s.add(c)
    s.commit()
    s.refresh(c)
    audit(s, "user", "source.connected", "source", c.id, provider=provider)
    enqueue(s, "source.poll", {"connection_id": c.id}, dedupe_key=f"source:{c.id}")
    return _dump(c)


class SourcePatch(BaseModel):
    enabled: Optional[bool] = None
    autopilot_enabled: Optional[bool] = None
    label: Optional[str] = None
    config: Optional[dict] = None


@r.patch("/job-sources/{cid}")
def patch_source(cid: int, body: SourcePatch, s: Session = S):
    c = _404(s.get(JobSourceConnection, cid))
    if body.autopilot_enabled is not None and body.autopilot_enabled != c.autopilot_enabled:
        if body.autopilot_enabled:
            s.add(ConsentRecord(purpose="autopilot_source", scope=f"{c.provider}:{c.id}"))
        else:
            for cr in s.exec(select(ConsentRecord).where(ConsentRecord.purpose == "autopilot_source",
                                                         ConsentRecord.scope == f"{c.provider}:{c.id}",
                                                         ConsentRecord.revoked_at == None)).all():  # noqa: E711
                cr.revoked_at = now()
                s.add(cr)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    s.add(c)
    s.commit()
    audit(s, "user", "source.updated", "source", cid, **body.model_dump(exclude_none=True, exclude={"config"}))
    return _dump(c)


@r.delete("/job-sources/{cid}")
def delete_source(cid: int, s: Session = S):
    c = _404(s.get(JobSourceConnection, cid))
    s.delete(c)
    s.commit()
    audit(s, "user", "source.disconnected", "source", cid)
    return {"ok": True}


@r.post("/job-sources/{cid}/poll")
def poll_source(cid: int, s: Session = S):
    _404(s.get(JobSourceConnection, cid))
    t = enqueue(s, "source.poll", {"connection_id": cid}, dedupe_key=f"source:{cid}")
    return {"task_id": t.id if t else None}


# ---------------------------------------------------------------- jobs

def _job_row(s: Session, j: Job, m: JobMatch | None) -> dict:
    d = _dump(j)
    d.pop("description", None)
    d.pop("requirements", None)
    d["match"] = _dump(m)
    app = s.exec(select(Application).where(Application.job_id == j.id)).first()
    d["application"] = {"id": app.id, "status": app.status} if app else None
    return d


@r.get("/jobs")
def list_jobs(q: str = "", show: str = "active", min_score: float = 0, source: Optional[int] = None,
              limit: int = Query(200, le=1000), s: Session = S):
    stmt = select(Job, JobMatch).join(JobMatch, JobMatch.job_id == Job.id, isouter=True).where(Job.duplicate_of == None)  # noqa: E711
    if show == "saved":
        stmt = stmt.where(Job.saved == True)  # noqa: E712
    elif show == "dismissed":
        stmt = stmt.where(Job.dismissed == True)  # noqa: E712
    else:
        stmt = stmt.where(Job.dismissed == False)  # noqa: E712
    if show == "eligible":
        stmt = stmt.where(JobMatch.eligible == True)  # noqa: E712
    if q:
        like = f"%{q}%"
        stmt = stmt.where((Job.title.ilike(like)) | (Job.company.ilike(like)) | (Job.location.ilike(like)))
    if source:
        stmt = stmt.where(Job.source_connection_id == source)
    if min_score:
        stmt = stmt.where(JobMatch.score >= min_score)
    rows = s.exec(stmt.order_by(JobMatch.score.desc().nulls_last(), Job.discovered_at.desc()).limit(limit)).all()
    return [_job_row(s, j, m) for j, m in rows]


@r.get("/jobs/{jid}")
def get_job(jid: int, s: Session = S):
    j = _404(s.get(Job, jid))
    m = s.exec(select(JobMatch).where(JobMatch.job_id == jid)).first()
    tls = s.exec(select(Tailoring).where(Tailoring.job_id == jid).order_by(Tailoring.created_at.desc())).all()
    app = s.exec(select(Application).where(Application.job_id == jid)).first()
    dups = s.exec(select(Job).where(Job.duplicate_of == jid)).all()
    return {"job": _dump(j), "match": _dump(m), "application": _dump(app),
            "tailorings": [{"id": t.id, "status": t.status, "qa_status": t.qa_status, "created_at": t.created_at,
                            "error": t.error} for t in tls],
            "duplicates": [{"id": d.id, "provider": d.provider, "url": d.url} for d in dups]}


class UrlIn(BaseModel):
    url: str


@r.post("/jobs/import-url")
def import_job_url(body: UrlIn, s: Session = S):
    from .jobs.service import upsert_job
    from .providers.base import ProviderError
    from .providers.url_import import NeedsPaste, import_url
    try:
        nj = import_url(body.url)
    except NeedsPaste as e:
        raise HTTPException(422, {"needs_paste": True, "message": str(e)})
    except ProviderError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, {"needs_paste": True, "message": f"Could not import: {e}"})
    job, _ = upsert_job(s, nj)
    audit(s, "user", "job.imported", "job", job.id, url=body.url)
    enqueue(s, "job.match", {"job_id": job.id}, dedupe_key=f"match:{job.id}")
    return _dump(job)


class ManualJobIn(BaseModel):
    title: str
    company: str = ""
    location: str = ""
    description: str
    url: str = ""


@r.post("/jobs/manual")
def manual_job(body: ManualJobIn, s: Session = S):
    from .jobs.service import manual_job as mk
    if len(body.description.strip()) < 100:
        raise HTTPException(400, "Paste the full job description (at least 100 characters).")
    job = mk(s, body.title, body.company, body.description, body.location, body.url)
    enqueue(s, "job.match", {"job_id": job.id}, dedupe_key=f"match:{job.id}")
    return _dump(job)


class SearchIn(BaseModel):
    provider: str
    config: dict


@r.post("/jobs/search")
def search_jobs(body: SearchIn, s: Session = S):
    """One-off search without saving a connection."""
    from .jobs.service import upsert_job
    from .providers.registry import get_provider
    try:
        jobs, _ = get_provider(body.provider).search_jobs(body.config, None)
    except KeyError:
        raise HTTPException(404, "unknown provider")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
    out = []
    for nj in jobs:
        j, _ = upsert_job(s, nj)
        out.append(j.id)
    return {"job_ids": out}


class JobPatch(BaseModel):
    description: Optional[str] = None
    saved: Optional[bool] = None
    dismissed: Optional[bool] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None


@r.patch("/jobs/{jid}")
def patch_job(jid: int, body: JobPatch, s: Session = S):
    j = _404(s.get(Job, jid))
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(j, k, v)
    if "description" in data:
        j.requirements = {k: v for k, v in j.requirements.items() if k == "_requisition_id"}
    s.add(j)
    s.commit()
    if "description" in data:
        enqueue(s, "job.match", {"job_id": j.id}, dedupe_key=f"match:{j.id}")
    return _dump(j)


@r.post("/jobs/{jid}/match")
def rematch(jid: int, s: Session = S):
    _404(s.get(Job, jid))
    t = enqueue(s, "job.match", {"job_id": jid}, dedupe_key=f"match:{jid}")
    return {"task_id": t.id if t else None}


class TailorIn(BaseModel):
    options: dict = {}


@r.post("/jobs/{jid}/tailor-resume")
def tailor_resume(jid: int, body: TailorIn, s: Session = S):
    from .tailoring.schema import TailorOptions
    j = _404(s.get(Job, jid))
    if len(j.description) < 100:
        raise HTTPException(400, "This job has no full description yet. Paste it on the job page first.")
    opts = TailorOptions(**body.options)
    tl = Tailoring(job_id=jid, options=opts.model_dump(), status="generating")
    s.add(tl)
    s.commit()
    s.refresh(tl)
    enqueue(s, "resume.tailor", {"tailoring_id": tl.id}, dedupe_key=f"tailor:{tl.id}", max_attempts=2)
    audit(s, "user", "resume.tailoring.requested", "tailoring", tl.id, job_id=jid)
    return _dump(tl)


class QuestionIn(BaseModel):
    question: str


@r.post("/jobs/{jid}/draft-answer")
def draft_answer(jid: int, body: QuestionIn, s: Session = S):
    from .questions import draft_answer as d
    return d(s, _404(s.get(Job, jid)), body.question)


# ---------------------------------------------------------------- tailorings

@r.get("/tailorings")
def list_tailorings(job_id: Optional[int] = None, s: Session = S):
    stmt = select(Tailoring).order_by(Tailoring.created_at.desc())
    if job_id:
        stmt = stmt.where(Tailoring.job_id == job_id)
    return [{"id": t.id, "job_id": t.job_id, "status": t.status, "qa_status": t.qa_status,
             "created_at": t.created_at} for t in s.exec(stmt.limit(200)).all()]


@r.get("/tailorings/{tid}")
def get_tailoring(tid: int, s: Session = S):
    t = _404(s.get(Tailoring, tid))
    job = s.get(Job, t.job_id)
    app = s.exec(select(Application).where(Application.tailoring_id == tid)).first()
    return _dump(t) | {"job": {"id": job.id, "title": job.title, "company": job.company, "url": job.url},
                       "application": _dump(app)}


@r.get("/tailorings/{tid}/download/{kind}")
def download(tid: int, kind: str, s: Session = S):
    from .tailoring.engine import output_path
    t = _404(s.get(Tailoring, tid))
    try:
        p = output_path(t, kind)
    except FileNotFoundError:
        raise HTTPException(404, "file not available")
    return FileResponse(p, filename=p.name)


@r.get("/tailorings/{tid}/preview", response_class=HTMLResponse)
def preview(tid: int, s: Session = S):
    from .render import html_for
    t = _404(s.get(Tailoring, tid))
    if not t.content.get("view"):
        raise HTTPException(404, "not generated yet")
    return html_for(t.content["view"], t.options.get("template", "classic"))


class TailorEdit(BaseModel):
    content: dict


@r.patch("/tailorings/{tid}")
def edit_tailoring(tid: int, body: TailorEdit, s: Session = S):
    """User edits bullets/summary → re-run deterministic QA and re-render."""
    from . import render
    from .jobs.service import ensure_requirements
    from .tailoring.engine import _job_terms
    from .tailoring.qa import run_checks, status_of
    from .tailoring.schema import TailoredResume, TailorOptions
    t = _404(s.get(Tailoring, tid))
    if t.status == "approved":
        raise HTTPException(409, "Approved resumes are locked. Create a new tailoring to change it.")
    tr = TailoredResume.model_validate(body.content)
    facts = {f.id: f for f in active_facts(s, verified_only=True)}
    job = s.get(Job, t.job_id)
    issues = run_checks(tr, facts, _job_terms(ensure_requirements(s, job)))
    opt = TailorOptions(**t.options)
    view = render.build_view(tr, facts, opt)
    render.render_docx(view, Path(t.docx_path))
    render.render_pdf(view, Path(t.pdf_path), opt.template)
    t.content = {**tr.model_dump(), "view": view}
    t.qa = {"issues": issues, "pages": render.pdf_check(Path(t.pdf_path), view)[0], "edited_by_user": True}
    t.qa_status = status_of(issues)
    t.change_report = {**t.change_report, "tailored_text": render.to_text(view)}
    s.add(t)
    s.commit()
    audit(s, "user", "tailoring.edited", "tailoring", tid, qa=t.qa_status)
    return _dump(t)


@r.post("/tailorings/{tid}/approve")
def approve_tailoring(tid: int, s: Session = S):
    t = _404(s.get(Tailoring, tid))
    app = s.exec(select(Application).where(Application.tailoring_id == tid)).first()
    if app is None:
        app = A.create_for_tailoring(s, t)
    try:
        A.approve(s, app)
    except A.ApplyError as e:
        raise HTTPException(400, str(e))
    audit(s, "user", "tailoring.approved", "tailoring", tid)
    return _dump(app)


@r.post("/tailorings/{tid}/reject")
def reject_tailoring(tid: int, s: Session = S):
    t = _404(s.get(Tailoring, tid))
    t.status = "rejected"
    s.add(t)
    s.commit()
    audit(s, "user", "tailoring.rejected", "tailoring", tid)
    return _dump(t)


# ---------------------------------------------------------------- applications

@r.get("/applications")
def list_apps(status: Optional[str] = None, s: Session = S):
    stmt = select(Application, Job).join(Job, Job.id == Application.job_id).order_by(Application.updated_at.desc())
    if status:
        stmt = stmt.where(Application.status == status)
    return [_dump(a) | {"job": {"id": j.id, "title": j.title, "company": j.company, "location": j.location,
                                "provider": j.provider}} for a, j in s.exec(stmt).all()]


@r.get("/applications/{aid}")
def get_app(aid: int, s: Session = S):
    a = _404(s.get(Application, aid))
    ev = s.exec(select(ApplicationEvent).where(ApplicationEvent.application_id == aid)
                .order_by(ApplicationEvent.occurred_at)).all()
    emails = s.exec(select(EmailEvent).where(EmailEvent.application_id == aid)).all()
    t = s.get(Tailoring, a.tailoring_id) if a.tailoring_id else None
    return {"application": _dump(a), "job": _dump(s.get(Job, a.job_id)), "events": [_dump(e) for e in ev],
            "emails": [_dump(e) for e in emails],
            "tailoring": {"id": t.id, "qa_status": t.qa_status, "status": t.status,
                          "has_cover": bool(t.cover_docx_path)} if t else None,
            "preflight": A.preflight(s, a) if not a.submitted_at else []}


class AppIn(BaseModel):
    job_id: int
    status: str = "SUBMITTED"


@r.post("/applications")
def create_app(body: AppIn, s: Session = S):
    """Track an application made outside JobPilot."""
    j = _404(s.get(Job, body.job_id))
    if A.find_existing(s, j):
        raise HTTPException(409, "An application for this job already exists.")
    a = Application(job_id=j.id, idempotency_key=A.idem_key(j), status="READY_FOR_REVIEW", user_approved=True,
                    approved_by="user", method="external")
    s.add(a)
    s.commit()
    s.refresh(a)
    A.transition(s, a, body.status, "manual", "created_manual", force=True)
    return _dump(a)


@r.post("/applications/{aid}/approve")
def approve_app(aid: int, s: Session = S):
    a = _404(s.get(Application, aid))
    try:
        return _dump(A.approve(s, a))
    except A.ApplyError as e:
        raise HTTPException(400, str(e))


@r.post("/applications/{aid}/handoff")
def handoff(aid: int, s: Session = S):
    a = _404(s.get(Application, aid))
    try:
        return A.handoff(s, a)
    except A.ApplyError as e:
        raise HTTPException(400, str(e))


class SubmittedIn(BaseModel):
    confirmation_id: str = ""
    answers: dict = {}


@r.post("/applications/{aid}/submitted")
def submitted(aid: int, body: SubmittedIn, s: Session = S):
    a = _404(s.get(Application, aid))
    if not a.submitted_at:
        other = A.find_existing(s, s.get(Job, a.job_id))
        if other and other.id != a.id and other.submitted_at:
            raise HTTPException(409, "You already applied to this role.")
    try:
        return _dump(A.mark_submitted(s, a, body.confirmation_id, body.answers))
    except A.ApplyError as e:
        raise HTTPException(400, str(e))


@r.post("/applications/{aid}/withdraw")
def withdraw(aid: int, s: Session = S):
    a = _404(s.get(Application, aid))
    A.transition(s, a, "WITHDRAWN", "manual", "withdrawn", force=True)
    return _dump(a)


class StatusIn(BaseModel):
    status: str
    note: str = ""


@r.post("/applications/{aid}/events")
def manual_status(aid: int, body: StatusIn, s: Session = S):
    a = _404(s.get(Application, aid))
    try:
        A.transition(s, a, body.status, "manual", "manual_update", force=True, note=body.note)
    except A.ApplyError as e:
        raise HTTPException(400, str(e))
    return _dump(a)


class AppPatch(BaseModel):
    notes: Optional[str] = None
    follow_up_at: Optional[str] = None


@r.patch("/applications/{aid}")
def patch_app(aid: int, body: AppPatch, s: Session = S):
    from .providers.base import parse_dt
    a = _404(s.get(Application, aid))
    if body.notes is not None:
        a.notes = body.notes
    if body.follow_up_at is not None:
        a.follow_up_at = parse_dt(body.follow_up_at) if body.follow_up_at else None
    s.add(a)
    s.commit()
    return _dump(a)


@r.get("/application-states")
def states():
    return {"pipeline": A.PIPELINE, "exceptions": A.EXCEPTIONS}


# ---------------------------------------------------------------- email

@r.get("/email/connections")
def email_conns(s: Session = S):
    from .email.clients import connect_state
    return {"connections": [_dump(c) | {"token_enc": None} for c in s.exec(select(EmailConnection)).all()],
            "pending": {p: connect_state(p) for p in ("gmail", "outlook")}}


@r.post("/email/{provider}/connect")
def email_connect(provider: str):
    from .db import session_scope
    from .email.clients import start_connect
    if provider not in ("gmail", "outlook"):
        raise HTTPException(404, "unknown mail provider")

    def done(prov, account, enc):
        with session_scope() as s2:
            existing = s2.exec(select(EmailConnection).where(EmailConnection.provider == prov,
                                                             EmailConnection.account == account)).first()
            c = existing or EmailConnection(provider=prov, account=account)
            c.token_enc, c.status, c.last_error = enc, "connected", ""
            c.scopes = ["gmail.readonly"] if prov == "gmail" else ["Mail.Read", "User.Read"]
            s2.add(c)
            s2.add(ConsentRecord(purpose="email_monitoring", scope=f"{prov}:{account}:read-only"))
            s2.commit()
            s2.refresh(c)
            audit(s2, "user", "email.connected", "email_connection", c.id, provider=prov)
            enqueue(s2, "email.poll", {"connection_id": c.id}, dedupe_key=f"email:{c.id}", max_attempts=2)

    start_connect(provider, done)
    return {"state": "running", "message": "A browser window opened for sign-in. Approve read-only access."}


@r.delete("/email/connections/{cid}")
def email_disconnect(cid: int, s: Session = S):
    c = _404(s.get(EmailConnection, cid))
    for cr in s.exec(select(ConsentRecord).where(ConsentRecord.purpose == "email_monitoring",
                                                 ConsentRecord.scope.startswith(f"{c.provider}:{c.account}"),
                                                 ConsentRecord.revoked_at == None)).all():  # noqa: E711
        cr.revoked_at = now()
        s.add(cr)
    c.token_enc, c.status = "", "disconnected"
    s.add(c)
    s.commit()
    audit(s, "user", "email.disconnected", "email_connection", cid)
    s.delete(c)
    s.commit()
    return {"ok": True, "note": "Local tokens deleted. You can also revoke JobPilot in your Google/Microsoft account settings."}


@r.post("/email/connections/{cid}/poll")
def email_poll_now(cid: int, s: Session = S):
    _404(s.get(EmailConnection, cid))
    t = enqueue(s, "email.poll", {"connection_id": cid}, dedupe_key=f"email:{cid}", max_attempts=2)
    return {"task_id": t.id if t else None}


@r.get("/email/events")
def email_events(status: Optional[str] = None, s: Session = S):
    stmt = select(EmailEvent).order_by(EmailEvent.received_at.desc()).limit(300)
    if status:
        stmt = stmt.where(EmailEvent.link_status == status)
    return [_dump(e) for e in s.exec(stmt).all()]


class ConfirmIn(BaseModel):
    application_id: Optional[int] = None


@r.post("/email/events/{eid}/confirm")
def email_confirm(eid: int, body: ConfirmIn, s: Session = S):
    from .email.monitor import confirm
    ev = _404(s.get(EmailEvent, eid))
    try:
        confirm(s, ev, body.application_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _dump(ev)


# ---------------------------------------------------------------- autopilot

@r.get("/autopilot/settings")
def ap_get(s: Session = S):
    p = AP.get_policy(s)
    return {"policy": p.model_dump(), "remaining_today": AP.caps_remaining(s, p),
            "sources": [_dump(c) for c in s.exec(select(JobSourceConnection)).all()]}


@r.put("/autopilot/settings")
def ap_put(body: AP.AutopilotPolicy, s: Session = S):
    return {"policy": AP.save_policy(s, body).model_dump()}


@r.post("/autopilot/pause")
def ap_pause(s: Session = S):
    return {"policy": AP.set_paused(s, True).model_dump()}


@r.post("/autopilot/resume")
def ap_resume(s: Session = S):
    return {"policy": AP.set_paused(s, False).model_dump()}


@r.post("/autopilot/run")
def ap_run(s: Session = S):
    t = enqueue(s, "autopilot.run", {}, dedupe_key="autopilot", max_attempts=1)
    return {"task_id": t.id if t else None}


@r.get("/autopilot/activity")
def ap_activity(s: Session = S):
    return [_dump(e) for e in AP.recent_actions(s, 100)]


# ---------------------------------------------------------------- notifications / answers / audit / tasks

@r.get("/notifications")
def notifications(unread: bool = False, s: Session = S):
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(100)
    if unread:
        stmt = stmt.where(Notification.read_at == None)  # noqa: E711
    rows = s.exec(stmt).all()
    n_unread = s.exec(select(func.count()).select_from(Notification).where(Notification.read_at == None)).one()  # noqa: E711
    return {"items": [_dump(n) for n in rows], "unread": n_unread}


@r.post("/notifications/{nid}/read")
def read_notification(nid: int, s: Session = S):
    n = _404(s.get(Notification, nid))
    n.read_at = now()
    s.add(n)
    s.commit()
    return {"ok": True}


@r.post("/notifications/read-all")
def read_all(s: Session = S):
    for n in s.exec(select(Notification).where(Notification.read_at == None)).all():  # noqa: E711
        n.read_at = now()
        s.add(n)
    s.commit()
    return {"ok": True}


@r.get("/answers")
def answers(s: Session = S):
    from .questions import SENSITIVE_PATTERNS
    rows = {a.key: _dump(a) for a in s.exec(select(QuestionAnswer)).all()}
    for k in SENSITIVE_PATTERNS:
        rows.setdefault(k, {"key": k, "question": k.replace("_", " ").capitalize(), "category": "sensitive",
                            "answer": "", "confirmed": False})
    for k, q in (("notice_period", "Notice period"), ("motivation", "Why are you looking for a new role?"),
                 ("availability", "Earliest start date")):
        rows.setdefault(k, {"key": k, "question": q, "category": "standard", "answer": "", "confirmed": False})
    return list(rows.values())


class AnswerIn(BaseModel):
    key: str
    question: str = ""
    answer: str
    confirmed: bool = False


@r.put("/answers")
def put_answer(body: AnswerIn, s: Session = S):
    from .questions import SENSITIVE_PATTERNS
    a = s.exec(select(QuestionAnswer).where(QuestionAnswer.key == body.key)).first() or QuestionAnswer(key=body.key)
    a.question, a.answer, a.confirmed, a.updated_at = body.question, body.answer, body.confirmed, now()
    a.category = "sensitive" if body.key in SENSITIVE_PATTERNS else "standard"
    s.add(a)
    s.commit()
    audit(s, "user", "answer.updated", "answer", a.id, key=a.key, confirmed=a.confirmed)
    return _dump(a)


@r.get("/audit")
def audit_log(limit: int = Query(200, le=2000), s: Session = S):
    return [_dump(e) for e in s.exec(select(AuditEvent).order_by(AuditEvent.ts.desc()).limit(limit)).all()]


@r.get("/consents")
def consents(s: Session = S):
    return [_dump(c) for c in s.exec(select(ConsentRecord).order_by(ConsentRecord.granted_at.desc())).all()]


@r.get("/tasks")
def tasks(status: Optional[str] = None, s: Session = S):
    stmt = select(Task).order_by(Task.updated_at.desc()).limit(100)
    if status:
        stmt = stmt.where(Task.status == status)
    return [_dump(t) for t in s.exec(stmt).all()]


@r.post("/tasks/{tid}/retry")
def retry_task(tid: int, s: Session = S):
    t = _404(s.get(Task, tid))
    t.status, t.attempts, t.next_run_at, t.last_error = "queued", 0, now(), ""
    s.add(t)
    s.commit()
    return _dump(t)


# ---------------------------------------------------------------- data export / deletion (spec §18.2)

@r.get("/export")
def export(s: Session = S):
    buf = io.BytesIO()
    models = [Resume, CandidateFact, Job, JobMatch, Tailoring, Application, ApplicationEvent, EmailEvent,
              Notification, ConsentRecord, AuditEvent, QuestionAnswer, JobSourceConnection]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for m in models:
            rows: list[Any] = [o.model_dump(mode="json") for o in s.exec(select(m)).all()]
            z.writestr(f"{m.__name__}.json", json.dumps(rows, indent=1, default=str))
        for res in s.exec(select(Resume)).all():
            if Path(res.file_path).exists():
                z.write(res.file_path, f"originals/{res.filename}")
    buf.seek(0)
    audit(s, "user", "data.exported", "account")
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=jobpilot-export.zip"})


class DeleteIn(BaseModel):
    confirm: str


@r.post("/delete-all-data")
def delete_all(body: DeleteIn, s: Session = S):
    if body.confirm != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm.")
    import os
    import shutil
    import stat
    cfg = get_settings()
    for m in [Task, ApplicationEvent, EmailEvent, Application, Tailoring, JobMatch, Job, CandidateFact, Resume,
              Notification, QuestionAnswer, JobSourceConnection, EmailConnection]:
        for o in s.exec(select(m)).all():
            s.delete(o)
    s.commit()

    def onerr(func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    for d in (cfg.originals_dir, cfg.outputs_dir):
        shutil.rmtree(d, onexc=onerr)
        d.mkdir(parents=True, exist_ok=True)
    audit(s, "user", "data.deleted", "account")
    return {"ok": True}
