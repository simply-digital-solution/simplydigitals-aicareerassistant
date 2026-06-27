"""
Global Gemini API rate limiter — token bucket using a sliding window.

RPM limit is read from settings (llm_rpm_limit). Default is 1000 for the
paid Gemini tier. Override in .env: LLM_RPM_LIMIT=<value>

Usage:
    await gemini_rate_limiter.acquire()   # blocks until a slot is available
    # then fire the HTTP request

The limiter is a module-level singleton so it is shared across all coroutines
in the process regardless of which user triggered the call.
"""
import asyncio
import time
import logging
from app.shared.config import get_settings

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60
DEFAULT_MAX_RPM = 1000


class SlidingWindowRateLimiter:
    """
    Allows at most `max_per_window` calls within any rolling `window_seconds`
    interval. Excess callers await until a slot opens.

    Thread-safe for asyncio (single-threaded event loop).
    """

    def __init__(self, max_per_window: int = DEFAULT_MAX_RPM, window_seconds: int = WINDOW_SECONDS):
        self._max = max_per_window
        self._window = window_seconds
        self._timestamps: list[float] = []   # monotonic times of recent acquisitions
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a rate-limit slot is available, then record the call."""
        while True:
            async with self._lock:
                now = time.monotonic()
                cutoff = now - self._window
                # Drop timestamps outside the window
                self._timestamps = [t for t in self._timestamps if t > cutoff]

                if len(self._timestamps) < self._max:
                    self._timestamps.append(now)
                    return   # slot acquired

                # Window is full — calculate how long until the oldest slot expires
                wait_for = self._timestamps[0] - cutoff
                logger.info(
                    "rate_limiter: Gemini slot full (%d/%d), waiting %.1fs",
                    len(self._timestamps), self._max, wait_for,
                )

            # Release lock while sleeping so other coroutines can check
            await asyncio.sleep(wait_for + 0.05)   # small buffer to avoid edge races

    @property
    def slots_used(self) -> int:
        now = time.monotonic()
        cutoff = now - self._window
        return sum(1 for t in self._timestamps if t > cutoff)

    @property
    def slots_available(self) -> int:
        return max(0, self._max - self.slots_used)


def _build_rate_limiter() -> SlidingWindowRateLimiter:
    try:
        rpm = get_settings().llm_rpm_limit
    except Exception:
        rpm = DEFAULT_MAX_RPM
    return SlidingWindowRateLimiter(max_per_window=rpm, window_seconds=WINDOW_SECONDS)


# Module-level singleton — shared across all requests in the process
gemini_rate_limiter = _build_rate_limiter()
