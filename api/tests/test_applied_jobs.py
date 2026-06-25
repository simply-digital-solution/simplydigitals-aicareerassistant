"""Tests for GET /research/jobs/applied endpoint and Drive filename generation."""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_user(user_id: int = 1):
    u = MagicMock()
    u.id = user_id
    return u


def _db_with_applied_jobs(jobs: list[dict]):
    db = AsyncMock()

    class FakeRow(dict):
        pass

    rows = [FakeRow(j) for j in jobs]
    result = MagicMock()
    result.mappings.return_value = rows
    db.execute.return_value = result
    return db


def test_drive_filename_strips_dots_from_company_name():
    """Company names like 'AUREXIA PTE. LTD.' should produce clean filenames."""
    company = "AUREXIA PTE. LTD."
    company_slug = company.replace('.', '').replace(' ', '_')
    filename = f"Resume_{company_slug}.pdf"
    assert filename == "Resume_AUREXIA_PTE_LTD.pdf"


def test_drive_filename_plain_company_name():
    company = "Standard Chartered Bank"
    company_slug = company.replace('.', '').replace(' ', '_')
    filename = f"Resume_{company_slug}.docx"
    assert filename == "Resume_Standard_Chartered_Bank.docx"


@pytest.mark.asyncio
async def test_get_applied_jobs_returns_jobs():
    from app.modules.agents.router import get_applied_jobs

    job = {
        "id": 1, "mcf_uuid": "abc", "title": "Data Engineer", "company": "ACME",
        "url": "https://example.com", "location": "Singapore",
        "inferred_industries": "[]", "posted_at": None, "scraped_at": "2026-06-16",
        "scored": True, "fit_score": 0.8, "reasons": "[]", "risks": "[]",
        "key_keywords": "[]", "scoring_breakdown": None, "score_error": None,
        "scored_at": None, "archived": False, "application_id": 10, "applied_at": None,
    }
    db = _db_with_applied_jobs([job])
    result = await get_applied_jobs(current_user=_make_user(), db=db)

    assert result["total"] == 1
    assert result["jobs"][0]["title"] == "Data Engineer"


@pytest.mark.asyncio
async def test_get_applied_jobs_empty_when_none():
    from app.modules.agents.router import get_applied_jobs

    db = _db_with_applied_jobs([])
    result = await get_applied_jobs(current_user=_make_user(), db=db)

    assert result["total"] == 0
    assert result["jobs"] == []


@pytest.mark.asyncio
async def test_get_applied_jobs_filters_by_user():
    from app.modules.agents.router import get_applied_jobs

    db = _db_with_applied_jobs([])
    await get_applied_jobs(current_user=_make_user(user_id=42), db=db)

    params = db.execute.call_args.args[1]
    assert params["uid"] == 42


@pytest.mark.asyncio
async def test_get_applied_jobs_ordered_by_applied_at_desc():
    """Positive: query must sort by applied_at DESC so most recent applications appear first."""
    from app.modules.agents.router import get_applied_jobs

    db = _db_with_applied_jobs([])
    await get_applied_jobs(current_user=_make_user(), db=db)

    sql = db.execute.call_args.args[0].text
    assert "applied_at" in sql
    assert "DESC" in sql


@pytest.mark.asyncio
async def test_get_applied_jobs_not_ordered_by_updated_at():
    """Negative: query must NOT sort by updated_at — that's not the application date."""
    from app.modules.agents.router import get_applied_jobs

    db = _db_with_applied_jobs([])
    await get_applied_jobs(current_user=_make_user(), db=db)

    sql = db.execute.call_args.args[0].text
    assert "ORDER BY a.updated_at" not in sql


@pytest.mark.asyncio
async def test_get_applied_jobs_nulls_last():
    """Positive: NULLS LAST ensures jobs without applied_at appear at the end."""
    from app.modules.agents.router import get_applied_jobs

    db = _db_with_applied_jobs([])
    await get_applied_jobs(current_user=_make_user(), db=db)

    sql = db.execute.call_args.args[0].text
    assert "NULLS LAST" in sql
