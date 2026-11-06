from datetime import datetime, timezone

from sqlmodel import select

from app import applications as A
from app import autopilot as AP
from app.email import clients
from app.email.monitor import EmailClass, poll, prefilter
from app.models import Application, EmailConnection, EmailEvent, Notification, Tailoring
from app.questions import classify, draft_answer


def _submitted_app(s, job):
    t = Tailoring(job_id=job.id, status="draft", qa_status="pass")
    s.add(t)
    s.commit()
    a = A.create_for_tailoring(s, t)
    A.mark_submitted(s, a)
    return a


def _conn(s):
    c = EmailConnection(provider="gmail", account="me@example.com", token_enc="x")
    s.add(c)
    s.commit()
    s.refresh(c)
    return c


def test_prefilter_skips_unrelated_mail():
    mk = lambda subj, snd="friend@example.com": clients.Msg("1", snd, subj, "", None)  # noqa: E731
    assert prefilter(mk("Interview invitation – Lead Data Engineer"))
    assert prefilter(mk("Update", "no-reply@greenhouse.io"))
    assert not prefilter(mk("Dinner on Friday?"))


def test_email_links_and_advances_status(s, job, llm, monkeypatch):
    a = _submitted_app(s, job)
    c = _conn(s)
    msgs = [clients.Msg("gmail:1", "Gamma Talent <talent@gamma.com>", "Interview invitation: Lead Data Engineer",
                        "We'd like to invite you to interview", datetime.now(timezone.utc)),
            clients.Msg("gmail:2", "mum@example.com", "Dinner?", "see you", datetime.now(timezone.utc))]
    monkeypatch.setattr(clients, "fetch", lambda p, t, since: (msgs, "newtok"))
    llm.queue("EmailClass", EmailClass(event_type="interview", company="Gamma", role="Lead Data Engineer", confidence=0.95))
    stats = poll(s, c.id)
    assert stats["classified"] == 1  # unrelated email never sent to the model
    s.refresh(a)
    assert a.status == "INTERVIEW"
    assert s.exec(select(Notification).where(Notification.important == True)).first()  # noqa: E712
    # re-poll does not reprocess
    assert poll(s, c.id)["classified"] == 0


def test_ambiguous_email_requires_confirmation(s, job, llm, monkeypatch):
    _submitted_app(s, job)
    c = _conn(s)
    msgs = [clients.Msg("gmail:9", "noreply@ats.com", "Your application", "status update", datetime.now(timezone.utc))]
    monkeypatch.setattr(clients, "fetch", lambda p, t, since: (msgs, "tok"))
    llm.queue("EmailClass", EmailClass(event_type="offer", company="", role="", confidence=0.6))
    poll(s, c.id)
    ev = s.exec(select(EmailEvent)).one()
    assert ev.link_status == "needs_confirmation"
    assert s.exec(select(Application)).one().status == "SUBMITTED"


def test_sensitive_questions_never_ai_answered(s, job, llm):
    assert classify("Do you require visa sponsorship to work in Singapore?") == "work_authorisation"
    assert classify("Do you have any criminal convictions?") == "criminal_history"
    assert classify("What is your expected salary?") == "salary_expectations"
    out = draft_answer(s, job, "Are you a Singapore citizen or PR?")
    assert out["sensitive"] and out["answer"] == ""
    assert not any(name == "text" for name, _ in llm.prompts)
    assert draft_answer(s, job, "Describe a relevant project")["sensitive"] is False


def test_autopilot_off_by_default_and_safety_invariants(s):
    p = AP.get_policy(s)
    assert p.enabled is False and p.auto_submit.enabled is False
    p.enabled = True
    p.auto_submit.pause_on_sensitive_questions = False
    p.require_user_approval_for = []
    saved = AP.save_policy(s, p)
    assert saved.auto_submit.pause_on_sensitive_questions is True
    assert "work_authorisation" in saved.require_user_approval_for


def test_autopilot_caps_and_pause(s, ledger, job, llm, monkeypatch):
    from app.matching import MatchAssessment
    from app.models import JobSourceConnection, Job
    src = JobSourceConnection(provider="greenhouse", config={"board": "gamma"}, autopilot_enabled=True)
    s.add(src)
    s.commit()
    jobs = [job]
    for i in range(3):
        j = Job(provider="greenhouse", external_id=f"x{i}", dedupe_key=f"d{i}", title="Lead Data Engineer",
                company=f"Co{i}", location="Singapore", description="Spark AWS " * 30, requirements=job.requirements)
        s.add(j)
        jobs.append(j)
    s.commit()
    for j in jobs:
        j.source_connection_id = src.id
        s.add(j)
    s.commit()
    llm.queue("MatchAssessment", MatchAssessment(requirements=[{"requirement": "Skill: Spark", "status": "met"}],
                                                 role_alignment=95, domain_alignment=90))

    def fake_tailor(sess, tid):
        t = sess.get(Tailoring, tid)
        t.status, t.qa_status = "draft", "pass"
        sess.add(t)
        sess.commit()
        return t
    monkeypatch.setattr("app.tailoring.engine.tailor", fake_tailor)
    p = AP.get_policy(s)
    p.enabled, p.minimum_match_score, p.max_applications_per_day = True, 50, 2
    AP.save_policy(s, p)
    stats = AP.run(s)
    assert stats["prepared"] == 2  # daily cap enforced
    apps = s.exec(select(Application)).all()
    assert all(a.approved_by == "autopilot" and a.status == "APPROVED" and not a.submitted_at for a in apps)
    assert AP.run(s)["prepared"] == 0
    AP.set_paused(s, True)
    assert AP.run(s) == {"skipped": "paused"}
