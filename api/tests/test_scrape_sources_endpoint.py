"""
Unit tests for the `sources` query param on POST /api/v1/research/scrape
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


def test_no_sources_param_passes_none(client):
    with patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=3)) as mock_scrape:
        resp = client.post("/api/v1/research/scrape")

    assert resp.status_code == 200
    assert resp.json() == {"inserted": 3}
    assert mock_scrape.call_args.kwargs["sources"] is None


def test_single_source_parsed_into_set(client):
    with patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=2)) as mock_scrape:
        resp = client.post("/api/v1/research/scrape?sources=mycareersfuture")

    assert resp.status_code == 200
    assert mock_scrape.call_args.kwargs["sources"] == {"mycareersfuture"}


def test_multiple_sources_parsed_into_set(client):
    with patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=0)) as mock_scrape:
        resp = client.post("/api/v1/research/scrape?sources=mycareersfuture,efinancialcareers")

    assert resp.status_code == 200
    assert mock_scrape.call_args.kwargs["sources"] == {"mycareersfuture", "efinancialcareers"}


def test_no_efc_locations_param_passes_none(client):
    with patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=0)) as mock_scrape:
        resp = client.post("/api/v1/research/scrape?sources=efinancialcareers")

    assert resp.status_code == 200
    assert mock_scrape.call_args.kwargs["efc_locations"] is None


def test_single_efc_location_parsed_into_set(client):
    with patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=0)) as mock_scrape:
        resp = client.post("/api/v1/research/scrape?sources=efinancialcareers&efc_locations=singapore")

    assert resp.status_code == 200
    assert mock_scrape.call_args.kwargs["efc_locations"] == {"singapore"}


def test_multiple_efc_locations_parsed_into_set(client):
    with patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=0)) as mock_scrape:
        resp = client.post("/api/v1/research/scrape?sources=efinancialcareers&efc_locations=singapore,uae")

    assert resp.status_code == 200
    assert mock_scrape.call_args.kwargs["efc_locations"] == {"singapore", "uae"}
