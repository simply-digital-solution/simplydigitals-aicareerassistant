"""
System resource utilities for adaptive LLM traffic control.

_compute_batch_size() estimates how many concurrent LLM calls are safe
given current CPU and memory pressure on this host. It is intentionally
dead code in this release — wired up in Release 3 (LLMTrafficController).
"""
import logging

import psutil

logger = logging.getLogger(__name__)

# Thresholds for backing off concurrency
_CPU_HIGH_WATERMARK = 80.0    # % — above this, drop to minimum batch
_CPU_LOW_WATERMARK = 50.0     # % — below this, allow maximum batch
_MEM_HIGH_WATERMARK = 85.0   # % — above this, drop to minimum batch

_MIN_BATCH = 1
_MAX_BATCH = 5   # conservative ceiling for t3.micro (2 vCPU, 1 GB RAM)


def _compute_batch_size(
    *,
    min_batch: int = _MIN_BATCH,
    max_batch: int = _MAX_BATCH,
    cpu_high: float = _CPU_HIGH_WATERMARK,
    cpu_low: float = _CPU_LOW_WATERMARK,
    mem_high: float = _MEM_HIGH_WATERMARK,
) -> int:
    """
    Return a safe concurrent batch size based on current CPU and RAM usage.

    - CPU >= cpu_high OR RAM >= mem_high  → min_batch
    - CPU <= cpu_low                       → max_batch
    - CPU between cpu_low and cpu_high    → linear interpolation

    Parameters are exposed for testing; callers should use defaults.
    """
    cpu_pct = psutil.cpu_percent(interval=None)
    mem_pct = psutil.virtual_memory().percent

    logger.debug(
        "system_resources: cpu=%.1f%% mem=%.1f%%", cpu_pct, mem_pct
    )

    if cpu_pct >= cpu_high or mem_pct >= mem_high:
        return min_batch

    if cpu_pct <= cpu_low:
        return max_batch

    # Linear scale: cpu_low → max_batch, cpu_high → min_batch
    ratio = (cpu_pct - cpu_low) / (cpu_high - cpu_low)
    scaled = max_batch - ratio * (max_batch - min_batch)
    return max(min_batch, round(scaled))
