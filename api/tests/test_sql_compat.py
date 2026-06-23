"""Tests for sql_compat — PostgreSQL date helpers."""
from datetime import datetime, timedelta, timezone

from app.shared.sql_compat import days_ago, months_ago


def test_days_ago_returns_datetime():
    result = days_ago(30)
    assert isinstance(result, datetime)
    assert result.tzinfo is not None


def test_days_ago_correct_date():
    result = days_ago(7)
    expected = datetime.now(timezone.utc) - timedelta(days=7)
    assert abs((result - expected).total_seconds()) < 2


def test_days_ago_zero():
    result = days_ago(0)
    expected = datetime.now(timezone.utc)
    assert abs((result - expected).total_seconds()) < 2


def test_months_ago_returns_datetime():
    result = months_ago(3)
    assert isinstance(result, datetime)
    assert result.tzinfo is not None


def test_months_ago_is_before_today():
    result = months_ago(1)
    assert result < datetime.now(timezone.utc)


def test_months_ago_crosses_year_boundary():
    now = datetime.now(timezone.utc)
    result = months_ago(now.month + 1)
    assert result.year < now.year
