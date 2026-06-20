import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_PROD_LOGS_DIR = Path("/var/log/aicareer")
_DEV_LOGS_DIR = Path(__file__).parents[3] / "logs"
_LOGS_DIR = _PROD_LOGS_DIR if os.access(_PROD_LOGS_DIR.parent, os.W_OK) else _DEV_LOGS_DIR
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Thread-safe rotating file handler — one file per day, kept for 90 days
_audit_handler = TimedRotatingFileHandler(
    filename=str(_LOGS_DIR / "audit.jsonl"),
    when="midnight",
    interval=1,
    backupCount=90,
    utc=True,
    encoding="utf-8",
)
_audit_handler.suffix = "%Y-%m-%d"
_audit_logger = logging.getLogger("audit_file")
_audit_logger.setLevel(logging.INFO)
_audit_logger.addHandler(_audit_handler)
_audit_logger.propagate = False

LOG_FILE = _LOGS_DIR / "audit.jsonl"


def _configure_structlog():
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


_configure_structlog()
log = structlog.get_logger()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class AuditLogger:
    """
    Hash-chained tamper-evident audit log.
    Writes to both SQLite audit_log table and logs/audit.jsonl.
    Chain: chain_hash = sha256(prev_chain_hash + sha256(json_payload))
    """

    GENESIS_HASH = "0" * 64

    async def log_event(
        self,
        db: AsyncSession,
        event_type: str,
        entity_type: str,
        entity_id: int | None,
        actor: str,
        payload: dict[str, Any],
    ) -> None:
        content = json.dumps(payload, sort_keys=True, default=str)
        content_hash = _sha256(content)
        prev_hash = await self._get_last_chain_hash(db)
        chain_hash = _sha256(prev_hash + content_hash)
        timestamp = datetime.now(timezone.utc).isoformat()

        await db.execute(
            text("""
                INSERT INTO audit_log
                    (timestamp, event_type, entity_type, entity_id, actor,
                     payload, content_hash, prev_hash, chain_hash)
                VALUES
                    (:ts, :et, :ety, :eid, :actor,
                     :payload, :ch, :ph, :cch)
            """),
            {
                "ts": timestamp,
                "et": event_type,
                "ety": entity_type,
                "eid": entity_id,
                "actor": actor,
                "payload": content,
                "ch": content_hash,
                "ph": prev_hash,
                "cch": chain_hash,
            },
        )

        # Append to JSONL file as secondary tamper-evident archive (thread-safe via handler)
        entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor": actor,
            "content_hash": content_hash,
            "prev_hash": prev_hash,
            "chain_hash": chain_hash,
        }
        _audit_logger.info(json.dumps(entry))

    async def verify_chain(self, db: AsyncSession) -> tuple[bool, list[int]]:
        """Replay all entries and verify hash chain integrity."""
        rows = await db.execute(
            text("SELECT id, payload, content_hash, prev_hash, chain_hash FROM audit_log ORDER BY id")
        )
        entries = rows.fetchall()

        broken_ids: list[int] = []
        prev_hash = self.GENESIS_HASH

        for row in entries:
            expected_content_hash = _sha256(row.payload)
            expected_chain_hash = _sha256(prev_hash + expected_content_hash)

            if row.content_hash != expected_content_hash:
                broken_ids.append(row.id)
            elif row.chain_hash != expected_chain_hash:
                broken_ids.append(row.id)
            elif row.prev_hash != prev_hash:
                broken_ids.append(row.id)

            prev_hash = row.chain_hash

        return len(broken_ids) == 0, broken_ids

    async def _get_last_chain_hash(self, db: AsyncSession) -> str:
        result = await db.execute(
            text("SELECT chain_hash FROM audit_log ORDER BY id DESC LIMIT 1")
        )
        row = result.fetchone()
        return row[0] if row else self.GENESIS_HASH


audit_logger = AuditLogger()
