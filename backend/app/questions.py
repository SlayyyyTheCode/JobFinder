"""Application question assistance (spec §10.2). Sensitive declarations are never AI-answered."""
import re

from sqlmodel import Session, select

from .ledger import active_facts, facts_for_prompt
from .llm import get_llm
from .llm.prompts import QUESTION_SYSTEM
from .models import Job, QuestionAnswer

SENSITIVE_PATTERNS = {
    "work_authorisation": r"work (permit|pass|authori[sz]ation)|right to work|visa|sponsor|citizen|permanent resident|\bpr\b|employment pass",
    "security_clearance": r"clearance|vetting|baseline|nv1|nv2|secret",
    "criminal_history": r"criminal|convict|offen[cs]e|arrest|court",
    "demographic_questions": r"gender|race|ethnic|religio|sexual orientation|veteran|age\b|date of birth|marital|nationality",
    "disability_questions": r"disabilit|impairment|accommodat|medical condition|health condition",
    "conflict_of_interest": r"conflict of interest|related to (any|an) employee|relative|family member works",
    "legal_declarations": r"declare|declaration|attest|certify that|true and correct|non-compete|bankrupt",
    "salary_expectations": r"salary|compensation|pay expectation|expected (pay|package)|current (pay|ctc|salary)",
}


def classify(question: str) -> str | None:
    q = question.lower()
    for key, pat in SENSITIVE_PATTERNS.items():
        if re.search(pat, q):
            return key
    return None


def draft_answer(s: Session, job: Job, question: str) -> dict:
    key = classify(question)
    if key:
        saved = s.exec(select(QuestionAnswer).where(QuestionAnswer.key == key)).first()
        if saved and saved.confirmed and saved.answer:
            return {"sensitive": True, "category": key, "answer": saved.answer, "source": "your saved answer",
                    "requires_confirmation": True}
        return {"sensitive": True, "category": key, "answer": "",
                "source": "This is a sensitive declaration. JobPilot will not guess it — enter and confirm "
                          "your answer under Settings → Application answers.", "requires_confirmation": True}
    standard = s.exec(select(QuestionAnswer).where(QuestionAnswer.category == "standard",
                                                   QuestionAnswer.confirmed == True)).all()  # noqa: E712
    prefs = "\n".join(f"- {a.question or a.key}: {a.answer}" for a in standard)
    facts = active_facts(s, verified_only=True)
    prompt = (f"ROLE: {job.title} at {job.company}\nJOB DESCRIPTION (excerpt):\n{job.description[:5000]}\n\n"
              f"CANDIDATE FACTS:\n{facts_for_prompt(facts)}\n\nUSER-PROVIDED ANSWERS/PREFERENCES:\n{prefs or '(none)'}\n\n"
              f"QUESTION: {question}")
    return {"sensitive": False, "category": "standard",
            "answer": get_llm().generate_text(prompt, system=QUESTION_SYSTEM, fast=True, temperature=0.3),
            "source": "drafted from your verified facts — review before using", "requires_confirmation": True}
