"""Owner login for hosted mode. Desktop mode (HOSTED unset) has no login.

Single owner, password verified against a scrypt hash from the environment; the session is an
HMAC-signed, expiring, HttpOnly cookie. Failed logins are rate-limited and audited."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlmodel import Session

from .audit import audit
from .config import get_settings
from .db import get_session

COOKIE = "jp_session"
PUBLIC_PATHS = {"/api/v1/auth/login", "/api/v1/auth/status", "/api/v1/auth/logout"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_N, _R, _P = 14, 8, 1  # scrypt cost (2**14 ≈ 16 MB)

router = APIRouter(prefix="/api/v1/auth")


# ---------------- password hashing ----------------

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** _N, r=_R, p=_P, dklen=32, maxmem=64 * 1024 * 1024)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=2 ** int(n), r=int(r), p=int(p), dklen=32,
                             maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(got, _unb64(dk))
    except Exception:  # noqa: BLE001 — malformed hash must never authenticate
        return False


# ---------------- session tokens ----------------

def _sign(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def make_token(secret: str, days: int, now: float | None = None) -> str:
    payload = _b64(json.dumps({"exp": int((now or time.time()) + days * 86400), "n": secrets.token_hex(8)}).encode())
    return f"{payload}.{_sign(payload, secret)}"


def check_token(token: str | None, secret: str, now: float | None = None) -> bool:
    if not token or "." not in token or not secret:
        return False
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload, secret)):
        return False
    try:
        return json.loads(_unb64(payload))["exp"] > (now or time.time())
    except Exception:  # noqa: BLE001
        return False


def is_authenticated(request: Request) -> bool:
    s = get_settings()
    return (not s.hosted) or check_token(request.cookies.get(COOKIE), s.session_secret)


def origin_ok(request: Request) -> bool:
    """CSRF defence in depth (cookie is also SameSite=Lax): state-changing requests must come from
    an allowed origin when the browser sends one."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    s = get_settings()
    allowed = {o.strip().rstrip("/") for o in s.allowed_origins.split(",") if o.strip()}
    if s.public_url:
        allowed.add(s.public_url.rstrip("/"))
    return origin.rstrip("/") in allowed


# ---------------- login rate limiting ----------------

_fail: dict[str, deque] = defaultdict(deque)
PER_IP, GLOBAL, WINDOW = 5, 30, 15 * 60


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[0].strip() or (request.client.host if request.client else "?")


def _prune(key: str, now: float) -> deque:
    q = _fail[key]
    while q and now - q[0] > WINDOW:
        q.popleft()
    return q


def _locked(ip: str, now: float) -> bool:
    return len(_prune(ip, now)) >= PER_IP or len(_prune("*", now)) >= GLOBAL


# ---------------- routes ----------------

class LoginIn(BaseModel):
    password: str


@router.get("/status")
def auth_status(request: Request):
    s = get_settings()
    return {"hosted": s.hosted, "authenticated": is_authenticated(request)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, s_db: Session = Depends(get_session)):
    s = get_settings()
    if not s.hosted:
        return {"ok": True}
    ip, now = client_ip(request), time.time()
    if _locked(ip, now):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    if not verify_password(body.password, s.app_password_hash):
        _fail[ip].append(now)
        _fail["*"].append(now)
        audit(s_db, "user", "auth.login_failed", "auth", None, ip=ip)
        raise HTTPException(401, "Incorrect password.")
    _fail.pop(ip, None)
    response.set_cookie(COOKIE, make_token(s.session_secret, s.session_days), max_age=s.session_days * 86400,
                        httponly=True, secure=True, samesite="lax", path="/")
    audit(s_db, "user", "auth.login", "auth", None, ip=ip)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


# ---------------- CLI helpers: python -m app.auth hash | fernet-key | secret ----------------

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "hash":
        import getpass
        pw = getpass.getpass("Choose a password (12+ characters): ")
        if len(pw) < 12:
            sys.exit("Password must be at least 12 characters.")
        if pw != getpass.getpass("Repeat: "):
            sys.exit("Passwords do not match.")
        print(hash_password(pw))
    elif cmd == "fernet-key":
        from cryptography.fernet import Fernet
        print(Fernet.generate_key().decode())
    elif cmd == "secret":
        print(secrets.token_urlsafe(48))
    else:
        sys.exit("usage: python -m app.auth hash | fernet-key | secret")
