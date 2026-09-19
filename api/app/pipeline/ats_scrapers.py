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
