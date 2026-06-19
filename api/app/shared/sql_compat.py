"""
sql_compat.py — dialect-neutral SQL helpers.

All raw-SQL date math and formatting goes through these functions so that
the rest of the codebase stays identical for SQLite (dev) and PostgreSQL (prod).
"""
from datetime import datetime, timedelta, timezone


def days_ago(n: int) -> str:
    """Return an ISO date string for N days ago — use as a bound parameter in WHERE clauses.

    Usage:
        WHERE some_date_col >= :since
        params: {"since": days_ago(30)}
    """
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def months_ago(n: int) -> str:
    """Return an ISO date string for N months ago — use as a bound parameter in WHERE clauses.

    Usage:
        WHERE some_date_col >= :since
        params: {"since": months_ago(3)}
    """
    now = datetime.now(timezone.utc)
    month = now.month - n
    year = now.year
    while month <= 0:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc).strftime("%Y-%m-%d")


def month_trunc(col: str, dialect: str) -> str:
    """Return SQL fragment that formats a timestamp column as 'YYYY-MM'.

    Args:
        col:     Column name or expression, e.g. 'status_updated_at'
        dialect: 'sqlite' or 'postgresql'

    Usage:
        month_trunc('status_updated_at', dialect) + ' AS month'
    """
    if dialect == "postgresql":
        return f"TO_CHAR({col}, 'YYYY-MM')"
    return f"strftime('%Y-%m', {col})"


def nulls_last(col: str, dialect: str) -> str:
    """Return ORDER BY fragment that sorts NULLs last on both dialects.

    Args:
        col:     e.g. 'last_active DESC'
        dialect: 'sqlite' or 'postgresql'

    Usage:
        f"ORDER BY {nulls_last('last_active DESC', dialect)}"
    """
    if dialect == "postgresql":
        return f"{col} NULLS LAST"
    # SQLite: sort a nullable column last by adding a IS NULL sentinel column
    bare = col.split()[0]
    direction = col.split()[1] if len(col.split()) > 1 else "ASC"
    return f"{bare} IS NULL, {bare} {direction}"


def last_insert_id(result) -> int:
    """Return the last inserted row ID from an INSERT result.

    Works on both SQLite (lastrowid) and PostgreSQL (lastrowid via RETURNING).
    """
    return result.lastrowid


def get_dialect(database_url: str) -> str:
    """Derive the dialect string from the DATABASE_URL."""
    if "postgresql" in database_url or "postgres" in database_url:
        return "postgresql"
    return "sqlite"
