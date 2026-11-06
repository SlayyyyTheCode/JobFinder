"""Resume ingestion pipeline (spec §5.2)."""
from pathlib import Path

from sqlmodel import Session, select

from ..audit import audit, notify
from ..config import get_settings
from ..llm import get_llm
from ..llm.prompts import EXTRACT_SYSTEM
from ..models import CandidateFact, Resume, now
from ..textutil import norm, support_score
from . import extract as X
from .schemas import ExtractedResume

LOW_CONFIDENCE = 0.75


def save_upload(s: Session, filename: str, data: bytes) -> Resume:
    fmt = X.detect_format(filename, data)
    digest = X.sha256(data)
    existing = s.exec(select(Resume).where(Resume.sha256 == digest)).first()
    if existing:
        return existing
    ext = {"pdf": ".pdf", "docx": ".docx", "doc": ".doc"}[fmt]
    path = get_settings().originals_dir / f"{digest}{ext}"
    path.write_bytes(data)
    try:
        X.malware_scan(path)
    except X.IngestError:
        path.unlink(missing_ok=True)
        raise
    path.chmod(0o444)  # originals are immutable
    first = s.exec(select(Resume)).first() is None
    r = Resume(filename=Path(filename).name, sha256=digest, format=fmt, file_path=str(path), is_master=first)
    s.add(r)
    s.commit()
    s.refresh(r)
    audit(s, "user", "resume.uploaded", "resume", r.id, filename=r.filename, format=fmt)
    return r


def _get_text(r: Resume) -> tuple[str, list[tuple[bytes, str]]]:
    path = Path(r.file_path)
    if r.format == "doc":
        path = X.convert_doc_to_docx(path)
    data = path.read_bytes()
    if r.format == "pdf":
        text = X.pdf_text(data)
        if X.needs_ocr(text):  # scanned PDF → let the multimodal model read the document itself
            return "", [(data, "application/pdf")]
        return text, []
    return X.docx_text(data), []


def parse_resume(s: Session, resume_id: int) -> int:
    r = s.get(Resume, resume_id)
    if r is None:
        raise ValueError("resume not found")
    r.parse_status = "parsing"
    s.add(r)
    s.commit()
    try:
        text, files = _get_text(r)
        llm = get_llm()
        prompt = ("Parse this resume.\n\n<resume>\n" + text + "\n</resume>") if text else \
            "This is a scanned resume. Transcribe it into raw_text and parse it."
        ex = llm.generate_structured(prompt, ExtractedResume, system=EXTRACT_SYSTEM, files=files, temperature=0)
        if not text:
            text = ex.raw_text or ""
        r.raw_text = text
        n = store_facts(s, r, ex)
        r.parse_status = "parsed"
        r.parse_error = ""
        s.add(r)
        s.commit()
        audit(s, "system", "resume.parsed", "resume", r.id, facts=n, model=llm.model_name())
        notify(s, "resume", "Resume parsed", f"{n} facts extracted from {r.filename}. Review and verify them.", "/profile")
        return n
    except Exception as e:
        r.parse_status = "failed"
        r.parse_error = str(e)[:1000]
        s.add(r)
        s.commit()
        raise


def _conf(base: float, snippet: str, raw: str) -> float:
    """Lower confidence when extracted text can't be found in the source (possible hallucination/mis-parse)."""
    if not raw:
        return min(base, 0.7)
    sup = support_score(snippet, raw)
    return round(min(base, 1.0) * (1.0 if sup >= 0.9 else sup), 2)


def store_facts(s: Session, r: Resume, ex: ExtractedResume) -> int:
    raw = r.raw_text
    existing = {(f.type, norm(f.text)) for f in s.exec(select(CandidateFact).where(CandidateFact.active == True)).all()}  # noqa: E712
    added = 0
    order = 0

    def add(type_: str, text: str, data: dict, conf: float = 1.0, parent: int | None = None,
            excerpt: str = "") -> CandidateFact | None:
        nonlocal added, order
        text = (text or "").strip()
        if not text or (type_, norm(text)) in existing:
            return None
        order += 1
        f = CandidateFact(type=type_, text=text, data=data, parent_id=parent, source_resume_id=r.id,
                          source_excerpt=excerpt or text, confidence=_conf(conf, excerpt or text, raw),
                          sort_order=order)
        s.add(f)
        s.flush()
        existing.add((type_, norm(text)))
        added += 1
        return f

    c = ex.contact
    if c.name:
        add("contact", c.name, c.model_dump())
    if ex.summary:
        add("summary", ex.summary, {})
    for e in ex.employment:
        label = f"{e.title}, {e.employer} ({e.start or '?'} – {e.end or '?'})"
        parent = add("employment", label, {"employer": e.employer, "title": e.title, "location": e.location,
                                           "start": e.start, "end": e.end}, e.confidence,
                     excerpt=f"{e.title} {e.employer}")
        pid = parent.id if parent else None
        for b in e.achievements:
            add("achievement", b, {"employer": e.employer, "title": e.title}, e.confidence, pid)
    for ed in ex.education:
        label = ", ".join(x for x in [ed.qualification, ed.field, ed.institution] if x)
        add("education", label, ed.model_dump(), ed.confidence, excerpt=f"{ed.qualification} {ed.institution}")
    for sk in ex.skills:
        add("skill", sk.name, {"category": sk.category, "level": sk.level})
    for ce in ex.certifications:
        add("certification", ce.name, ce.model_dump())
    for p in ex.projects:
        parent = add("project", p.name, {"description": p.description, "tools": p.tools},
                     excerpt=f"{p.name} {p.description}")
        pid = parent.id if parent else None
        for b in p.bullets:
            add("achievement", b, {"project": p.name}, 1.0, pid)
    for l in ex.languages:
        add("language", l, {})
    for a in ex.awards:
        add("award", a, {})
    for pub in ex.publications:
        add("publication", pub, {})
    s.commit()
    return added


def verify_fact(s: Session, fact_id: int, verified: bool = True) -> CandidateFact:
    f = s.get(CandidateFact, fact_id)
    if f is None:
        raise ValueError("fact not found")
    f.verified = verified
    f.verified_at = now() if verified else None
    s.add(f)
    s.commit()
    audit(s, "user", "fact.verified" if verified else "fact.unverified", "fact", fact_id)
    return f
