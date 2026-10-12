"""
Unit tests for run_resume_generate_agent()'s client selection — it must
use get_resume_client() (Haiku), not get_llm_client() (Gemini), so a
Gemini billing outage doesn't block resume generation.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.agents.resume_generate_agent import run_resume_generate_agent
from app.shared.schemas import GeneratedResumeOutput


def _make_client(name: str):
    client = MagicMock(name=name)
    client.run_agent = AsyncMock(return_value=(
        GeneratedResumeOutput(name="Test Candidate", headline="Engineer", sections=[]),
        {"model": name},
    ))
    return client


@pytest.mark.asyncio
async def test_run_resume_generate_agent_uses_resume_client():
    resume_client = _make_client("resume")

    with patch("app.modules.agents.resume_generate_agent.get_resume_client", return_value=resume_client) as mock_get_resume, \
         patch("app.modules.agents.resume_generate_agent._load_system_prompt", return_value="sys"):
        await run_resume_generate_agent(resume_text="my resume", jd_text="a job")

    mock_get_resume.assert_called_once()
    resume_client.run_agent.assert_called_once()
