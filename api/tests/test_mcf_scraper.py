"""
Unit test for scrape_mycareersfuture()'s error-logging behavior.
"""
import httpx
import pytest
import respx

from app.pipeline.scraper import scrape_mycareersfuture, _MCF_BASE


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
