from fastapi.testclient import TestClient

from app.api import r
from fastapi import FastAPI

app = FastAPI()
app.include_router(r)


def test_api_smoke(s, ledger, llm, monkeypatch):
    c = TestClient(app)
    st = c.get("/api/v1/status").json()
    assert st["verified_facts"] >= 5 and st["llm"]["provider"] == "gemini"
    prof = c.get("/api/v1/candidate-profile").json()
    assert prof["groups"]["employment"]

    f = c.post("/api/v1/candidate-profile/facts", json={"type": "skill", "text": "Terraform"}).json()
    assert f["verified"] is True
    assert c.patch(f"/api/v1/candidate-profile/facts/{f['id']}", json={"text": "Terraform (IaC)"}).json()["version"] == 2

    p = c.put("/api/v1/preferences", json={"criteria": {"titles": {"rule_type": "soft", "value": ["Data Engineer"]},
                                                         "bogus": {"rule_type": "hard", "value": 1}}}).json()
    assert p["criteria"]["titles"]["value"] == ["Data Engineer"]
    assert c.put("/api/v1/preferences", json={"criteria": {"titles": {"rule_type": "maybe"}}}).status_code == 400

    assert c.post("/api/v1/jobs/manual", json={"title": "X", "description": "short"}).status_code == 400
    j = c.post("/api/v1/jobs/manual", json={"title": "Data Engineer", "company": "Delta",
                                            "description": "Spark and AWS data engineering role. " * 10}).json()
    assert c.get(f"/api/v1/jobs/{j['id']}").json()["job"]["title"] == "Data Engineer"
    assert any(x["id"] == j["id"] for x in c.get("/api/v1/jobs").json())

    tl = c.post(f"/api/v1/jobs/{j['id']}/tailor-resume", json={"options": {"tone": "conservative"}}).json()
    assert tl["status"] == "generating"

    a = c.post("/api/v1/applications", json={"job_id": j["id"], "status": "SUBMITTED"}).json()
    assert a["status"] == "SUBMITTED"
    assert c.post("/api/v1/applications", json={"job_id": j["id"]}).status_code == 409
    assert c.post(f"/api/v1/applications/{a['id']}/events", json={"status": "INTERVIEW"}).json()["status"] == "INTERVIEW"
    detail = c.get(f"/api/v1/applications/{a['id']}").json()
    assert [e["to_status"] for e in detail["events"]][-1] == "INTERVIEW"

    ap = c.get("/api/v1/autopilot/settings").json()
    assert ap["policy"]["enabled"] is False
    ap["policy"]["enabled"] = True
    assert c.put("/api/v1/autopilot/settings", json=ap["policy"]).json()["policy"]["enabled"] is True
    assert c.post("/api/v1/autopilot/pause").json()["policy"]["paused"] is True
    assert any(x["purpose"] == "autopilot" for x in c.get("/api/v1/consents").json())

    d = c.get("/api/v1/dashboard").json()
    assert d["interviews"] == 1
    ans = c.get("/api/v1/answers").json()
    assert any(x["key"] == "work_authorisation" and x["category"] == "sensitive" for x in ans)
    assert c.get("/api/v1/export").status_code == 200
    assert c.post("/api/v1/delete-all-data", json={"confirm": "nope"}).status_code == 400
