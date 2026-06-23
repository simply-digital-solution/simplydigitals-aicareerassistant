"""
sql_compat.py — PostgreSQL SQL helpers.

Date arithmetic helpers kept here so callers don't need to inline
datetime math. All SQL is PostgreSQL-only.
"""
from datetime import date, datetime, timedelta, timezone


def now_utc() -> datetime:
    """Current UTC datetime — use for all SQL TIMESTAMP bind parameters."""
    return datetime.now(timezone.utc)


def today_utc() -> date:
    """Current UTC date — use for all SQL DATE bind parameters."""
    return datetime.now(timezone.utc).date()


def days_ago(n: int) -> datetime:
    return now_utc() - timedelta(days=n)


def months_ago(n: int) -> datetime:
    now = now_utc()
    month = now.month - n
    year = now.year
    while month <= 0:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc)
