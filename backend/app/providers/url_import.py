"""Job URL import (spec §7.4): known ATS → official API; otherwise schema.org JobPosting JSON-LD;
otherwise ask the user to paste the description. Sites that prohibit automated access are not fetched."""
import json
import re
from urllib.parse import urlparse

from .base import NormalizedJob, ProviderError, client, html_to_text, parse_dt

# Sites whose terms prohibit automated retrieval or that block it — user must paste text.
BLOCKED = ("linkedin.com", "indeed.", "glassdoor.", "jobstreet.", "seek.com", "jobsdb.", "monster.",
           "ziprecruiter.")


class NeedsPaste(Exception):
    pass


def _validate(url: str) -> str:
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ProviderError("Enter a full http(s) URL.")
    host = u.hostname or ""
    if host in ("localhost",) or host.startswith(("127.", "10.", "192.168.", "169.254.")) or host.endswith(".local"):
        raise ProviderError("Local/private addresses are not allowed.")
    return url.strip()


def _known_ats(url: str) -> NormalizedJob | None:
    from .registry import get_provider
    u = urlparse(url)
    host, parts = u.hostname or "", [p for p in u.path.split("/") if p]
    if "greenhouse.io" in host:
        m = re.search(r"/jobs/(\d+)", u.path)
        gh_jid = re.search(r"gh_jid=(\d+)", u.query or "")
        board = parts[0] if parts and parts[0] not in ("embed",) else None
        if board and (m or gh_jid):
            return get_provider("greenhouse").get_job({"board": board}, (m or gh_jid).group(1))
    if host.endswith("lever.co") and len(parts) >= 2:
        return get_provider("lever").get_job({"board": parts[0], "region": "eu" if ".eu." in host else ""}, parts[1])
    if host == "jobs.ashbyhq.com" and len(parts) >= 2:
        return get_provider("ashby").get_job({"board": parts[0]}, parts[1])
    if "mycareersfuture.gov.sg" in host and parts:
        m = re.search(r"([0-9a-f]{32})$", parts[-1])
        if m:
            return get_provider("mycareersfuture").get_job({}, m.group(1))
    return None


def _jsonld_jobs(html: str) -> list[dict]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                t = d.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    out.append(d)
                stack.extend(v for v in d.values() if isinstance(v, (list, dict)))
            elif isinstance(d, list):
                stack.extend(d)
    return out


def _from_jsonld(d: dict, url: str) -> NormalizedJob:
    org = d.get("hiringOrganization") or {}
    loc = d.get("jobLocation") or {}
    loc = loc[0] if isinstance(loc, list) and loc else loc
    addr = (loc or {}).get("address") or {}
    if isinstance(addr, str):
        location = addr
    else:
        location = ", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion"),
                                          addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else ""] if x)
    sal = d.get("baseSalary") or {}
    val = sal.get("value") or {} if isinstance(sal, dict) else {}
    arr = "remote" if d.get("jobLocationType") == "TELECOMMUTE" else ""
    return NormalizedJob(
        provider="url", external_id=str((d.get("identifier") or {}).get("value", "") if isinstance(d.get("identifier"), dict) else d.get("identifier", "")) or url,
        title=d.get("title", ""), company=org.get("name", "") if isinstance(org, dict) else str(org),
        location=location, url=url, apply_url=d.get("url") or url, description=html_to_text(d.get("description", "")),
        work_arrangement=arr,
        employment_type=", ".join(d["employmentType"]) if isinstance(d.get("employmentType"), list) else d.get("employmentType", ""),
        salary_min=val.get("minValue") if isinstance(val, dict) else None,
        salary_max=val.get("maxValue") if isinstance(val, dict) else None,
        salary_currency=sal.get("currency", "") if isinstance(sal, dict) else "",
        salary_period=(val.get("unitText") or "").lower() if isinstance(val, dict) else "",
        posted_at=parse_dt(d.get("datePosted")))


def import_url(url: str) -> NormalizedJob:
    url = _validate(url)
    host = urlparse(url).hostname or ""
    if any(b in host for b in BLOCKED):
        raise NeedsPaste(f"{host} does not permit automated retrieval. Paste the job description instead.")
    job = _known_ats(url)
    if job:
        return job
    with client() as c:
        r = c.get(url, headers={"Accept": "text/html"})
    if r.status_code >= 400:
        raise NeedsPaste(f"Could not load the page (HTTP {r.status_code}). Paste the job description instead.")
    jobs = _jsonld_jobs(r.text)
    if not jobs:
        raise NeedsPaste("This page has no structured job data. Paste the job description instead.")
    return _from_jsonld(jobs[0], url)
