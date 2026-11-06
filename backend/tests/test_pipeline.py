import io
from pathlib import Path

import docx
import pytest

from app.ingest.extract import IngestError, detect_format, docx_text
from app.ingest.pipeline import parse_resume, save_upload
from app.ingest.schemas import ExtractedResume
from app.ledger import active_facts
from app.models import Tailoring
from app.tailoring.engine import tailor
from app.tailoring.schema import JudgeResult, TailoredResume


def make_docx() -> bytes:
    d = docx.Document()
    d.add_paragraph("Alex Tan")
    d.add_paragraph("alex@example.com | Singapore")
    d.add_paragraph("EXPERIENCE")
    d.add_paragraph("Senior Data Engineer, Acme Corp, Mar 2021 – Present")
    d.add_paragraph("Built Spark pipelines on AWS processing 2TB daily for 40 analysts")
    d.add_paragraph("SKILLS: Python, SQL, Spark")
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def test_format_detection():
    assert detect_format("x.docx", make_docx()) == "docx"
    assert detect_format("x.pdf", b"%PDF-1.7 ...") == "pdf"
    with pytest.raises(IngestError):
        detect_format("x.exe", b"MZ\x90\x00")
    with pytest.raises(IngestError):
        detect_format("x.pdf", b"")
    assert "Acme Corp" in docx_text(make_docx())


def test_upload_parse_and_hallucination_flag(s, llm, monkeypatch):
    monkeypatch.setattr("app.ingest.extract.malware_scan", lambda p: None)
    llm.queue("ExtractedResume", ExtractedResume.model_validate({
        "contact": {"name": "Alex Tan", "email": "alex@example.com"},
        "employment": [{"employer": "Acme Corp", "title": "Senior Data Engineer", "start": "2021-03", "end": "Present",
                        "achievements": ["Built Spark pipelines on AWS processing 2TB daily for 40 analysts",
                                         "Won the CEO award for platform migration excellence"]}],
        "skills": [{"name": "Python"}, {"name": "SQL"}, {"name": "Spark"}]}))
    r = save_upload(s, "cv.docx", make_docx())
    assert r.is_master and Path(r.file_path).exists()
    assert save_upload(s, "again.docx", make_docx()).id == r.id  # same file → same record
    n = parse_resume(s, r.id)
    facts = active_facts(s)
    assert n == len(facts) >= 6
    real = next(f for f in facts if "2TB" in f.text)
    fake = next(f for f in facts if "CEO award" in f.text)
    assert real.confidence >= 0.9
    assert fake.confidence < 0.75  # not present in source → flagged for review
    assert all(not f.verified for f in facts)


def test_tailor_end_to_end(s, llm, ledger, job):
    L = ledger
    good = TailoredResume.model_validate({
        "summary": "Data engineer building Spark pipelines on AWS.",
        "summary_fact_ids": [f"F{L['a1'].id}"],
        "roles": [{"fact_id": f"F{L['emp1'].id}", "bullets": [
            {"text": "Built Spark data pipelines on AWS processing 2TB daily for 40 analysts", "fact_ids": [f"F{L['a1'].id}"]},
            {"text": "Cut cloud costs by 30% by migrating batch jobs to Databricks", "fact_ids": [f"F{L['a2'].id}"]}]},
                  {"fact_id": f"F{L['emp2'].id}", "bullets": [
                      {"text": "Automated weekly SQL reporting for the sales team", "fact_ids": [f"F{L['a3'].id}"]}]}],
        "skills": [{"name": "Spark", "fact_id": f"F{L['skills'][2].id}"}, {"name": "AWS", "fact_id": f"F{L['skills'][3].id}"}],
        "education_fact_ids": [f"F{L['edu'].id}"],
        "unsupported_requirements": ["Kubernetes", "Airflow"]})
    bad = good.model_copy(deep=True)
    bad.roles[0].bullets[0].text = "Built Spark pipelines on Kubernetes processing 5TB daily"
    llm.queue("TailoredResume", bad)   # first attempt fabricates → QA fails → regenerated
    llm.queue("TailoredResume", good)
    llm.queue("JudgeResult", JudgeResult())
    t = Tailoring(job_id=job.id, options={"length": "one_page"})
    s.add(t)
    s.commit()
    t = tailor(s, t.id)
    assert t.status == "draft" and t.qa_status == "pass", t.qa
    assert Path(t.docx_path).exists() and Path(t.pdf_path).exists()
    assert t.qa["pages"] == 1
    assert "Kubernetes" in t.change_report["unsupported_requirements"]
    assert "Acme Corp" in t.change_report["tailored_text"]
    # regeneration prompt carried QA feedback
    tailor_prompts = [p for name, p in llm.prompts if name == "TailoredResume"]
    assert len(tailor_prompts) == 2 and "FAILED THESE CHECKS" in tailor_prompts[1]
    # employer/title/dates in the document come from the ledger
    text = "\n".join(p.text for p in docx.Document(t.docx_path).paragraphs)
    assert "Senior Data Engineer" in text and "Mar 2021" in text


def test_tailor_requires_verified_facts(s, llm, job):
    t = Tailoring(job_id=job.id, options={})
    s.add(t)
    s.commit()
    with pytest.raises(ValueError, match="verify"):
        tailor(s, t.id)
    s.refresh(t)
    assert t.status == "failed"
