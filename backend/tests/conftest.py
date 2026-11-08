import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="jobpilot-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["JOBPILOT_NO_WORKER"] = "1"
os.environ["GEMINI_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from app import db  # noqa: E402
from app.llm import set_llm  # noqa: E402
from app.models import CandidateFact, Job  # noqa: E402


class FakeLLM:
    """Returns queued responses per schema; records prompts."""
    name = "fake"

    def __init__(self):
        self.structured: dict[str, list] = {}
        self.texts: list[str] = []
        self.prompts: list[tuple[str, str]] = []

    def model_name(self, fast=False):
        return "fake-fast" if fast else "fake-pro"

    def queue(self, schema_name: str, obj):
        self.structured.setdefault(schema_name, []).append(obj)

    def generate_structured(self, prompt, schema, *, system="", fast=False, files=None, temperature=0.2):
        self.prompts.append((schema.__name__, prompt))
        q = self.structured.get(schema.__name__)
        if q:
            obj = q.pop(0) if len(q) > 1 else q[0]
            return obj if isinstance(obj, schema) else schema.model_validate(obj)
        return schema()

    def generate_text(self, prompt, *, system="", fast=False, temperature=0.4):
        self.prompts.append(("text", prompt))
        return self.texts.pop(0) if self.texts else "Drafted text."

    def embed(self, texts):
        return [[0.0] * 8 for _ in texts]


@pytest.fixture
def llm():
    f = FakeLLM()
    set_llm(f)
    yield f
    set_llm(None)


@pytest.fixture
def s(tmp_path):
    """SQLite by default. Set TEST_DATABASE_URL=postgresql://… to run the whole suite on Postgres."""
    from app import models  # noqa: F401
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        from app.config import Settings
        eng = db.make_engine(Settings(database_url=url).db_url)
        SQLModel.metadata.drop_all(eng)
    else:
        eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    db.set_engine(eng)
    with Session(eng) as session:
        yield session
    db.set_engine(None)
    eng.dispose()


@pytest.fixture
def ledger(s):
    """A small verified fact ledger."""
    def add(**kw):
        f = CandidateFact(verified=True, **kw)
        s.add(f)
        s.commit()
        s.refresh(f)
        return f
    contact = add(type="contact", text="Alex Tan", data={"name": "Alex Tan", "email": "alex@example.com",
                                                         "phone": "+65 9000 0000", "location": "Singapore", "links": []})
    emp1 = add(type="employment", text="Senior Data Engineer, Acme Corp (2021-03 – Present)",
               data={"employer": "Acme Corp", "title": "Senior Data Engineer", "location": "Singapore",
                     "start": "2021-03", "end": "Present"}, sort_order=1)
    a1 = add(type="achievement", text="Built Spark pipelines on AWS processing 2TB daily for 40 analysts",
             parent_id=emp1.id, data={}, sort_order=2)
    a2 = add(type="achievement", text="Cut cloud costs by 30% by migrating batch jobs to Databricks",
             parent_id=emp1.id, data={}, sort_order=3)
    emp2 = add(type="employment", text="Data Analyst, Beta Pte Ltd (2018-01 – 2021-02)",
               data={"employer": "Beta Pte Ltd", "title": "Data Analyst", "location": "Singapore",
                     "start": "2018-01", "end": "2021-02"}, sort_order=4)
    a3 = add(type="achievement", text="Automated weekly SQL reporting for the sales team", parent_id=emp2.id,
             data={}, sort_order=5)
    sk = [add(type="skill", text=n, data={"category": "tech", "level": "unspecified"}, sort_order=10 + i)
          for i, n in enumerate(["Python", "SQL", "Spark", "AWS", "Databricks"])]
    edu = add(type="education", text="BSc, Computer Science, NUS",
              data={"institution": "NUS", "qualification": "BSc", "field": "Computer Science", "start": "2014",
                    "end": "2017"}, sort_order=20)
    return {"contact": contact, "emp1": emp1, "emp2": emp2, "a1": a1, "a2": a2, "a3": a3, "skills": sk, "edu": edu}


@pytest.fixture
def job(s):
    j = Job(provider="greenhouse", external_id="123", dedupe_key="k1", title="Lead Data Engineer", company="Gamma",
            location="Singapore", work_arrangement="hybrid", url="https://boards.greenhouse.io/gamma/jobs/123",
            apply_url="https://boards.greenhouse.io/gamma/jobs/123",
            description="We need a data engineer with Spark, AWS, Kubernetes and Airflow. " * 5,
            requirements={"_version": "jobreq-v1", "normalized_title": "Lead Data Engineer", "seniority": "lead",
                          "required_skills": ["Spark", "AWS", "Kubernetes"], "preferred_skills": ["Airflow"],
                          "keywords": ["data pipelines", "Spark", "Kubernetes"], "responsibilities": [],
                          "qualifications": [], "industry": "tech", "work_arrangement": "hybrid",
                          "sensitive_requirements": []})
    s.add(j)
    s.commit()
    s.refresh(j)
    return j
