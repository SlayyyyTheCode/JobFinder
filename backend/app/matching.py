"""Job matching & ranking (spec §8). Hard filters are deterministic and applied before scoring.
The score is an estimate of fit, not a prediction of interview probability."""
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .jobs.service import JobRequirements, ensure_requirements
from .ledger import active_facts, facts_for_prompt
from .llm import get_llm
from .llm.prompts import MATCH_SYSTEM
from .models import Job, JobMatch, now
from .prefs import load_prefs, weights
from .textutil import jaccard, norm

SENIORITY = ["entry", "mid", "senior", "lead", "head", "director", "executive"]


class ReqAssessment(BaseModel):
    requirement: str
    status: str = Field(description="met | partial | not_met")
    fact_ids: list[str] = Field(default_factory=list)
    note: str = ""


class MatchAssessment(BaseModel):
    requirements: list[ReqAssessment] = Field(default_factory=list)
    role_alignment: int = 50
    role_reason: str = ""
    domain_alignment: int = 50
    domain_reason: str = ""


def _contains_any(hay: str, needles: list[str]) -> str | None:
    h = norm(hay)
    for n in needles:
        if n and norm(n) in h:
            return n
    return None


def _annual(amount: float | None, period: str) -> float | None:
    if amount is None:
        return None
    p = (period or "").lower()
    if "month" in p:
        return amount * 12
    if "hour" in p:
        return amount * 2080
    if "week" in p:
        return amount * 52
    if "day" in p:
        return amount * 260
    return amount


def hard_and_soft_checks(job: Job, req: JobRequirements | None, prefs: dict) -> tuple[list[str], list[str], dict]:
    """Returns (hard_failures, soft_misses, dimension_scores for location/salary/seniority)."""
    hard, soft, dims = [], [], {}

    def fail(crit: str, msg: str):
        rt = prefs[crit]["rule_type"]
        (hard if rt == "hard" else soft if rt == "soft" else []).append(msg)

    v = lambda k: prefs[k]["value"]  # noqa: E731

    # excluded companies / keywords
    if v("excluded_companies") and _contains_any(job.company, v("excluded_companies")):
        fail("excluded_companies", f"Employer '{job.company}' is excluded")
    kw = _contains_any(f"{job.title}\n{job.description}", v("excluded_keywords") or [])
    if kw:
        fail("excluded_keywords", f"Mentions excluded keyword '{kw}'")

    # location
    locs = v("locations") or []
    arrangement = job.work_arrangement or (req.work_arrangement if req else "")
    if locs:
        remote_ok = any(norm(l) == "remote" for l in locs)
        if remote_ok and arrangement == "remote":
            dims["location"] = 100
        elif not job.location:
            dims["location"] = 50
        elif _contains_any(job.location, [l for l in locs if norm(l) != "remote"]):
            dims["location"] = 100
        else:
            dims["location"] = 0
            fail("locations", f"Location '{job.location}' not in {', '.join(locs)}")
    else:
        dims["location"] = 70

    wa = [norm(x) for x in v("work_arrangement") or []]
    if wa and arrangement in ("onsite", "hybrid", "remote") and arrangement not in wa:
        fail("work_arrangement", f"Work arrangement '{arrangement}' not in {', '.join(wa)}")
        dims["location"] = min(dims["location"], 30)

    et = v("employment_type") or []
    if et and job.employment_type and not _contains_any(job.employment_type, et):
        fail("employment_type", f"Employment type '{job.employment_type}' not wanted")

    # salary
    sm = v("salary_min")
    if sm and sm.get("amount"):
        want = _annual(float(sm["amount"]), sm.get("period", "year"))
        have = _annual(job.salary_max or job.salary_min, job.salary_period)
        cur_ok = not job.salary_currency or not sm.get("currency") or norm(job.salary_currency) == norm(sm["currency"])
        if have is None or not cur_ok:
            dims["salary"] = 50
        elif have >= want:
            dims["salary"] = 100
        else:
            dims["salary"] = max(0, int(100 * have / want) - 20)
            fail("salary_min", f"Salary up to {job.salary_currency} {have:,.0f}/yr below minimum {want:,.0f}/yr")
    else:
        dims["salary"] = 70

    # seniority
    want_s = [norm(x) for x in v("seniority") or []]
    js = req.seniority if req else "unknown"
    if not want_s or js not in SENIORITY:
        dims["seniority"] = 60
    elif js in want_s:
        dims["seniority"] = 100
    else:
        dist = min(abs(SENIORITY.index(js) - SENIORITY.index(w)) for w in want_s if w in SENIORITY) if any(
            w in SENIORITY for w in want_s) else 2
        dims["seniority"] = 60 if dist == 1 else 15
        if dist > 1:
            fail("seniority", f"Seniority '{js}' outside {', '.join(want_s)}")

    # titles
    titles = v("titles") or []
    if titles:
        best = max(jaccard(job.title, t) for t in titles)
        if best < 0.25 and not _contains_any(job.title, titles):
            fail("titles", f"Title '{job.title}' differs from target titles")

    # posting age
    max_age = v("max_posting_age_days")
    if max_age and job.posted_at:
        pa = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - pa).days
        if age > int(max_age):
            fail("max_posting_age_days", f"Posted {age} days ago")
    return hard, soft, dims


def match_job(s: Session, job: Job) -> JobMatch:
    prefs = load_prefs(s)
    req = ensure_requirements(s, job)
    hard, soft, dims = hard_and_soft_checks(job, req, prefs)
    facts = active_facts(s)

    reqs = [f"Skill: {x}" for x in req.required_skills] + [f"Qualification: {x}" for x in req.qualifications]
    if req.min_years_experience:
        reqs.append(f"At least {req.min_years_experience:g} years of relevant experience")
    reqs += [f"Preferred: {x}" for x in req.preferred_skills[:10]]
    reqs += [f"Responsibility: {x}" for x in req.responsibilities[:8]]

    assessment = MatchAssessment()
    if facts:
        prompt = (f"JOB: {job.title} at {job.company}\nIndustry: {req.industry}\n\nREQUIREMENTS:\n" +
                  "\n".join(f"- {r}" for r in reqs) + "\n\nCANDIDATE FACTS:\n" + facts_for_prompt(facts))
        assessment = get_llm().generate_structured(prompt, MatchAssessment, system=MATCH_SYSTEM, fast=True,
                                                   temperature=0)

    core = [a for a in assessment.requirements if not a.requirement.startswith(("Preferred:", "Responsibility:"))]
    pts = {"met": 1.0, "partial": 0.5}
    skills_score = 100 * sum(pts.get(a.status, 0) for a in core) / len(core) if core else 60
    industry = assessment.domain_alignment
    pref_ind = prefs["industries"]["value"] or []
    if pref_ind and _contains_any(req.industry + " " + job.description[:2000], pref_ind):
        industry = max(industry, 85)

    breakdown = {"skills": round(skills_score), "role": assessment.role_alignment, "seniority": dims["seniority"],
                 "industry": industry, "location": dims["location"], "salary": dims["salary"]}
    w = weights(s)
    score = sum(breakdown[k] * w[k] / 100 for k in breakdown)
    score -= 5 * len(soft)
    if _contains_any(job.company, prefs["preferred_companies"]["value"] or []):
        score += 5
    score = max(0.0, min(100.0, score))

    strong = [a.requirement for a in assessment.requirements if a.status == "met"][:10]
    gaps = [f"{a.requirement}" + (f" — {a.note}" if a.note else "") for a in assessment.requirements
            if a.status == "not_met"][:10]
    gaps += [f"Preference not met: {m}" for m in soft]
    eligible = not hard
    if not eligible:
        action = "Excluded by hard requirement"
    elif score >= 80:
        action = "Strong fit — tailor resume and apply"
    elif score >= 60:
        action = "Possible fit — review gaps before applying"
    else:
        action = "Weak fit — probably skip"
    explanation = (f"Estimated fit {score:.0f}/100. {assessment.role_reason} "
                   f"{len(strong)} key requirements evidenced, {len([a for a in core if a.status == 'not_met'])} not evidenced. "
                   f"{assessment.domain_reason}").strip()

    m = s.exec(select(JobMatch).where(JobMatch.job_id == job.id)).first() or JobMatch(job_id=job.id)
    m.score, m.eligible, m.hard_failures, m.breakdown = round(score, 1), eligible, hard, breakdown
    m.strong_matches, m.gaps, m.explanation, m.recommended_action, m.created_at = strong, gaps, explanation, action, now()
    s.add(m)
    s.commit()
    s.refresh(m)
    return m
