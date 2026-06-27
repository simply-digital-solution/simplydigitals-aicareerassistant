"""
Tests for _compute_batch_size() in app.shared.system_resources.
"""
import pytest
from unittest.mock import patch, MagicMock

from app.shared.system_resources import _compute_batch_size, _MIN_BATCH, _MAX_BATCH


def _mock_psutil(cpu: float, mem: float):
    """Patch psutil to return fixed cpu% and mem%."""
    mem_mock = MagicMock()
    mem_mock.percent = mem
    return (
        patch("app.shared.system_resources.psutil.cpu_percent", return_value=cpu),
        patch("app.shared.system_resources.psutil.virtual_memory", return_value=mem_mock),
    )


# ---------------------------------------------------------------------------
# Positive — CPU low, memory normal → max batch allowed
# ---------------------------------------------------------------------------

def test_low_cpu_low_mem_returns_max_batch():
    """Positive: idle host should allow maximum concurrency."""
    cpu_p, mem_p = _mock_psutil(cpu=10.0, mem=30.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert result == _MAX_BATCH


def test_cpu_exactly_at_low_watermark_returns_max_batch():
    """Positive: CPU exactly at low watermark → max batch."""
    cpu_p, mem_p = _mock_psutil(cpu=50.0, mem=30.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert result == _MAX_BATCH


def test_cpu_midpoint_returns_interpolated_value():
    """Positive: CPU midway between watermarks → interpolated batch between min and max."""
    cpu_p, mem_p = _mock_psutil(cpu=65.0, mem=30.0)  # midpoint of 50–80
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert _MIN_BATCH < result < _MAX_BATCH


def test_custom_min_max_respected():
    """Positive: caller-supplied min/max override module defaults."""
    cpu_p, mem_p = _mock_psutil(cpu=10.0, mem=30.0)
    with cpu_p, mem_p:
        result = _compute_batch_size(min_batch=2, max_batch=8)
    assert result == 8


def test_result_always_at_least_min_batch():
    """Positive: result is never below min_batch regardless of load."""
    cpu_p, mem_p = _mock_psutil(cpu=99.0, mem=99.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert result >= _MIN_BATCH


def test_result_never_exceeds_max_batch():
    """Positive: result never exceeds max_batch even at zero load."""
    cpu_p, mem_p = _mock_psutil(cpu=0.0, mem=0.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert result <= _MAX_BATCH


# ---------------------------------------------------------------------------
# Negative — high CPU or memory → min batch enforced
# ---------------------------------------------------------------------------

def test_high_cpu_returns_min_batch():
    """Negative: CPU above high watermark forces minimum batch size."""
    cpu_p, mem_p = _mock_psutil(cpu=85.0, mem=30.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert result == _MIN_BATCH


def test_cpu_exactly_at_high_watermark_returns_min_batch():
    """Negative: CPU exactly at high watermark → min batch."""
    cpu_p, mem_p = _mock_psutil(cpu=80.0, mem=30.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert result == _MIN_BATCH


def test_high_memory_returns_min_batch():
    """Negative: memory above high watermark forces minimum batch even with low CPU."""
    cpu_p, mem_p = _mock_psutil(cpu=10.0, mem=90.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert result == _MIN_BATCH


def test_memory_exactly_at_high_watermark_returns_min_batch():
    """Negative: memory exactly at high watermark → min batch."""
    cpu_p, mem_p = _mock_psutil(cpu=10.0, mem=85.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert result == _MIN_BATCH


def test_both_cpu_and_mem_high_returns_min_batch():
    """Negative: both CPU and memory critical → min batch."""
    cpu_p, mem_p = _mock_psutil(cpu=95.0, mem=95.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert result == _MIN_BATCH


def test_custom_watermarks_respected_for_high_cpu():
    """Negative: caller-supplied cpu_high threshold is respected."""
    cpu_p, mem_p = _mock_psutil(cpu=60.0, mem=30.0)
    with cpu_p, mem_p:
        # With cpu_high=55, cpu=60 should trigger min_batch
        result = _compute_batch_size(cpu_low=30.0, cpu_high=55.0)
    assert result == _MIN_BATCH


def test_return_type_is_int():
    """Negative: result must always be a plain int, never a float."""
    cpu_p, mem_p = _mock_psutil(cpu=65.0, mem=30.0)
    with cpu_p, mem_p:
        result = _compute_batch_size()
    assert isinstance(result, int)
