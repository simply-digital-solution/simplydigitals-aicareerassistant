"""
Tests for LLMTrafficController in app.shared.llm_traffic_controller.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.shared.llm_traffic_controller import (
    LLMTrafficController,
    _init_controller,
    _clear_controller,
    get_controller,
    _QUEUE_MAX_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_controller() -> LLMTrafficController:
    """Return a fresh controller without starting the dispatch loop."""
    return LLMTrafficController()


# ---------------------------------------------------------------------------
# Lifecycle — start / stop
# ---------------------------------------------------------------------------

def test_controller_not_running_before_start():
    """Positive: fresh controller is not running."""
    ctrl = make_controller()
    assert ctrl._running is False
    assert ctrl._dispatch_task is None


@pytest.mark.asyncio
async def test_start_sets_running_and_creates_task():
    """Positive: start() sets _running and creates the dispatch task."""
    ctrl = make_controller()
    ctrl.start()
    try:
        assert ctrl._running is True
        assert ctrl._dispatch_task is not None
        assert not ctrl._dispatch_task.done()
    finally:
        ctrl.stop()


@pytest.mark.asyncio
async def test_stop_cancels_task_and_clears_running():
    """Positive: stop() cancels dispatch task and sets _running=False."""
    ctrl = make_controller()
    ctrl.start()
    ctrl.stop()
    assert ctrl._running is False
    assert ctrl._dispatch_task is None


@pytest.mark.asyncio
async def test_start_twice_is_safe():
    """Negative: calling start() twice does not raise or create a second task."""
    ctrl = make_controller()
    ctrl.start()
    first_task = ctrl._dispatch_task
    ctrl.start()  # second call — should log warning and return
    try:
        assert ctrl._dispatch_task is first_task  # same task, not replaced
    finally:
        ctrl.stop()


def test_stop_before_start_is_safe():
    """Negative: calling stop() on a never-started controller does not raise."""
    ctrl = make_controller()
    ctrl.stop()  # must not raise


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------

def test_enqueue_returns_true_when_space_available():
    """Positive: enqueue returns True when queue has space."""
    ctrl = make_controller()
    assert ctrl.enqueue(user_id=1, job_id=100) is True


def test_enqueue_increases_queue_size():
    """Positive: queue_size increments after enqueue."""
    ctrl = make_controller()
    ctrl.enqueue(user_id=1, job_id=101)
    ctrl.enqueue(user_id=1, job_id=102)
    assert ctrl.queue_size == 2


def test_enqueue_returns_false_when_queue_full():
    """Negative: enqueue returns False and does not raise when queue is full."""
    ctrl = LLMTrafficController()
    for i in range(_QUEUE_MAX_SIZE):
        ctrl.enqueue(user_id=1, job_id=i)
    result = ctrl.enqueue(user_id=1, job_id=99999)
    assert result is False
    assert ctrl.queue_size == _QUEUE_MAX_SIZE


def test_enqueue_different_users():
    """Positive: items from different users all enter the same queue."""
    ctrl = make_controller()
    ctrl.enqueue(user_id=1, job_id=10)
    ctrl.enqueue(user_id=2, job_id=20)
    ctrl.enqueue(user_id=3, job_id=30)
    assert ctrl.queue_size == 3


# ---------------------------------------------------------------------------
# Per-user lock
# ---------------------------------------------------------------------------

def test_get_user_lock_creates_lock_on_first_call():
    """Positive: _get_user_lock() creates a new asyncio.Lock for a new user."""
    ctrl = make_controller()
    lock = ctrl._get_user_lock(user_id=42)
    assert isinstance(lock, asyncio.Lock)


def test_get_user_lock_returns_same_lock_for_same_user():
    """Positive: same user always gets the same lock instance."""
    ctrl = make_controller()
    lock1 = ctrl._get_user_lock(user_id=7)
    lock2 = ctrl._get_user_lock(user_id=7)
    assert lock1 is lock2


def test_get_user_lock_returns_different_locks_for_different_users():
    """Positive: different users get different lock instances."""
    ctrl = make_controller()
    lock_a = ctrl._get_user_lock(user_id=1)
    lock_b = ctrl._get_user_lock(user_id=2)
    assert lock_a is not lock_b


@pytest.mark.asyncio
async def test_per_user_lock_serialises_concurrent_calls():
    """Positive: two concurrent calls for same user run sequentially, not in parallel."""
    ctrl = make_controller()
    order = []

    async def fake_score(user_id, job_id):
        order.append(f"start-{job_id}")
        await asyncio.sleep(0.05)
        order.append(f"end-{job_id}")

    ctrl._do_score = fake_score

    await asyncio.gather(
        ctrl._score_with_lock(user_id=1, job_id=10),
        ctrl._score_with_lock(user_id=1, job_id=11),
    )

    # With per-user lock, first job must fully complete before second starts
    assert order.index("end-10") < order.index("start-11") or \
           order.index("end-11") < order.index("start-10")


@pytest.mark.asyncio
async def test_different_users_run_concurrently():
    """Positive: calls for different users are not blocked by each other's lock."""
    ctrl = make_controller()
    started = []

    async def fake_score(user_id, job_id):
        started.append(user_id)
        await asyncio.sleep(0.05)

    ctrl._do_score = fake_score

    await asyncio.gather(
        ctrl._score_with_lock(user_id=1, job_id=10),
        ctrl._score_with_lock(user_id=2, job_id=20),
    )

    assert 1 in started and 2 in started


# ---------------------------------------------------------------------------
# _score_with_lock — error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_with_lock_catches_exception():
    """Negative: exception in _do_score is caught and does not propagate."""
    ctrl = make_controller()

    async def failing_score(user_id, job_id):
        raise RuntimeError("Gemini 503")

    ctrl._do_score = failing_score
    await ctrl._score_with_lock(user_id=1, job_id=99)  # must not raise


@pytest.mark.asyncio
async def test_score_with_lock_releases_lock_after_exception():
    """Negative: lock is released even when _do_score raises."""
    ctrl = make_controller()
    call_count = 0

    async def failing_then_ok(user_id, job_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("first call fails")

    ctrl._do_score = failing_then_ok
    await ctrl._score_with_lock(user_id=1, job_id=1)
    # Lock must be released — second call must not deadlock
    await ctrl._score_with_lock(user_id=1, job_id=2)
    assert call_count == 2


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

def test_get_controller_returns_none_before_init():
    """Positive: get_controller() returns None when never initialised."""
    _clear_controller()
    assert get_controller() is None


def test_init_controller_returns_instance():
    """Positive: _init_controller() returns a LLMTrafficController."""
    _clear_controller()
    ctrl = _init_controller()
    assert isinstance(ctrl, LLMTrafficController)
    _clear_controller()


def test_get_controller_returns_instance_after_init():
    """Positive: get_controller() returns the same instance after _init_controller()."""
    _clear_controller()
    ctrl = _init_controller()
    assert get_controller() is ctrl
    _clear_controller()


def test_clear_controller_sets_singleton_to_none():
    """Positive: _clear_controller() resets singleton to None."""
    _init_controller()
    _clear_controller()
    assert get_controller() is None


def test_init_controller_replaces_existing_singleton():
    """Negative: calling _init_controller() twice replaces the first instance."""
    _clear_controller()
    ctrl1 = _init_controller()
    ctrl2 = _init_controller()
    assert ctrl1 is not ctrl2
    assert get_controller() is ctrl2
    _clear_controller()


# ---------------------------------------------------------------------------
# scheduler integration — _start_traffic_controller
# ---------------------------------------------------------------------------

def test_scheduler_does_not_start_controller_when_flag_off():
    """Negative: controller is not created when enable_llm_traffic_controller=False."""
    _clear_controller()
    from app.pipeline.scheduler import _start_traffic_controller
    mock_settings = MagicMock()
    mock_settings.enable_llm_traffic_controller = False
    with patch("app.pipeline.scheduler.get_settings", return_value=mock_settings):
        _start_traffic_controller()
    assert get_controller() is None


@pytest.mark.asyncio
async def test_scheduler_starts_controller_when_flag_on():
    """Positive: controller is created and started when flag=True."""
    _clear_controller()
    from app.pipeline.scheduler import _start_traffic_controller
    mock_settings = MagicMock()
    mock_settings.enable_llm_traffic_controller = True
    with patch("app.pipeline.scheduler.get_settings", return_value=mock_settings):
        _start_traffic_controller()
    ctrl = get_controller()
    try:
        assert ctrl is not None
        assert ctrl._running is True
    finally:
        if ctrl:
            ctrl.stop()
        _clear_controller()


def test_scheduler_start_controller_exception_does_not_crash():
    """Negative: exception during controller start is caught — scheduler continues."""
    _clear_controller()
    from app.pipeline.scheduler import _start_traffic_controller
    mock_settings = MagicMock()
    mock_settings.enable_llm_traffic_controller = True
    with patch("app.pipeline.scheduler.get_settings", return_value=mock_settings):
        with patch(
            "app.shared.llm_traffic_controller._init_controller",
            side_effect=RuntimeError("init failed"),
        ):
            _start_traffic_controller()  # must not raise


def test_scheduler_stop_controller_is_safe_when_never_started():
    """Negative: _stop_traffic_controller() does not raise if controller was never started."""
    _clear_controller()
    from app.pipeline.scheduler import _stop_traffic_controller
    _stop_traffic_controller()  # must not raise
