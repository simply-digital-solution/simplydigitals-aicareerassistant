"""
Unit tests for POST /api/v1/research/jobs/bulk-archive
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.auth.router import get_current_user
from app.shared.database import get_db


def _make_user(user_id=1, email="test@example.com"):
    u = MagicMock()
    u.id = user_id
    u.email = email
    return u


def _make_db(update_rowcount=2):
    db = AsyncMock()
    update_result = MagicMock()
    update_result.rowcount = update_rowcount
    db.execute.return_value = update_result
    return db


@pytest.fixture
def client(user_id=1):
    user = _make_user(user_id=user_id)
    db = _make_db()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c, db
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Happy path — multiple job IDs archived
# ---------------------------------------------------------------------------

def test_bulk_archive_calls_update_with_all_ids(client):
    c, db = client
    resp = c.post("/api/v1/research/jobs/bulk-archive", json={"job_ids": [1, 2, 3]})
    assert resp.status_code == 204
    db.execute.assert_called_once()
    sql = db.execute.call_args.args[0].text
    assert "archived = true" in sql
    params = db.execute.call_args.args[1]
    assert set(params[k] for k in params if k.startswith("id")) == {1, 2, 3}


def test_bulk_archive_commits(client):
    c, db = client
    c.post("/api/v1/research/jobs/bulk-archive", json={"job_ids": [10]})
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Validation — empty list rejected
# ---------------------------------------------------------------------------

def test_bulk_archive_empty_list_returns_422(client):
    c, db = client
    resp = c.post("/api/v1/research/jobs/bulk-archive", json={"job_ids": []})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# User isolation — query always includes user_id
# ---------------------------------------------------------------------------

def test_bulk_archive_filters_by_user_id(client):
    c, db = client
    c.post("/api/v1/research/jobs/bulk-archive", json={"job_ids": [5, 6]})
    params = db.execute.call_args.args[1]
    assert params["uid"] == 1
