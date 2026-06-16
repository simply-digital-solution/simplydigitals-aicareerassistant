"""
Unit tests for Google Drive helpers and OAuth endpoints.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.shared.google_drive import (
    get_oauth_url,
    token_expiry_iso,
    is_token_expired,
)


# ---------------------------------------------------------------------------
# get_oauth_url
# ---------------------------------------------------------------------------

def test_get_oauth_url_contains_client_id(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    with patch("app.shared.google_drive.get_settings") as mock_settings:
        s = MagicMock()
        s.google_client_id = "test-client-id"
        s.google_redirect_uri = "http://localhost:8000/api/v1/auth/google/callback"
        mock_settings.return_value = s
        url = get_oauth_url()
    assert "test-client-id" in url
    assert "accounts.google.com" in url
    assert "drive.file" in url


def test_get_oauth_url_requests_offline_access():
    with patch("app.shared.google_drive.get_settings") as mock_settings:
        s = MagicMock()
        s.google_client_id = "cid"
        s.google_redirect_uri = "http://localhost:8000/api/v1/auth/google/callback"
        mock_settings.return_value = s
        url = get_oauth_url()
    assert "offline" in url
    assert "consent" in url


# ---------------------------------------------------------------------------
# token_expiry_iso / is_token_expired
# ---------------------------------------------------------------------------

def test_token_expiry_iso_returns_future():
    expiry = token_expiry_iso(3600)
    dt = datetime.fromisoformat(expiry)
    assert dt > datetime.now(timezone.utc)


def test_is_token_expired_with_past_time():
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    assert is_token_expired(past) is True


def test_is_token_expired_with_future_time():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert is_token_expired(future) is False


def test_is_token_expired_with_none():
    assert is_token_expired(None) is True


# ---------------------------------------------------------------------------
# exchange_code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exchange_code_calls_token_endpoint():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "access_token": "acc123",
        "refresh_token": "ref456",
        "expires_in": 3600,
    }

    with patch("app.shared.google_drive.get_settings") as mock_settings, \
         patch("httpx.AsyncClient") as mock_client_cls:
        s = MagicMock()
        s.google_client_id = "cid"
        s.google_client_secret = "secret"
        s.google_redirect_uri = "http://localhost:8000/api/v1/auth/google/callback"
        mock_settings.return_value = s

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from app.shared.google_drive import exchange_code
        result = await exchange_code("auth_code_xyz")

    assert result["access_token"] == "acc123"
    assert result["refresh_token"] == "ref456"
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert "authorization_code" in str(call_kwargs)


# ---------------------------------------------------------------------------
# upload_or_update_file — folder creation + file upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_creates_folder_hierarchy_and_file():
    """upload_or_update_file should create root folder, sub-folder, then POST the file."""
    folder_resp = MagicMock()
    folder_resp.raise_for_status = MagicMock()

    search_empty = MagicMock()
    search_empty.raise_for_status = MagicMock()
    search_empty.json.return_value = {"files": []}

    folder_created = MagicMock()
    folder_created.raise_for_status = MagicMock()
    folder_created.json.side_effect = [
        {"id": "root_folder_id"},
        {"id": "sub_folder_id"},
    ]

    upload_resp = MagicMock()
    upload_resp.raise_for_status = MagicMock()
    upload_resp.json.return_value = {"id": "file_id_abc", "webViewLink": "https://drive.google.com/file/abc"}

    with patch("app.shared.google_drive.get_settings") as mock_settings, \
         patch("app.shared.google_drive.is_token_expired", return_value=False), \
         patch("httpx.AsyncClient") as mock_client_cls:
        s = MagicMock()
        s.google_client_id = "cid"
        s.google_client_secret = "secret"
        s.google_redirect_uri = "http://localhost:8000/callback"
        mock_settings.return_value = s

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        # GET calls: two folder searches (both empty), then folder creates via POST
        mock_client.get = AsyncMock(return_value=search_empty)
        mock_client.post = AsyncMock(side_effect=[
            folder_created,   # create root folder
            folder_created,   # create sub-folder
            upload_resp,      # upload file
        ])
        mock_client_cls.return_value = mock_client

        from app.shared.google_drive import upload_or_update_file
        file_id, link, new_tokens = await upload_or_update_file(
            access_token="acc",
            refresh_token="ref",
            expiry_iso=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            folder_name="Acme Corp - Engineer",
            filename="Resume_Acme_Corp.docx",
            file_bytes=b"fake docx content",
            existing_file_id=None,
        )

    assert file_id == "file_id_abc"
    assert "drive.google.com" in link
    assert new_tokens is None  # token was not expired, so no refresh


@pytest.mark.asyncio
async def test_upload_updates_existing_file():
    """When existing_file_id is provided, PATCH should be used (Drive versions preserved)."""
    search_found = MagicMock()
    search_found.raise_for_status = MagicMock()
    search_found.json.return_value = {"files": [{"id": "existing_folder"}]}

    patch_resp = MagicMock()
    patch_resp.raise_for_status = MagicMock()
    patch_resp.json.return_value = {"id": "existing_file_id", "webViewLink": "https://drive.google.com/file/existing"}

    with patch("app.shared.google_drive.get_settings") as mock_settings, \
         patch("app.shared.google_drive.is_token_expired", return_value=False), \
         patch("httpx.AsyncClient") as mock_client_cls:
        s = MagicMock()
        s.google_client_id = "cid"
        s.google_client_secret = "secret"
        s.google_redirect_uri = "http://localhost:8000/callback"
        mock_settings.return_value = s

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=search_found)
        mock_client.patch = AsyncMock(return_value=patch_resp)
        mock_client_cls.return_value = mock_client

        from app.shared.google_drive import upload_or_update_file
        file_id, link, _ = await upload_or_update_file(
            access_token="acc",
            refresh_token="ref",
            expiry_iso=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            folder_name="Acme Corp - Engineer",
            filename="Resume_Acme_Corp.docx",
            file_bytes=b"updated docx content",
            existing_file_id="existing_file_id",
        )

    assert file_id == "existing_file_id"
    mock_client.patch.assert_called_once()
    mock_client.post.assert_not_called()  # no new file created
