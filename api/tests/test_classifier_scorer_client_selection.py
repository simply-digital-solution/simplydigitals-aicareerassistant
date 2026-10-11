"""
Unit tests for get_classifier_client() / get_scorer_client() — per-task
Anthropic opt-in with fallback to get_llm_client() (Gemini/Ollama).
"""
from unittest.mock import MagicMock, patch

from app.shared import api_client
from app.shared.api_client import AnthropicClient, GeminiClient


def _reset_singletons():
    api_client._client = None
    api_client._classifier_client = None
    api_client._scorer_client = None


def _mock_settings(anthropic_key="", gemini_key="some-gemini-key"):
    settings = MagicMock()
    settings.anthropic_api_key = anthropic_key
    settings.anthropic_haiku_model = "claude-haiku-5-5"
    settings.anthropic_sonnet_model = "claude-sonnet-5-5"
    settings.gemini_api_key = gemini_key
    settings.gemini_model = "gemini-flash-latest"
    settings.app_env = "development"
    settings.max_self_corrections = 3
    return settings


# ---------------------------------------------------------------------------
# get_classifier_client()
# ---------------------------------------------------------------------------

def test_classifier_client_uses_anthropic_haiku_when_key_set():
    _reset_singletons()
    settings = _mock_settings(anthropic_key="sk-ant-test")

    with patch("app.shared.api_client.get_settings", return_value=settings):
        client = api_client.get_classifier_client()

    assert isinstance(client, AnthropicClient)
    assert client._model == "claude-haiku-5-5"
    _reset_singletons()


def test_classifier_client_falls_back_to_llm_client_when_no_anthropic_key():
    _reset_singletons()
    settings = _mock_settings(anthropic_key="")

    with patch("app.shared.api_client.get_settings", return_value=settings):
        client = api_client.get_classifier_client()

    assert isinstance(client, GeminiClient)
    _reset_singletons()


def test_classifier_client_is_cached_across_calls():
    _reset_singletons()
    settings = _mock_settings(anthropic_key="sk-ant-test")

    with patch("app.shared.api_client.get_settings", return_value=settings):
        client1 = api_client.get_classifier_client()
        client2 = api_client.get_classifier_client()

    assert client1 is client2
    _reset_singletons()


# ---------------------------------------------------------------------------
# get_scorer_client()
# ---------------------------------------------------------------------------

def test_scorer_client_uses_anthropic_haiku_when_key_set():
    _reset_singletons()
    settings = _mock_settings(anthropic_key="sk-ant-test")

    with patch("app.shared.api_client.get_settings", return_value=settings):
        client = api_client.get_scorer_client()

    assert isinstance(client, AnthropicClient)
    assert client._model == "claude-haiku-5-5"
    _reset_singletons()


def test_scorer_client_falls_back_to_llm_client_when_no_anthropic_key():
    _reset_singletons()
    settings = _mock_settings(anthropic_key="")

    with patch("app.shared.api_client.get_settings", return_value=settings):
        client = api_client.get_scorer_client()

    assert isinstance(client, GeminiClient)
    _reset_singletons()


def test_classifier_and_scorer_are_independent_instances():
    """classifier and scorer must be separate client instances/singletons —
    not one shared object, unlike get_llm_client() — even though both
    currently run on the same Haiku model."""
    _reset_singletons()
    settings = _mock_settings(anthropic_key="sk-ant-test")

    with patch("app.shared.api_client.get_settings", return_value=settings):
        classifier = api_client.get_classifier_client()
        scorer = api_client.get_scorer_client()

    assert classifier is not scorer
    _reset_singletons()
