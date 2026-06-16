"""
Google Drive OAuth2 + file upload helpers.

Uses the Drive v3 REST API directly via httpx — no heavy Google SDK needed.

OAuth2 flow:
  1. get_oauth_url()          → redirect user to Google consent screen
  2. exchange_code(code)      → trade auth code for access + refresh tokens
  3. refresh_access_token()   → get new access token when current one expires

Upload flow:
  upload_or_update_file()    → creates or updates a file in:
      My Drive / AI Career Assistant / {folder_name} / Resume_{company}.docx
  Returns (file_id, web_view_link).
  Re-uploading the same file_id preserves Drive version history.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.shared.config import get_settings

_SCOPES = "https://www.googleapis.com/auth/drive.file"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
_ROOT_FOLDER_NAME = "AI Career Assistant"


def get_oauth_url(state: str = "") -> str:
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "access_type": "offline",
        "prompt": "consent",          # force refresh_token on every consent
    }
    if state:
        params["state"] = state
    return f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """Trade an authorisation code for access + refresh tokens.

    Returns dict with keys: access_token, refresh_token, expires_in (seconds).
    """
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(_TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Get a new access token using the stored refresh token.

    Returns dict with keys: access_token, expires_in.
    """
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(_TOKEN_URL, data={
            "refresh_token": refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        return resp.json()


def token_expiry_iso(expires_in: int) -> str:
    """Convert expires_in seconds to an ISO-8601 UTC string."""
    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
    return expiry.isoformat()


def is_token_expired(expiry_iso: Optional[str]) -> bool:
    if not expiry_iso:
        return True
    try:
        expiry = datetime.fromisoformat(expiry_iso)
        return datetime.now(timezone.utc) >= expiry
    except ValueError:
        return True


async def _get_valid_access_token(access_token: str, refresh_token: str, expiry_iso: Optional[str]) -> tuple[str, Optional[dict]]:
    """Return a valid access token, refreshing if necessary.

    Returns (token, new_token_data | None).
    new_token_data is non-None when the caller should persist updated tokens.
    """
    if not is_token_expired(expiry_iso):
        return access_token, None
    data = await refresh_access_token(refresh_token)
    new_token_data = {
        "access_token": data["access_token"],
        "expiry_iso": token_expiry_iso(data["expires_in"]),
    }
    return data["access_token"], new_token_data


async def _find_or_create_folder(client: httpx.AsyncClient, token: str, name: str, parent_id: Optional[str] = None) -> str:
    """Find a Drive folder by name (and optional parent), creating it if absent. Returns folder id."""
    q_parts = [f"name='{name}'", "mimeType='application/vnd.google-apps.folder'", "trashed=false"]
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")
    resp = await client.get(
        _DRIVE_FILES,
        params={"q": " and ".join(q_parts), "fields": "files(id)", "spaces": "drive"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])
    if files:
        return files[0]["id"]

    # Create the folder
    body: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]
    resp = await client.post(
        _DRIVE_FILES,
        json=body,
        params={"fields": "id"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()["id"]


async def upload_or_update_file(
    access_token: str,
    refresh_token: str,
    expiry_iso: Optional[str],
    folder_name: str,
    filename: str,
    file_bytes: bytes,
    existing_file_id: Optional[str] = None,
) -> tuple[str, str, Optional[dict]]:
    """Upload a file to Drive, creating or updating it.

    Folder structure: My Drive / AI Career Assistant / {folder_name} / {filename}

    Returns (file_id, web_view_link, new_token_data | None).
    new_token_data is non-None when caller should persist refreshed tokens.
    """
    token, new_token_data = await _get_valid_access_token(access_token, refresh_token, expiry_iso)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Ensure folder hierarchy exists
        root_id = await _find_or_create_folder(client, token, _ROOT_FOLDER_NAME)
        sub_id = await _find_or_create_folder(client, token, folder_name, parent_id=root_id)

        mime = (
            "application/pdf"
            if filename.lower().endswith(".pdf")
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": _multipart_content_type(),
        }

        if existing_file_id:
            # Update existing file — Drive keeps version history automatically
            resp = await client.patch(
                f"{_UPLOAD_URL}/{existing_file_id}",
                params={"uploadType": "multipart", "fields": "id,webViewLink"},
                content=_build_multipart(filename, mime, file_bytes),
                headers=headers,
            )
        else:
            metadata = {"name": filename, "parents": [sub_id]}
            resp = await client.post(
                _UPLOAD_URL,
                params={"uploadType": "multipart", "fields": "id,webViewLink"},
                content=_build_multipart(filename, mime, file_bytes, metadata),
                headers=headers,
            )

        resp.raise_for_status()
        data = resp.json()
        return data["id"], data["webViewLink"], new_token_data


# ---------------------------------------------------------------------------
# Multipart MIME helpers (avoids needing the Google SDK)
# ---------------------------------------------------------------------------

_BOUNDARY = "aca_boundary_xyz"


def _multipart_content_type() -> str:
    return f"multipart/related; boundary={_BOUNDARY}"


def _build_multipart(filename: str, mime: str, file_bytes: bytes, metadata: Optional[dict] = None) -> bytes:
    import json
    meta = metadata or {"name": filename}
    meta_json = json.dumps(meta).encode()
    parts = (
        f"--{_BOUNDARY}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode() + meta_json + b"\r\n" + (
        f"--{_BOUNDARY}\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + file_bytes + f"\r\n--{_BOUNDARY}--".encode()
    return parts
