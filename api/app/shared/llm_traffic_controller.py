"""
LLM Traffic Controller — queue-based dispatcher for concurrent LLM scoring.

Accepts score requests from the scorer loop, dispatches them concurrently
up to an adaptive batch size determined by current CPU/RAM usage, and
enforces a per-user asyncio.Lock so two scoring calls for the same user
never run simultaneously.

This module is instantiated only when enable_llm_traffic_controller=True
in settings.

Architecture:
  - asyncio.Queue holds pending (user_id, job_id) pairs
  - _dispatch_loop() runs forever, pulling items and launching workers
  - _user_locks dict ensures one active call per user at a time
  - _compute_batch_size() from system_resources controls concurrency
"""
import asyncio
import logging
from typing import Callable, Awaitable

from app.shared.system_resources import _compute_batch_size

logger = logging.getLogger(__name__)

# Hard ceiling — never exceed this regardless of system resources
_QUEUE_MAX_SIZE = 500


class LLMTrafficController:
    """
    Manages concurrent LLM scoring calls with adaptive batching and
    per-user serialisation.
    """

    def __init__(self, get_db_context_fn: Callable) -> None:
        self._get_db_context = get_db_context_fn
        self._queue: asyncio.Queue[tuple[int, int]] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the dispatch loop. Call once from scheduler.start()."""
        if self._running:
            logger.warning("llm_traffic_controller: already running — ignoring start()")
            return
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("llm_traffic_controller: started")

    def stop(self) -> None:
        """Cancel the dispatch loop. Call from scheduler.stop()."""
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            self._dispatch_task = None
        logger.info("llm_traffic_controller: stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, user_id: int, job_id: int) -> bool:
        """
        Add a (user_id, job_id) pair to the scoring queue.
        Returns True if enqueued, False if the queue is full.
        """
        try:
            self._queue.put_nowait((user_id, job_id))
            return True
        except asyncio.QueueFull:
            logger.warning(
                "llm_traffic_controller: queue full (%d) — dropping job_id=%d for user_id=%d",
                _QUEUE_MAX_SIZE, job_id, user_id,
            )
            return False

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._user_locks:
            self._user_locks[user_id] = asyncio.Lock()
        return self._user_locks[user_id]

    async def _dispatch_loop(self) -> None:
        """Pull items from the queue and dispatch them concurrently."""
        active: set[asyncio.Task] = set()

        while self._running:
            batch_size = _compute_batch_size()

            # Fill up to batch_size concurrent workers
            while len(active) < batch_size and not self._queue.empty():
                try:
                    user_id, job_id = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                task = asyncio.create_task(self._score_with_lock(user_id, job_id))
                active.add(task)
                task.add_done_callback(active.discard)

            if active:
                # Wait for at least one worker to finish before re-filling
                await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            else:
                # Nothing in queue — yield control briefly
                await asyncio.sleep(0.1)

    async def _score_with_lock(
        self,
        user_id: int,
        job_id: int,
    ) -> None:
        """Acquire per-user lock then invoke the registered score callable."""
        lock = self._get_user_lock(user_id)
        async with lock:
            try:
                await self._do_score(user_id, job_id)
            except Exception:
                logger.exception(
                    "llm_traffic_controller: error scoring job_id=%d user_id=%d",
                    job_id, user_id,
                )

    async def _do_score(self, user_id: int, job_id: int) -> None:
        """Open a DB session and call score_single_job for the given job."""
        from app.pipeline.llm_scorer import score_single_job
        async with self._get_db_context() as db:
            await score_single_job(db, job_id=job_id, user_id=user_id)


# Module-level singleton — created only when the feature flag is enabled.
# Instantiated by scheduler.start(); never imported directly by callers.
_controller: LLMTrafficController | None = None


def get_controller() -> LLMTrafficController | None:
    """Return the active controller instance, or None if flag is off."""
    return _controller


def _init_controller(get_db_context_fn: Callable) -> LLMTrafficController:
    """Create and return a new controller. Called once by scheduler.start()."""
    global _controller
    _controller = LLMTrafficController(get_db_context_fn)
    return _controller


def _clear_controller() -> None:
    """Tear down the singleton. Called by scheduler.stop()."""
    global _controller
    _controller = None
