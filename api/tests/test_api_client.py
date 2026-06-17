"""
Unit tests for BaseLLMClient.run_agent() reflexion behaviour:
  - max_self_corrections override (0 = no retries)
  - asyncio.sleep(5) called between reflexion retries
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from pydantic import BaseModel

from app.shared.schemas import AgentError


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------

class _SimpleOutput(BaseModel):
    value: str


def _make_client(max_corrections: int = 3):
    from app.shared.api_client import BaseLLMClient

    class _FakeClient(BaseLLMClient):
        def __init__(self):
            self._max_corrections = max_corrections
            self._model = "fake-model"

        async def _call(self, messages, stream_callback=None, **kwargs):
            return '{"value": "ok"}', {"input_tokens": 10, "output_tokens": 5}

        def _scrub_secrets(self, text): pass

    return _FakeClient()


# ---------------------------------------------------------------------------
# max_self_corrections=0 → no retries even when parse fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_retries_when_max_self_corrections_zero():
    client = _make_client(max_corrections=3)
    call_count = 0

    async def bad_call(messages, stream_callback=None, **kwargs):
        nonlocal call_count
        call_count += 1
        return "not valid json at all $$$$", {}

    client._call = bad_call

    with patch("app.shared.api_client.asyncio.sleep", AsyncMock()) as mock_sleep:
        result, _ = await client.run_agent(
            agent_name="test",
            system_prompt="sys",
            user_message="usr",
            output_schema=_SimpleOutput,
            max_self_corrections=0,
        )

    assert isinstance(result, AgentError)
    assert call_count == 1        # only the initial call, no retries
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# max_self_corrections override respected over instance default
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_self_corrections_override_limits_retries():
    client = _make_client(max_corrections=3)
    call_count = 0

    async def bad_call(messages, stream_callback=None, **kwargs):
        nonlocal call_count
        call_count += 1
        return "bad json $$$$", {}

    client._call = bad_call

    with patch("app.shared.api_client.asyncio.sleep", AsyncMock()):
        result, _ = await client.run_agent(
            agent_name="test",
            system_prompt="sys",
            user_message="usr",
            output_schema=_SimpleOutput,
            max_self_corrections=1,
        )

    assert isinstance(result, AgentError)
    assert call_count == 2        # initial + 1 retry (not 3)


# ---------------------------------------------------------------------------
# asyncio.sleep(5) called between reflexion retries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sleep_called_between_retries():
    client = _make_client(max_corrections=2)
    call_count = 0

    async def bad_call(messages, stream_callback=None, **kwargs):
        nonlocal call_count
        call_count += 1
        return "bad json $$$$", {}

    client._call = bad_call

    with patch("app.shared.api_client.asyncio.sleep", AsyncMock()) as mock_sleep:
        await client.run_agent(
            agent_name="test",
            system_prompt="sys",
            user_message="usr",
            output_schema=_SimpleOutput,
        )

    # 2 retries → 2 sleeps, each of 5 seconds
    assert mock_sleep.call_count == 2
    for c in mock_sleep.call_args_list:
        assert c == call(5)


# ---------------------------------------------------------------------------
# No sleep on successful first call (no retries needed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_sleep_when_parse_succeeds_first_try():
    client = _make_client(max_corrections=3)

    with patch("app.shared.api_client.asyncio.sleep", AsyncMock()) as mock_sleep:
        result, _ = await client.run_agent(
            agent_name="test",
            system_prompt="sys",
            user_message="usr",
            output_schema=_SimpleOutput,
        )

    assert result.value == "ok"
    mock_sleep.assert_not_called()
