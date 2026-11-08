import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings, get_settings
from app.main import app

PW = "correct horse battery"
ORIGIN = "https://jobpilot.example.com"


@pytest.fixture
def hosted(s, monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "hosted", True)
    monkeypatch.setattr(cfg, "app_password_hash", auth.hash_password(PW))
    monkeypatch.setattr(cfg, "session_secret", "x" * 48)
    monkeypatch.setattr(cfg, "public_url", ORIGIN)
    auth._fail.clear()
    return TestClient(app, base_url="https://testserver")


def test_password_hash_roundtrip_and_malformed():
    h = auth.hash_password(PW)
    assert auth.verify_password(PW, h) and not auth.verify_password("wrong", h)
    assert not auth.verify_password(PW, "garbage") and not auth.verify_password(PW, "")


def test_token_expiry_and_tamper():
    t = auth.make_token("s" * 40, 7)
    assert auth.check_token(t, "s" * 40)
    assert not auth.check_token(t, "other" * 10)
    assert not auth.check_token(t[:-2] + "xx", "s" * 40)
    assert not auth.check_token(auth.make_token("s" * 40, 7, now=time.time() - 8 * 86400), "s" * 40)
    assert not auth.check_token(None, "s" * 40) and not auth.check_token("a.b", "")


def test_api_requires_login_when_hosted(hosted):
    assert hosted.get("/api/v1/status").status_code == 401
    assert hosted.get("/api/v1/jobs").status_code == 401
    assert hosted.post("/api/v1/delete-all-data", json={"confirm": "DELETE"}).status_code == 401
    assert hosted.get("/api/v1/auth/status").json() == {"hosted": True, "authenticated": False}
    assert hosted.get("/healthz").status_code == 200


def test_api_docs_are_off_in_a_hosted_process():
    import subprocess
    import sys
    from pathlib import Path
    code = ("from app.main import app; "
            "print(app.docs_url, app.openapi_url, [r.path for r in app.routes "
            "if getattr(r, 'path', '') in ('/docs','/openapi.json')])")
    import os
    import tempfile
    env = {**os.environ, "HOSTED": "1", "DATA_DIR": tempfile.mkdtemp()}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                         cwd=str(Path(__file__).resolve().parents[1]), timeout=60)
    assert out.stdout.strip() == "None None []", out.stdout + out.stderr


def test_login_flow_and_logout(hosted):
    assert hosted.post("/api/v1/auth/login", json={"password": "nope"}).status_code == 401
    r = hosted.post("/api/v1/auth/login", json={"password": PW})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=lax" in r.headers["set-cookie"].lower() and "secure" in r.headers["set-cookie"].lower()
    assert hosted.get("/api/v1/status").status_code == 200
    assert hosted.get("/api/v1/auth/status").json()["authenticated"] is True
    hosted.post("/api/v1/auth/logout")
    assert hosted.get("/api/v1/status").status_code == 401


def test_login_rate_limited(hosted):
    for _ in range(auth.PER_IP):
        assert hosted.post("/api/v1/auth/login", json={"password": "bad"}).status_code == 401
    assert hosted.post("/api/v1/auth/login", json={"password": PW}).status_code == 429  # even the right one


def test_cross_origin_writes_blocked(hosted):
    hosted.post("/api/v1/auth/login", json={"password": PW})
    evil = {"Origin": "https://evil.example.com"}
    assert hosted.post("/api/v1/preferences/criteria", headers=evil).status_code == 403
    assert hosted.put("/api/v1/preferences", json={"criteria": {}}, headers=evil).status_code == 403
    ok = hosted.put("/api/v1/preferences", json={"criteria": {}}, headers={"Origin": ORIGIN})
    assert ok.status_code == 200
    assert hosted.get("/api/v1/status", headers=evil).status_code == 200  # reads are fine


def test_desktop_mode_has_no_login(s):
    c = TestClient(app)
    assert c.get("/api/v1/status").status_code == 200
    assert c.get("/api/v1/auth/status").json() == {"hosted": False, "authenticated": True}


def test_hosted_refuses_to_start_unconfigured():
    with pytest.raises(RuntimeError) as e:
        Settings(hosted=True, app_password_hash="", session_secret="short", database_url="").validate_hosted()
    msg = str(e.value)
    assert all(k in msg for k in ("APP_PASSWORD_HASH", "SESSION_SECRET", "DATABASE_URL", "TOKEN_ENCRYPTION_KEY"))
    ok = Settings(hosted=True, app_password_hash=auth.hash_password(PW), session_secret="x" * 40,
                  database_url="postgres://u:p@h/db", token_encryption_key="k")
    ok.validate_hosted()
    assert ok.db_url == "postgresql+psycopg://u:p@h/db"


def test_hosted_mailbox_connect_returns_redirect(hosted, monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "google_client_id", "cid")
    monkeypatch.setattr(cfg, "google_client_secret", "sec")
    hosted.post("/api/v1/auth/login", json={"password": PW})
    r = hosted.post("/api/v1/email/gmail/connect", headers={"Origin": ORIGIN}).json()
    assert r["state"] == "redirect" and "accounts.google.com" in r["redirect"]
    assert f"redirect_uri={ORIGIN.replace(':', '%3A').replace('/', '%2F')}%2Fapi%2Fv1%2Femail%2Fgmail%2Fcallback" in r["redirect"]
    assert "gmail.readonly" in r["redirect"] and "state=" in r["redirect"]
    # a callback with an unknown state is rejected, not exchanged
    cb = hosted.get("/api/v1/email/gmail/callback?code=x&state=forged", follow_redirects=False)
    assert cb.status_code == 303 and "mail_error=" in cb.headers["location"]
