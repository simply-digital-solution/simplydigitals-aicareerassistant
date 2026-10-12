"""
Unit tests for POST /research/jobs/{job_id}/retry-drive-upload

Regression coverage for a bug where the job-info lookup queried
job_postings.user_id directly — a column that does not exist on
job_postings (ownership only exists via user_job_postings) — causing
every retry to fail with asyncpg.UndefinedColumnError instead of
actually retrying the Drive upload.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


async def _call_retry(db, user_id=1, job_id=1):
    from app.modules.agents.router import retry_drive_upload
    user = MagicMock()
    user.id = user_id
    return await retry_drive_upload(job_id=job_id, current_user=user, db=db)


def _profile_result(connected=True):
    result = MagicMock()
    result.mappings.return_value.first.return_value = (
        {
            "google_access_token": "at",
            "google_refresh_token": "rt",
            "google_token_expiry": "2026-01-01T00:00:00+00:00",
        }
        if connected else None
    )
    return result


def _stored_resume_result(has_resume=True):
    result = MagicMock()
    result.mappings.return_value.first.return_value = (
        {"resume_json": '{"name": "Jane", "headline": "", "header_lines": [], "sections": []}',
         "drive_file_id": None}
        if has_resume else None
    )
    return result


def _job_result(found=True):
    result = MagicMock()
    result.mappings.return_value.first.return_value = (
        {"title": "Engineer", "company": "ACME"} if found else None
    )
    return result


# ---------------------------------------------------------------------------
# Drive not connected → 422, no further queries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_not_connected_raises_422():
    db = AsyncMock()
    db.execute.side_effect = [_profile_result(connected=False)]

    with pytest.raises(HTTPException) as exc:
        await _call_retry(db)
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# No stored resume → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_stored_resume_raises_404():
    db = AsyncMock()
    db.execute.side_effect = [_profile_result(), _stored_resume_result(has_resume=False)]

    with pytest.raises(HTTPException) as exc:
        await _call_retry(db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Job info query — must join user_job_postings, not filter job_postings.user_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_lookup_joins_user_job_postings_not_direct_user_id():
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_result(), _stored_resume_result(), _job_result(found=False),
    ]

    with pytest.raises(HTTPException) as exc:
        await _call_retry(db)
    assert exc.value.status_code == 404

    job_query_sql = db.execute.call_args_list[2].args[0].text
    assert "user_job_postings" in job_query_sql
    assert "WHERE id=:jid AND user_id=:uid" not in job_query_sql
    assert "WHERE id = :jid AND user_id = :uid" not in job_query_sql


# ---------------------------------------------------------------------------
# Happy path — upload succeeds, resume_json cleared
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_retry_uploads_and_clears_resume_json():
    db = AsyncMock()
    update_result = MagicMock()
    db.execute.side_effect = [
        _profile_result(), _stored_resume_result(), _job_result(), update_result,
    ]

    with (
        patch("app.shared.google_drive.convert_docx_to_pdf_bytes",
              AsyncMock(return_value=(b"pdf-bytes", None))),
        patch("app.shared.google_drive.upload_or_update_file",
              AsyncMock(return_value=("file123", "https://drive.google.com/file123", None))),
    ):
        result = await _call_retry(db)

    assert result["drive_file_id"] == "file123"
    assert result["drive_link"] == "https://drive.google.com/file123"
    db.commit.assert_called()
