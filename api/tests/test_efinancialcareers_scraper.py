"""
Unit tests for scrape_efinancialcareers() — eFinancialCareers' internal
(undocumented) job search API.
"""
import httpx
import pytest
import respx

from app.pipeline.scraper import scrape_efinancialcareers

_SEARCH_URL = "https://job-search-ui.efinancialcareers.com/v1/efc/jobs/search"


def _make_item(**overrides):
    item = {
        "id": "x52qC9SYGIfEzLWG",
        "jobId": "24813911",
        "title": "Project Manager - 1 year contract (Banking)",
        "detailsPageUrl": "/jobs-Singapore-Singapore-Project_Manager_-_1_year_contract_Banking.id24813911",
        "jobLocation": {"displayName": "Singapore"},
        "companyName": "Randstad Singapore Pte Ltd",
        "description": "Lead and manage a diverse portfolio of business initiatives.",
        "summary": "Lead and manage...",
        "postedDate": "2026-10-06T01:30:00.200Z",
    }
    item.update(overrides)
    return item


@pytest.mark.asyncio
@respx.mock
async def test_parses_jobs_into_common_shape():
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json={"data": [_make_item()]}))

    jobs = await scrape_efinancialcareers("Project Manager")

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Project Manager - 1 year contract (Banking)"
    assert job["company"] == "Randstad Singapore Pte Ltd"
    assert job["url"] == (
        "https://www.efinancialcareers.sg"
        "/jobs-Singapore-Singapore-Project_Manager_-_1_year_contract_Banking.id24813911"
    )
    assert job["external_id"] == "efinancialcareers:24813911"
    assert job["location"] == "Singapore"
    assert job["description"] == "Lead and manage a diverse portfolio of business initiatives."
    assert job["source"] == "efinancialcareers"
    assert job["posted_at"] == "2026-10-06T01:30:00.200Z"
    assert job["inferred_industries"] == []


@pytest.mark.asyncio
@respx.mock
async def test_uses_q_param_not_keywords():
    """
    The site's own HTML embeds a misleading `keywords` param on a page that
    doesn't actually filter — only `q` on this endpoint genuinely narrows
    results (verified against the live API). Regression guard against
    reverting to the wrong param name.
    """
    route = respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

    await scrape_efinancialcareers("Delivery Manager")

    sent_params = dict(route.calls[0].request.url.params)
    assert sent_params.get("q") == "Delivery Manager"
    assert "keywords" not in sent_params


@pytest.mark.asyncio
@respx.mock
async def test_sends_full_location_scoping_params():
    """
    countryCode2=SG alone does NOT scope results to Singapore — verified
    live against the real API that a query with only countryCode2 returns
    jobs from Qatar, the US, India, etc. Real scoping requires
    locationPrecision + latitude/longitude + location together, matching
    what the site's own "jobs in Singapore" page sends. Regression guard
    against dropping these and silently pulling global results again.
    """
    route = respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

    await scrape_efinancialcareers("Manager")

    sent_params = dict(route.calls[0].request.url.params)
    assert sent_params.get("locationPrecision") == "Country"
    assert sent_params.get("location") == "Singapore"
    assert "latitude" in sent_params
    assert "longitude" in sent_params


@pytest.mark.asyncio
@respx.mock
async def test_empty_results_returns_empty():
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

    jobs = await scrape_efinancialcareers("nonexistent role")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_request_failure_returns_empty():
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(500))

    jobs = await scrape_efinancialcareers("Project Manager")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_malformed_response_returns_empty():
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json={"unexpected": "shape"}))

    jobs = await scrape_efinancialcareers("Project Manager")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_skips_items_missing_id_path_or_title():
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json={
        "data": [
            {"title": "No id or path"},
            _make_item(),
        ]
    }))

    jobs = await scrape_efinancialcareers("Project Manager")

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Project Manager - 1 year contract (Banking)"


@pytest.mark.asyncio
@respx.mock
async def test_falls_back_to_summary_when_description_missing():
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json={
        "data": [_make_item(description="", summary="Short summary text")]
    }))

    jobs = await scrape_efinancialcareers("Project Manager")

    assert jobs[0]["description"] == "Short summary text"
