"""
Unit tests for additional_skills round-tripping through PATCH /api/v1/profile
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


def test_additional_skills_round_trips(client):
    c, db, profile = client
    payload = ["Negotiation", "Public Speaking"]

    resp = c.patch("/api/v1/profile", json={"additional_skills": json.dumps(payload)})

    assert resp.status_code == 200
    assert json.loads(resp.json()["additional_skills"]) == payload
    assert profile.additional_skills == json.dumps(payload)


def test_additional_skills_omitted_when_not_provided(client):
    c, db, profile = client
    profile.additional_skills = json.dumps(["Existing Skill"])

    resp = c.patch("/api/v1/profile", json={"full_name": "New Name"})

    assert resp.status_code == 200
    assert json.loads(resp.json()["additional_skills"]) == ["Existing Skill"]


def test_additional_skills_deduped_case_insensitively(client):
    c, db, profile = client
    payload = ["Negotiation", "negotiation", "Public Speaking"]

    resp = c.patch("/api/v1/profile", json={"additional_skills": json.dumps(payload)})

    assert resp.status_code == 200
    result = json.loads(resp.json()["additional_skills"])
    assert result == ["Negotiation", "Public Speaking"]


def test_additional_skills_kept_separate_from_master_skills(client):
    """additional_skills and skills must be independently settable — writing
    one must not touch the other."""
    c, db, profile = client
    profile.skills = json.dumps(["Python", "SQL"])

    resp = c.patch("/api/v1/profile", json={"additional_skills": json.dumps(["Negotiation"])})

    assert resp.status_code == 200
    assert json.loads(resp.json()["skills"]) == ["Python", "SQL"]
    assert json.loads(resp.json()["additional_skills"]) == ["Negotiation"]
