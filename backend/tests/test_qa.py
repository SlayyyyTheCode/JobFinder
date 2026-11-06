"""Factuality gate: fabricated content must fail deterministic checks."""
from app.tailoring.qa import run_checks, status_of, total_years
from app.tailoring.schema import TailoredResume

TERMS = ["Spark", "AWS", "Kubernetes", "Airflow"]


def facts_of(ledger):
    out = {}
    for v in ledger.values():
        for f in (v if isinstance(v, list) else [v]):
            out[f.id] = f
    return out


def base(ledger, bullets1=None, skills=None, summary="", summary_ids=None):
    L = ledger
    return TailoredResume(
        summary=summary, summary_fact_ids=summary_ids or [],
        roles=[{"fact_id": f"F{L['emp1'].id}", "bullets": bullets1 if bullets1 is not None else [
            {"text": "Built Spark pipelines on AWS processing 2TB daily for 40 analysts", "fact_ids": [f"F{L['a1'].id}"]},
            {"text": "Reduced cloud costs by 30% by moving batch jobs to Databricks", "fact_ids": [f"F{L['a2'].id}"]}]},
               {"fact_id": f"F{L['emp2'].id}", "bullets": [
                   {"text": "Automated weekly SQL reporting for sales", "fact_ids": [f"F{L['a3'].id}"]}]}],
        skills=skills if skills is not None else [{"name": "Spark", "fact_id": f"F{L['skills'][2].id}"},
                                                  {"name": "AWS", "fact_id": f"F{L['skills'][3].id}"}],
        education_fact_ids=[f"F{L['edu'].id}"])


def fails(issues, check=None):
    return [i for i in issues if i["severity"] == "fail" and (check is None or i["check"] == check)]


def test_faithful_resume_passes(ledger):
    issues = run_checks(base(ledger), facts_of(ledger), TERMS)
    assert not fails(issues), issues


def test_invented_metric_fails(ledger):
    t = base(ledger, bullets1=[{"text": "Cut cloud costs by 45% via Databricks", "fact_ids": [f"F{ledger['a2'].id}"]}])
    assert fails(run_checks(t, facts_of(ledger), TERMS), "metrics")


def test_invented_team_size_fails(ledger):
    t = base(ledger, bullets1=[{"text": "Led a team of 12 engineers building Spark pipelines",
                                "fact_ids": [f"F{ledger['a1'].id}"]}])
    assert fails(run_checks(t, facts_of(ledger), TERMS), "metrics")


def test_skill_not_in_profile_fails(ledger):
    t = base(ledger, skills=[{"name": "Kubernetes", "fact_id": "F9999"}])
    assert fails(run_checks(t, facts_of(ledger), TERMS), "skills")


def test_job_keyword_injected_into_bullet_fails(ledger):
    t = base(ledger, bullets1=[{"text": "Built Spark pipelines on Kubernetes processing 2TB daily",
                                "fact_ids": [f"F{ledger['a1'].id}"]}])
    assert fails(run_checks(t, facts_of(ledger), TERMS), "unsupported_claim")


def test_uncited_bullet_fails(ledger):
    t = base(ledger, bullets1=[{"text": "Architected the data platform", "fact_ids": []}])
    assert fails(run_checks(t, facts_of(ledger), TERMS), "traceability")


def test_unknown_fact_id_fails(ledger):
    t = base(ledger, bullets1=[{"text": "Built pipelines", "fact_ids": ["F4242"]}])
    assert fails(run_checks(t, facts_of(ledger), TERMS), "traceability")


def test_achievement_moved_to_other_employer_fails(ledger):
    L = ledger
    t = base(ledger)
    t.roles[1].bullets.append(t.roles[0].bullets[0])  # Acme achievement under Beta
    assert fails(run_checks(t, facts_of(L), TERMS), "attribution")


def test_years_claim_allowed_only_up_to_real_tenure(ledger):
    f = facts_of(ledger)
    yrs = total_years(f)
    assert yrs >= 7
    ok = base(ledger, summary=f"Data engineer with {yrs}+ years of experience in Spark and AWS",
              summary_ids=[f"F{ledger['emp1'].id}", f"F{ledger['emp2'].id}"])
    assert not fails(run_checks(ok, f, TERMS), "metrics")
    bad = base(ledger, summary="Data engineer with 15+ years of experience",
               summary_ids=[f"F{ledger['emp1'].id}"])
    assert fails(run_checks(bad, f, TERMS), "metrics")


def test_omitted_role_warns(ledger):
    t = base(ledger)
    t.roles = t.roles[:1]
    issues = run_checks(t, facts_of(ledger), TERMS)
    assert any(i["check"] == "chronology" and i["severity"] == "warn" for i in issues)
    assert status_of(issues) == "warn"
