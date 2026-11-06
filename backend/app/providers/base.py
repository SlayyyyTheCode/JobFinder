"""Provider adapter contract (spec §7.3). Capabilities are declared explicitly."""
import html as htmllib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

USER_AGENT = "JobPilot/1.0 (personal job-search assistant; single-user local app)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class NotSupported(Exception):
    pass


class ProviderError(Exception):
    pass


@dataclass
class Capabilities:
    discovery: bool = True
    get_job: bool = True
    submit: bool = False  # no candidate-side submit API exists for current providers → handoff
    status: bool = False
    webhook: bool = False


@dataclass
class NormalizedJob:
    provider: str
    external_id: str
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    apply_url: str = ""
    description: str = ""
    work_arrangement: str = ""
    employment_type: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = ""
    salary_period: str = ""
    posted_at: Optional[datetime] = None
    extra: dict = field(default_factory=dict)


class Provider:
    name = "base"
    label = "Base"
    capabilities = Capabilities()
    config_fields: list[dict[str, Any]] = []  # UI hints

    def connect(self, config: dict) -> dict:
        """Validate config by fetching one page. Returns normalised config."""
        self.search_jobs(config, None)
        return config

    def disconnect(self, config: dict) -> None:
        return None  # public boards: nothing to revoke

    def search_jobs(self, config: dict, cursor: Any) -> tuple[list[NormalizedJob], Any]:
        raise NotSupported

    def get_job(self, config: dict, external_id: str) -> NormalizedJob:
        raise NotSupported

    def get_application_url(self, job: NormalizedJob) -> str:
        return job.apply_url or job.url

    def submit_application(self, payload: dict) -> dict:
        raise NotSupported(f"{self.label} has no candidate-side submission API; use handoff.")

    def get_application_status(self, application_id: str) -> str:
        raise NotSupported

    def handle_webhook(self, event: dict) -> None:
        raise NotSupported


def client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                        follow_redirects=True)


def get_json(url: str, params: dict | None = None) -> Any:
    with client() as c:
        r = c.get(url, params=params)
    if r.status_code == 404:
        raise ProviderError(f"Not found: {url}")
    if r.status_code == 429:
        raise ProviderError("Rate limited by provider (429). Will retry later.")
    r.raise_for_status()
    return r.json()


def html_to_text(s: str) -> str:
    if not s:
        return ""
    from bs4 import BeautifulSoup
    s = htmllib.unescape(s) if "&lt;" in s else s
    soup = BeautifulSoup(s, "html.parser")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for tag in soup.find_all(["p", "br", "div", "h1", "h2", "h3", "h4", "h5", "ul", "ol", "tr"]):
        tag.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(l.strip() for l in text.splitlines()).strip()


def parse_dt(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
    try:
        from dateutil import parser
        d = parser.isoparse(str(v)) if "T" in str(v) else parser.parse(str(v))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError):
        return None


def arrangement_from_text(*parts: str) -> str:
    t = " ".join(p.lower() for p in parts if p)
    if "hybrid" in t:
        return "hybrid"
    if "remote" in t:
        return "remote"
    if "on-site" in t or "onsite" in t or "in office" in t:
        return "onsite"
    return ""
