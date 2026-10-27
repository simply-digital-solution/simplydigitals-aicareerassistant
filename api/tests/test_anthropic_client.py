"""
Unit tests for AnthropicClient._call().
"""
from unittest.mock import AsyncMock, patch

import pytest


def _make_response(text: str, input_tokens=100, output_tokens=50,
                    cache_read=0, cache_creation=0, model="claude-haiku-5-5"):
    from anthropic.types import Message, TextBlock, Usage

    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model=model,
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
        ),
    )


def _make_client(model="claude-haiku-5-5"):
    """
    Build an AnthropicClient with its SDK client mocked out. Patches
    get_settings at its import site in api_client.py (not app.shared.config)
    — api_client.py does `from app.shared.config import get_settings`, so
    the name lives in its own module namespace and must be patched there,
    or the constructor silently falls through to real settings/.env values.
    """
    from app.shared.api_client import AnthropicClient

    with patch("app.shared.api_client.get_settings") as mock_settings:
        mock_settings.return_value.anthropic_api_key = "test-key"
        mock_settings.return_value.max_self_corrections = 3
        client = AnthropicClient(model=model)
    client._client = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Model selection — per-instance, not a single global setting
# ---------------------------------------------------------------------------

def test_constructor_sets_model_per_instance():
    haiku_client = _make_client(model="claude-haiku-5-5")
    sonnet_client = _make_client(model="claude-sonnet-5-5")

    assert haiku_client._model == "claude-haiku-5-5"
    assert sonnet_client._model == "claude-sonnet-5-5"


# ---------------------------------------------------------------------------
# _call() — message formatting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_splits_system_message_into_top_level_param():
    """run_agent() sends system as a message with role='system' — Anthropic
    takes it as a separate top-level `system` param, not a message."""
    client = _make_client()
    client._client.messages.create = AsyncMock(return_value=_make_response("ok"))

    with patch("app.shared.llm_logger.log_llm_call"):
        await client._call([
            {"role": "system", "content": "You are a classifier."},
            {"role": "user", "content": "Classify this job."},
        ])

    call_kwargs = client._client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == [{
        "type": "text",
        "text": "You are a classifier.",
        "cache_control": {"type": "ephemeral"},
    }]
    assert call_kwargs["messages"] == [{"role": "user", "content": "Classify this job."}]


@pytest.mark.asyncio
async def test_call_passes_model_and_omits_temperature():
    """
    temperature is removed on current-generation Claude models (Haiku 5.5,
    Sonnet 5.5) — sending any value, including the 0.1 GeminiClient uses for
    deterministic output, returns a 400 "`temperature` is deprecated for
    this model." Confirmed against the live API. Omit the param entirely
    rather than guessing at an output_config.effort replacement.
    """
    client = _make_client(model="claude-sonnet-5-5")
    client._client.messages.create = AsyncMock(return_value=_make_response("ok"))

    with patch("app.shared.llm_logger.log_llm_call"):
        await client._call([{"role": "user", "content": "hi"}])

    call_kwargs = client._client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-5-5"
    assert "temperature" not in call_kwargs


@pytest.mark.asyncio
async def test_call_preserves_multi_turn_reflexion_messages():
    """Reflexion retries append assistant + user turns after the first
    exchange — these must pass through unchanged, not be treated as system."""
    client = _make_client()
    client._client.messages.create = AsyncMock(return_value=_make_response("ok"))

    with patch("app.shared.llm_logger.log_llm_call"):
        await client._call([
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "bad output"},
            {"role": "user", "content": "please fix it"},
        ])

    call_kwargs = client._client.messages.create.call_args.kwargs
    assert call_kwargs["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "bad output"},
        {"role": "user", "content": "please fix it"},
    ]


# ---------------------------------------------------------------------------
# _call() — response parsing and usage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_extracts_text_from_content_blocks():
    client = _make_client()
    client._client.messages.create = AsyncMock(
        return_value=_make_response("the classification result")
    )

    with patch("app.shared.llm_logger.log_llm_call"):
        text, _ = await client._call([{"role": "user", "content": "hi"}])

    assert text == "the classification result"


@pytest.mark.asyncio
async def test_call_reports_real_cache_token_counts():
    """Unlike Gemini/Ollama (always 0), Anthropic reports real cache hits —
    this is the actual cost-saving signal the whole caching feature exists for."""
    client = _make_client()
    client._client.messages.create = AsyncMock(
        return_value=_make_response(
            "ok", input_tokens=120, output_tokens=40, cache_read=1500, cache_creation=0,
        )
    )

    with patch("app.shared.llm_logger.log_llm_call"):
        _, usage = await client._call([{"role": "user", "content": "hi"}])

    assert usage["input_tokens"] == 120
    assert usage["output_tokens"] == 40
    assert usage["cache_read_tokens"] == 1500
    assert usage["cache_creation_tokens"] == 0


@pytest.mark.asyncio
async def test_call_handles_zero_cache_tokens():
    client = _make_client()
    client._client.messages.create = AsyncMock(
        return_value=_make_response("ok", cache_read=0, cache_creation=0)
    )

    with patch("app.shared.llm_logger.log_llm_call"):
        _, usage = await client._call([{"role": "user", "content": "hi"}])

    assert usage["cache_read_tokens"] == 0
    assert usage["cache_creation_tokens"] == 0


@pytest.mark.asyncio
async def test_call_invokes_stream_callback_when_provided():
    client = _make_client()
    client._client.messages.create = AsyncMock(return_value=_make_response("streamed text"))
    callback = AsyncMock()

    with patch("app.shared.llm_logger.log_llm_call"):
        await client._call([{"role": "user", "content": "hi"}], stream_callback=callback)

    callback.assert_called_once_with("streamed text")


# ---------------------------------------------------------------------------
# _call() — error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_reraises_rate_limit_error():
    import anthropic

    client = _make_client()
    # RateLimitError requires a response/body in this SDK version's constructor
    err = anthropic.RateLimitError("rate limited", response=AsyncMock(status_code=429, headers={}), body=None)
    client._client.messages.create = AsyncMock(side_effect=err)

    with pytest.raises(anthropic.RateLimitError):
        await client._call([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_call_reraises_connection_error():
    import anthropic

    client = _make_client()
    err = anthropic.APIConnectionError(request=AsyncMock())
    client._client.messages.create = AsyncMock(side_effect=err)

    with pytest.raises(anthropic.APIConnectionError):
        await client._call([{"role": "user", "content": "hi"}])
