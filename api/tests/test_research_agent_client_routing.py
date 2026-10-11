"""
Unit tests for run_research_agent()'s client selection — scoring
(request_type="scoring") must use get_scorer_client(), every other
request_type must keep using get_llm_client() unchanged.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.agents.research_agent import run_research_agent
from app.shared.schemas import ResearchOutput


def _make_client(name: str):
    client = MagicMock(name=name)
    client.run_agent = AsyncMock(return_value=(
        ResearchOutput(opportunities=[]), {"model": name},
    ))
    return client


@pytest.mark.asyncio
async def test_scoring_request_type_uses_scorer_client():
    scorer_client = _make_client("scorer")
    research_client = _make_client("research")

    with patch("app.modules.agents.research_agent.get_scorer_client", return_value=scorer_client) as mock_get_scorer, \
         patch("app.modules.agents.research_agent.get_llm_client", return_value=research_client) as mock_get_llm, \
         patch("app.modules.agents.research_agent._load_system_prompt", return_value="sys"):
        await run_research_agent(
            profile={}, job_postings=[], request_type="scoring",
        )

    mock_get_scorer.assert_called_once()
    mock_get_llm.assert_not_called()
    scorer_client.run_agent.assert_called_once()


@pytest.mark.asyncio
async def test_default_request_type_keeps_using_llm_client():
    scorer_client = _make_client("scorer")
    research_client = _make_client("research")

    with patch("app.modules.agents.research_agent.get_scorer_client", return_value=scorer_client) as mock_get_scorer, \
         patch("app.modules.agents.research_agent.get_llm_client", return_value=research_client) as mock_get_llm, \
         patch("app.modules.agents.research_agent._load_system_prompt", return_value="sys"):
        await run_research_agent(
            profile={}, job_postings=[],  # request_type defaults to "research"
        )

    mock_get_llm.assert_called_once()
    mock_get_scorer.assert_not_called()
    research_client.run_agent.assert_called_once()


@pytest.mark.asyncio
async def test_other_non_scoring_request_types_also_use_llm_client():
    scorer_client = _make_client("scorer")
    research_client = _make_client("research")

    with patch("app.modules.agents.research_agent.get_scorer_client", return_value=scorer_client) as mock_get_scorer, \
         patch("app.modules.agents.research_agent.get_llm_client", return_value=research_client) as mock_get_llm, \
         patch("app.modules.agents.research_agent._load_system_prompt", return_value="sys"):
        await run_research_agent(
            profile={}, job_postings=[], request_type="some_other_type",
        )

    mock_get_llm.assert_called_once()
    mock_get_scorer.assert_not_called()
