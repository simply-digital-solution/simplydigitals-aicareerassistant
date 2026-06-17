"""
Unit tests for GeminiClient and get_claude_client() provider switching.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gemini_response(text: str, prompt_tokens: int = 50, output_tokens: int = 20):
    """Build a minimal Gemini API response dict."""
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}}
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": output_tokens,
        },
    }


def _make_mock_http(response_data: dict):
    """Return a mock httpx.AsyncClient whose post() returns response_data."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = response_data

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_resp)
    return mock_http


# ---------------------------------------------------------------------------
# GeminiClient._call() — request format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_call_sends_correct_url_and_key():
    """_call() must POST to the Gemini generateContent endpoint with the API key."""
    from app.shared.api_client import GeminiClient, GEMINI_BASE_URL

    mock_http = _make_mock_http(_make_gemini_response("hello"))

    with patch("httpx.AsyncClient", return_value=mock_http), \
         patch("app.shared.llm_logger.log_llm_call"):

        client = GeminiClient()
        client._api_key = "test-key"
        client._model = "gemini-2.0-flash"

        await client._call([{"role": "user", "content": "hi"}])

    mock_http.post.assert_called_once()
    call_args = mock_http.post.call_args
    assert call_args[0][0] == f"{GEMINI_BASE_URL}/gemini-2.0-flash:generateContent"
    assert call_args[1]["params"]["key"] == "test-key"


@pytest.mark.asyncio
async def test_gemini_call_converts_messages_to_contents():
    """System and user messages must be mapped to Gemini contents with role='user'."""
    from app.shared.api_client import GeminiClient

    mock_http = _make_mock_http(_make_gemini_response("ok"))
    captured_payload = {}

    async def capture_post(url, *, json, params):
        captured_payload.update(json)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _make_gemini_response("ok")
        return mock_resp

    mock_http.post = capture_post

    with patch("httpx.AsyncClient", return_value=mock_http), \
         patch("app.shared.llm_logger.log_llm_call"):

        client = GeminiClient()
        client._api_key = "key"
        client._model = "gemini-2.0-flash"

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Score this job."},
        ]
        await client._call(messages)

    contents = captured_payload["contents"]
    assert len(contents) == 2
    # Both system and user map to role="user" in Gemini format
    assert all(c["role"] == "user" for c in contents)
    assert contents[0]["parts"][0]["text"] == "You are a helpful assistant."
    assert contents[1]["parts"][0]["text"] == "Score this job."


@pytest.mark.asyncio
async def test_gemini_call_assistant_message_maps_to_model_role():
    """Assistant (reflexion) turns must map to role='model' for Gemini."""
    from app.shared.api_client import GeminiClient

    captured_payload = {}

    async def capture_post(url, *, json, params):
        captured_payload.update(json)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _make_gemini_response("retry response")
        return mock_resp

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = capture_post

    with patch("httpx.AsyncClient", return_value=mock_http), \
         patch("app.shared.llm_logger.log_llm_call"):

        client = GeminiClient()
        client._api_key = "key"
        client._model = "gemini-2.0-flash"

        messages = [
            {"role": "user", "content": "Score this."},
            {"role": "assistant", "content": "Bad JSON response."},
            {"role": "user", "content": "Please fix your output."},
        ]
        await client._call(messages)

    contents = captured_payload["contents"]
    assert contents[1]["role"] == "model"
    assert contents[0]["role"] == "user"
    assert contents[2]["role"] == "user"


# ---------------------------------------------------------------------------
# GeminiClient._call() — response parsing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_call_extracts_text_from_candidates():
    """_call() must return the text from candidates[0].content.parts."""
    from app.shared.api_client import GeminiClient

    mock_http = _make_mock_http(_make_gemini_response("parsed output text"))

    with patch("httpx.AsyncClient", return_value=mock_http), \
         patch("app.shared.llm_logger.log_llm_call"):

        client = GeminiClient()
        client._api_key = "key"
        client._model = "gemini-2.0-flash"

        full_text, _ = await client._call([{"role": "user", "content": "hi"}])

    assert full_text == "parsed output text"


@pytest.mark.asyncio
async def test_gemini_call_uses_real_token_counts_from_usage_metadata():
    """Token counts must come from usageMetadata, not word-count estimates."""
    from app.shared.api_client import GeminiClient

    mock_http = _make_mock_http(_make_gemini_response("result", prompt_tokens=123, output_tokens=456))

    with patch("httpx.AsyncClient", return_value=mock_http), \
         patch("app.shared.llm_logger.log_llm_call"):

        client = GeminiClient()
        client._api_key = "key"
        client._model = "gemini-2.0-flash"

        _, usage = await client._call([{"role": "user", "content": "hi"}])

    assert usage["input_tokens"] == 123
    assert usage["output_tokens"] == 456


@pytest.mark.asyncio
async def test_gemini_call_falls_back_to_word_count_when_no_usage_metadata():
    """When usageMetadata is absent, token counts fall back to word counts."""
    from app.shared.api_client import GeminiClient

    response_without_metadata = {
        "candidates": [{"content": {"parts": [{"text": "one two three four five"}]}}]
    }
    mock_http = _make_mock_http(response_without_metadata)

    with patch("httpx.AsyncClient", return_value=mock_http), \
         patch("app.shared.llm_logger.log_llm_call"):

        client = GeminiClient()
        client._api_key = "key"
        client._model = "gemini-2.0-flash"

        _, usage = await client._call([{"role": "user", "content": "hi"}])

    # Falls back to word count of output (5 words)
    assert usage["output_tokens"] == 5


@pytest.mark.asyncio
async def test_gemini_call_returns_empty_string_when_no_candidates():
    """_call() must return empty string (not raise) when candidates list is empty."""
    from app.shared.api_client import GeminiClient

    mock_http = _make_mock_http({"candidates": [], "usageMetadata": {}})

    with patch("httpx.AsyncClient", return_value=mock_http), \
         patch("app.shared.llm_logger.log_llm_call"):

        client = GeminiClient()
        client._api_key = "key"
        client._model = "gemini-2.0-flash"

        full_text, usage = await client._call([{"role": "user", "content": "hi"}])

    assert full_text == ""
    assert usage["output_tokens"] == 0


# ---------------------------------------------------------------------------
# GeminiClient._call() — streaming and usage logging
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_call_invokes_stream_callback_with_full_text():
    """When stream_callback is provided, it must be called with the full response text."""
    from app.shared.api_client import GeminiClient

    mock_http = _make_mock_http(_make_gemini_response("streamed content"))
    received = []

    async def callback(token):
        received.append(token)

    with patch("httpx.AsyncClient", return_value=mock_http), \
         patch("app.shared.llm_logger.log_llm_call"):

        client = GeminiClient()
        client._api_key = "key"
        client._model = "gemini-2.0-flash"

        await client._call([{"role": "user", "content": "hi"}], callback)

    assert received == ["streamed content"]


@pytest.mark.asyncio
async def test_gemini_call_calls_log_llm_call():
    """_call() must call log_llm_call with the correct request_type and model."""
    from app.shared.api_client import GeminiClient

    mock_http = _make_mock_http(_make_gemini_response("out", prompt_tokens=10, output_tokens=5))

    with patch("httpx.AsyncClient", return_value=mock_http), \
         patch("app.shared.llm_logger.log_llm_call") as mock_log:

        client = GeminiClient()
        client._api_key = "key"
        client._model = "gemini-2.0-flash"

        await client._call(
            [{"role": "user", "content": "score"}],
            user_id=3,
            job_posting_id=77,
            request_type="scoring",
        )

    mock_log.assert_called_once()
    kw = mock_log.call_args[1]
    assert kw["request_type"] == "scoring"
    assert kw["model"] == "gemini-2.0-flash"
    assert kw["input_tokens"] == 10
    assert kw["output_tokens"] == 5
    assert kw["user_id"] == 3
    assert kw["job_posting_id"] == 77


# ---------------------------------------------------------------------------
# get_claude_client() — provider switching
# ---------------------------------------------------------------------------

def test_get_claude_client_returns_gemini_when_key_is_set():
    """get_claude_client() must return GeminiClient when gemini_api_key is non-empty."""
    from app.shared import api_client
    from app.shared.api_client import GeminiClient

    # Reset singleton so the factory runs fresh
    api_client._client = None

    mock_settings = MagicMock()
    mock_settings.gemini_api_key = "some-key"
    mock_settings.gemini_model = "gemini-2.0-flash"
    mock_settings.max_self_corrections = 3

    with patch("app.shared.api_client.get_settings", return_value=mock_settings):
        client = api_client.get_claude_client()

    assert isinstance(client, GeminiClient)
    api_client._client = None  # clean up


def test_get_claude_client_returns_ollama_when_key_is_empty():
    """get_claude_client() must return OllamaClient when gemini_api_key is empty."""
    from app.shared import api_client
    from app.shared.api_client import OllamaClient

    api_client._client = None

    mock_settings = MagicMock()
    mock_settings.gemini_api_key = ""
    mock_settings.specialist_model = "deepseek-r1:7b"
    mock_settings.max_self_corrections = 3

    with patch("app.shared.api_client.get_settings", return_value=mock_settings):
        client = api_client.get_claude_client()

    assert isinstance(client, OllamaClient)
    api_client._client = None  # clean up
