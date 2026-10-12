"""
Regression test for agent_runs.user_id being NOT NULL.

industry_backfill.py's classification calls have no single user_id (a
classification batch spans many users' jobs) and always called
run_agent() with user_id=None — consistent with run_agent()'s own
Optional[int] signature and with llm_usage_logs.user_id already being
nullable. But agent_runs.user_id was NOT NULL since the foundational
migration, so every classification batch crashed at the _record_run()
INSERT with asyncpg.NotNullViolationError and rolled back the entire
batch, discarding classification work that had already been paid for.

This hits the real test database directly (unlike the rest of the
suite, which mocks db.execute) because a NOT NULL constraint violation
is invisible to a mock — that's exactly how this bug went undetected.
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.shared.config import get_settings


def _has_real_db() -> bool:
    return bool(get_settings().database_url)


@pytest.mark.asyncio
@pytest.mark.skipif(not _has_real_db(), reason="requires a running test database")
async def test_agent_runs_insert_succeeds_with_null_user_id():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from sqlalchemy import text

    async with session_factory() as db:
        try:
            result = await db.execute(
                text("""
                    INSERT INTO agent_runs
                        (user_id, application_id, agent_name, reasoning_pattern, status,
                         attempt_number, system_prompt, final_output,
                         input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                         cost_usd, started_at, completed_at)
                    VALUES
                        (NULL, NULL, 'test_regression_marker', 'single_call', 'complete',
                         1, 'test', 'test',
                         0, 0, 0, 0,
                         0.0, now(), now())
                    RETURNING id
                """),
            )
            inserted_id = result.scalar_one()
            await db.execute(
                text("DELETE FROM agent_runs WHERE id = :id"), {"id": inserted_id},
            )
            await db.commit()
        finally:
            await engine.dispose()
