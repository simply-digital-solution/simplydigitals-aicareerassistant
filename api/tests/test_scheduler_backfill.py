"""
Tests for _startup_industry_backfill and _count_unclassified_jobs in scheduler.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

from app.pipeline.scheduler import _count_unclassified_jobs, _startup_industry_backfill


def make_db_context(db_mock):
    """Return an async context manager that yields db_mock."""
    @asynccontextmanager
    async def _ctx():
        yield db_mock
    return _ctx


# ---------------------------------------------------------------------------
# _count_unclassified_jobs
# ---------------------------------------------------------------------------

def _make_db_with_count(n):
    """AsyncMock db whose execute() returns a MagicMock with scalar() = n."""
    result = MagicMock()
    result.scalar.return_value = n
    db = AsyncMock()
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_count_returns_zero_when_all_classified():
    assert await _count_unclassified_jobs(_make_db_with_count(0)) == 0


@pytest.mark.asyncio
async def test_count_returns_positive_when_unclassified_jobs_exist():
    assert await _count_unclassified_jobs(_make_db_with_count(42)) == 42


@pytest.mark.asyncio
async def test_count_handles_none_scalar():
    """scalar() returning None (empty table) must be treated as 0."""
    assert await _count_unclassified_jobs(_make_db_with_count(None)) == 0


# ---------------------------------------------------------------------------
# _startup_industry_backfill — positive cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backfill_called_when_unclassified_jobs_exist():
    """Positive: backfill_industries is called when count > 0."""
    db = AsyncMock()
    with patch("app.pipeline.scheduler._count_unclassified_jobs", new=AsyncMock(return_value=5)):
        with patch("app.pipeline.industry_backfill.backfill_industries", new_callable=AsyncMock, return_value=5) as mock_backfill:
            await _startup_industry_backfill(make_db_context(db))
    mock_backfill.assert_called_once()


@pytest.mark.asyncio
async def test_backfill_not_called_when_all_classified():
    """Negative: backfill_industries is NOT called when count == 0."""
    db = AsyncMock()
    with patch("app.pipeline.scheduler._count_unclassified_jobs", new=AsyncMock(return_value=0)):
        with patch("app.pipeline.industry_backfill.backfill_industries", new_callable=AsyncMock) as mock_backfill:
            await _startup_industry_backfill(make_db_context(db))
    mock_backfill.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_opens_two_db_contexts():
    """Positive: one context for count check, a second for the backfill itself."""
    db = AsyncMock()
    contexts_opened = []

    @asynccontextmanager
    async def tracking_ctx():
        contexts_opened.append(1)
        yield db

    with patch("app.pipeline.scheduler._count_unclassified_jobs", new=AsyncMock(return_value=3)):
        with patch("app.pipeline.industry_backfill.backfill_industries", new_callable=AsyncMock, return_value=3):
            await _startup_industry_backfill(tracking_ctx)

    assert len(contexts_opened) == 2


# ---------------------------------------------------------------------------
# _startup_industry_backfill — negative / error cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backfill_exception_does_not_crash_task():
    """Negative: exception inside backfill is caught and logged — task must not raise."""
    with patch("app.pipeline.scheduler._count_unclassified_jobs", new=AsyncMock(return_value=10)):
        with patch(
            "app.pipeline.industry_backfill.backfill_industries",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Gemini 503"),
        ):
            await _startup_industry_backfill(make_db_context(_make_db_with_count(10)))  # must not raise


@pytest.mark.asyncio
async def test_count_db_error_does_not_crash_task():
    """Negative: DB failure during count check is caught — task must not raise."""
    @asynccontextmanager
    async def broken_ctx():
        raise ConnectionError("DB unreachable")
        yield  # noqa: unreachable

    await _startup_industry_backfill(broken_ctx)  # must not raise
