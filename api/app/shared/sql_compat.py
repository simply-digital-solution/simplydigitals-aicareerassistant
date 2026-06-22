"""
sql_compat.py — PostgreSQL SQL helpers.

Date arithmetic helpers kept here so callers don't need to inline
datetime math. All SQL is PostgreSQL-only.
"""
from datetime import datetime, timedelta, timezone


def days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def months_ago(n: int) -> str:
    now = datetime.now(timezone.utc)
    month = now.month - n
    year = now.year
    while month <= 0:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc).strftime("%Y-%m-%d")
