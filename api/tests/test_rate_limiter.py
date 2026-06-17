"""
Unit tests for SlidingWindowRateLimiter.
"""
import asyncio
import pytest
import time

from app.shared.rate_limiter import SlidingWindowRateLimiter


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
