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


# ---------------------------------------------------------------------------
# GroqClient._call()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_groq_client_call_success():
    """GroqClient parses the OpenAI-compatible response format correctly."""
    from app.shared.api_client import GroqClient

    fake_response = {
        "choices": [{"message": {"content": '{"value": "hello"}'}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = fake_response

    with (
        patch("app.shared.api_client.get_settings") as mock_cfg,
        patch("app.shared.rate_limiter.groq_rate_limiter.acquire", AsyncMock()),
        patch("httpx.AsyncClient") as mock_http,
    ):
        mock_cfg.return_value = MagicMock(
            groq_api_key="test-key",
            groq_model="llama-3.1-8b-instant",
            max_self_corrections=3,
        )
        mock_http.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock(post=AsyncMock(return_value=mock_resp))
        )
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

        client = GroqClient()
        text_out, usage = await client._call(
            [{"role": "user", "content": "hello"}]
        )

    assert text_out == '{"value": "hello"}'
    assert usage["input_tokens"] == 50
    assert usage["output_tokens"] == 10


@pytest.mark.asyncio
async def test_groq_client_call_propagates_http_error():
    """GroqClient raises on non-2xx HTTP response."""
    import httpx
    from app.shared.api_client import GroqClient

    with (
        patch("app.shared.api_client.get_settings") as mock_cfg,
        patch("app.shared.rate_limiter.groq_rate_limiter.acquire", AsyncMock()),
        patch("httpx.AsyncClient") as mock_http,
    ):
        mock_cfg.return_value = MagicMock(
            groq_api_key="test-key",
            groq_model="llama-3.1-8b-instant",
            max_self_corrections=3,
        )
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=MagicMock()
        )
        mock_http.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock(post=AsyncMock(return_value=mock_resp))
        )
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

        client = GroqClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client._call([{"role": "user", "content": "hello"}])


# ---------------------------------------------------------------------------
# get_scoring_client() factory
# ---------------------------------------------------------------------------

def test_get_scoring_client_returns_groq_when_key_set():
    """Returns GroqClient when GROQ_API_KEY is configured."""
    from app.shared import api_client
    from app.shared.api_client import GroqClient

    original = api_client._scoring_client
    api_client._scoring_client = None
    try:
        with patch("app.shared.api_client.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                groq_api_key="gsk_test",
                gemini_api_key="",
                groq_model="llama-3.1-8b-instant",
                max_self_corrections=3,
            )
            client = api_client.get_scoring_client()
        assert isinstance(client, GroqClient)
    finally:
        api_client._scoring_client = original


def test_get_scoring_client_returns_gemini_when_no_groq():
    """Falls back to GeminiClient when only GEMINI_API_KEY is configured."""
    from app.shared import api_client
    from app.shared.api_client import GeminiClient

    original = api_client._scoring_client
    api_client._scoring_client = None
    try:
        with patch("app.shared.api_client.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                groq_api_key="",
                gemini_api_key="gm_test",
                gemini_model="gemini-flash-latest",
                max_self_corrections=3,
            )
            client = api_client.get_scoring_client()
        assert isinstance(client, GeminiClient)
    finally:
        api_client._scoring_client = original


def test_get_scoring_client_returns_ollama_as_last_resort():
    """Falls back to OllamaClient when neither Groq nor Gemini key is set."""
    from app.shared import api_client
    from app.shared.api_client import OllamaClient

    original = api_client._scoring_client
    api_client._scoring_client = None
    try:
        with patch("app.shared.api_client.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                groq_api_key="",
                gemini_api_key="",
                specialist_model="llama3.1:8b",
                max_self_corrections=3,
            )
            client = api_client.get_scoring_client()
        assert isinstance(client, OllamaClient)
    finally:
        api_client._scoring_client = original


def test_get_scoring_client_is_singleton():
    """Second call returns the same object (no re-instantiation)."""
    from app.shared import api_client

    original = api_client._scoring_client
    api_client._scoring_client = None
    try:
        with patch("app.shared.api_client.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                groq_api_key="gsk_test",
                gemini_api_key="",
                groq_model="llama-3.1-8b-instant",
                max_self_corrections=3,
            )
            c1 = api_client.get_scoring_client()
            c2 = api_client.get_scoring_client()
        assert c1 is c2
    finally:
        api_client._scoring_client = original
