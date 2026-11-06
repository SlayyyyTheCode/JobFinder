import pytest

from app import applications as A
from app.models import Application, Job, Tailoring


def _tl(s, job, qa="pass"):
    t = Tailoring(job_id=job.id, status="draft", qa_status=qa)
    s.add(t)
    s.commit()
    s.refresh(t)
    return t


def test_create_is_idempotent(s, job):
    t1, t2 = _tl(s, job), _tl(s, job)
    a1 = A.create_for_tailoring(s, t1)
    a2 = A.create_for_tailoring(s, t2)
    assert a1.id == a2.id
    assert len(s.exec(__import__("sqlmodel").select(Application)).all()) == 1


def test_same_role_other_source_is_detected(s, job):
    a = A.create_for_tailoring(s, _tl(s, job))
    A.mark_submitted(s, a)
    dup = Job(provider="mycareersfuture", external_id="abc", dedupe_key=job.dedupe_key, title=job.title,
              company=job.company, location=job.location, duplicate_of=job.id)
    s.add(dup)
    s.commit()
    assert A.find_existing(s, dup).id == a.id


def test_mark_submitted_idempotent_and_audited(s, job):
    a = A.create_for_tailoring(s, _tl(s, job))
    A.mark_submitted(s, a, "CONF-1")
    first = a.submitted_at
    A.mark_submitted(s, a, "CONF-2")
    assert a.submitted_at == first and a.confirmation_id == "CONF-1"
    assert a.status == "SUBMITTED" and a.user_approved


def test_cannot_approve_failed_qa(s, job):
    a = A.create_for_tailoring(s, _tl(s, job, qa="fail"))
    with pytest.raises(A.ApplyError):
        A.approve(s, a)
    assert "factuality" in " ".join(A.preflight(s, a))


def test_automated_sources_never_regress_status(s, job):
    a = A.create_for_tailoring(s, _tl(s, job))
    A.mark_submitted(s, a)
    A.transition(s, a, "INTERVIEW", "email")
    assert a.status == "INTERVIEW"
    A.transition(s, a, "ACKNOWLEDGED", "email")  # late confirmation email
    assert a.status == "INTERVIEW"
    A.transition(s, a, "REJECTED", "email")
    A.transition(s, a, "INTERVIEW", "email")  # terminal stays terminal
    assert a.status == "REJECTED"
    A.transition(s, a, "IN_REVIEW", "manual", force=True)  # user correction allowed
    assert a.status == "IN_REVIEW"


def test_handoff_returns_official_url(s, job):
    a = A.create_for_tailoring(s, _tl(s, job))
    out = A.handoff(s, a)
    assert out["url"] == job.apply_url
