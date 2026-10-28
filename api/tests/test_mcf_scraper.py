"""
Unit tests for scrape_mycareersfuture()'s error-logging, retry and failure-reporting behavior.
"""
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.pipeline.scraper import _MCF_BASE, scrape_mycareersfuture


@pytest.fixture(autouse=True)
def _no_backoff_and_no_dns():
    """Retries must not sleep for real, and failure logging must not hit real DNS."""
    with patch("app.pipeline.scraper._MCF_RETRY_BACKOFF_SECONDS", (0.0, 0.0)), \
         patch("app.pipeline.scraper._resolved_ips", AsyncMock(return_value=["1.2.3.4"])):
        yield


_ONE_JOB = {"total": 1, "results": [{"uuid": "abc", "title": "PM", "postedCompany": {"name": "Acme"}}]}


@pytest.mark.asyncio
@respx.mock
async def test_request_failure_returns_empty():
    respx.get(_MCF_BASE).mock(return_value=httpx.Response(500))

    jobs = await scrape_mycareersfuture("Delivery Manager")

    assert jobs == []


@pytest.mark.asyncio
@respx.mock
async def test_request_failure_logs_pipeline_error_marker(caplog):
    """
    scrape_and_score.sh greps subprocess output for "PIPELINE_ERROR:" to
    surface failures in its summary — this marker must appear on a real
    request failure so it isn't silently buried in verbose logs.
    """
    respx.get(_MCF_BASE).mock(return_value=httpx.Response(500))

    with caplog.at_level("ERROR"):
        await scrape_mycareersfuture("Delivery Manager")

    assert "PIPELINE_ERROR:" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_transient_failure_is_retried_then_succeeds():
    route = respx.get(_MCF_BASE).mock(
        side_effect=[httpx.ConnectTimeout("t"), httpx.Response(200, json=_ONE_JOB)]
    )
    failures: list[str] = []

    jobs = await scrape_mycareersfuture("PM", failures=failures)

    assert route.call_count == 2
    assert len(jobs) == 1
    assert failures == []


@pytest.mark.asyncio
@respx.mock
async def test_gives_up_after_three_attempts_and_reports_exception_type():
    route = respx.get(_MCF_BASE).mock(side_effect=httpx.ConnectTimeout(""))
    failures: list[str] = []

    jobs = await scrape_mycareersfuture("PM", failures=failures)

    assert jobs == []
    assert route.call_count == 3
    assert failures == ["ConnectTimeout"]


@pytest.mark.asyncio
@respx.mock
async def test_client_error_is_not_retried():
    route = respx.get(_MCF_BASE).mock(return_value=httpx.Response(404))
    failures: list[str] = []

    await scrape_mycareersfuture("PM", failures=failures)

    assert route.call_count == 1
    assert failures == ["HTTPStatusError"]


@pytest.mark.asyncio
@respx.mock
async def test_server_error_is_retried():
    route = respx.get(_MCF_BASE).mock(return_value=httpx.Response(503))

    await scrape_mycareersfuture("PM")

    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_failure_logs_carry_attempt_exception_type_and_resolved_ips(caplog):
    respx.get(_MCF_BASE).mock(side_effect=httpx.ConnectTimeout(""))

    with caplog.at_level("WARNING"):
        await scrape_mycareersfuture("PM")

    assert "attempt 1/3 failed" in caplog.text
    assert "attempt 3/3 failed" in caplog.text
    assert "ConnectTimeout" in caplog.text
    assert "resolved_ips=['1.2.3.4']" in caplog.text
    assert "PIPELINE_ERROR: MCF request failed for query='PM': ConnectTimeout" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_success_leaves_failures_list_empty():
    respx.get(_MCF_BASE).mock(return_value=httpx.Response(200, json=_ONE_JOB))
    failures: list[str] = []

    await scrape_mycareersfuture("PM", failures=failures)

    assert failures == []


def test_read_timeout_outlasts_mcf_cold_query_latency():
    """MCF took 12-16 s to answer an uncached search; a 15 s read limit abandoned those requests."""
    from app.pipeline.scraper import _MCF_TIMEOUT

    assert _MCF_TIMEOUT.read >= 45.0
    assert _MCF_TIMEOUT.connect <= 10.0  # a hang at connection time should still fail fast


@pytest.mark.asyncio
@respx.mock
async def test_request_uses_the_mcf_timeout():
    from app.pipeline.scraper import _MCF_TIMEOUT

    respx.get(_MCF_BASE).mock(return_value=httpx.Response(200, json=_ONE_JOB))
    real_client = httpx.AsyncClient
    seen = {}

    def _spy(*args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return real_client(*args, **kwargs)

    with patch("app.pipeline.scraper.httpx.AsyncClient", _spy):
        await scrape_mycareersfuture("PM")

    assert seen["timeout"] is _MCF_TIMEOUT
