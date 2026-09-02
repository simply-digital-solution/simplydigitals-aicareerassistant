"""
Unit tests for watched_companies round-tripping through PATCH /api/v1/profile
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.auth.router import get_current_user
from app.shared.database import get_db
from app.shared.models import Profile


def _make_user(user_id=1, email="test@example.com"):
    u = MagicMock()
    u.id = user_id
    u.email = email
    return u


def _make_db(profile: Profile):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db.execute.return_value = result
    return db


@pytest.fixture
def client():
    profile = Profile(id=1, user_id=1)
    db = _make_db(profile)

    app.dependency_overrides[get_current_user] = lambda: _make_user()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c, db, profile
    app.dependency_overrides.clear()


def test_watched_companies_round_trips(client):
    c, db, profile = client
    payload = [
        {"name": "Acme Corp", "url": "https://boards.greenhouse.io/acme"},
        {"name": "Globex", "url": "https://jobs.lever.co/globex"},
    ]

    resp = c.patch("/api/v1/profile", json={"watched_companies": json.dumps(payload)})

    assert resp.status_code == 200
    assert json.loads(resp.json()["watched_companies"]) == payload
    assert profile.watched_companies == json.dumps(payload)


def test_watched_companies_not_deduped_as_flat_strings(client):
    """watched_companies holds {name, url} objects — must not go through the
    flat-string dedupe helper used for excluded_companies etc."""
    c, db, profile = client
    payload = [
        {"name": "Acme", "url": "https://a.example.com"},
        {"name": "Acme", "url": "https://b.example.com"},
    ]

    resp = c.patch("/api/v1/profile", json={"watched_companies": json.dumps(payload)})

    assert resp.status_code == 200
    # both entries preserved — dedupe-by-stringified-object must not silently drop one
    assert json.loads(resp.json()["watched_companies"]) == payload


def test_watched_companies_omitted_when_not_provided(client):
    c, db, profile = client
    profile.watched_companies = json.dumps([{"name": "Existing", "url": "https://x.com"}])

    resp = c.patch("/api/v1/profile", json={"full_name": "New Name"})

    assert resp.status_code == 200
    assert json.loads(resp.json()["watched_companies"]) == [{"name": "Existing", "url": "https://x.com"}]
