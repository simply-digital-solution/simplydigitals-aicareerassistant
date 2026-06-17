"""
Unit tests for generate_resumes_for_jobs() in resume_generator.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_profile(resume_text="My resume", full_name="Ada Lovelace"):
    p = MagicMock()
    p.resume_text = resume_text
    p.full_name = full_name
    return p


def _make_db(profile=None, job_rows=None):
    db = AsyncMock()

    # [0] profile SELECT (scalar)
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile or _make_profile()

    # [1] job descriptions SELECT
    job_result = MagicMock()
    job_result.mappings.return_value.all.return_value = job_rows or []

    # remaining calls are INSERT/SELECT for application_id + upsert
    db.execute.side_effect = [profile_result, job_result] + [MagicMock()] * 30
    return db


def _make_resume_result():
    result = MagicMock()
    result.model_dump_json.return_value = '{"name": "Ada", "headline": "Dev", "sections": []}'
    return result


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_ids_returns_empty():
    from app.pipeline.resume_generator import generate_resumes_for_jobs
    db = AsyncMock()
    result = await generate_resumes_for_jobs(db, [], user_id=1)
    assert result == {}
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# No resume text → all False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_resume_text_returns_all_false():
    from app.pipeline.resume_generator import generate_resumes_for_jobs
    db = AsyncMock()
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = _make_profile(resume_text="")
    db.execute.side_effect = [profile_result]

    result = await generate_resumes_for_jobs(db, [1, 2], user_id=1)
    assert result == {1: False, 2: False}


# ---------------------------------------------------------------------------
# Happy path — all succeed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_jobs_succeed():
    from app.pipeline.resume_generator import generate_resumes_for_jobs
    job_rows = [{"id": 1, "description": "JD1"}, {"id": 2, "description": "JD2"}]
    db = _make_db(job_rows=job_rows)
    resume_result = _make_resume_result()

    with patch("app.pipeline.resume_generator.run_resume_generate_agent",
               AsyncMock(return_value=(resume_result, {}))):
        result = await generate_resumes_for_jobs(db, [1, 2], user_id=1)

    assert result == {1: True, 2: True}
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# AgentError → False for that job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_error_marks_false():
    from app.pipeline.resume_generator import generate_resumes_for_jobs
    from app.shared.schemas import AgentError
    job_rows = [{"id": 1, "description": "JD"}]
    db = _make_db(job_rows=job_rows)

    with patch("app.pipeline.resume_generator.run_resume_generate_agent",
               AsyncMock(return_value=(AgentError(error="bad parse"), {}))):
        result = await generate_resumes_for_jobs(db, [1], user_id=1)

    assert result == {1: False}


# ---------------------------------------------------------------------------
# Exception during agent call → False for that job, continues
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exception_marks_false_and_continues():
    from app.pipeline.resume_generator import generate_resumes_for_jobs
    job_rows = [{"id": 1, "description": "JD1"}, {"id": 2, "description": "JD2"}]
    db = _make_db(job_rows=job_rows)
    resume_result = _make_resume_result()

    call_count = 0
    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("timeout")
        return (resume_result, {})

    with patch("app.pipeline.resume_generator.run_resume_generate_agent", side_effect=side_effect):
        result = await generate_resumes_for_jobs(db, [1, 2], user_id=1)

    assert result[1] is False
    assert result[2] is True


# ---------------------------------------------------------------------------
# application_id set when application row exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_application_id_linked():
    from app.pipeline.resume_generator import generate_resumes_for_jobs
    job_rows = [{"id": 1, "description": "JD"}]

    db = AsyncMock()
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = _make_profile()

    job_result = MagicMock()
    job_result.mappings.return_value.all.return_value = job_rows

    # application SELECT returns a row with id=99
    app_result = MagicMock()
    app_result.mappings.return_value.first.return_value = {"id": 99}

    upsert_result = MagicMock()

    db.execute.side_effect = [profile_result, job_result, app_result, upsert_result]

    resume_result = _make_resume_result()

    with patch("app.pipeline.resume_generator.run_resume_generate_agent",
               AsyncMock(return_value=(resume_result, {}))):
        result = await generate_resumes_for_jobs(db, [1], user_id=1)

    assert result == {1: True}
    # The upsert call should have aid=99
    upsert_params = db.execute.call_args_list[3].args[1]
    assert upsert_params["aid"] == 99
