"""Job normalisation, deduplication, requirement extraction (spec §7, §8.1 steps 1-2)."""
import hashlib
from typing import Optional

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..llm import get_llm
from ..llm.prompts import JOB_REQ_SYSTEM, JOB_REQ_VERSION
from ..models import Job, now
from ..providers.base import NormalizedJob
from ..textutil import norm


class JobRequirements(BaseModel):
    normalized_title: str = ""
    seniority: str = "unknown"
    job_function: str = ""
    industry: str = ""
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list, description="degrees, certifications, licences required")
    min_years_experience: Optional[float] = None
    work_arrangement: str = "unknown"
    location: str = ""
    employment_type: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = ""
    salary_period: str = ""
    keywords: list[str] = Field(default_factory=list, description="important ATS keywords, max 25")
    sensitive_requirements: list[str] = Field(default_factory=list,
                                              description="security clearance, citizenship, work authorisation, licences, background checks")


def _city(loc: str) -> str:
    return norm(loc).split(",")[0].split("(")[0].strip()


def cross_key(title: str, company: str, location: str) -> str:
    raw = f"{norm(title)}|{norm(company)}|{_city(location)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def upsert_job(s: Session, n: NormalizedJob, source_connection_id: int | None = None) -> tuple[Job, bool]:
    """Returns (job, created). Exact provider id match → update. Same title/company/city from another
    source → stored but marked duplicate_of so it is hidden and never applied to twice."""
    existing = None
    if n.external_id:
        existing = s.exec(select(Job).where(Job.provider == n.provider, Job.external_id == n.external_id)).first()
    if existing:
        for f in ("title", "company", "location", "url", "apply_url", "description", "work_arrangement",
                  "employment_type", "salary_min", "salary_max", "salary_currency", "salary_period"):
            v = getattr(n, f)
            if v not in (None, ""):
                setattr(existing, f, v)
        existing.retrieved_at = now()
        s.add(existing)
        s.commit()
        return existing, False
    key = cross_key(n.title, n.company, n.location)
    dup = s.exec(select(Job).where(Job.dedupe_key == key, Job.duplicate_of == None)).first()  # noqa: E711
    job = Job(provider=n.provider, external_id=n.external_id, dedupe_key=key, url=n.url, apply_url=n.apply_url,
              title=n.title or "Untitled role", company=n.company, location=n.location,
              work_arrangement=n.work_arrangement, employment_type=n.employment_type,
              salary_min=n.salary_min, salary_max=n.salary_max, salary_currency=n.salary_currency,
              salary_period=n.salary_period, description=n.description, posted_at=n.posted_at,
              duplicate_of=dup.id if dup else None, source_connection_id=source_connection_id)
    if n.extra.get("requisition_id"):
        job.requirements = {"_requisition_id": n.extra["requisition_id"]}
    s.add(job)
    s.commit()
    s.refresh(job)
    return job, True


def manual_job(s: Session, title: str, company: str, description: str, location: str = "", url: str = "") -> Job:
    n = NormalizedJob(provider="manual", external_id="", title=title, company=company, location=location,
                      url=url, apply_url=url, description=description)
    job, _ = upsert_job(s, n)
    return job


def ensure_requirements(s: Session, job: Job, force: bool = False) -> JobRequirements:
    if job.requirements.get("_version") == JOB_REQ_VERSION and not force:
        return JobRequirements.model_validate({k: v for k, v in job.requirements.items() if not k.startswith("_")})
    llm = get_llm()
    prompt = (f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n"
              f"Employment type: {job.employment_type}\n\n<job_description>\n{job.description[:20000]}\n</job_description>")
    req = llm.generate_structured(prompt, JobRequirements, system=JOB_REQ_SYSTEM, fast=True, temperature=0)
    keep = {k: v for k, v in job.requirements.items() if k.startswith("_")}
    job.requirements = {**req.model_dump(), **keep, "_version": JOB_REQ_VERSION}
    if not job.work_arrangement and req.work_arrangement in ("onsite", "hybrid", "remote"):
        job.work_arrangement = req.work_arrangement
    if job.salary_min is None and req.salary_min:
        job.salary_min, job.salary_max = req.salary_min, req.salary_max
        job.salary_currency, job.salary_period = req.salary_currency, req.salary_period
    s.add(job)
    s.commit()
    return req


def requisition_id(job: Job) -> str:
    return str(job.requirements.get("_requisition_id") or job.external_id or "")
