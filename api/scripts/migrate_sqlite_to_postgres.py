"""
One-shot migration: copy all data from aicareercoach.db (SQLite) into the
local PostgreSQL database.

Run AFTER:
  1. docker compose -f ../docker-compose.dev.yml up -d
  2. make migrate   (creates all tables in Postgres via alembic)

Usage:
  cd api
  poetry run python scripts/migrate_sqlite_to_postgres.py
"""
import asyncio
import os
import sqlite3
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

SQLITE_PATH = Path(__file__).parent.parent / "aicareercoach.db"

# Tables to migrate, in dependency order (parents before children)
TABLES = [
    "users",
    "profiles",
    "applications",
    "agent_runs",
    "agent_jobs",
    "agent_memory",
    "audit_log",
    "budget_records",
    "daily_scoring_usage",
    "drafts",
    "generated_resumes",
    "graph_checkpoints",
    "job_feedback",
    "job_postings",
    "llm_usage_logs",
    "notifications",
    "pending_questions",
    "saved_searches",
    "title_skill_map",
    "tool_calls",
]

# Columns that are boolean integers in SQLite → must cast to Python bool for Postgres
BOOL_COLUMNS = {
    "users":        {"scoring_suspended"},
    "job_postings": {"scored", "archived", "rescoring"},
    "applications": set(),
    "saved_searches": {"is_active"},
    "notifications": {"is_read"},
    "pending_questions": {"is_expired"},
    "drafts": set(),
    "agent_jobs": set(),
    "agent_runs": set(),
    "tool_calls": {"is_self_correction"},
}


def _cast_row(table: str, row: dict) -> dict:
    bool_cols = BOOL_COLUMNS.get(table, set())
    return {
        k: bool(v) if k in bool_cols and v is not None else v
        for k, v in row.items()
    }


async def migrate():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and set it.")
    if "sqlite" in database_url:
        raise RuntimeError("DATABASE_URL still points to SQLite — update it to PostgreSQL first.")

    print(f"Source : {SQLITE_PATH}")
    print(f"Target : {database_url}\n")

    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        for table in TABLES:
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"  {table}: 0 rows — skipped")
                continue

            dicts = [_cast_row(table, dict(r)) for r in rows]
            cols = list(dicts[0].keys())
            placeholders = ", ".join(f":{c}" for c in cols)
            col_list = ", ".join(cols)

            # Use ON CONFLICT DO NOTHING so re-runs are safe
            sql = text(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT DO NOTHING"
            )

            inserted = 0
            for row in dicts:
                result = await session.execute(sql, row)
                inserted += result.rowcount

            await session.commit()
            print(f"  {table}: {len(rows)} rows read, {inserted} inserted")

        # Reset all sequences so next INSERT gets the right ID
        print("\nResetting sequences...")
        seq_rows = await session.execute(text("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE column_default LIKE 'nextval%'
              AND table_schema = 'public'
        """))
        for seq_row in seq_rows.fetchall():
            tbl, col = seq_row
            await session.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{tbl}', '{col}'), "
                f"COALESCE((SELECT MAX({col}) FROM {tbl}), 0) + 1, false)"
            ))
        await session.commit()
        print("Sequences reset.\n")

    sqlite_conn.close()
    await engine.dispose()
    print("Migration complete.")


if __name__ == "__main__":
    # Load .env so DATABASE_URL is available
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    asyncio.run(migrate())
