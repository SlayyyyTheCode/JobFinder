"""MyCareersFuture (Singapore). Public read API used by the MCF website. Polled conservatively."""
import threading
import time

from .base import (Capabilities, NormalizedJob, Provider, ProviderError, arrangement_from_text, get_json,
                   html_to_text, parse_dt)

API = "https://api.mycareersfuture.gov.sg/v2/jobs"
_last_call = 0.0
_lock = threading.Lock()


def _throttle():
    from ..config import get_settings
    global _last_call
    with _lock:
        wait = get_settings().mcf_min_interval_seconds - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


class MyCareersFuture(Provider):
    name, label = "mycareersfuture", "MyCareersFuture (SG)"
    capabilities = Capabilities()
    config_fields = [{"key": "search", "label": "Search keywords", "hint": "e.g. AI solution architect"},
                     {"key": "max_results", "label": "Max results per poll", "hint": "default 60", "optional": True}]

    def _norm(self, j: dict) -> NormalizedJob:
        meta = j.get("metadata") or {}
        sal = j.get("salary") or {}
        company = ((j.get("hiringCompany") or {}).get("name") or (j.get("postedCompany") or {}).get("name") or "")
        addr = j.get("address") or {}
        if addr.get("isOverseas"):
            loc = addr.get("overseasCountry") or "Overseas"
        else:
            districts = [d.get("location") for d in addr.get("districts") or [] if d.get("location")]
            loc = "Singapore" + (f" ({', '.join(districts)})" if districts else "")
        desc = html_to_text(j.get("description", ""))
        skills = [s.get("skill") for s in j.get("skills") or [] if s.get("skill")]
        if skills:
            desc += "\n\nSkills listed: " + ", ".join(skills)
        fwa = " ".join(str(x) for x in j.get("flexibleWorkArrangements") or [])
        url = meta.get("jobDetailsUrl") or f"https://www.mycareersfuture.gov.sg/job/{j['uuid']}"
        stype = ((sal.get("type") or {}).get("salaryType") or "").lower()
        hidden = meta.get("isHideSalary")
        return NormalizedJob(
            provider=self.name, external_id=j["uuid"], title=j.get("title", ""), company=company, location=loc,
            url=url, apply_url=url, description=desc,
            work_arrangement=arrangement_from_text(fwa, desc[:1500]),
            employment_type=", ".join(e.get("employmentType", "") for e in j.get("employmentTypes") or []),
            salary_min=None if hidden else sal.get("minimum"), salary_max=None if hidden else sal.get("maximum"),
            salary_currency="SGD" if sal and not hidden else "", salary_period=stype,
            posted_at=parse_dt(meta.get("newPostingDate") or meta.get("createdAt")),
            extra={"requisition_id": meta.get("jobPostId", ""),
                   "status": (j.get("status") or {}).get("jobStatus", ""),
                   "min_years": j.get("minimumYearsExperience"),
                   "levels": [p.get("position") for p in j.get("positionLevels") or []]})

    def search_jobs(self, config, cursor):
        q = (config.get("search") or "").strip()
        if not q:
            raise ProviderError("Search keywords are required")
        page = int(cursor or 0)
        limit = 20
        max_results = int(config.get("max_results") or 60)
        _throttle()
        data = get_json(API, {"search": q, "limit": limit, "page": page, "sortBy": "new_posting_date"})
        jobs = [self._norm(j) for j in data.get("results", [])]
        fetched = (page + 1) * limit
        nxt = page + 1 if jobs and fetched < min(data.get("total", 0), max_results) else None
        return jobs, nxt

    def get_job(self, config, external_id):
        _throttle()
        return self._norm(get_json(f"{API}/{external_id}"))

    def is_open(self, external_id: str) -> bool | None:
        try:
            j = self.get_job({}, external_id)
            return (j.extra.get("status") or "Open").lower() == "open"
        except ProviderError:
            return False
