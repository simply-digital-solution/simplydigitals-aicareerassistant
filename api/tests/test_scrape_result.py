"""
Unit tests for scripts/scrape_result.py — the check scrape_and_score.sh uses to tell a
scrape where every MCF query failed from one that merely found nothing new.
"""
import json

import pytest

from scripts.scrape_result import summarize


def _body(inserted=0, attempted=None, failed=None):
    body = {"inserted": inserted}
    if attempted is not None:
        body["mcf_queries_attempted"] = attempted
        body["mcf_queries_failed"] = failed
    return json.dumps(body)


def test_all_queries_failed_is_an_error():
    message, code = summarize(_body(attempted=10, failed=10))

    assert code == 1
    assert message.startswith("PIPELINE_ERROR:")
    assert "all 10" in message


def test_some_queries_failed_is_a_warning_not_an_error():
    message, code = summarize(_body(inserted=3, attempted=10, failed=8))

    assert code == 0
    assert message.startswith("WARNING:")
    assert "8 of 10" in message


def test_no_failures_is_clean():
    message, code = summarize(_body(attempted=10, failed=0))

    assert code == 0
    assert "10 attempted, 0 failed" in message


def test_response_without_stats_is_not_an_error():
    """eFC-only runs attempt no MCF queries."""
    message, code = summarize(_body(inserted=5))

    assert code == 0
    assert "PIPELINE_ERROR" not in message


@pytest.mark.parametrize("raw", ["", "not json", "<html>502</html>", "[]", '{"detail":"x"}'])
def test_unparseable_or_unexpected_response_is_an_error(raw):
    message, code = summarize(raw)

    assert code == 1
    assert message.startswith("PIPELINE_ERROR:")
