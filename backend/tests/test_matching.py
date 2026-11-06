from app.matching import MatchAssessment, hard_and_soft_checks, match_job
from app.models import Job
from app.prefs import load_prefs, save_prefs


def test_hard_filters(s, job):
    save_prefs(s, {"excluded_companies": {"rule_type": "hard", "value": ["gamma"]},
                   "locations": {"rule_type": "hard", "value": ["Singapore"]}})
    hard, soft, _ = hard_and_soft_checks(job, None, load_prefs(s))
    assert any("excluded" in h for h in hard)


def test_location_and_salary(s, job):
    save_prefs(s, {"locations": {"rule_type": "hard", "value": ["London", "Remote"]},
                   "salary_min": {"rule_type": "soft", "value": {"amount": 150000, "currency": "SGD", "period": "year"}}})
    job.salary_max, job.salary_currency, job.salary_period = 9000, "SGD", "monthly"
    hard, soft, dims = hard_and_soft_checks(job, None, load_prefs(s))
    assert any("Location" in h for h in hard)
    assert any("Salary" in m for m in soft)  # 108k/yr < 150k, soft → ranking penalty only
    assert dims["salary"] < 100


def test_remote_ok(s):
    j = Job(provider="x", dedupe_key="r", title="Engineer", location="Berlin", work_arrangement="remote")
    save_prefs(s, {"locations": {"rule_type": "hard", "value": ["Singapore", "Remote"]}})
    hard, _, dims = hard_and_soft_checks(j, None, load_prefs(s))
    assert not hard and dims["location"] == 100


def test_match_score_and_explanation(s, job, ledger, llm):
    L = ledger
    llm.queue("MatchAssessment", MatchAssessment(requirements=[
        {"requirement": "Skill: Spark", "status": "met", "fact_ids": [f"F{L['a1'].id}"]},
        {"requirement": "Skill: AWS", "status": "met", "fact_ids": [f"F{L['a1'].id}"]},
        {"requirement": "Skill: Kubernetes", "status": "not_met"}], role_alignment=85, domain_alignment=70))
    save_prefs(s, {"locations": {"rule_type": "hard", "value": ["Singapore"]},
                   "seniority": {"rule_type": "soft", "value": ["senior", "lead"]}})
    m = match_job(s, job)
    assert m.eligible and 60 < m.score <= 100
    assert "Skill: Kubernetes" in " ".join(m.gaps)
    assert "estimate" in m.explanation.lower() or "Estimated" in m.explanation
