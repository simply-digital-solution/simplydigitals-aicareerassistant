"""
Job scraper — Phase 0.

Sources:
  - Indeed          — location-based HTTP scrape
  - Adzuna          — free REST API, 50+ countries, location-aware (needs ADZUNA_APP_ID + ADZUNA_APP_KEY)
  - Remotive        — free JSON API, remote tech jobs
  - Jobicy          — free RSS, remote jobs
  - RemoteOK        — free RSS, remote tech jobs
  - WeWorkRemotely  — free RSS, remote jobs
  - Manual paste    — passthrough

All scrapers return a list of dicts:
  {title, company, url, location, description, source, scraped_at}

Playwright ATS scrapers (Workday, Greenhouse, Lever) are Phase 1.
"""
import asyncio
import json
import logging
import socket
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCF category → profile industry name mapping
# Built from the full set of categories observed in the MCF API.
# Each MCF category maps to one or more profile industry names.
# ---------------------------------------------------------------------------
MCF_CATEGORY_MAP: dict[str, list[str]] = {
    "Information Technology":         ["Technology & Software"],
    "Banking and Finance":            ["Banking & Financial Services"],
    "Risk Management":                ["Banking & Financial Services", "Capital Markets & Investment Management"],
    "Accounting / Auditing / Taxation": ["Banking & Financial Services"],
    "Professional Services":          ["Consulting & Professional Services"],
    "Consulting":                     ["Consulting & Professional Services"],
    "Engineering":                    [],   # too generic — covers mechanical, civil, manufacturing
    "Sciences / Laboratory / R&D":    ["Healthcare & Life Sciences"],
    "Healthcare / Pharmaceutical":    ["Healthcare & Life Sciences"],
    "Medical / Therapy Services":     ["Healthcare & Life Sciences"],
    "Real Estate / Property Management": ["Real Estate & Infrastructure"],
    "Building and Construction":      ["Real Estate & Infrastructure"],
    "Logistics / Supply Chain":       ["Supply Chain & Logistics"],
    "Advertising / Media":            ["Media, Marketing & Communications"],
    "Marketing / Public Relations":   ["Media, Marketing & Communications"],
    "Education and Training":         ["Education"],
    "Energy and Chemicals":           ["Energy & Resources"],
    "Environment / Health":           ["Energy & Resources"],
    "Insurance":                      ["Insurance"],
    "General Management":             [],   # too generic — no mapping
    "Admin / Secretarial":            [],
    "Customer Service":               [],
    "Design":                         [],
    "F&B":                            [],
    "Hospitality":                    [],
    "Human Resources":                [],
    "Legal":                          [],
    "Manufacturing":                  [],
    "Others":                         [],
    "Precision Engineering":          [],
    "Purchasing / Merchandising":     [],
    "Repair and Maintenance":         [],
    "Sales / Retail":                 [],
    "Security and Investigation":     [],
    "Social Services":                [],
    "Travel / Tourism":               [],
    "Wholesale Trade":                [],
    "Architecture / Interior Design": [],
}


def _mcf_categories_to_industries(item: dict) -> list[str]:
    """
    Read MCF's structured categories field and return profile industry names.
    Deduplicates while preserving order.
    Unknown MCF categories fall back to the raw category string so data is not lost.
    """
    seen: set[str] = set()
    result: list[str] = []
    for cat in item.get("categories") or []:
        label = cat.get("category", "")
        if not label:
            continue
        mapped = MCF_CATEGORY_MAP.get(label)
        if mapped is None:
            # Unknown category — store raw so it's visible and filterable
            targets = [label]
        else:
            targets = mapped
        for t in targets:
            if t and t not in seen:
                seen.add(t)
                result.append(t)
    return result

DATA_DIR = Path(tempfile.gettempdir()) / "aicareer_jobs_raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SCRAPE_DELAY_SECONDS = 1.5

RSS_FEEDS = {
    "remoteok": "https://remoteok.com/remote-jobs.rss",
    "weworkremotely_programming": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "weworkremotely_all": "https://weworkremotely.com/remote-jobs.rss",
    "jobicy": "https://jobicy.com/?feed=job_feed",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _save_raw(jobs: list[dict], source: str) -> Path:
    """Save raw scraped jobs to data/jobs_raw/ for audit trail."""
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = DATA_DIR / f"{source}_{ts}.json"
    path.write_text(json.dumps(jobs, indent=2, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manual paste
# ---------------------------------------------------------------------------

def parse_manual_paste(
    title: str,
    company: str,
    description: str,
    url: str = "",
    location: str = "",
) -> dict:
    """Wraps a user-pasted job description into the standard job dict."""
    return {
        "title": title,
        "company": company,
        "url": url,
        "location": location,
        "description": description,
        "source": "manual",
        "scraped_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# RSS feeds
# ---------------------------------------------------------------------------

def scrape_rss(feed_name: str, keyword: str = "") -> list[dict]:
    """
    Parse an RSS feed and return matching jobs.
    feedparser is synchronous — call in a thread if needed.
    """
    url = RSS_FEEDS.get(feed_name)
    if not url:
        return []

    feed = feedparser.parse(url)
    jobs = []
    for entry in feed.entries:
        title = entry.get("title", "")
        description = entry.get("summary", "")

        if keyword and keyword.lower() not in (title + description).lower():
            continue

        clean_desc = BeautifulSoup(description, "lxml").get_text(separator=" ")[:2000]
        jobs.append({
            "title": title,
            "company": entry.get("author", entry.get("dc_company", "Unknown")),
            "url": entry.get("link", ""),
            "location": entry.get("location", "Remote"),
            "description": clean_desc,
            "inferred_industries": [],
            "source": f"rss_{feed_name}",
            "scraped_at": _now_iso(),
        })

    return jobs


async def scrape_rss_async(feed_name: str, keyword: str = "") -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, scrape_rss, feed_name, keyword)


# ---------------------------------------------------------------------------
# Indeed (HTTP + BeautifulSoup)
# ---------------------------------------------------------------------------

_INDEED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


async def scrape_indeed(query: str, location: str = "Remote", max_results: int = 10) -> list[dict]:
    """
    Scrape Indeed job search results.
    Respectful: 1.5s delay between requests, max 2 pages.
    Returns up to max_results jobs.
    """
    jobs: list[dict] = []
    base_url = "https://www.indeed.com/jobs"

    async with httpx.AsyncClient(
        headers=_INDEED_HEADERS,
        follow_redirects=True,
        timeout=15.0,
    ) as client:
        for start in range(0, min(max_results, 20), 10):
            try:
                params = {"q": query, "l": location, "start": start, "fromage": 14}
                resp = await client.get(base_url, params=params)
                resp.raise_for_status()
            except (httpx.HTTPError, httpx.TimeoutException):
                break

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select("div.job_seen_beacon, div[data-testid='slider_item']")

            for card in cards:
                title_el = card.select_one("h2.jobTitle span, a.jcs-JobTitle span")
                company_el = card.select_one("[data-testid='company-name'], .companyName")
                location_el = card.select_one("[data-testid='text-location'], .companyLocation")
                link_el = card.select_one("h2.jobTitle a, a.jcs-JobTitle")

                if not title_el:
                    continue

                href = link_el.get("href", "") if link_el else ""
                job_url = f"https://www.indeed.com{href}" if href.startswith("/") else href

                snippet_el = card.select_one(".job-snippet, ul.jobsearch-ResultsList li")
                snippet = snippet_el.get_text(separator=" ").strip() if snippet_el else ""

                jobs.append({
                    "title": title_el.get_text(strip=True),
                    "company": company_el.get_text(strip=True) if company_el else "Unknown",
                    "url": job_url,
                    "location": location_el.get_text(strip=True) if location_el else location,
                    "description": snippet,
                    "inferred_industries": [],
                    "source": "indeed",
                    "scraped_at": _now_iso(),
                })

                if len(jobs) >= max_results:
                    break

            if len(jobs) >= max_results:
                break

            await asyncio.sleep(SCRAPE_DELAY_SECONDS)

    return jobs


# ---------------------------------------------------------------------------
# MyCareersFuture (Singapore government job portal — free, no auth)
# ---------------------------------------------------------------------------

_MCF_BASE = "https://api.mycareersfuture.gov.sg/v2/jobs"
_MCF_JOB_URL = "https://www.mycareersfuture.gov.sg/job"


# Separate connect/read limits so a hang at connection time is labelled as such and fails fast.
# MCF answers an uncached search slowly (12-16 s measured) and then serves it from cache in
# well under a second, so the read limit must be well above the cold-query latency.
_MCF_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
_MCF_ATTEMPTS = 3
_MCF_RETRY_BACKOFF_SECONDS = (2.0, 5.0)  # sleep before attempt 2 and 3


def _is_transient(exc: Exception) -> bool:
    """Network-level failures and 429/5xx are worth retrying; other 4xx are not."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


async def _resolved_ips(url: str) -> list[str]:
    """Best-effort DNS lookup for diagnostics; the host rotates through many addresses."""
    host = httpx.URL(url).host
    try:
        infos = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), timeout=3.0
        )
        return sorted({info[4][0] for info in infos})
    except Exception as exc:
        return [f"lookup failed: {type(exc).__name__}"]


async def _get_json_with_retry(url: str, params: dict, label: str) -> dict:
    """
    GET `url` and return the parsed JSON, retrying transient failures with backoff.
    Every failed attempt is logged with the exception type, elapsed time and the
    addresses the host currently resolves to. Raises the last exception once the
    attempts are exhausted or the failure is not transient.
    """
    for attempt in range(1, _MCF_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_MCF_TIMEOUT) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            elapsed = time.monotonic() - started
            will_retry = attempt < _MCF_ATTEMPTS and _is_transient(exc)
            logger.warning(
                "%s: attempt %d/%d failed after %.2fs: %s(%r); resolved_ips=%s%s",
                label, attempt, _MCF_ATTEMPTS, elapsed, type(exc).__name__, str(exc),
                await _resolved_ips(url), " — retrying" if will_retry else "",
            )
            if not will_retry:
                raise
            await asyncio.sleep(_MCF_RETRY_BACKOFF_SECONDS[attempt - 1])
    raise AssertionError("unreachable")  # pragma: no cover


async def scrape_mycareersfuture(
    query: str, max_results: int = 20, failures: list[str] | None = None
) -> list[dict]:
    """
    Fetch MCF jobs for `query`. Returns [] on failure; callers that need to tell a
    failed query from one with no results pass a `failures` list, which receives a
    "<ExceptionType>" entry when the request ultimately failed.
    """
    params = {"search": query, "limit": min(max_results, 100)}
    logger.info("MCF: GET %s params=%s", _MCF_BASE, params)
    try:
        data = await _get_json_with_retry(_MCF_BASE, params, label=f"MCF query={query!r}")
    except Exception as e:
        logger.error(
            "PIPELINE_ERROR: MCF request failed for query=%r: %s(%r)", query, type(e).__name__, str(e)
        )
        if failures is not None:
            failures.append(type(e).__name__)
        return []

    total_available = data.get("total", "unknown")
    raw_count = len(data.get("results", []))
    logger.info(
        "MCF: query=%r HTTP 200 — total_available=%s results_in_response=%d cap=%d",
        query, total_available, raw_count, max_results,
    )

    jobs = []
    for item in data.get("results", [])[:max_results]:
        company = (item.get("postedCompany") or item.get("hiringCompany") or {}).get("name", "Unknown")
        uuid = item.get("uuid", "")
        job_url = f"{_MCF_JOB_URL}/{uuid}" if uuid else ""

        salary = item.get("salary") or {}
        salary_min = salary.get("minimum")
        salary_max = salary.get("maximum")
        salary_note = f"SGD {salary_min:,}–{salary_max:,}/month" if salary_min and salary_max else ""

        skills = [s["skill"] for s in item.get("skills", [])[:10] if s.get("skill")]
        min_exp = item.get("minimumYearsExperience")
        levels = [p.get("position") for p in item.get("positionLevels", []) if p.get("position")]
        emp_types = [e.get("description") for e in item.get("employmentTypes", []) if e and e.get("description")]

        parts = []
        if salary_note:
            parts.append(f"Salary: {salary_note}")
        if min_exp:
            parts.append(f"Min experience: {min_exp} yrs")
        if levels:
            parts.append(f"Level: {', '.join(levels)}")
        if emp_types:
            parts.append(f"Type: {', '.join(emp_types)}")
        if skills:
            parts.append(f"Skills: {', '.join(skills)}")

        structured_summary = " | ".join(parts)

        # Strip HTML tags from the full job description for ATS scoring
        import re
        raw_html = item.get("description") or ""
        full_text = re.sub(r"<[^>]+>", " ", raw_html)
        full_text = re.sub(r"\s+", " ", full_text).strip()

        description = f"{structured_summary}\n\n{full_text}" if full_text else structured_summary

        metadata = item.get("metadata") or {}
        original_posting_date = metadata.get("originalPostingDate")  # "YYYY-MM-DD" plain date

        jobs.append({
            "title": item.get("title", ""),
            "company": company,
            "url": job_url,
            "location": "Singapore",
            "description": description,
            "inferred_industries": [],
            "source": "mycareersfuture",
            "scraped_at": _now_iso(),
            "posted_at": original_posting_date,
        })

    logger.info("MCF: query=%r → built %d job dicts", query, len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# eFinancialCareers — finance/banking job aggregator, multi-country.
# No official search API; this is the undocumented internal endpoint the
# site's own frontend calls (found via its embedded API URL, verified live).
# ---------------------------------------------------------------------------

_EFC_SEARCH_BASE = "https://job-search-ui.efinancialcareers.com/v1/efc/jobs/search"
_EFC_SITE_BASE = "https://www.efinancialcareers.sg"

# countryCode2=SG alone does NOT scope results to a country — verified live
# that a plain query with only countryCode2 returns jobs globally (Qatar,
# the US, India, etc). Each entry's locationPrecision + latitude/longitude +
# location must be sent together (the parameter set the site's own
# "jobs in <country>" pages actually send) — every entry here was verified
# live against the real API before being added.
_EFC_LOCATIONS: dict[str, dict] = {
    "singapore": {
        "location": "Singapore", "countryCode2": "SG",
        "latitude": 1.35208, "longitude": 103.81983, "currencyCode": "SGD",
    },
    "uae": {
        "location": "Dubai", "countryCode2": "AE",
        "latitude": 25.2048, "longitude": 55.2708, "currencyCode": "USD",
    },
    "qatar": {
        "location": "Doha", "countryCode2": "QA",
        "latitude": 25.2854, "longitude": 51.5310, "currencyCode": "USD",
    },
    "saudi_arabia": {
        "location": "Riyadh", "countryCode2": "SA",
        "latitude": 24.7136, "longitude": 46.6753, "currencyCode": "USD",
    },
    "bahrain": {
        "location": "Manama", "countryCode2": "BH",
        "latitude": 26.2285, "longitude": 50.5860, "currencyCode": "USD",
    },
    "australia": {
        "location": "Sydney", "countryCode2": "AU",
        "latitude": -33.8688, "longitude": 151.2093, "currencyCode": "AUD",
    },
}


async def scrape_efinancialcareers(query: str, max_results: int = 20, location: str = "singapore") -> list[dict]:
    """
    Search eFinancialCareers by keyword, scoped to one country from
    _EFC_LOCATIONS. The `q` param is the real keyword filter — note the
    site's own HTML embeds a misleading `keywords` param on an unrelated
    endpoint that does NOT filter; verified live that only `q` on
    job-search-ui actually narrows results.
    """
    loc = _EFC_LOCATIONS.get(location)
    if not loc:
        logger.warning("eFC: unknown location=%r, skipping", location)
        return []

    params = {
        "q": query,
        "locationPrecision": "Country",
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "location": loc["location"],
        "countryCode2": loc["countryCode2"],
        "radius": 50,
        "radiusUnit": "mi",
        "page": 1,
        "pageSize": min(max_results, 100),
        "currencyCode": loc["currencyCode"],
        "culture": "en",
    }
    logger.info("eFC: GET %s params=%s", _EFC_SEARCH_BASE, params)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_EFC_SEARCH_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("PIPELINE_ERROR: eFC request failed for query=%r location=%r: %s", query, location, e)
        return []

    raw_jobs = data.get("data")
    if not isinstance(raw_jobs, list):
        logger.warning("eFC: unexpected response shape for query=%r", query)
        return []

    jobs = []
    for item in raw_jobs[:max_results]:
        job_id = item.get("jobId") or item.get("id")
        details_path = item.get("detailsPageUrl", "")
        title = item.get("title", "")
        if not job_id or not details_path or not title:
            continue

        job_url = f"{_EFC_SITE_BASE}{details_path}"
        job_location = (item.get("jobLocation") or {}).get("displayName", "")
        description = item.get("description") or item.get("summary") or ""

        jobs.append({
            "title": title,
            "company": item.get("companyName", ""),
            "url": job_url,
            "external_id": f"efinancialcareers:{job_id}",
            "location": job_location,
            "description": description,
            "inferred_industries": [],
            "source": "efinancialcareers",
            "scraped_at": _now_iso(),
            "posted_at": item.get("postedDate"),
        })

    logger.info("eFC: query=%r → built %d job dicts", query, len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# Adzuna (free REST API — needs ADZUNA_APP_ID + ADZUNA_APP_KEY)
# Sign up free at https://developer.adzuna.com
# ---------------------------------------------------------------------------

# Maps common location strings to Adzuna country codes
_ADZUNA_COUNTRY_MAP = {
    "us": "us", "usa": "us", "united states": "us", "new york": "us", "san francisco": "us",
    "gb": "gb", "uk": "gb", "united kingdom": "gb", "london": "gb",
    "au": "au", "australia": "au", "sydney": "au", "melbourne": "au",
    "ca": "ca", "canada": "ca", "toronto": "ca", "vancouver": "ca",
    "de": "de", "germany": "de", "berlin": "de",
    "fr": "fr", "france": "fr", "paris": "fr",
    "sg": "sg", "singapore": "sg",
    "in": "in", "india": "in", "bangalore": "in", "mumbai": "in", "hyderabad": "in",
    "nl": "nl", "netherlands": "nl", "amsterdam": "nl",
    "remote": "us",  # Adzuna requires a country even for remote
}


def _adzuna_country(location: str) -> str:
    key = location.strip().lower()
    for fragment, code in _ADZUNA_COUNTRY_MAP.items():
        if fragment in key:
            return code
    return "us"


async def scrape_adzuna(
    query: str,
    location: str = "Remote",
    max_results: int = 15,
    app_id: str = "",
    app_key: str = "",
) -> list[dict]:
    if not app_id or not app_key:
        return []

    country = _adzuna_country(location)
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": min(max_results, 50),
        "what": query,
        "content-type": "application/json",
    }
    # Only pass location param when not purely remote
    if location.strip().lower() != "remote":
        params["where"] = location

    jobs: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Adzuna scrape failed for %r in %r: %s", query, location, e)
        return []

    for item in data.get("results", []):
        desc = item.get("description", "")[:2000]
        jobs.append({
            "title": item.get("title", ""),
            "company": item.get("company", {}).get("display_name", "Unknown"),
            "url": item.get("redirect_url", ""),
            "location": item.get("location", {}).get("display_name", location),
            "description": desc,
            "inferred_industries": [],
            "source": "adzuna",
            "scraped_at": _now_iso(),
        })

    return jobs


# ---------------------------------------------------------------------------
# Remotive (free JSON API — remote tech jobs, no auth needed)
# ---------------------------------------------------------------------------

async def scrape_remotive(query: str, max_results: int = 15) -> list[dict]:
    url = "https://remotive.com/api/remote-jobs"
    params = {"search": query, "limit": min(max_results, 50)}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Remotive scrape failed for %r: %s", query, e)
        return []

    jobs = []
    for item in data.get("jobs", [])[:max_results]:
        description = BeautifulSoup(item.get("description", ""), "lxml").get_text(separator=" ")[:2000]
        jobs.append({
            "title": item.get("title", ""),
            "company": item.get("company_name", "Unknown"),
            "url": item.get("url", ""),
            "location": item.get("candidate_required_location", "Remote"),
            "description": description,
            "inferred_industries": [],
            "source": "remotive",
            "scraped_at": _now_iso(),
        })

    return jobs


# ---------------------------------------------------------------------------
# Aggregate scraper
# ---------------------------------------------------------------------------

async def search_jobs(
    query: str,
    location: str = "Remote",
    sources: list[str] | None = None,
    max_per_source: int = 10,
    keyword_filter: str = "",
) -> list[dict]:
    """
    Aggregate job search across selected sources.

    sources options:
      "indeed"       — location-based HTTP scrape
      "adzuna"       — free REST API, location-aware (needs ADZUNA_APP_ID/KEY in .env)
      "remotive"     — free JSON API, remote tech roles
      "rss_remoteok" — RemoteOK RSS feed
      "rss_weworkremotely_programming" — WeWorkRemotely RSS
      "rss_jobicy"   — Jobicy RSS feed

    Default: adzuna + remotive + rss_remoteok for remote;
             indeed + adzuna for location-based.

    Raises RuntimeError if all sources return 0 results, including the failure reasons.
    """
    from app.shared.config import get_settings
    settings = get_settings()

    is_remote = location.strip().lower() in ("remote", "")

    is_singapore = any(k in location.lower() for k in ("singapore", " sg", "sg ")) or location.strip().lower() == "sg"

    if sources is None:
        if is_remote:
            sources = ["remotive", "adzuna", "rss_remoteok", "rss_weworkremotely_programming"]
        elif is_singapore:
            sources = ["mycareersfuture", "adzuna"]
        else:
            sources = ["indeed", "adzuna", "rss_remoteok"]

    all_jobs: list[dict] = []
    source_results: dict[str, int] = {}
    source_errors: dict[str, str] = {}

    import time as _time
    for source in sources:
        t_src = _time.monotonic()
        try:
            if source == "mycareersfuture":
                # MCF works best with just the role title — use keyword_filter if available
                mcf_query = keyword_filter if keyword_filter else query
                jobs = await scrape_mycareersfuture(mcf_query, max_results=max_per_source)
            elif source == "indeed":
                jobs = await scrape_indeed(query, location, max_results=max_per_source)
            elif source == "adzuna":
                jobs = await scrape_adzuna(
                    query, location,
                    max_results=max_per_source,
                    app_id=settings.adzuna_app_id,
                    app_key=settings.adzuna_app_key,
                )
            elif source == "remotive":
                jobs = await scrape_remotive(query, max_results=max_per_source)
            elif source.startswith("rss_"):
                feed_name = source[4:]
                jobs = await scrape_rss_async(feed_name, keyword=keyword_filter or query.split()[0])
                jobs = jobs[:max_per_source]
            else:
                continue

            source_results[source] = len(jobs)
            logger.info("TIMING scraper source=%s → %d jobs in %.2fs", source, len(jobs), _time.monotonic() - t_src)
            all_jobs.extend(jobs)
        except Exception as e:
            source_errors[source] = str(e)
            logger.warning("scraper: source=%s failed: %s", source, e)

        await asyncio.sleep(0.5)

    # Deduplicate by URL
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for job in all_jobs:
        url = job.get("url", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(job)

    if deduped:
        _save_raw(deduped, "aggregate")
    else:
        # Build a diagnostic message so callers can show a useful error
        parts = []
        for src in sources:
            if src in source_errors:
                parts.append(f"{src}: error — {source_errors[src]}")
            elif src in source_results:
                parts.append(f"{src}: 0 results")
            else:
                parts.append(f"{src}: skipped (missing credentials?)")
        diagnostic = "; ".join(parts)
        logger.warning("scraper: no jobs found for %r in %r. Details: %s", query, location, diagnostic)
        raise RuntimeError(f"No jobs found. Sources tried: {diagnostic}")

    return deduped
