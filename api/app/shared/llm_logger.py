"""
Daily rotating file logger for LLM usage.

Writes one line per LLM call to api/logs/llm_usage_YYYY-MM-DD.log.
A new file is created automatically at midnight.
"""
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_LOGS_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

_file_handler = TimedRotatingFileHandler(
    filename=str(_LOGS_DIR / "llm_usage.log"),
    when="midnight",
    interval=1,
    backupCount=90,
    utc=False,
    encoding="utf-8",
)
_file_handler.suffix = "%Y-%m-%d"
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))

llm_file_logger = logging.getLogger("llm_usage_file")
llm_file_logger.setLevel(logging.INFO)
llm_file_logger.addHandler(_file_handler)
llm_file_logger.propagate = False


def log_llm_call(
    *,
    user_id: int | None,
    job_posting_id: int | None,
    request_type: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    requested_at: str,
    responded_at: str,
    duration_s: float,
) -> None:
    llm_file_logger.info(
        "user_id=%s job_id=%s type=%s model=%s input=%d output=%d duration=%.1fs requested=%s responded=%s",
        user_id, job_posting_id, request_type, model,
        input_tokens, output_tokens, duration_s,
        requested_at, responded_at,
    )
