import httpx
import respx

from app.jobs.service import upsert_job
from app.providers.boards import Ashby, Greenhouse, Lever
from app.providers.mcf import MyCareersFuture
from app.providers.url_import import NeedsPaste, import_url

import pytest


@respx.mock
def test_greenhouse():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme").mock(return_value=httpx.Response(200, json={"name": "Acme"}))
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(return_value=httpx.Response(200, json={"jobs": [
        {"id": 77, "title": "AI Engineer", "location": {"name": "Singapore (Hybrid)"}, "absolute_url": "https://x/77",
         "content": "&lt;p&gt;Build &lt;b&gt;LLM&lt;/b&gt; apps&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;",
         "updated_at": "2026-10-01T00:00:00Z"}]}))
    jobs, cur = Greenhouse().search_jobs({"board": "acme"}, None)
    j = jobs[0]
    assert cur is None and j.company == "Acme" and j.external_id == "77"
    assert "Build LLM apps" in j.description and "- Python" in j.description
    assert j.work_arrangement == "hybrid"


@respx.mock
def test_lever():
    respx.get("https://api.lever.co/v0/postings/acme").mock(return_value=httpx.Response(200, json=[
        {"id": "abc", "text": "Data Scientist", "categories": {"location": "Remote", "commitment": "Full-time"},
         "workplaceType": "remote", "descriptionPlain": "Do data science.", "lists": [{"text": "Requirements",
                                                                                        "content": "<li>SQL</li>"}],
         "hostedUrl": "https://jobs.lever.co/acme/abc", "applyUrl": "https://jobs.lever.co/acme/abc/apply",
         "createdAt": 1767225600000, "salaryRange": {"min": 100, "max": 150, "currency": "USD", "interval": "per-year-salary"}}]))
    j = Lever().search_jobs({"board": "acme"}, None)[0][0]
    assert j.work_arrangement == "remote" and j.salary_max == 150 and "SQL" in j.description
    assert j.apply_url.endswith("/apply")


@respx.mock
def test_ashby():
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(return_value=httpx.Response(200, json={"jobs": [
        {"id": "u1", "title": "ML Eng", "location": "Singapore", "isListed": True, "workplaceType": "Hybrid",
         "descriptionPlain": "ML work", "jobUrl": "https://jobs.ashbyhq.com/acme/u1", "applyUrl": "https://jobs.ashbyhq.com/acme/u1/application",
         "publishedAt": "2026-10-10T00:00:00Z", "employmentType": "FullTime",
         "compensation": {"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "SGD",
                                                 "minValue": 120000, "maxValue": 160000}]}},
        {"id": "u2", "title": "Hidden", "isListed": False}]}))
    jobs, _ = Ashby().search_jobs({"board": "acme"}, None)
    assert len(jobs) == 1 and jobs[0].salary_min == 120000 and jobs[0].work_arrangement == "hybrid"


@respx.mock
def test_mcf_paging(monkeypatch):
    monkeypatch.setattr("app.providers.mcf._throttle", lambda: None)
    item = {"uuid": "a" * 32, "title": "Data Engineer", "description": "<p>Spark</p>",
            "salary": {"minimum": 7000, "maximum": 9000, "type": {"salaryType": "Monthly"}},
            "postedCompany": {"name": "Acme Pte Ltd"}, "address": {"isOverseas": False, "districts": [{"location": "Islandwide"}]},
            "employmentTypes": [{"employmentType": "Permanent"}], "skills": [{"skill": "PySpark"}],
            "metadata": {"jobPostId": "MCF-1", "newPostingDate": "2026-10-31", "jobDetailsUrl": "https://www.mycareersfuture.gov.sg/job/x"},
            "status": {"jobStatus": "Open"}}
    respx.get("https://api.mycareersfuture.gov.sg/v2/jobs").mock(return_value=httpx.Response(200, json={"results": [item] * 20, "total": 100}))
    jobs, nxt = MyCareersFuture().search_jobs({"search": "data", "max_results": 60}, None)
    assert nxt == 1 and jobs[0].salary_currency == "SGD" and jobs[0].salary_period == "monthly"
    assert "PySpark" in jobs[0].description and jobs[0].extra["requisition_id"] == "MCF-1"
    _, nxt = MyCareersFuture().search_jobs({"search": "data", "max_results": 60}, 2)
    assert nxt is None


@respx.mock
def test_url_jsonld():
    html = """<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
    "title":"Platform Engineer","description":"<p>Run Kubernetes</p>","hiringOrganization":{"name":"Zeta"},
    "jobLocation":{"address":{"addressLocality":"Singapore","addressCountry":"SG"}},"datePosted":"2026-10-01"}</script></html>"""
    respx.get("https://careers.zeta.com/jobs/1").mock(return_value=httpx.Response(200, text=html))
    j = import_url("https://careers.zeta.com/jobs/1")
    assert j.title == "Platform Engineer" and j.company == "Zeta" and "Kubernetes" in j.description


def test_url_blocked_sites_need_paste():
    with pytest.raises(NeedsPaste):
        import_url("https://www.linkedin.com/jobs/view/123")


def test_url_private_address_rejected():
    from app.providers.base import ProviderError
    with pytest.raises(ProviderError):
        import_url("http://127.0.0.1:8000/admin")


def test_dedupe_across_sources(s):
    from app.providers.base import NormalizedJob
    a, c1 = upsert_job(s, NormalizedJob(provider="greenhouse", external_id="1", title="Data Engineer", company="Acme",
                                        location="Singapore"))
    a2, c2 = upsert_job(s, NormalizedJob(provider="greenhouse", external_id="1", title="Data Engineer (updated)",
                                         company="Acme", location="Singapore"))
    b, c3 = upsert_job(s, NormalizedJob(provider="mycareersfuture", external_id="z", title="Data  Engineer",
                                        company="ACME", location="Singapore (Islandwide)"))
    assert c1 and not c2 and a.id == a2.id and c3
    assert b.duplicate_of == a.id
