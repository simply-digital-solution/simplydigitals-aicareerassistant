"""Tests for sql_compat — dialect-neutral SQL helpers."""
from datetime import datetime, timedelta, timezone

import pytest

from app.shared.sql_compat import (
    days_ago,
    months_ago,
    month_trunc,
    nulls_last,
    last_insert_id,
    get_dialect,
)


# ---------------------------------------------------------------------------
# get_dialect
# ---------------------------------------------------------------------------

def test_get_dialect_sqlite():
    assert get_dialect("sqlite+aiosqlite:///./aicareercoach.db") == "sqlite"


def test_get_dialect_postgres_full():
    assert get_dialect("postgresql+asyncpg://user:pass@host/db") == "postgresql"


def test_get_dialect_postgres_short():
    assert get_dialect("postgres://user:pass@host/db") == "postgresql"


# ---------------------------------------------------------------------------
# days_ago
# ---------------------------------------------------------------------------

def test_days_ago_format():
    result = days_ago(30)
    # Must be a valid ISO date string YYYY-MM-DD
    datetime.strptime(result, "%Y-%m-%d")


def test_days_ago_correct_date():
    result = days_ago(7)
    expected = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    assert result == expected


def test_days_ago_zero():
    result = days_ago(0)
    expected = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert result == expected


# ---------------------------------------------------------------------------
# months_ago
# ---------------------------------------------------------------------------

def test_months_ago_format():
    result = months_ago(3)
    datetime.strptime(result, "%Y-%m-%d")


def test_months_ago_is_before_today():
    result = months_ago(1)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert result < today


def test_months_ago_crosses_year_boundary():
    # Force a year rollover by going back enough months from January
    now = datetime.now(timezone.utc)
    result = months_ago(now.month + 1)
    year = int(result[:4])
    assert year < now.year


# ---------------------------------------------------------------------------
# month_trunc
# ---------------------------------------------------------------------------

def test_month_trunc_sqlite():
    result = month_trunc("status_updated_at", "sqlite")
    assert result == "strftime('%Y-%m', status_updated_at)"


def test_month_trunc_postgres():
    result = month_trunc("status_updated_at", "postgresql")
    assert result == "TO_CHAR(status_updated_at, 'YYYY-MM')"


# ---------------------------------------------------------------------------
# nulls_last
# ---------------------------------------------------------------------------

def test_nulls_last_postgres():
    result = nulls_last("last_active DESC", "postgresql")
    assert result == "last_active DESC NULLS LAST"


def test_nulls_last_sqlite():
    result = nulls_last("last_active DESC", "sqlite")
    # SQLite sentinel: sort NULLs last via IS NULL trick
    assert "last_active IS NULL" in result
    assert "last_active DESC" in result


def test_nulls_last_sqlite_asc():
    result = nulls_last("last_active ASC", "sqlite")
    assert "last_active IS NULL" in result
    assert "last_active ASC" in result


# ---------------------------------------------------------------------------
# last_insert_id
# ---------------------------------------------------------------------------

def test_last_insert_id_uses_lastrowid():
    class FakeResult:
        lastrowid = 42

    assert last_insert_id(FakeResult()) == 42
