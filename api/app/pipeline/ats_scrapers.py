"""
Scrapers for company career pages, keyed by ATS (applicant tracking system)
platform. A watched company is identified only by its careers page URL — the
platform is detected from the URL's hostname, never asked of the user.

Each scraper returns job dicts in the same shape scrape_mycareersfuture()
produces (title, company, url, location, description, inferred_industries,
scraped_at, posted_at), so they flow through the existing daily_scrape.py
insert logic unchanged. That logic derives its dedup key from the last path
segment of `url`, so each job's URL must end in a stable, unique id.
"""
import html
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_PLATFORM_HOST_SUFFIXES: dict[str, str] = {
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "myworkdayjobs.com": "workday",
}


def detect_ats_platform(url: str) -> str | None:
    """
    Identify the ATS platform a careers page URL belongs to, based on its
    hostname. Returns None if the URL doesn't match a known platform —
    callers must treat that as "not yet supported", not guess further.
    """
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()

    for suffix, platform in _PLATFORM_HOST_SUFFIXES.items():
        if host == suffix or host.endswith("." + suffix):
            return platform
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_workday_posted_on(posted_on: str) -> str | None:
    """
    Convert Workday's relative posting text ("Posted Today", "Posted 9 Days
    Ago") into an ISO date. Returns None for anything else (e.g. "Posted
    30+ Days Ago" has no exact day count) rather than guessing.
    """
    if not posted_on:
        return None
    text = posted_on.strip().lower()
    if text == "posted today":
        days_ago = 0
    else:
        match = re.match(r"posted (\d+) days? ago$", text)
        if not match:
            return None
        days_ago = int(match.group(1))

    from datetime import timedelta
    posted_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return posted_date.date().isoformat()


def _strip_html(raw_html: str) -> str:
    # Greenhouse's `content` field is HTML-entity-escaped HTML (e.g. "&lt;p&gt;"),
    # so entities must be decoded before tags can be recognized and stripped.
    unescaped = html.unescape(raw_html or "")
    text = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Greenhouse — public Job Board API, no auth required
# ---------------------------------------------------------------------------

_GREENHOUSE_API_BASE = "https://boards-api.greenhouse.io/v1/boards"


def _greenhouse_board_token(careers_url: str) -> str | None:
    """
    Extract the board token from a Greenhouse careers URL, e.g.
    https://boards.greenhouse.io/acme -> "acme"
    https://job-boards.greenhouse.io/acme/jobs/123 -> "acme"
    """
    path = urlparse(careers_url).path.strip("/")
    if not path:
        return None
    return path.split("/")[0] or None


async def scrape_greenhouse(careers_url: str, company_name: str) -> list[dict]:
    """
    Fetch current job listings for a company from Greenhouse's public
    Job Board API. Returns [] on any failure (bad token, network error,
    unexpected response shape) rather than raising — callers scrape many
    companies in a loop and one bad watchlist entry must not abort the rest.
    """
    board_token = _greenhouse_board_token(careers_url)
    if not board_token:
        logger.warning("Greenhouse: could not extract board token from url=%r", careers_url)
        return []

    api_url = f"{_GREENHOUSE_API_BASE}/{board_token}/jobs"
    params = {"content": "true"}
    logger.info("Greenhouse: GET %s", api_url)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Greenhouse: request failed for board_token=%r: %s", board_token, e)
        return []

    raw_jobs = data.get("jobs")
    if not isinstance(raw_jobs, list):
        logger.warning("Greenhouse: unexpected response shape for board_token=%r", board_token)
        return []

    jobs = []
    for item in raw_jobs:
        job_id = item.get("id")
        job_url = item.get("absolute_url", "")
        if not job_id or not job_url:
            continue

        location = (item.get("location") or {}).get("name", "")
        description = _strip_html(item.get("content", ""))
        updated_at = item.get("updated_at")

        jobs.append({
            "title": item.get("title", ""),
            "company": company_name,
            "url": job_url,
            "location": location,
            "description": description,
            "inferred_industries": [],
            "source": "greenhouse",
            "scraped_at": _now_iso(),
            "posted_at": updated_at,
        })

    logger.info("Greenhouse: board_token=%r → built %d job dicts", board_token, len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# Workday — undocumented internal JSON API (no public API exists).
# The same endpoint the career site's own JavaScript calls; no auth required.
# ---------------------------------------------------------------------------


def _workday_tenant_site_host(careers_url: str) -> tuple[str, str, str] | None:
    """
    Extract (host, tenant, site) from a Workday careers URL, e.g.
    https://uobgroup.wd3.myworkdayjobs.com/UOBExternal
      -> ("uobgroup.wd3.myworkdayjobs.com", "uobgroup", "UOBExternal")
    """
    parsed = urlparse(careers_url)
    host = parsed.hostname
    if not host:
        return None
    tenant = host.split(".")[0]
    site = parsed.path.strip("/").split("/")[0]
    if not tenant or not site:
        return None
    return host, tenant, site


async def scrape_workday(
    careers_url: str,
    company_name: str,
    query: str = "",
    max_results: int = 20,
) -> list[dict]:
    """
    Fetch job listings for a company from Workday's internal jobs API,
    filtered by `query` (passed as Workday's own search text) and capped
    at `max_results` most-recent matches, then fetch each match's full
    description from the job detail endpoint.

    Returns [] on any failure — callers scrape many companies in a loop
    and one bad watchlist entry must not abort the rest.
    """
    parsed = _workday_tenant_site_host(careers_url)
    if not parsed:
        logger.warning("Workday: could not extract tenant/site from url=%r", careers_url)
        return []
    host, tenant, site = parsed

    list_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    payload = {"limit": min(max_results, 20), "offset": 0, "searchText": query}
    logger.info("Workday: POST %s query=%r", list_url, query)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(list_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Workday: list request failed for host=%r query=%r: %s", host, query, e)
        return []

    raw_postings = data.get("jobPostings")
    if not isinstance(raw_postings, list):
        logger.warning("Workday: unexpected response shape for host=%r", host)
        return []

    jobs = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for item in raw_postings[:max_results]:
            external_path = item.get("externalPath", "")
            title = item.get("title", "")
            if not external_path or not title:
                continue

            job_url = f"https://{host}/{site}{external_path}"
            # externalPath embeds the full job title (can run well past 100
            # chars); the requisition id after the last "_" is short, stable,
            # and unique per tenant — use that as the dedup key instead.
            requisition_id = external_path.rsplit("_", 1)[-1] if "_" in external_path else external_path
            external_id = f"workday:{tenant}:{requisition_id}"[:100]
            description = ""
            try:
                detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{external_path}"
                detail_resp = await client.get(detail_url)
                detail_resp.raise_for_status()
                detail_data = detail_resp.json()
                raw_description = (detail_data.get("jobPostingInfo") or {}).get("jobDescription", "")
                description = _strip_html(raw_description)
            except Exception as e:
                logger.warning("Workday: detail request failed for path=%r: %s", external_path, e)
                # keep the job with an empty description rather than dropping it —
                # the listing itself (title, location) is still real, usable data

            jobs.append({
                "title": title,
                "company": company_name,
                "url": job_url,
                "external_id": external_id,
                "location": item.get("locationsText", ""),
                "description": description,
                "inferred_industries": [],
                "source": "workday",
                "scraped_at": _now_iso(),
                "posted_at": _parse_workday_posted_on(item.get("postedOn", "")),
            })

    logger.info("Workday: host=%r query=%r → built %d job dicts", host, query, len(jobs))
    return jobs
