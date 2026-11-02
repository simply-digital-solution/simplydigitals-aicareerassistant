"""
Unit tests for GET /api/v1/research/jobs pagination ordering.

posted_at is a date and created_at is shared by every job inserted in one
scrape, so ordering on them alone leaves ties that Postgres may resolve
differently per request — a job can then appear on two pages, or on none.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.auth.router import get_current_user
from app.shared.database import get_db


@pytest.fixture
def client():
    user = MagicMock()
    user.id = 1
    user.email = "test@example.com"

    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    rows_result = MagicMock()
    rows_result.mappings.return_value = []
    db.execute.side_effect = [count_result, rows_result]

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    with patch("app.modules.agents.router._load_profile", AsyncMock(return_value={})):
        with TestClient(app) as c:
            yield c, db
    app.dependency_overrides.clear()


def test_job_list_order_ends_with_unique_tiebreaker(client):
    c, db = client
    resp = c.get("/api/v1/research/jobs?page=2&per_page=10")
    assert resp.status_code == 200
    list_sql = " ".join(db.execute.call_args_list[1].args[0].text.split())
    assert "ORDER BY jp.posted_at DESC, ujp.created_at DESC, jp.id DESC LIMIT" in list_sql
