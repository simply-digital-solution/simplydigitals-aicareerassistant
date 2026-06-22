"""Tests for sql_compat — PostgreSQL date helpers."""
from datetime import datetime, timedelta, timezone

from app.shared.sql_compat import days_ago, months_ago


def test_days_ago_format():
    result = days_ago(30)
    datetime.strptime(result, "%Y-%m-%d")


def test_days_ago_correct_date():
    result = days_ago(7)
    expected = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    assert result == expected


def test_days_ago_zero():
    result = days_ago(0)
    expected = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert result == expected


def test_months_ago_format():
    result = months_ago(3)
    datetime.strptime(result, "%Y-%m-%d")


def test_months_ago_is_before_today():
    result = months_ago(1)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert result < today


def test_months_ago_crosses_year_boundary():
    now = datetime.now(timezone.utc)
    result = months_ago(now.month + 1)
    year = int(result[:4])
    assert year < now.year
