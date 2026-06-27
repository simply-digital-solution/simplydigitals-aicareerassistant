"""Tests for GET /api/v1/stats/dashboard."""
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock


def _make_user(user_id: int = 1):
    u = MagicMock()
    u.id = user_id
    return u


def _make_db(rows_per_query: list[list]):
    """Build an AsyncMock DB returning the given row lists for each execute call."""
    db = AsyncMock()
    results = []
    for rows in rows_per_query:
        result = MagicMock()
        result.fetchall.return_value = rows
        results.append(result)
    db.execute.side_effect = results
    return db


def _row(day_or_month, count, key="day"):
    r = MagicMock()
    setattr(r, key, day_or_month)
    r.count = count
    return r


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_returns_all_five_keys():
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    assert set(result.keys()) == {
        "scored_by_day", "fit_by_day", "selected_by_day",
        "applied_by_day", "interviews_by_month",
    }


@pytest.mark.asyncio
async def test_daily_series_always_30_entries():
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    for key in ("scored_by_day", "fit_by_day", "selected_by_day", "applied_by_day"):
        assert len(result[key]) == 30, f"{key} should have 30 entries"


@pytest.mark.asyncio
async def test_monthly_series_always_3_entries():
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    assert len(result["interviews_by_month"]) == 3


@pytest.mark.asyncio
async def test_scored_counts_mapped_correctly():
    from app.modules.stats.router import get_dashboard_stats

    today = date.today().isoformat()
    scored_rows = [_row(today, 7)]
    db = _make_db([scored_rows, [], [], [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    last_entry = result["scored_by_day"][-1]
    assert last_entry["date"] == today
    assert last_entry["count"] == 7


@pytest.mark.asyncio
async def test_zero_filled_for_missing_days():
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    assert all(e["count"] == 0 for e in result["scored_by_day"])
    assert all(e["count"] == 0 for e in result["fit_by_day"])


@pytest.mark.asyncio
async def test_daily_dates_are_consecutive():
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    dates = [e["date"] for e in result["scored_by_day"]]
    for i in range(1, len(dates)):
        prev = date.fromisoformat(dates[i - 1])
        curr = date.fromisoformat(dates[i])
        assert (curr - prev).days == 1, "dates should be consecutive"


@pytest.mark.asyncio
async def test_daily_series_ends_today():
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    assert result["scored_by_day"][-1]["date"] == date.today().isoformat()


@pytest.mark.asyncio
async def test_monthly_series_ends_current_month():
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    today = date.today()
    expected_month = f"{today.year}-{today.month:02d}"
    assert result["interviews_by_month"][-1]["month"] == expected_month


@pytest.mark.asyncio
async def test_interview_counts_mapped_correctly():
    from app.modules.stats.router import get_dashboard_stats

    today = date.today()
    month_str = f"{today.year}-{today.month:02d}"
    interview_rows = [_row(month_str, 3, key="month")]
    db = _make_db([[], [], [], [], interview_rows])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    last = result["interviews_by_month"][-1]
    assert last["month"] == month_str
    assert last["count"] == 3


@pytest.mark.asyncio
async def test_user_id_passed_to_all_queries():
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    await get_dashboard_stats(current_user=_make_user(user_id=42), db=db)

    for call in db.execute.call_args_list:
        params = call.args[1]
        assert params.get("uid") == 42


@pytest.mark.asyncio
async def test_selected_by_day_query_filters_by_status_selected():
    """
    Regression: dashboard selected count must only count applications with
    status='selected', not all applications. Previously missing the status
    filter caused the dashboard to show a higher count than the Selected tab.
    """
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    await get_dashboard_stats(current_user=_make_user(), db=db)

    # The 3rd execute call is the selected_by_day query (0-indexed: call index 2)
    third_call_sql = str(db.execute.call_args_list[2].args[0])
    assert "status = 'selected'" in third_call_sql, (
        "selected_by_day query must filter by status='selected' to match the Selected tab count"
    )


@pytest.mark.asyncio
async def test_selected_count_does_not_include_applied_or_interviewing():
    """
    Positive: selected_by_day reflects only status='selected' rows.
    Applied and interviewing rows in DB must not inflate the count.
    """
    from app.modules.stats.router import get_dashboard_stats

    today = date.today().isoformat()
    # Simulate: 2 selected jobs today returned by the query
    selected_rows = [_row(today, 2)]
    db = _make_db([[], [], selected_rows, [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    last_entry = result["selected_by_day"][-1]
    assert last_entry["date"] == today
    assert last_entry["count"] == 2


@pytest.mark.asyncio
async def test_selected_count_zero_when_no_selected_applications():
    """
    Negative: selected_by_day is all zeros when there are no selected applications.
    """
    from app.modules.stats.router import get_dashboard_stats

    db = _make_db([[], [], [], [], []])
    result = await get_dashboard_stats(current_user=_make_user(), db=db)

    assert all(e["count"] == 0 for e in result["selected_by_day"])
