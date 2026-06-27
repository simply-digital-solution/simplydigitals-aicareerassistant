"""
Unit tests for SlidingWindowRateLimiter.
"""
import asyncio
import pytest
import time
from unittest.mock import patch, MagicMock

from app.shared.rate_limiter import SlidingWindowRateLimiter, _build_rate_limiter


@pytest.mark.asyncio
async def test_allows_up_to_max_immediately():
    limiter = SlidingWindowRateLimiter(max_per_window=3, window_seconds=60)
    for _ in range(3):
        await limiter.acquire()
    assert limiter.slots_used == 3
    assert limiter.slots_available == 0


@pytest.mark.asyncio
async def test_slots_used_after_window_expire():
    limiter = SlidingWindowRateLimiter(max_per_window=2, window_seconds=1)
    await limiter.acquire()
    await limiter.acquire()
    assert limiter.slots_used == 2

    # After the window passes, slots should free
    await asyncio.sleep(1.1)
    assert limiter.slots_used == 0
    assert limiter.slots_available == 2


@pytest.mark.asyncio
async def test_blocks_when_full_then_releases():
    limiter = SlidingWindowRateLimiter(max_per_window=1, window_seconds=1)
    await limiter.acquire()

    start = time.monotonic()
    await limiter.acquire()   # must wait ~1s for the first slot to expire
    elapsed = time.monotonic() - start

    # Should have waited at least 0.9s (window expiry minus tiny timing slack)
    assert elapsed >= 0.9, f"Expected to wait ~1s, waited {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_concurrent_requests_serialised_within_limit():
    limiter = SlidingWindowRateLimiter(max_per_window=3, window_seconds=60)

    results = []
    async def worker(n):
        await limiter.acquire()
        results.append(n)

    await asyncio.gather(*[worker(i) for i in range(3)])
    assert len(results) == 3
    assert limiter.slots_used == 3


@pytest.mark.asyncio
async def test_slots_available_property():
    limiter = SlidingWindowRateLimiter(max_per_window=5, window_seconds=60)
    assert limiter.slots_available == 5
    await limiter.acquire()
    await limiter.acquire()
    assert limiter.slots_available == 3


def test_build_rate_limiter_reads_from_settings():
    """Positive: _build_rate_limiter() uses llm_rpm_limit from settings."""
    mock_settings = MagicMock()
    mock_settings.llm_rpm_limit = 500
    with patch("app.shared.rate_limiter.get_settings", return_value=mock_settings):
        limiter = _build_rate_limiter()
    assert limiter._max == 500


def test_build_rate_limiter_different_rpm_values():
    """Positive: different llm_rpm_limit values are respected."""
    for rpm in [100, 750, 1000]:
        mock_settings = MagicMock()
        mock_settings.llm_rpm_limit = rpm
        with patch("app.shared.rate_limiter.get_settings", return_value=mock_settings):
            limiter = _build_rate_limiter()
        assert limiter._max == rpm, f"Expected _max={rpm}, got {limiter._max}"


def test_build_rate_limiter_falls_back_on_import_error():
    """Negative: ImportError from get_settings falls back to DEFAULT_MAX_RPM."""
    with patch("app.shared.rate_limiter.get_settings", side_effect=ImportError("no settings")):
        limiter = _build_rate_limiter()
    from app.shared.rate_limiter import DEFAULT_MAX_RPM
    assert limiter._max == DEFAULT_MAX_RPM


def test_build_rate_limiter_falls_back_on_attribute_error():
    """Negative: missing llm_rpm_limit attribute falls back to DEFAULT_MAX_RPM."""
    mock_settings = MagicMock(spec=[])  # spec=[] means no attributes allowed
    with patch("app.shared.rate_limiter.get_settings", return_value=mock_settings):
        limiter = _build_rate_limiter()
    from app.shared.rate_limiter import DEFAULT_MAX_RPM
    assert limiter._max == DEFAULT_MAX_RPM


def test_build_rate_limiter_falls_back_on_general_exception():
    """Negative: any exception from get_settings falls back gracefully."""
    with patch("app.shared.rate_limiter.get_settings", side_effect=RuntimeError("env not loaded")):
        limiter = _build_rate_limiter()
    from app.shared.rate_limiter import DEFAULT_MAX_RPM
    assert limiter._max == DEFAULT_MAX_RPM


def test_singleton_does_not_use_old_hardcoded_15():
    """Positive: the module singleton must not use the old free-tier default of 15."""
    from app.shared.rate_limiter import gemini_rate_limiter
    assert gemini_rate_limiter._max != 15, (
        "gemini_rate_limiter is still using the free-tier limit of 15 RPM. "
        "It should read from settings (llm_rpm_limit=1000)."
    )
