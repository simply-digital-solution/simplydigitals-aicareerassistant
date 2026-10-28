"""
The parts of the app that sit directly on Starlette/FastAPI: health route, CORS (including
the X-User-Email header), the catch-all 500 handler and a StreamingResponse endpoint.
These guard FastAPI/Starlette upgrades.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import app, unhandled_exception_handler
from app.modules.auth.router import get_current_user
from app.shared.config import get_settings
from app.shared.database import get_db


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _allowed_origin() -> str:
    return get_settings().allowed_origins.split(",")[0].strip()


def test_health_returns_ok(client):
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cors_preflight_allows_configured_origin_and_user_email_header(client):
    origin = _allowed_origin()

    resp = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-user-email",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin
    assert resp.headers["access-control-allow-credentials"] == "true"
    assert "x-user-email" in resp.headers["access-control-allow-headers"].lower()


def test_cors_preflight_rejects_unknown_origin(client):
    resp = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers


def test_unhandled_exception_handler_returns_500_json():
    request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": [], "query_string": b""})

    resp = asyncio.run(unhandled_exception_handler(request, ValueError("boom")))

    assert resp.status_code == 500
    assert json.loads(resp.body) == {"detail": "ValueError: boom"}


def test_streaming_csv_export_streams_header_and_rows(client):
    row = SimpleNamespace(
        id=7, company_name="Acme", role_title="Engineer", status="applied",
        fit_score=88, applied_at=None, deadline=None, source_url="https://acme.example/job",
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    db = AsyncMock()
    db.execute.return_value = result
    user = MagicMock()
    user.id = 1
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db

    resp = client.get("/api/v1/applications/pipeline/export")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["content-disposition"] == "attachment; filename=tracked_apps.csv"
    lines = resp.text.strip().splitlines()
    assert lines[0] == "id,company,role,status,fit_score,applied_at,deadline,source_url"
    assert lines[1].startswith("7,Acme,Engineer,applied,88,")
