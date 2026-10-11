"""
Unit tests for scrape_workday() — Workday's internal (undocumented) jobs API.
"""
import httpx
import pytest
import respx

from app.pipeline.ats_scrapers import scrape_workday, _parse_workday_posted_on

_CAREERS_URL = "https://acme.wd3.myworkdayjobs.com/AcmeExternal"
_LIST_URL = "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/AcmeExternal/jobs"
_DETAIL_URL = (
    "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/AcmeExternal"
    "/job/Singapore/Senior-Engineer_JR12345"
)


@pytest.mark.asyncio
@respx.mock
async def test_parses_jobs_into_common_shape():
    respx.post(_LIST_URL).mock(return_value=httpx.Response(200, json={
        "total": 1,
        "jobPostings": [
            {
                "title": "Senior Engineer",
                "externalPath": "/job/Singapore/Senior-Engineer_JR12345",
                "locationsText": "Singapore",
                "postedOn": "Posted Today",
            },
        ],
    }))
    respx.get(_DETAIL_URL).mock(return_value=httpx.Response(200, json={
        "jobPostingInfo": {
            "title": "Senior Engineer",
            "jobDescription": "<p>Build things.</p>",
        }
    }))

    jobs = await scrape_workday(_CAREERS_URL, "Acme Corp", query="Engineer")

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Senior Engineer"
    assert job["company"] == "Acme Corp"
    assert job["url"] == "https://acme.wd3.myworkdayjobs.com/AcmeExternal/job/Singapore/Senior-Engineer_JR12345"
    assert job["external_id"] == "workday:acme:JR12345"
    assert job["location"] == "Singapore"
    assert job["description"] == "Build things."
    assert job["source"] == "workday"
    assert job["inferred_industries"] == []


@pytest.mark.asyncio
@respx.mock
async def test_external_id_stays_under_100_chars_even_for_long_title_slugs():
    """
    Regression test: externalPath embeds the full job title and can exceed
    100 chars, but job_postings.mcf_uuid is varchar(100) — the dedup key
    must be derived from the short requisition id, not the full path.
    """
    long_path = (
        "/job/Central-Region-City-Area/"
        "Senior-Officer--Production-Support-Analyst--Compliance--"
        "Group-Infrastructure---Platform-Services_JR89227"
    )
    assert len(long_path) > 100  # sanity check that this reproduces the real failure

    respx.post(_LIST_URL).mock(return_value=httpx.Response(200, json={
        "total": 1,
        "jobPostings": [
            {
                "title": "Senior Officer, Production Support Analyst, Compliance",
                "externalPath": long_path,
                "locationsText": "Central Region (City Area)",
                "postedOn": "Posted Today",
            },
        ],
    }))
    respx.get(f"{_LIST_URL.rsplit('/jobs', 1)[0]}{long_path}").mock(
        return_value=httpx.Response(200, json={"jobPostingInfo": {"jobDescription": ""}})
    )

    jobs = await scrape_workday(_CAREERS_URL, "Acme Corp")

    assert len(jobs) == 1
    assert len(jobs[0]["external_id"]) <= 100
    assert jobs[0]["external_id"] == "workday:acme:JR89227"


@pytest.mark.asyncio
@respx.mock
async def test_empty_results_returns_empty():
    respx.post(_LIST_URL).mock(return_value=httpx.Response(200, json={"total": 0, "jobPostings": []}))

    jobs = await scrape_workday(_CAREERS_URL, "Acme Corp", query="nonexistent-role")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_list_request_failure_returns_empty():
    respx.post(_LIST_URL).mock(return_value=httpx.Response(500))

    jobs = await scrape_workday(_CAREERS_URL, "Acme Corp")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_list_request_failure_logs_pipeline_error_marker(caplog):
    respx.post(_LIST_URL).mock(return_value=httpx.Response(500))

    with caplog.at_level("ERROR"):
        await scrape_workday(_CAREERS_URL, "Acme Corp")

    assert "PIPELINE_ERROR:" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_malformed_list_response_returns_empty():
    respx.post(_LIST_URL).mock(return_value=httpx.Response(200, json={"unexpected": "shape"}))

    jobs = await scrape_workday(_CAREERS_URL, "Acme Corp")

    assert jobs == []


@pytest.mark.asyncio
async def test_url_without_tenant_or_site_returns_empty():
    jobs = await scrape_workday("https://myworkdayjobs.com/", "Acme Corp")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_detail_failure_keeps_job_with_empty_description():
    respx.post(_LIST_URL).mock(return_value=httpx.Response(200, json={
        "total": 1,
        "jobPostings": [
            {
                "title": "Senior Engineer",
                "externalPath": "/job/Singapore/Senior-Engineer_JR12345",
                "locationsText": "Singapore",
                "postedOn": "Posted Today",
            },
        ],
    }))
    respx.get(_DETAIL_URL).mock(return_value=httpx.Response(500))

    jobs = await scrape_workday(_CAREERS_URL, "Acme Corp")

    assert len(jobs) == 1
    assert jobs[0]["description"] == ""
    assert jobs[0]["title"] == "Senior Engineer"


@pytest.mark.asyncio
@respx.mock
async def test_skips_postings_missing_path_or_title():
    respx.post(_LIST_URL).mock(return_value=httpx.Response(200, json={
        "total": 1,
        "jobPostings": [{"locationsText": "Singapore", "postedOn": "Posted Today"}],
    }))

    jobs = await scrape_workday(_CAREERS_URL, "Acme Corp")

    assert jobs == []


# ---------------------------------------------------------------------------
# _parse_workday_posted_on
# ---------------------------------------------------------------------------

def test_parses_posted_today():
    from datetime import datetime, timezone
    result = _parse_workday_posted_on("Posted Today")
    assert result == datetime.now(timezone.utc).date().isoformat()


def test_parses_posted_n_days_ago():
    from datetime import datetime, timedelta, timezone
    result = _parse_workday_posted_on("Posted 9 Days Ago")
    expected = (datetime.now(timezone.utc) - timedelta(days=9)).date().isoformat()
    assert result == expected


def test_returns_none_for_unparseable_text():
    assert _parse_workday_posted_on("Posted 30+ Days Ago") is None
    assert _parse_workday_posted_on("") is None
    assert _parse_workday_posted_on("Some other text") is None
