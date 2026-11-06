"""Deterministic factuality + quality checks (spec §9.3, §9.5, §18.4).
Each issue: {check, severity: fail|warn, message, item}. Any fail blocks approval/autopilot."""
import re
from datetime import date

from ..models import CandidateFact
from ..textutil import jaccard, norm, numbers, tokens
from .schema import TailoredResume

_YEARS_CLAIM = re.compile(r"(\d+)\s*\+?\s*(?:years|yrs)", re.I)


def parse_ym(s: str) -> tuple[int, int] | None:
    s = (s or "").strip()
    if not s:
        return None
    if norm(s) in ("present", "current", "now", "ongoing"):
        t = date.today()
        return (t.year, t.month)
    m = re.match(r"^(\d{4})(?:[-/](\d{1,2}))?", s)
    if m:
        return (int(m.group(1)), int(m.group(2) or 1))
    try:
        from dateutil import parser
        d = parser.parse(s, default=parser.parse("2000-01-01"))
        return (d.year, d.month)
    except (ValueError, OverflowError):
        return None


def total_years(facts: dict[int, CandidateFact]) -> int:
    spans = []
    for f in facts.values():
        if f.type == "employment":
            a, b = parse_ym(f.data.get("start", "")), parse_ym(f.data.get("end", "") or "present")
            if a and b and a <= b:
                spans.append((a[0] * 12 + a[1], b[0] * 12 + b[1]))
    spans.sort()
    months, cur = 0, None
    for s, e in spans:  # merge overlaps
        if cur and s <= cur[1]:
            cur = (cur[0], max(cur[1], e))
        else:
            if cur:
                months += cur[1] - cur[0]
            cur = (s, e)
    if cur:
        months += cur[1] - cur[0]
    return months // 12


def _ids(ids: list[str]) -> list[int]:
    out = []
    for i in ids:
        m = re.match(r"^\s*F?(\d+)\s*$", str(i))
        if m:
            out.append(int(m.group(1)))
    return out


def run_checks(t: TailoredResume, facts: dict[int, CandidateFact], job_terms: list[str],
               require_verified: bool = True) -> list[dict]:
    issues: list[dict] = []
    ledger_skills = {norm(f.text) for f in facts.values() if f.type == "skill"}
    ledger_norm = norm(" ".join(f.text for f in facts.values()))
    ledger_toks = set(tokens(ledger_norm))
    yrs = total_years(facts)

    def add(check, sev, msg, item=""):
        issues.append({"check": check, "severity": sev, "message": msg, "item": item})

    def cited_text(ids: list[int]) -> str:
        parts = []
        for i in ids:
            f = facts.get(i)
            if f:
                parts.append(f.text)
                parts.extend(str(v) for v in f.data.values() if isinstance(v, (str, int, float)))
                if f.parent_id and f.parent_id in facts:
                    parts.append(facts[f.parent_id].text)
        return "\n".join(parts)

    def check_claim(text: str, raw_ids: list[str], where: str, allowed_parents: set[int] | None = None):
        ids = _ids(raw_ids)
        if not ids:
            add("traceability", "fail", f"{where}: no source fact cited", text)
            return
        missing = [i for i in ids if i not in facts]
        if missing:
            add("traceability", "fail", f"{where}: cites unknown fact(s) {', '.join('F%d' % i for i in missing)}", text)
            return
        if require_verified:
            unv = [i for i in ids if not facts[i].verified]
            if unv:
                add("verification", "warn", f"{where}: relies on unverified fact(s) {', '.join('F%d' % i for i in unv)}", text)
        src = cited_text(ids)
        # numbers / metrics must come from cited facts
        src_nums = numbers(src)
        for n in numbers(text) - src_nums:
            ok = False
            for m in _YEARS_CLAIM.finditer(text):
                if f"{float(m.group(1)):g}" == n and int(m.group(1)) <= yrs:
                    ok = True
            if not ok:
                add("metrics", "fail", f"{where}: number '{n}' not found in cited facts", text)
        # skills/keywords from the job must not be introduced without evidence
        src_norm, txt_norm = norm(src), norm(text)
        for term in job_terms:
            tn = norm(term)
            if len(tn) < 2 or tn not in txt_norm:
                continue
            if tn in src_norm:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(tn)}(?![a-z0-9])", txt_norm) is None:
                continue
            term_toks = set(tokens(term))
            if term_toks and term_toks <= set(tokens(src)):
                continue  # every word of a multi-word phrase is evidenced by the cited facts
            if tn in ledger_norm or (term_toks and term_toks <= ledger_toks):
                add("attribution", "warn", f"{where}: mentions '{term}' — in your profile, but not in the facts cited "
                                           f"for this bullet. Confirm you used it here.", text)
            else:
                add("unsupported_claim", "fail", f"{where}: adds '{term}' which is not anywhere in your profile", text)
        # misattribution: achievements must belong to this role/project
        if allowed_parents is not None:
            for i in ids:
                f = facts[i]
                if f.type == "achievement" and f.parent_id and f.parent_id not in allowed_parents:
                    owner = facts.get(f.parent_id)
                    add("attribution", "fail",
                        f"{where}: uses F{i} which belongs to '{owner.text if owner else f.parent_id}'", text)
        # mostly-new content heuristic
        new_toks = [w for w in tokens(text) if w not in set(tokens(src)) and len(w) > 3]
        if len(new_toks) > max(6, 0.6 * len(tokens(text))):
            add("grounding", "warn", f"{where}: much of the wording is not in the source facts — please confirm", text)

    # summary
    if t.summary:
        check_claim(t.summary, t.summary_fact_ids, "Summary")

    # roles
    emp_ids = {i for i, f in facts.items() if f.type == "employment"}
    seen_roles = set()
    for r in t.roles:
        rid = _ids([r.fact_id])
        if not rid or rid[0] not in facts or facts[rid[0]].type != "employment":
            add("structure", "fail", f"Role references invalid employment fact {r.fact_id}")
            continue
        rid = rid[0]
        seen_roles.add(rid)
        label = facts[rid].data.get("employer") or facts[rid].text
        for b in r.bullets:
            check_claim(b.text, b.fact_ids, f"{label}", allowed_parents={rid})
    omitted = emp_ids - seen_roles
    for i in omitted:
        add("chronology", "warn", f"Role omitted from tailored resume: {facts[i].text}")

    for p in t.projects:
        pid = _ids([p.fact_id])
        if not pid or pid[0] not in facts or facts[pid[0]].type != "project":
            add("structure", "fail", f"Project references invalid project fact {p.fact_id}")
            continue
        for b in p.bullets:
            check_claim(b.text, b.fact_ids, f"Project {facts[pid[0]].text}", allowed_parents={pid[0]})

    # skills ⊆ ledger
    for sk in t.skills:
        sid = _ids([sk.fact_id])
        f = facts.get(sid[0]) if sid else None
        if f is None or f.type != "skill":
            if norm(sk.name) in ledger_skills:
                continue
            add("skills", "fail", f"Skill '{sk.name}' is not in your profile", sk.name)
        elif norm(sk.name) != norm(f.text) and jaccard(sk.name, f.text) < 0.5:
            add("skills", "fail", f"Skill '{sk.name}' does not match profile skill '{f.text}'", sk.name)

    for label, ids, typ in (("Education", t.education_fact_ids, "education"),
                            ("Certification", t.certification_fact_ids, "certification")):
        for i in _ids(ids):
            if i not in facts or facts[i].type != typ:
                add("structure", "fail", f"{label} references invalid fact F{i}")

    # chronology of ledger roles used
    for i in seen_roles:
        d = facts[i].data
        a, b = parse_ym(d.get("start", "")), parse_ym(d.get("end", "") or "present")
        if not a:
            add("chronology", "warn", f"Missing or unreadable start date for {facts[i].text}")
        elif b and a > b:
            add("chronology", "fail", f"Start date after end date for {facts[i].text}")
        elif a > (date.today().year, date.today().month):
            add("chronology", "fail", f"Start date in the future for {facts[i].text}")

    # duplicates
    bullets = [b.text for r in t.roles for b in r.bullets] + [b.text for p in t.projects for b in p.bullets]
    for x in range(len(bullets)):
        for y in range(x + 1, len(bullets)):
            if jaccard(bullets[x], bullets[y]) > 0.8:
                add("duplicate", "warn", "Near-duplicate bullets", bullets[y])

    # relevance / keyword stuffing
    alltext = norm(" ".join(bullets + [t.summary]))
    hits = [k for k in job_terms if norm(k) and norm(k) in alltext]
    if job_terms and not hits:
        add("relevance", "warn", "None of the job's key terms appear in the tailored resume")
    for k in hits:
        if alltext.count(norm(k)) > 4:
            add("keyword_stuffing", "warn", f"'{k}' repeated {alltext.count(norm(k))} times")
    if not bullets:
        add("completeness", "fail", "Tailored resume has no experience bullets")
    return issues


def status_of(issues: list[dict]) -> str:
    if any(i["severity"] == "fail" for i in issues):
        return "fail"
    if issues:
        return "warn"
    return "pass"
