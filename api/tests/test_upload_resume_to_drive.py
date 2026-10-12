"""
Unit tests for POST /research/jobs/{job_id}/upload-to-drive

Regression coverage for a bug where the job-info lookup queried
job_postings.user_id directly — a column that does not exist on
job_postings (ownership only exists via user_job_postings) — causing
every upload to fail with asyncpg.UndefinedColumnError.
"""
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile


async def _call_upload(db, user_id=1, job_id=1, filename="resume.docx"):
    from app.modules.agents.router import upload_resume_to_drive
    user = MagicMock()
    user.id = user_id
    file = UploadFile(filename=filename, file=BytesIO(b"fake-bytes"))
    return await upload_resume_to_drive(job_id=job_id, file=file, current_user=user, db=db)


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


def _job_result(found=True):
    result = MagicMock()
    result.mappings.return_value.first.return_value = (
        {"title": "Engineer", "company": "ACME"} if found else None
    )
    return result


def _gr_result(existing_file_id=None):
    result = MagicMock()
    result.mappings.return_value.first.return_value = (
        {"id": 1, "drive_file_id": existing_file_id} if existing_file_id is not None else None
    )
    return result


@pytest.mark.asyncio
async def test_drive_not_connected_raises_403():
    db = AsyncMock()
    db.execute.side_effect = [_profile_result(connected=False)]

    with pytest.raises(HTTPException) as exc:
        await _call_upload(db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_job_lookup_joins_user_job_postings_not_direct_user_id():
    db = AsyncMock()
    db.execute.side_effect = [_profile_result(), _job_result(found=False)]

    with pytest.raises(HTTPException) as exc:
        await _call_upload(db)
    assert exc.value.status_code == 404

    job_query_sql = db.execute.call_args_list[1].args[0].text
    assert "user_job_postings" in job_query_sql
    assert "WHERE id = :jid AND user_id = :uid" not in job_query_sql
    assert "WHERE id=:jid AND user_id=:uid" not in job_query_sql


@pytest.mark.asyncio
async def test_successful_upload_returns_drive_link():
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_result(), _job_result(), _gr_result(), AsyncMock(),
    ]

    with patch(
        "app.shared.google_drive.upload_or_update_file",
        AsyncMock(return_value=("file123", "https://drive.google.com/file123", None)),
    ):
        result = await _call_upload(db)

    assert result["drive_link"] == "https://drive.google.com/file123"
    db.commit.assert_called()
