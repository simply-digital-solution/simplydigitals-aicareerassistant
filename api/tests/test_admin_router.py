"""Tests for admin router — access control and endpoint correctness."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.shared.database import get_db

ADMIN_EMAIL = "pandiri.vasu@gmail.com"
OTHER_EMAIL = "other@example.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_override(rows):
    """Return a get_db override that yields a mock db returning given rows."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    mock_result.rowcount = len(rows)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    async def _override():
        yield mock_db

    return _override


def _db_override_rowcount(rowcount: int):
    """Return a get_db override whose execute result has a specific rowcount."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.rowcount = rowcount

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    async def _override():
        yield mock_db

    return _override


@pytest.fixture
def app():
    from app.main import app as fastapi_app
    return fastapi_app


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_endpoint_rejects_non_admin(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/admin/users",
            headers={"X-User-Email": OTHER_EMAIL},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_endpoint_accepts_admin(app):
    app.dependency_overrides[get_db] = _db_override([])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/users",
                headers={"X-User-Email": ADMIN_EMAIL},
            )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_require_admin_missing_header(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/users")
    assert resp.status_code in (400, 403, 422)


# ---------------------------------------------------------------------------
# /admin/stats/users-active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_users_active_returns_list(app):
    app.dependency_overrides[get_db] = _db_override([("2026-06-10", 3), ("2026-06-11", 5)])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/stats/users-active",
                headers={"X-User-Email": ADMIN_EMAIL},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["date"] == "2026-06-10"
        assert data[0]["count"] == 3
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /admin/stats/llm-tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_llm_tokens_returns_list(app):
    app.dependency_overrides[get_db] = _db_override([("2026-06-10", 1000, 500)])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/stats/llm-tokens",
                headers={"X-User-Email": ADMIN_EMAIL},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["input_tokens"] == 1000
        assert data[0]["output_tokens"] == 500
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /admin/stats/jobs-scraped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_jobs_scraped_returns_list(app):
    app.dependency_overrides[get_db] = _db_override([("2026-06-10", 42)])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/stats/jobs-scraped",
                headers={"X-User-Email": ADMIN_EMAIL},
            )
        assert resp.status_code == 200
        assert resp.json()[0]["count"] == 42
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /admin/stats/llm-per-user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_llm_per_user_returns_list(app):
    app.dependency_overrides[get_db] = _db_override(
        [("2026-06-10", "user@example.com", 7, 800, 400)]
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/stats/llm-per-user",
                headers={"X-User-Email": ADMIN_EMAIL},
            )
        assert resp.status_code == 200
        row = resp.json()[0]
        assert row["email"] == "user@example.com"
        assert row["requests"] == 7
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /admin/stats/agent-runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_agent_runs_returns_list(app):
    app.dependency_overrides[get_db] = _db_override([("2026-06-10", 10, 2)])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/stats/agent-runs",
                headers={"X-User-Email": ADMIN_EMAIL},
            )
        assert resp.status_code == 200
        row = resp.json()[0]
        assert row["complete"] == 10
        assert row["failed"] == 2
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /admin/users/{id}/suspend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suspend_user(app):
    app.dependency_overrides[get_db] = _db_override_rowcount(1)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/users/42/suspend",
                headers={"X-User-Email": ADMIN_EMAIL},
            )
        assert resp.status_code == 200
        assert resp.json()["suspended"] is True
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_suspend_user_not_found(app):
    app.dependency_overrides[get_db] = _db_override_rowcount(0)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/users/999/suspend",
                headers={"X-User-Email": ADMIN_EMAIL},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /admin/users/{id}/activate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_activate_user(app):
    from app.pipeline.suspension import reactivate_user
    from unittest.mock import patch

    app.dependency_overrides[get_db] = _db_override([])
    try:
        with patch("app.modules.admin.router.reactivate_user", AsyncMock(return_value=True)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/users/42/activate",
                    headers={"X-User-Email": ADMIN_EMAIL},
                )
        assert resp.status_code == 200
        assert resp.json()["activated"] is True
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_user_not_found(app):
    from unittest.mock import patch

    app.dependency_overrides[get_db] = _db_override([])
    try:
        with patch("app.modules.admin.router.reactivate_user", AsyncMock(return_value=False)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/users/999/activate",
                    headers={"X-User-Email": ADMIN_EMAIL},
                )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Non-admin cannot suspend/activate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_admin_cannot_suspend(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/admin/users/1/suspend",
            headers={"X-User-Email": OTHER_EMAIL},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_non_admin_cannot_activate(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/admin/users/1/activate",
            headers={"X-User-Email": OTHER_EMAIL},
        )
    assert resp.status_code == 403
