"""Resume tailoring (spec §9) + cover letters (§10)."""
import re
from pathlib import Path

from sqlmodel import Session

from .. import render
from ..audit import audit, notify
from ..config import get_settings
from ..jobs.service import ensure_requirements
from ..ledger import active_facts, facts_for_prompt
from ..llm import get_llm
from ..llm.prompts import (COVER_SYSTEM, COVER_VERSION, JUDGE_SYSTEM, JUDGE_VERSION, TAILOR_SYSTEM,
                           TAILOR_VERSION)
from ..models import CandidateFact, Job, Tailoring
from ..textutil import norm, slug
from .qa import _ids, run_checks, status_of
from .schema import JudgeResult, TailoredResume, TailorOptions

TONE = {
    "conservative": "Stay very close to the original wording; mostly select and reorder.",
    "balanced": "Rephrase for clarity and relevance while keeping meaning identical.",
    "targeted": "Rephrase strongly toward the job's language — but only where facts genuinely support it.",
}
LENGTH = {
    "one_page": "Target ONE page: summary ≤ 3 lines, ≤ 5 bullets for the most relevant role, ≤ 2 for older roles, ≤ 12 skills.",
    "two_page": "Target TWO pages at most.",
    "flexible": "Use the length the content warrants; omit weak or irrelevant bullets.",
}


class TailoringError(Exception):
    pass


def _job_terms(req) -> list[str]:
    terms = list(req.required_skills) + list(req.preferred_skills) + list(req.keywords)
    out, seen = [], set()
    for t in terms:
        t = t.strip()
        if t and len(t.split()) <= 4 and norm(t) not in seen:
            seen.add(norm(t))
            out.append(t)
    return out


def _prompt(job: Job, req, facts: list[CandidateFact], opt: TailorOptions, feedback: str = "") -> str:
    excluded = ", ".join(f"F{i}" for i in opt.exclude_project_ids)
    parts = [
        f"TARGET JOB: {job.title} at {job.company} ({job.location})",
        f"Seniority: {req.seniority}. Industry: {req.industry}.",
        "Required skills: " + "; ".join(req.required_skills),
        "Preferred skills: " + "; ".join(req.preferred_skills),
        "Responsibilities: " + "; ".join(req.responsibilities[:12]),
        "Qualifications: " + "; ".join(req.qualifications),
        "Keywords: " + "; ".join(req.keywords),
        "",
        "STYLE: " + TONE.get(opt.tone, TONE["balanced"]) + " " + LENGTH.get(opt.length, LENGTH["flexible"]),
        f"Spelling: {'British' if opt.spelling == 'uk' else 'American'} English. Use strong action verbs, no first person.",
        "Projects: " + ("include relevant ones" if opt.include_projects else "do not include projects") +
        (f" (never include {excluded})" if excluded else ""),
        "Order: " + ("keep roles in reverse-chronological order" if opt.ordering == "preserve"
                     else "keep roles reverse-chronological; within each role order bullets by relevance"),
        "",
        "CANDIDATE FACTS (the only allowed source of information):",
        facts_for_prompt(facts),
        "",
        "<job_description>",
        job.description[:15000],
        "</job_description>",
    ]
    if feedback:
        parts += ["", "YOUR PREVIOUS ATTEMPT FAILED THESE CHECKS — fix every one:", feedback]
    return "\n".join(parts)


def _judge(t: TailoredResume, facts: dict[int, CandidateFact]) -> list[dict]:
    items = []
    for r in t.roles:
        items += [(b.text, b.fact_ids) for b in r.bullets]
    for p in t.projects:
        items += [(b.text, b.fact_ids) for b in p.bullets]
    if t.summary:
        items.append((t.summary, t.summary_fact_ids))
    if not items:
        return []
    blocks = []
    for n, (text, ids) in enumerate(items, 1):
        src = "\n".join(f"  F{i}: {facts[i].text}" for i in _ids(ids) if i in facts)
        blocks.append(f"#{n} BULLET: {text}\n  SOURCES:\n{src}")
    res = get_llm().generate_structured("\n\n".join(blocks), JudgeResult, system=JUDGE_SYSTEM, fast=True,
                                        temperature=0)
    return [{"check": "overstatement", "severity": "warn", "message": f"Possible overstatement: {i.reason}",
             "item": i.bullet} for i in res.items if i.flagged]


def _change_report(t: TailoredResume, facts: dict[int, CandidateFact], view: dict, master_text: str,
                   req, issues: list[dict]) -> dict:
    used = set()
    for r in t.roles:
        for b in r.bullets:
            used.update(_ids(b.fact_ids))
    for p in t.projects:
        for b in p.bullets:
            used.update(_ids(b.fact_ids))
    removed = [f.text for f in facts.values() if f.type == "achievement" and f.id not in used]
    text = norm(render.to_text(view))
    master = norm(master_text)
    kw_in = [k for k in _job_terms(req) if norm(k) in text]
    kw_new_emphasis = [k for k in kw_in if master.count(norm(k)) < text.count(norm(k))]
    rewritten = sum(1 for r in t.roles for b in r.bullets
                    if not any(norm(b.text) == norm(facts[i].text) for i in _ids(b.fact_ids) if i in facts))
    sections = ["Summary"] if t.summary else []
    if t.roles:
        sections.append(f"Experience ({rewritten} bullets reworded)")
    if t.projects:
        sections.append("Projects")
    if t.skills:
        sections.append("Skills (reordered by relevance)")
    return {
        "sections_changed": sections,
        "keywords_incorporated": kw_in,
        "keywords_emphasised": kw_new_emphasis,
        "experience_prioritised": t.emphasis_notes,
        "content_removed": removed,
        "needs_confirmation": t.needs_confirmation + [i["item"] for i in issues if i["severity"] == "warn" and i["item"]],
        "unsupported_requirements": t.unsupported_requirements,
        "qa_summary": {"fail": sum(1 for i in issues if i["severity"] == "fail"),
                       "warn": sum(1 for i in issues if i["severity"] == "warn")},
        "master_text": master_text,
        "tailored_text": render.to_text(view),
    }


def master_view(facts: dict[int, CandidateFact], opt: TailorOptions) -> dict:
    """The untailored master resume (all facts, original order) for comparison."""
    from .schema import TBullet, TProject, TRole, TSkill
    t = TailoredResume(
        summary=next((f.text for f in facts.values() if f.type == "summary"), ""),
        roles=[TRole(fact_id=f"F{e.id}", bullets=[TBullet(text=a.text, fact_ids=[f"F{a.id}"]) for a in facts.values()
                                                  if a.parent_id == e.id]) for e in facts.values() if e.type == "employment"],
        projects=[TProject(fact_id=f"F{p.id}", bullets=[TBullet(text=a.text, fact_ids=[f"F{a.id}"]) for a in facts.values()
                                                        if a.parent_id == p.id]) for p in facts.values() if p.type == "project"],
        skills=[TSkill(name=f.text, fact_id=f"F{f.id}") for f in facts.values() if f.type == "skill"],
        education_fact_ids=[f"F{f.id}" for f in facts.values() if f.type == "education"],
        certification_fact_ids=[f"F{f.id}" for f in facts.values() if f.type == "certification"],
    )
    return render.build_view(t, facts, TailorOptions(**{**opt.model_dump(), "ordering": "preserve", "include_projects": True}))


def tailor(s: Session, tailoring_id: int) -> Tailoring:
    tl = s.get(Tailoring, tailoring_id)
    job = s.get(Job, tl.job_id)
    opt = TailorOptions(**(tl.options or {}))
    try:
        fact_list = active_facts(s, verified_only=True)
        if not any(f.type == "employment" for f in fact_list):
            raise TailoringError("No verified employment facts. Open Profile and verify your facts first.")
        facts = {f.id: f for f in fact_list}
        req = ensure_requirements(s, job)
        terms = _job_terms(req)
        llm = get_llm()

        feedback, t, issues = "", None, []
        for _attempt in range(2):
            t = llm.generate_structured(_prompt(job, req, fact_list, opt, feedback), TailoredResume,
                                        system=TAILOR_SYSTEM, temperature=0.3)
            issues = run_checks(t, facts, terms)
            fails = [i for i in issues if i["severity"] == "fail"]
            if not fails:
                break
            feedback = "\n".join(f"- [{i['check']}] {i['message']}: {i['item']}" for i in fails)
        issues += _judge(t, facts)

        view = render.build_view(t, facts, opt)
        out = get_settings().outputs_dir / f"t{tl.id}"
        out.mkdir(parents=True, exist_ok=True)
        base = f"{slug(view['name'] or 'resume')}-{slug(job.company or 'company')}-{slug(job.title)}"[:90]
        docx_p, pdf_p = out / f"{base}.docx", out / f"{base}.pdf"
        render.render_docx(view, docx_p)
        render.render_pdf(view, pdf_p, opt.template)
        pages, missing = render.pdf_check(pdf_p, view)
        if missing:
            issues.append({"check": "ats_readability", "severity": "fail",
                           "message": "Generated PDF text could not be re-read: " + ", ".join(missing), "item": ""})
        limit = {"one_page": 1, "two_page": 2}.get(opt.length)
        if limit and pages > limit:
            issues.append({"check": "length", "severity": "warn", "message": f"PDF is {pages} pages (target {limit})",
                           "item": ""})

        master_text = render.to_text(master_view(facts, opt))
        tl.content = {**t.model_dump(), "view": view}
        tl.qa = {"issues": issues, "pages": pages}
        tl.qa_status = status_of(issues)
        tl.change_report = _change_report(t, facts, view, master_text, req, issues)
        tl.docx_path, tl.pdf_path = str(docx_p), str(pdf_p)
        tl.model, tl.prompt_version = llm.model_name(), f"{TAILOR_VERSION}+{JUDGE_VERSION}"
        if opt.cover_letter:
            tl.cover_letter = cover_letter(job, fact_list, opt.motivation)
            cl = out / f"{base}-cover-letter.docx"
            render.render_letter(view["name"], view["contact_line"], tl.cover_letter, cl)
            tl.cover_docx_path = str(cl)
            tl.prompt_version += f"+{COVER_VERSION}"
        tl.status = "draft"
        tl.error = ""
        s.add(tl)
        s.commit()
        audit(s, "system", "resume.tailoring.completed", "tailoring", tl.id, job_id=job.id, qa=tl.qa_status,
              model=tl.model, prompt=tl.prompt_version)
        notify(s, "tailoring", f"Tailored resume ready: {job.title}",
               f"QA: {tl.qa_status}. Review the change report before approving.", f"/studio/{tl.id}")
        return tl
    except Exception as e:
        s.rollback()
        tl = s.get(Tailoring, tailoring_id)
        tl.status, tl.error = "failed", str(e)[:1000]
        s.add(tl)
        s.commit()
        if isinstance(e, TailoringError):
            raise ValueError(str(e)) from e  # non-retryable
        raise


def cover_letter(job: Job, facts: list[CandidateFact], motivation: str) -> str:
    prompt = (f"ROLE: {job.title} at {job.company}\n\nJOB DESCRIPTION:\n{job.description[:8000]}\n\n"
              f"CANDIDATE FACTS:\n{facts_for_prompt(facts)}\n\nUSER-SUPPLIED MOTIVATION: {motivation or '(none)'}")
    txt = get_llm().generate_text(prompt, system=COVER_SYSTEM, temperature=0.4)
    return re.sub(r"\[[^\]]{2,40}\]", "", txt).strip()


def output_path(tl: Tailoring, kind: str) -> Path:
    p = {"docx": tl.docx_path, "pdf": tl.pdf_path, "cover": tl.cover_docx_path}.get(kind)
    if not p:
        raise FileNotFoundError
    return Path(p)
