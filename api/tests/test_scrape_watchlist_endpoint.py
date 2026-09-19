"""
Unit test for POST /api/v1/research/scrape-watchlist
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


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_trigger_watchlist_scrape_returns_inserted_count(client):
    with patch(
        "app.pipeline.daily_scrape.scrape_watchlist_for_user", AsyncMock(return_value=7),
    ) as mock_scrape:
        resp = client.post("/api/v1/research/scrape-watchlist")

    assert resp.status_code == 200
    assert resp.json() == {"inserted": 7}
    assert mock_scrape.call_args.args[0] == 1
