"""Gmail (gmail.readonly) and Outlook/Hotmail (Microsoft Graph Mail.Read) clients.
Least privilege: read-only scopes; only messages passing a job-related pre-filter are classified."""
import base64
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from ..config import get_settings
from .secrets import decrypt, encrypt

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GRAPH_SCOPES = ["Mail.Read", "User.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"

GMAIL_QUERY = ('(subject:(application OR applying OR applied OR interview OR assessment OR offer OR candidate OR '
               'position OR role OR "job alert" OR jobs OR recruit) OR from:(greenhouse.io OR lever.co OR ashbyhq.com '
               'OR myworkday.com OR workday.com OR smartrecruiters.com OR mycareersfuture.gov.sg OR linkedin.com OR '
               'indeed.com OR jobstreet.com OR icims.com OR successfactors.com OR taleo.net))')


class EmailAuthError(Exception):
    pass


@dataclass
class Msg:
    id: str
    sender: str
    subject: str
    snippet: str
    received_at: datetime | None


# ---------------- Gmail ----------------

def gmail_connect_blocking() -> tuple[str, str]:
    """Runs Google's installed-app OAuth (loopback redirect, opens browser). Returns (account, enc_token)."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    path = get_settings().google_client_secrets_file
    if not path:
        raise EmailAuthError("GOOGLE_CLIENT_SECRETS_FILE is not set in .env (see docs/SETUP_OAUTH.md).")
    flow = InstalledAppFlow.from_client_secrets_file(path, scopes=GMAIL_SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                  authorization_prompt_message="", timeout_seconds=300)
    svc = _gmail_service(creds)
    account = svc.users().getProfile(userId="me").execute().get("emailAddress", "")
    return account, encrypt(creds.to_json())


def _gmail_creds(token_enc: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_info(json.loads(decrypt(token_enc)), GMAIL_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:  # noqa: BLE001
                raise EmailAuthError(f"Gmail token refresh failed — reconnect the mailbox. {e}") from e
        else:
            raise EmailAuthError("Gmail authorisation expired — reconnect the mailbox.")
    return creds


def _gmail_service(creds):
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def gmail_fetch(token_enc: str, since: datetime) -> tuple[list[Msg], str]:
    creds = _gmail_creds(token_enc)
    svc = _gmail_service(creds)
    days = max(1, (datetime.now(timezone.utc) - since).days + 1)
    res = svc.users().messages().list(userId="me", q=f"newer_than:{days}d {GMAIL_QUERY}", maxResults=100).execute()
    out = []
    for m in res.get("messages", []):
        full = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                          metadataHeaders=["From", "Subject"]).execute()
        h = {x["name"].lower(): x["value"] for x in full.get("payload", {}).get("headers", [])}
        ts = datetime.fromtimestamp(int(full.get("internalDate", "0")) / 1000, tz=timezone.utc)
        if ts < since:
            continue
        out.append(Msg(id=f"gmail:{m['id']}", sender=h.get("from", ""), subject=h.get("subject", ""),
                       snippet=full.get("snippet", ""), received_at=ts))
    return out, encrypt(creds.to_json())


def gmail_body(token_enc: str, msg_id: str) -> str:
    svc = _gmail_service(_gmail_creds(token_enc))
    full = svc.users().messages().get(userId="me", id=msg_id.split(":", 1)[1], format="full").execute()

    def walk(p):
        if p.get("mimeType", "").startswith("text/") and p.get("body", {}).get("data"):
            yield p["mimeType"], base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", "replace")
        for c in p.get("parts", []) or []:
            yield from walk(c)

    parts = list(walk(full.get("payload", {})))
    html = next((b for m, b in parts if m == "text/html"), None)
    return html or next((b for _, b in parts), "")


# ---------------- Outlook / Microsoft Graph ----------------

def _msal_app(cache_json: str = ""):
    import msal
    s = get_settings()
    if not s.ms_client_id:
        raise EmailAuthError("MS_CLIENT_ID is not set in .env (see docs/SETUP_OAUTH.md).")
    cache = msal.SerializableTokenCache()
    if cache_json:
        cache.deserialize(cache_json)
    return msal.PublicClientApplication(s.ms_client_id, authority=s.ms_authority, token_cache=cache), cache


def outlook_connect_blocking() -> tuple[str, str]:
    app, cache = _msal_app()
    res = app.acquire_token_interactive(scopes=GRAPH_SCOPES, prompt="select_account", timeout=300)
    if "access_token" not in res:
        raise EmailAuthError(res.get("error_description") or "Microsoft sign-in failed")
    account = (res.get("id_token_claims") or {}).get("preferred_username", "")
    return account, encrypt(cache.serialize())


def _outlook_token(token_enc: str) -> tuple[str, str]:
    app, cache = _msal_app(decrypt(token_enc))
    accounts = app.get_accounts()
    if not accounts:
        raise EmailAuthError("Outlook authorisation missing — reconnect the mailbox.")
    res = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
    if not res or "access_token" not in res:
        raise EmailAuthError("Outlook token refresh failed — reconnect the mailbox.")
    return res["access_token"], encrypt(cache.serialize())


def outlook_fetch(token_enc: str, since: datetime) -> tuple[list[Msg], str]:
    tok, new_enc = _outlook_token(token_enc)
    iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (f"{GRAPH}/me/mailFolders/inbox/messages?$select=id,subject,from,receivedDateTime,bodyPreview"
           f"&$filter=receivedDateTime ge {iso}&$orderby=receivedDateTime desc&$top=100")
    out = []
    with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {tok}"}) as c:
        for _ in range(3):  # up to 300 messages per poll
            r = c.get(url)
            if r.status_code == 401:
                raise EmailAuthError("Outlook rejected the token — reconnect the mailbox.")
            r.raise_for_status()
            data = r.json()
            for m in data.get("value", []):
                frm = (m.get("from") or {}).get("emailAddress") or {}
                out.append(Msg(id=f"outlook:{m['id']}", sender=f"{frm.get('name', '')} <{frm.get('address', '')}>",
                               subject=m.get("subject") or "", snippet=m.get("bodyPreview") or "",
                               received_at=datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00"))))
            url = data.get("@odata.nextLink")
            if not url:
                break
    return out, new_enc


def outlook_body(token_enc: str, msg_id: str) -> str:
    tok, _ = _outlook_token(token_enc)
    with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {tok}"}) as c:
        r = c.get(f"{GRAPH}/me/messages/{msg_id.split(':', 1)[1]}?$select=body")
        r.raise_for_status()
        return (r.json().get("body") or {}).get("content", "")


def fetch(provider: str, token_enc: str, since: datetime):
    return (gmail_fetch if provider == "gmail" else outlook_fetch)(token_enc, since)


def body(provider: str, token_enc: str, msg_id: str) -> str:
    return (gmail_body if provider == "gmail" else outlook_body)(token_enc, msg_id)


# ---------------- connect flow (runs in background thread; browser consent) ----------------

_pending: dict[str, dict] = {}


def start_connect(provider: str, on_done) -> None:
    if _pending.get(provider, {}).get("state") == "running":
        return
    _pending[provider] = {"state": "running", "error": ""}

    def run():
        try:
            account, enc = (gmail_connect_blocking if provider == "gmail" else outlook_connect_blocking)()
            on_done(provider, account, enc)
            _pending[provider] = {"state": "done", "error": ""}
        except Exception as e:  # noqa: BLE001
            _pending[provider] = {"state": "error", "error": str(e)[:500]}

    threading.Thread(target=run, daemon=True).start()


def connect_state(provider: str) -> dict:
    return _pending.get(provider, {"state": "idle", "error": ""})


def default_since(last: datetime | None) -> datetime:
    if last:
        return (last if last.tzinfo else last.replace(tzinfo=timezone.utc)) - timedelta(minutes=5)
    return datetime.now(timezone.utc) - timedelta(days=21)
