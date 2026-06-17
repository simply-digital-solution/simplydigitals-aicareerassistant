"""
Tests for LLM usage logging: file logger and DB insert in OllamaClient._call().
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# llm_logger.py unit tests
# ---------------------------------------------------------------------------

def test_log_llm_call_writes_to_file_logger():
    """log_llm_call() should emit one INFO line to the llm_usage_file logger."""
    from app.shared.llm_logger import log_llm_call, llm_file_logger

    with patch.object(llm_file_logger, "info") as mock_info:
        log_llm_call(
            user_id=1,
            job_posting_id=42,
            request_type="scoring",
            model="deepseek-r1:7b",
            input_tokens=100,
            output_tokens=200,
            requested_at="2026-06-17T05:00:00",
            responded_at="2026-06-17T05:01:00",
            duration_s=60.0,
        )

    mock_info.assert_called_once()
    logged = mock_info.call_args[0]
    # The format string is first positional arg; check all key values appear
    formatted = logged[0] % logged[1:]
    assert "user_id=1" in formatted
    assert "job_id=42" in formatted
    assert "type=scoring" in formatted
    assert "model=deepseek-r1:7b" in formatted
    assert "input=100" in formatted
    assert "output=200" in formatted
    assert "duration=60.0s" in formatted


def test_log_llm_call_none_user_and_job():
    """log_llm_call() must not raise when user_id and job_posting_id are None."""
    from app.shared.llm_logger import log_llm_call, llm_file_logger

    with patch.object(llm_file_logger, "info") as mock_info:
        log_llm_call(
            user_id=None,
            job_posting_id=None,
            request_type="research",
            model="llama3.1:8b",
            input_tokens=50,
            output_tokens=80,
            requested_at="2026-06-17T05:00:00",
            responded_at="2026-06-17T05:00:05",
            duration_s=5.0,
        )

    mock_info.assert_called_once()


# ---------------------------------------------------------------------------
# OllamaClient._call() — DB insert and log_llm_call integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_inserts_llm_usage_log_row():
    """_call() should INSERT into llm_usage_logs when db is provided."""
    from app.shared.api_client import OllamaClient

    # Mock Ollama HTTP response
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": "hello world output"}
    }

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    with patch("httpx.AsyncClient") as mock_http_cls, \
         patch("app.shared.llm_logger.log_llm_call") as mock_log:

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http_cls.return_value = mock_http

        client = OllamaClient()
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Score this job."},
        ]

        full_text, usage = await client._call(
            messages,
            user_id=7,
            job_posting_id=99,
            request_type="scoring",
            db=mock_db,
        )

    assert full_text == "hello world output"
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0

    # DB insert was called
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()
    call_kwargs = mock_db.execute.call_args[0][1]
    assert call_kwargs["user_id"] == 7
    assert call_kwargs["job_posting_id"] == 99
    assert call_kwargs["request_type"] == "scoring"

    # File log was called
    mock_log.assert_called_once()
    log_kwargs = mock_log.call_args[1]
    assert log_kwargs["user_id"] == 7
    assert log_kwargs["job_posting_id"] == 99
    assert log_kwargs["request_type"] == "scoring"
    assert log_kwargs["input_tokens"] > 0
    assert log_kwargs["output_tokens"] > 0


@pytest.mark.asyncio
async def test_call_skips_db_insert_when_no_db():
    """_call() should not raise and should still call log_llm_call when db=None."""
    from app.shared.api_client import OllamaClient

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"message": {"content": "output"}}

    with patch("httpx.AsyncClient") as mock_http_cls, \
         patch("app.shared.llm_logger.log_llm_call") as mock_log:

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http_cls.return_value = mock_http

        client = OllamaClient()
        messages = [{"role": "user", "content": "hello"}]

        full_text, usage = await client._call(
            messages,
            user_id=None,
            job_posting_id=None,
            request_type="research",
            db=None,
        )

    assert full_text == "output"
    mock_log.assert_called_once()


# ---------------------------------------------------------------------------
# run_agent() threads request_type through to _call()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_passes_request_type_to_call():
    """run_agent() should forward request_type and job_posting_id to _call()."""
    from app.shared.api_client import OllamaClient
    from pydantic import BaseModel

    class DummySchema(BaseModel):
        value: str

    import json as _json
    valid_output = _json.dumps({"value": "ok"})

    with patch.object(OllamaClient, "_call", new_callable=AsyncMock) as mock_call, \
         patch.object(OllamaClient, "_record_run", new_callable=AsyncMock, return_value=1), \
         patch("app.shared.api_client._update_budget", new_callable=AsyncMock):

        mock_call.return_value = (valid_output, {
            "input_tokens": 10, "output_tokens": 5,
            "cache_read_tokens": 0, "cache_creation_tokens": 0,
        })

        client = OllamaClient()
        mock_db = AsyncMock()

        await client.run_agent(
            agent_name="test_agent",
            system_prompt="sys",
            user_message="user",
            output_schema=DummySchema,
            db=mock_db,
            user_id=3,
            job_posting_id=55,
            request_type="scoring",
        )

    mock_call.assert_called_once()
    _, call_kwargs = mock_call.call_args
    assert call_kwargs["user_id"] == 3
    assert call_kwargs["job_posting_id"] == 55
    assert call_kwargs["request_type"] == "scoring"
