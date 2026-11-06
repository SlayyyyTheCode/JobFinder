"""Public ATS job-board APIs: Greenhouse, Lever, Ashby (read-only, documented, no key needed)."""
from .base import (Capabilities, NormalizedJob, Provider, ProviderError, arrangement_from_text, get_json,
                   html_to_text, parse_dt)


class Greenhouse(Provider):
    name, label = "greenhouse", "Greenhouse"
    capabilities = Capabilities()
    config_fields = [{"key": "board", "label": "Board token", "hint": "boards.greenhouse.io/<token>"}]
    BASE = "https://boards-api.greenhouse.io/v1/boards"

    def _company(self, board: str) -> str:
        try:
            return get_json(f"{self.BASE}/{board}").get("name") or board
        except Exception:  # noqa: BLE001
            return board

    def _norm(self, j: dict, board: str, company: str) -> NormalizedJob:
        loc = (j.get("location") or {}).get("name", "")
        desc = html_to_text(j.get("content", ""))
        return NormalizedJob(
            provider=self.name, external_id=str(j["id"]), title=j.get("title", ""), company=company,
            location=loc, url=j.get("absolute_url", ""), apply_url=j.get("absolute_url", ""),
            description=desc, work_arrangement=arrangement_from_text(loc, j.get("title", "")),
            posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
            extra={"board": board, "requisition_id": j.get("requisition_id") or ""})

    def search_jobs(self, config, cursor):
        board = config["board"].strip()
        data = get_json(f"{self.BASE}/{board}/jobs", {"content": "true"})
        company = config.get("company") or self._company(board)
        return [self._norm(j, board, company) for j in data.get("jobs", [])], None

    def get_job(self, config, external_id):
        board = config["board"].strip()
        j = get_json(f"{self.BASE}/{board}/jobs/{external_id}")
        return self._norm(j, board, config.get("company") or self._company(board))


class Lever(Provider):
    name, label = "lever", "Lever"
    capabilities = Capabilities()
    config_fields = [{"key": "board", "label": "Company handle", "hint": "jobs.lever.co/<handle>"},
                     {"key": "region", "label": "Region", "hint": "global or eu", "optional": True}]

    def _base(self, config):
        return "https://api.eu.lever.co/v0/postings" if config.get("region") == "eu" else "https://api.lever.co/v0/postings"

    def _norm(self, j: dict, config: dict) -> NormalizedJob:
        cat = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description", ""))]
        for lst in j.get("lists") or []:
            parts.append(f"\n{lst.get('text', '')}\n{html_to_text(lst.get('content', ''))}")
        parts.append(j.get("additionalPlain") or html_to_text(j.get("additional", "")))
        sal = j.get("salaryRange") or {}
        wt = (j.get("workplaceType") or "").lower()
        return NormalizedJob(
            provider=self.name, external_id=j["id"], title=j.get("text", ""),
            company=config.get("company") or config["board"], location=cat.get("location", ""),
            url=j.get("hostedUrl", ""), apply_url=j.get("applyUrl") or j.get("hostedUrl", ""),
            description="\n".join(p for p in parts if p).strip(),
            work_arrangement={"onsite": "onsite", "remote": "remote", "hybrid": "hybrid"}.get(wt, "")
            or arrangement_from_text(cat.get("location", "")),
            employment_type=cat.get("commitment", ""),
            salary_min=sal.get("min"), salary_max=sal.get("max"), salary_currency=sal.get("currency", ""),
            salary_period=(sal.get("interval") or "").replace("-", " "),
            posted_at=parse_dt(j.get("createdAt")))

    def search_jobs(self, config, cursor):
        data = get_json(f"{self._base(config)}/{config['board'].strip()}", {"mode": "json"})
        if not isinstance(data, list):
            raise ProviderError("Unexpected Lever response")
        return [self._norm(j, config) for j in data], None

    def get_job(self, config, external_id):
        return self._norm(get_json(f"{self._base(config)}/{config['board'].strip()}/{external_id}"), config)


class Ashby(Provider):
    name, label = "ashby", "Ashby"
    capabilities = Capabilities()
    config_fields = [{"key": "board", "label": "Job board name", "hint": "jobs.ashbyhq.com/<name>"}]
    BASE = "https://api.ashbyhq.com/posting-api/job-board"

    def _norm(self, j: dict, config: dict) -> NormalizedJob:
        smin = smax = None
        cur = period = ""
        for comp in ((j.get("compensation") or {}).get("summaryComponents") or []):
            if comp.get("compensationType") == "Salary":
                smin, smax = comp.get("minValue"), comp.get("maxValue")
                cur = comp.get("currencyCode") or ""
                period = (comp.get("interval") or "").lower().removeprefix("1 ").strip()
                break
        wt = (j.get("workplaceType") or "").lower()
        arr = {"onsite": "onsite", "remote": "remote", "hybrid": "hybrid"}.get(wt, "")
        if not arr and j.get("isRemote"):
            arr = "remote"
        return NormalizedJob(
            provider=self.name, external_id=j["id"], title=j.get("title", ""),
            company=config.get("company") or config["board"], location=j.get("location", ""),
            url=j.get("jobUrl", ""), apply_url=j.get("applyUrl") or j.get("jobUrl", ""),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
            work_arrangement=arr, employment_type=j.get("employmentType", ""),
            salary_min=smin, salary_max=smax, salary_currency=cur, salary_period=period,
            posted_at=parse_dt(j.get("publishedAt")))

    def search_jobs(self, config, cursor):
        data = get_json(f"{self.BASE}/{config['board'].strip()}", {"includeCompensation": "true"})
        return [self._norm(j, config) for j in data.get("jobs", []) if j.get("isListed", True)], None

    def get_job(self, config, external_id):
        jobs, _ = self.search_jobs(config, None)
        for j in jobs:
            if j.external_id == external_id:
                return j
        raise ProviderError("Job no longer listed")
