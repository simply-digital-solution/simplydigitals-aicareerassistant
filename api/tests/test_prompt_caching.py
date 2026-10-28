"""
Unit tests for prompt caching on the scoring path:
  - run_research_agent() only passes cacheable_prefix for request_type="scoring"
  - BaseLLMClient.run_agent() builds [cacheable_prefix, user_message] content
    when given a cacheable_prefix, and a plain string otherwise
  - AnthropicClient._call() turns that two-piece content into text blocks
    with cache_control on the first block only
  - GeminiClient._call()/OllamaClient._call() flatten list content back to
    a plain string (defensive — scoring normally only reaches Anthropic)
  - _scrub_secrets() still sees secrets that appear only in cacheable_prefix
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.modules.agents.research_agent import run_research_agent
from app.shared.schemas import ResearchOutput

# ---------------------------------------------------------------------------
# research_agent.py: cacheable_prefix only passed for request_type="scoring"
# ---------------------------------------------------------------------------

def _make_client(name: str):
    client = MagicMock(name=name)
    client.run_agent = AsyncMock(return_value=(
        ResearchOutput(opportunities=[]), {"model": name},
    ))
    return client


@pytest.mark.asyncio
async def test_scoring_request_passes_cacheable_prefix():
    scorer_client = _make_client("scorer")
    profile = {
        "candidate_summary": "Senior PM",
        "background": {"years_experience": 10, "skills": ["SAP"]},
    }
    job_postings = [{"title": "PM", "company": "Acme", "description": "Build things"}]

    with patch("app.modules.agents.research_agent.get_scorer_client", return_value=scorer_client), \
         patch("app.modules.agents.research_agent.get_llm_client", return_value=_make_client("research")), \
         patch("app.modules.agents.research_agent._load_system_prompt", return_value="sys"):
        await run_research_agent(
            profile=profile, job_postings=job_postings, request_type="scoring",
        )

    _, kwargs = scorer_client.run_agent.call_args
    assert "cacheable_prefix" in kwargs
    assert "Senior PM" in kwargs["cacheable_prefix"]
    # The job posting (variable per call) must NOT be in the cacheable prefix.
    assert "Acme" not in kwargs["cacheable_prefix"]
    assert "Acme" in kwargs["user_message"]


@pytest.mark.asyncio
async def test_non_scoring_request_does_not_pass_cacheable_prefix():
    research_client = _make_client("research")
    profile = {"candidate_summary": "Senior PM", "background": {}}

    with patch("app.modules.agents.research_agent.get_scorer_client", return_value=_make_client("scorer")), \
         patch("app.modules.agents.research_agent.get_llm_client", return_value=research_client), \
         patch("app.modules.agents.research_agent._load_system_prompt", return_value="sys"):
        await run_research_agent(
            profile=profile, job_postings=[], request_type="research",
        )

    _, kwargs = research_client.run_agent.call_args
    assert "cacheable_prefix" not in kwargs
    # Full message still contains the profile content, same as before caching existed.
    assert "Senior PM" in kwargs["user_message"]


# ---------------------------------------------------------------------------
# BaseLLMClient.run_agent(): content shape built from cacheable_prefix
# ---------------------------------------------------------------------------

class _Output(BaseModel):
    value: str


def _make_fake_llm_client(capture: dict):
    from app.shared.api_client import BaseLLMClient

    class _FakeClient(BaseLLMClient):
        def __init__(self):
            self._max_corrections = 0
            self._model = "fake-model"

        async def _call(self, messages, stream_callback=None, **kwargs):
            capture["messages"] = messages
            return '{"value": "ok"}', {"input_tokens": 1, "output_tokens": 1}

        def _scrub_secrets(self, text):
            capture["scrubbed_text"] = text

    return _FakeClient()


@pytest.mark.asyncio
async def test_run_agent_without_cacheable_prefix_sends_plain_string():
    capture = {}
    client = _make_fake_llm_client(capture)

    await client.run_agent(
        agent_name="test", system_prompt="sys", user_message="usr",
        output_schema=_Output,
    )

    user_msg = capture["messages"][1]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "usr"


@pytest.mark.asyncio
async def test_run_agent_with_cacheable_prefix_sends_two_piece_list():
    capture = {}
    client = _make_fake_llm_client(capture)

    await client.run_agent(
        agent_name="test", system_prompt="sys", user_message="job stuff",
        output_schema=_Output, cacheable_prefix="profile stuff",
    )

    user_msg = capture["messages"][1]
    assert user_msg["content"] == ["profile stuff", "job stuff"]


@pytest.mark.asyncio
async def test_run_agent_scrubs_secrets_in_cacheable_prefix():
    capture = {}
    client = _make_fake_llm_client(capture)

    await client.run_agent(
        agent_name="test", system_prompt="sys", user_message="job stuff",
        output_schema=_Output,
        cacheable_prefix="password: supersecret123",
    )

    assert "password: supersecret123" in capture["scrubbed_text"]


# ---------------------------------------------------------------------------
# AnthropicClient._call(): two-piece content -> blocks with cache_control
# on the cacheable piece only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anthropic_client_marks_only_cacheable_prefix_block():
    from app.shared.api_client import AnthropicClient

    client = AnthropicClient.__new__(AnthropicClient)
    client._model = "claude-haiku"
    client._max_corrections = 0

    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="ok")]
    fake_response.usage.input_tokens = 100
    fake_response.usage.output_tokens = 10
    fake_response.usage.cache_read_input_tokens = 50
    fake_response.usage.cache_creation_input_tokens = 0

    fake_anthropic_client = MagicMock()
    fake_anthropic_client.messages.create = AsyncMock(return_value=fake_response)
    client._client = fake_anthropic_client

    with patch.object(AnthropicClient, "_persist_usage", AsyncMock()):
        await client._call(
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": ["profile stuff", "job stuff"]},
            ],
        )

    _, call_kwargs = fake_anthropic_client.messages.create.call_args
    user_content = call_kwargs["messages"][0]["content"]
    assert user_content[0] == {
        "type": "text", "text": "profile stuff",
        "cache_control": {"type": "ephemeral"},
    }
    assert user_content[1] == {"type": "text", "text": "job stuff"}


@pytest.mark.asyncio
async def test_anthropic_client_persists_real_cache_tokens_to_agent_runs():
    """
    _record_run() used to hardcode cache_read_tokens/cache_creation_tokens
    to 0 regardless of what the Anthropic response reported — this
    verifies the real values from usage now reach the agent_runs INSERT.
    """
    from app.shared.api_client import AnthropicClient

    client = AnthropicClient.__new__(AnthropicClient)
    client._model = "claude-haiku"
    client._max_corrections = 0

    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text='{"value": "ok"}')]
    fake_response.usage.input_tokens = 128
    fake_response.usage.output_tokens = 50
    fake_response.usage.cache_read_input_tokens = 7967
    fake_response.usage.cache_creation_input_tokens = 0

    fake_anthropic_client = MagicMock()
    fake_anthropic_client.messages.create = AsyncMock(return_value=fake_response)
    client._client = fake_anthropic_client

    mock_db = AsyncMock()
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = 1
    mock_db.execute = AsyncMock(return_value=insert_result)
    mock_db.commit = AsyncMock()

    with patch("app.shared.api_client._update_budget", new_callable=AsyncMock):
        await client.run_agent(
            agent_name="research", system_prompt="sys", user_message="job stuff",
            output_schema=_Output, cacheable_prefix="profile stuff",
            db=mock_db, user_id=2,
        )

    agent_runs_call = next(
        c for c in mock_db.execute.call_args_list
        if "INSERT INTO agent_runs" in str(c.args[0])
    )
    params = agent_runs_call.args[1]
    assert params["crt"] == 7967
    assert params["cct"] == 0


@pytest.mark.asyncio
async def test_anthropic_client_plain_string_content_unaffected():
    from app.shared.api_client import AnthropicClient

    client = AnthropicClient.__new__(AnthropicClient)
    client._model = "claude-haiku"
    client._max_corrections = 0

    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="ok")]
    fake_response.usage.input_tokens = 100
    fake_response.usage.output_tokens = 10
    fake_response.usage.cache_read_input_tokens = 0
    fake_response.usage.cache_creation_input_tokens = 0

    fake_anthropic_client = MagicMock()
    fake_anthropic_client.messages.create = AsyncMock(return_value=fake_response)
    client._client = fake_anthropic_client

    with patch.object(AnthropicClient, "_persist_usage", AsyncMock()):
        await client._call(
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "plain message"},
            ],
        )

    _, call_kwargs = fake_anthropic_client.messages.create.call_args
    assert call_kwargs["messages"][0]["content"] == "plain message"


# ---------------------------------------------------------------------------
# GeminiClient/OllamaClient: list content is flattened, never crashes
# ---------------------------------------------------------------------------

def test_flatten_content_helper():
    from app.shared.api_client import _flatten_content

    assert _flatten_content("plain") == "plain"
    assert _flatten_content(["a", "b"]) == "ab"


@pytest.mark.asyncio
async def test_gemini_client_flattens_list_content():
    from app.shared.api_client import GeminiClient

    client = GeminiClient.__new__(GeminiClient)
    client._model = "gemini-model"
    client._fallback_model = None
    client._api_key = "key"
    client._max_corrections = 0

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1},
    }

    fake_http_client = AsyncMock()
    fake_http_client.__aenter__.return_value = fake_http_client
    fake_http_client.__aexit__.return_value = None
    fake_http_client.post = AsyncMock(return_value=fake_resp)

    with patch("app.shared.api_client.httpx.AsyncClient", return_value=fake_http_client), \
         patch("app.shared.rate_limiter.gemini_rate_limiter.acquire", AsyncMock()), \
         patch.object(GeminiClient, "_persist_usage", AsyncMock()):
        full_text, usage = await client._call(
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": ["profile stuff", "job stuff"]},
            ],
        )

    assert full_text == "ok"
    sent_payload = fake_http_client.post.call_args.kwargs["json"]
    user_parts = sent_payload["contents"][1]["parts"]
    assert user_parts == [{"text": "profile stuffjob stuff"}]


@pytest.mark.asyncio
async def test_ollama_client_flattens_list_content():
    from app.shared.api_client import OllamaClient

    client = OllamaClient.__new__(OllamaClient)
    client._model = "ollama-model"
    client._max_corrections = 0

    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"message": {"content": "ok"}}

    fake_http_client = AsyncMock()
    fake_http_client.__aenter__.return_value = fake_http_client
    fake_http_client.__aexit__.return_value = None
    fake_http_client.post = AsyncMock(return_value=fake_resp)

    with patch("app.shared.api_client.httpx.AsyncClient", return_value=fake_http_client), \
         patch.object(OllamaClient, "_persist_usage", AsyncMock()):
        full_text, usage = await client._call(
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": ["profile stuff", "job stuff"]},
            ],
        )

    assert full_text == "ok"
    sent_payload = fake_http_client.post.call_args.kwargs["json"]
    assert sent_payload["messages"][1]["content"] == "profile stuffjob stuff"
