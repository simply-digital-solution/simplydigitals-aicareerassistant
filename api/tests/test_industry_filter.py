"""
Tests for industry filter logic: fuzzy match and job-list filtering.
(industry_extractor.py was removed in favour of LLM-based extraction.)
"""
import pytest
from app.modules.agents.router import _filter_by_industry, _industry_match


# ---------------------------------------------------------------------------
# Fuzzy match similarity
# ---------------------------------------------------------------------------

def test_exact_match_is_100pct():
    assert _industry_match("Banking & Financial Services", "Banking & Financial Services") == 1.0


def test_partial_name_passes_80pct():
    # "Banking & Finance" vs full taxonomy name
    ratio = _industry_match("Banking & Finance", "Banking & Financial Services")
    assert ratio >= 0.80


def test_unrelated_industry_below_80pct():
    ratio = _industry_match("Healthcare & Life Sciences", "Banking & Financial Services")
    assert ratio < 0.80


def test_tech_vs_banking_below_80pct():
    ratio = _industry_match("Technology & Software", "Banking & Financial Services")
    assert ratio < 0.80


# ---------------------------------------------------------------------------
# Filter logic
# ---------------------------------------------------------------------------

def test_matching_industry_is_kept():
    jobs = [{"inferred_industries": ["Banking & Financial Services"]}]
    result = _filter_by_industry(jobs, ["Banking & Financial Services"])
    assert len(result) == 1


def test_non_matching_industry_is_dropped():
    jobs = [{"inferred_industries": ["Healthcare & Life Sciences"]}]
    result = _filter_by_industry(jobs, ["Banking & Financial Services"])
    assert len(result) == 0


def test_no_inferred_industry_passes_through():
    jobs = [{"inferred_industries": []}]
    result = _filter_by_industry(jobs, ["Banking & Financial Services"])
    assert len(result) == 1


def test_missing_inferred_key_passes_through():
    jobs = [{"title": "Some Job"}]  # no inferred_industries key at all
    result = _filter_by_industry(jobs, ["Banking & Financial Services"])
    assert len(result) == 1


def test_no_target_industries_skips_filter():
    jobs = [
        {"inferred_industries": ["Healthcare & Life Sciences"]},
        {"inferred_industries": ["Technology & Software"]},
    ]
    # Filter is not called when target_industries is empty — but if called with empty list,
    # all jobs should pass since there is nothing to match against.
    result = _filter_by_industry(jobs, [])
    assert len(result) == 2


def test_multiple_jobs_mixed_results():
    jobs = [
        {"inferred_industries": ["Banking & Financial Services"]},
        {"inferred_industries": ["Technology & Software"]},
        {"inferred_industries": []},  # unknown — keep
    ]
    result = _filter_by_industry(jobs, ["Banking & Financial Services"])
    assert len(result) == 2  # banking + unknown kept; tech dropped


def test_partial_industry_name_match_kept():
    # User typed "Banking & Finance" in their profile (abbreviated)
    jobs = [{"inferred_industries": ["Banking & Financial Services"]}]
    result = _filter_by_industry(jobs, ["Banking & Finance"])
    assert len(result) == 1
