"""
Multipart upload through POST /api/v1/profile/parse-resume.

This is the one route family that exercises python-multipart end to end, so it
guards dependency bumps of python-multipart / Starlette form parsing.
"""
import base64
import io
from unittest.mock import AsyncMock, MagicMock

import docx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.auth.router import get_current_user
from app.shared.database import get_db
from app.shared.models import Profile


@pytest.fixture
def client():
    user = MagicMock()
    user.id = 1
    profile = Profile(id=1, user_id=1)
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db.execute.return_value = result

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c, profile
    app.dependency_overrides.clear()


def test_txt_upload_is_parsed_from_multipart(client):
    c, _ = client
    resp = c.post(
        "/api/v1/profile/parse-resume",
        files={"file": ("cv.txt", b"Jane Doe\nPython engineer", "text/plain")},
    )

    assert resp.status_code == 200
    assert resp.json()["text"] == "Jane Doe\nPython engineer"
    assert resp.json()["obj"] is None


def test_docx_upload_is_parsed_and_stored_base64(client):
    c, profile = client
    document = docx.Document()
    document.add_paragraph("Jane Doe")
    buf = io.BytesIO()
    document.save(buf)
    raw = buf.getvalue()

    resp = c.post(
        "/api/v1/profile/parse-resume",
        files={"file": ("cv.docx", raw, "application/octet-stream")},
    )

    assert resp.status_code == 200
    assert resp.json()["text"] == "Jane Doe"
    assert profile.resume_obj == base64.b64encode(raw).decode("ascii")


def test_unsupported_extension_returns_415(client):
    c, _ = client
    resp = c.post(
        "/api/v1/profile/parse-resume",
        files={"file": ("cv.exe", b"MZ", "application/octet-stream")},
    )

    assert resp.status_code == 415


def test_missing_file_part_returns_422(client):
    c, _ = client
    resp = c.post("/api/v1/profile/parse-resume", data={"other": "x"})

    assert resp.status_code == 422
