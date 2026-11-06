"""Candidate fact ledger helpers."""
from sqlmodel import Session, select

from .models import CandidateFact, FactRevision, now

TYPE_ORDER = ["contact", "summary", "employment", "achievement", "project", "education", "certification",
              "skill", "language", "award", "publication"]


def active_facts(s: Session, verified_only: bool = False) -> list[CandidateFact]:
    q = select(CandidateFact).where(CandidateFact.active == True)  # noqa: E712
    if verified_only:
        q = q.where(CandidateFact.verified == True)  # noqa: E712
    return list(s.exec(q.order_by(CandidateFact.sort_order)).all())


def fid(f: CandidateFact) -> str:
    return f"F{f.id}"


def facts_for_prompt(facts: list[CandidateFact], include_contact: bool = False) -> str:
    lines = []
    for f in facts:
        if f.type == "contact" and not include_contact:
            continue
        extra = ""
        if f.type == "skill" and f.data.get("level") not in (None, "", "unspecified"):
            extra = f" (level: {f.data['level']})"
        parent = f" [under F{f.parent_id}]" if f.parent_id else ""
        flag = "" if f.verified else " (unverified)"
        lines.append(f"F{f.id} {f.type.upper()}{parent}: {f.text}{extra}{flag}")
    return "\n".join(lines)


def update_fact(s: Session, f: CandidateFact, text: str | None, data: dict | None, notes: str | None) -> CandidateFact:
    s.add(FactRevision(fact_id=f.id, version=f.version, text=f.text, data=f.data))
    if text is not None:
        f.text = text
    if data is not None:
        f.data = {**f.data, **data}
        if f.type == "employment":
            d = f.data
            f.text = f"{d.get('title', '')}, {d.get('employer', '')} ({d.get('start') or '?'} – {d.get('end') or '?'})"
    if notes is not None:
        f.notes = notes
    f.version += 1
    f.updated_at = now()
    f.confidence = 1.0  # user-edited
    s.add(f)
    s.commit()
    return f


def candidate_skill_names(facts: list[CandidateFact]) -> set[str]:
    from .textutil import norm
    return {norm(f.text) for f in facts if f.type == "skill"}


def contact(facts: list[CandidateFact]) -> dict:
    for f in facts:
        if f.type == "contact":
            return f.data
    return {}
