"""
Unit tests for scrape_greenhouse() — Greenhouse public Job Board API.
"""
import httpx
import pytest
import respx

from app.pipeline.ats_scrapers import scrape_greenhouse

_BOARD_URL = "https://boards.greenhouse.io/acme/jobs/1234567"
_API_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"


@pytest.mark.asyncio
@respx.mock
async def test_parses_jobs_into_common_shape():
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={
        "jobs": [
            {
                "id": 1234567,
                "title": "Senior Backend Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1234567",
                "location": {"name": "Singapore"},
                "content": "&lt;p&gt;Build &lt;b&gt;things&lt;/b&gt;.&lt;/p&gt;",
                "updated_at": "2026-09-01T00:00:00Z",
            },
        ]
    }))

    jobs = await scrape_greenhouse("https://boards.greenhouse.io/acme", "Acme Corp")

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Senior Backend Engineer"
    assert job["company"] == "Acme Corp"
    assert job["url"] == "https://boards.greenhouse.io/acme/jobs/1234567"
    assert job["location"] == "Singapore"
    assert job["description"] == "Build things ."
    assert job["source"] == "greenhouse"
    assert job["posted_at"] == "2026-09-01T00:00:00Z"
    assert job["inferred_industries"] == []
    assert "scraped_at" in job


@pytest.mark.asyncio
@respx.mock
async def test_empty_job_list_returns_empty():
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={"jobs": []}))

    jobs = await scrape_greenhouse("https://boards.greenhouse.io/acme", "Acme Corp")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_unknown_board_token_404_returns_empty():
    respx.get(_API_URL).mock(return_value=httpx.Response(404))

    jobs = await scrape_greenhouse("https://boards.greenhouse.io/acme", "Acme Corp")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_request_failure_logs_pipeline_error_marker(caplog):
    respx.get(_API_URL).mock(return_value=httpx.Response(404))

    with caplog.at_level("ERROR"):
        await scrape_greenhouse("https://boards.greenhouse.io/acme", "Acme Corp")

    assert "PIPELINE_ERROR:" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_malformed_response_returns_empty():
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={"unexpected": "shape"}))

    jobs = await scrape_greenhouse("https://boards.greenhouse.io/acme", "Acme Corp")

    assert jobs == []


@pytest.mark.asyncio
async def test_url_without_board_token_returns_empty():
    jobs = await scrape_greenhouse("https://boards.greenhouse.io/", "Acme Corp")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_skips_jobs_missing_id_or_url():
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={
        "jobs": [
            {"title": "No id or url"},
            {
                "id": 999,
                "title": "Has both",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/999",
                "location": {"name": "Remote"},
                "content": "",
                "updated_at": "2026-09-01T00:00:00Z",
            },
        ]
    }))

    jobs = await scrape_greenhouse("https://boards.greenhouse.io/acme", "Acme Corp")

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Has both"
