"""Job preferences (spec §6) with hard / soft / info rule types."""
from typing import Any

from sqlmodel import Session, select

from .db import get_setting
from .models import JobPreference

# criterion -> (default rule_type, default value, description)
CRITERIA: dict[str, tuple[str, Any, str]] = {
    "titles": ("soft", [], "Target job titles"),
    "job_functions": ("soft", [], "Job functions, e.g. AI/ML, data, product"),
    "industries": ("soft", [], "Industries"),
    "seniority": ("soft", [], "Seniority levels: entry, mid, senior, lead, head, director, executive"),
    "locations": ("hard", [], "Acceptable locations (city/country). Add 'Remote' to accept remote anywhere"),
    "work_arrangement": ("soft", [], "onsite, hybrid, remote"),
    "employment_type": ("soft", [], "Permanent, Contract, Temporary, Internship, Full-time, Part-time"),
    "salary_min": ("hard", None, "Minimum salary {amount, currency, period: month|year}"),
    "preferred_companies": ("soft", [], "Preferred employers"),
    "excluded_companies": ("hard", [], "Never apply to these employers"),
    "required_skills": ("soft", [], "Skills the role should use"),
    "excluded_keywords": ("hard", [], "Reject jobs mentioning these words in title/description"),
    "max_posting_age_days": ("info", 30, "Ignore postings older than N days"),
    "min_years_gap": ("info", 2, "Allow roles asking for up to N more years than you have"),
}

DEFAULT_WEIGHTS = {"skills": 30, "role": 25, "seniority": 15, "industry": 10, "location": 10, "salary": 10}


def load_prefs(s: Session) -> dict[str, dict]:
    rows = {p.criterion: p for p in s.exec(select(JobPreference)).all()}
    out = {}
    for k, (rt, dv, desc) in CRITERIA.items():
        p = rows.get(k)
        out[k] = {"rule_type": p.rule_type if p else rt, "value": p.value if p else dv, "description": desc}
    return out


def save_prefs(s: Session, data: dict[str, dict]) -> None:
    rows = {p.criterion: p for p in s.exec(select(JobPreference)).all()}
    for k, v in data.items():
        if k not in CRITERIA:
            continue
        rt = v.get("rule_type", CRITERIA[k][0])
        if rt not in ("hard", "soft", "info"):
            raise ValueError(f"invalid rule_type for {k}")
        p = rows.get(k) or JobPreference(criterion=k)
        p.rule_type, p.value = rt, v.get("value")
        s.add(p)
    s.commit()


def weights(s: Session) -> dict[str, float]:
    w = {**DEFAULT_WEIGHTS, **(get_setting(s, "scoring_weights", {}) or {})}
    total = sum(w.values()) or 1
    return {k: v * 100 / total for k, v in w.items()}
