"""Tests for industry_refinement and updated resume_detail_extractor."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# resume_detail_extractor — job_industry_labels parameter
# ---------------------------------------------------------------------------

def test_system_prompt_free_form_when_no_labels():
    from app.shared.resume_detail_extractor import _build_system_prompt
    prompt = _build_system_prompt([])
    assert "pick ONLY from this exact list" not in prompt
    assert "1-5 industries this person has worked in or is suited for" in prompt


def test_system_prompt_constrained_when_labels_provided():
    from app.shared.resume_detail_extractor import _build_system_prompt
    labels = ["Banking & Financial Services", "Technology & Software"]
    prompt = _build_system_prompt(labels)
    assert "pick ONLY from this exact list" in prompt
    assert "Banking & Financial Services" in prompt
    assert "Technology & Software" in prompt


@pytest.mark.asyncio
async def test_extract_resume_details_passes_labels_to_prompt():
    from app.shared.resume_detail_extractor import extract_resume_details

    captured_messages = []

    async def _mock_call(messages):
        captured_messages.extend(messages)
        return (json.dumps({
            "years_experience": 5, "seniority_level": "senior",
            "target_industries": ["Banking & Financial Services"],
            "target_roles": ["PM"], "skills": ["Agile"],
            "education": [], "certifications": [],
            "contact": {"phone_country_code": "", "phone_local": "", "email": ""},
        }), {})

    client = MagicMock()
    client._call = _mock_call

    await extract_resume_details("resume text", client, job_industry_labels=["Banking & Financial Services"])

    system_msg = captured_messages[0]["content"]
    assert "Banking & Financial Services" in system_msg
    assert "pick ONLY from this exact list" in system_msg


@pytest.mark.asyncio
async def test_extract_resume_details_free_form_when_no_labels():
    from app.shared.resume_detail_extractor import extract_resume_details

    captured_messages = []

    async def _mock_call(messages):
        captured_messages.extend(messages)
        return (json.dumps({
            "years_experience": 3, "seniority_level": "mid",
            "target_industries": ["Finance"],
            "target_roles": ["Analyst"], "skills": [],
            "education": [], "certifications": [],
            "contact": {"phone_country_code": "", "phone_local": "", "email": ""},
        }), {})

    client = MagicMock()
    client._call = _mock_call

    result = await extract_resume_details("resume text", client, job_industry_labels=[])

    system_msg = captured_messages[0]["content"]
    assert "pick ONLY from this exact list" not in system_msg
    assert result["target_industries"] == ["Finance"]


# ---------------------------------------------------------------------------
# industry_refinement — refine_user_industries
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager


def _make_db(profile_industries, job_labels):
    """Build a mock db that returns profile industries then job labels."""
    db = AsyncMock()
    call_count = 0

    async def _execute(query, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            # First call: SELECT target_industries FROM profiles
            row = MagicMock()
            row.__getitem__ = lambda self, i: json.dumps(profile_industries)
            mock_result.fetchone.return_value = row
        else:
            # Second call: SELECT DISTINCT job labels
            mock_result.fetchall.return_value = [(label,) for label in job_labels]
        return mock_result

    db.execute = _execute
    return db


@pytest.mark.asyncio
async def test_refine_skips_when_no_profile():
    from app.pipeline.industry_refinement import refine_user_industries

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.fetchone.return_value = None
    db.execute.return_value = result_mock

    updated = await refine_user_industries(user_id=1, db=db)
    assert updated is False


@pytest.mark.asyncio
async def test_refine_skips_when_no_job_labels():
    from app.pipeline.industry_refinement import refine_user_industries

    db = _make_db(
        profile_industries=["Banking"],
        job_labels=[],
    )
    updated = await refine_user_industries(user_id=1, db=db)
    assert updated is False


@pytest.mark.asyncio
async def test_refine_skips_when_already_aligned():
    from app.pipeline.industry_refinement import refine_user_industries

    aligned_labels = ["Banking & Financial Services", "Technology & Software"]
    db = _make_db(
        profile_industries=aligned_labels,
        job_labels=aligned_labels,
    )
    updated = await refine_user_industries(user_id=1, db=db)
    assert updated is False


@pytest.mark.asyncio
async def test_refine_updates_profile_when_misaligned():
    from app.pipeline.industry_refinement import refine_user_industries

    db = _make_db(
        profile_industries=["Banking", "Technology"],
        job_labels=["Banking & Financial Services", "Technology & Software", "Education"],
    )

    llm_response = json.dumps({"industries": ["Banking & Financial Services", "Technology & Software"]})
    client = MagicMock()
    client._call = AsyncMock(return_value=(llm_response, {}))

    with patch("app.pipeline.industry_refinement.get_llm_client", return_value=client):
        updated = await refine_user_industries(user_id=1, db=db)

    assert updated is True
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_refine_drops_labels_not_in_job_postings():
    """LLM response values not in job_labels must be stripped."""
    from app.pipeline.industry_refinement import refine_user_industries

    db = _make_db(
        profile_industries=["Banking"],
        job_labels=["Banking & Financial Services"],
    )

    # LLM hallucinates a label not in job_labels
    llm_response = json.dumps({"industries": ["Banking & Financial Services", "FinTech"]})
    client = MagicMock()
    client._call = AsyncMock(return_value=(llm_response, {}))

    execute_calls = []
    original_execute = db.execute

    async def _capturing_execute(query, params=None):
        execute_calls.append((str(query), params))
        return await original_execute(query, params)

    db.execute = _capturing_execute

    with patch("app.pipeline.industry_refinement.get_llm_client", return_value=client):
        await refine_user_industries(user_id=1, db=db)

    # Find the UPDATE call and verify FinTech was stripped
    update_calls = [(q, p) for q, p in execute_calls if "UPDATE" in q]
    assert len(update_calls) == 1
    saved = json.loads(update_calls[0][1]["ind"])
    assert "FinTech" not in saved
    assert "Banking & Financial Services" in saved


@pytest.mark.asyncio
async def test_refine_returns_false_on_llm_error():
    from app.pipeline.industry_refinement import refine_user_industries

    db = _make_db(
        profile_industries=["Banking"],
        job_labels=["Banking & Financial Services"],
    )

    client = MagicMock()
    client._call = AsyncMock(side_effect=RuntimeError("LLM down"))

    with patch("app.pipeline.industry_refinement.get_llm_client", return_value=client):
        updated = await refine_user_industries(user_id=1, db=db)

    assert updated is False
