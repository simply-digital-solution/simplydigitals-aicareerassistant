"""
Unit tests for AuditLogger thread-safe file writing (M1+M2).

Verifies that:
- log_event() writes via TimedRotatingFileHandler (not plain open())
- The written line is valid JSON with all required fields
- log_event() does not raise when the handler emits
- log_path resolves to /var/log/aicareer in prod-like envs, falls back to api/logs in dev
"""
import json
import logging
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# AuditLogger — _audit_logger.info() is called with a JSON line
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_event_emits_via_rotating_handler():
    """log_event() must call _audit_logger.info() with a JSON-encoded line."""
    from app.shared.logger import AuditLogger, _audit_logger

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))

    audit = AuditLogger()

    with patch.object(_audit_logger, "info") as mock_info:
        await audit.log_event(
            db=mock_db,
            event_type="profile.updated",
            entity_type="user",
            entity_id=7,
            actor="user:7",
            payload={"field": "resume_text", "action": "update"},
        )

    mock_info.assert_called_once()
    raw_line = mock_info.call_args[0][0]
    entry = json.loads(raw_line)

    assert entry["event_type"] == "profile.updated"
    assert entry["entity_type"] == "user"
    assert entry["entity_id"] == 7
    assert entry["actor"] == "user:7"
    assert "timestamp" in entry
    assert "content_hash" in entry
    assert "chain_hash" in entry


@pytest.mark.asyncio
async def test_log_event_chain_hash_uses_genesis_when_table_empty():
    """When audit_log is empty, prev_hash must equal GENESIS_HASH."""
    from app.shared.logger import AuditLogger, _audit_logger

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))

    audit = AuditLogger()

    with patch.object(_audit_logger, "info") as mock_info:
        await audit.log_event(
            db=mock_db,
            event_type="test.event",
            entity_type="test",
            entity_id=None,
            actor="system",
            payload={},
        )

    raw_line = mock_info.call_args[0][0]
    entry = json.loads(raw_line)
    assert entry["prev_hash"] == AuditLogger.GENESIS_HASH


@pytest.mark.asyncio
async def test_log_event_no_plain_open_call():
    """log_event() must not call builtins.open — all writes go through the handler."""
    from app.shared.logger import AuditLogger, _audit_logger

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))

    audit = AuditLogger()

    with patch.object(_audit_logger, "info"):
        with patch("builtins.open") as mock_open:
            await audit.log_event(
                db=mock_db,
                event_type="no.open",
                entity_type="test",
                entity_id=1,
                actor="test",
                payload={"x": 1},
            )

    # open() must not be called from log_event() itself
    for call in mock_open.call_args_list:
        # allow open() from other imports at module level but not for audit.jsonl
        if call.args:
            assert "audit" not in str(call.args[0]), "log_event() must not call open() for audit file"


# ---------------------------------------------------------------------------
# _LOGS_DIR resolution: prod vs dev fallback
# ---------------------------------------------------------------------------

def test_logs_dir_falls_back_to_dev_when_var_log_not_writable(tmp_path, monkeypatch):
    """If /var/log is not writable, _LOGS_DIR should be the api/logs directory."""
    import importlib
    import app.shared.logger as logger_mod

    # /var/log is not writable in CI/dev — just assert the module already chose a fallback
    logs_dir = logger_mod._LOGS_DIR
    var_log_aicareer = logger_mod._PROD_LOGS_DIR

    if not os.access(var_log_aicareer.parent, os.W_OK):
        # In dev, should have resolved to the api/logs relative path
        assert logs_dir != var_log_aicareer
        assert logs_dir.name == "logs"
    else:
        # In a prod-like environment where /var/log is writable, allow prod path
        assert logs_dir == var_log_aicareer


def test_audit_handler_is_timed_rotating():
    """The audit file handler must be a TimedRotatingFileHandler, not a plain FileHandler."""
    from logging.handlers import TimedRotatingFileHandler
    from app.shared.logger import _audit_handler

    assert isinstance(_audit_handler, TimedRotatingFileHandler)
    assert _audit_handler.backupCount == 90
    assert _audit_handler.when.lower() == "midnight"
