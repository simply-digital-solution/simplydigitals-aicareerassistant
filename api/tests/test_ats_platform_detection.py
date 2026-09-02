"""
Unit tests for detect_ats_platform() — identifying ATS platform from a
careers page URL's hostname.
"""
import pytest

from app.pipeline.ats_scrapers import detect_ats_platform


@pytest.mark.parametrize("url", [
    "https://boards.greenhouse.io/acme",
    "https://job-boards.greenhouse.io/acme",
    "http://boards.greenhouse.io/acme/jobs/12345",
])
def test_detects_greenhouse(url):
    assert detect_ats_platform(url) == "greenhouse"


@pytest.mark.parametrize("url", [
    "https://jobs.lever.co/acme",
    "https://jobs.lever.co/acme/senior-engineer-abc123",
])
def test_detects_lever(url):
    assert detect_ats_platform(url) == "lever"


@pytest.mark.parametrize("url", [
    "https://acme.wd1.myworkdayjobs.com/careers",
    "https://acme.wd5.myworkdayjobs.com/en-US/External",
])
def test_detects_workday(url):
    assert detect_ats_platform(url) == "workday"


@pytest.mark.parametrize("url", [
    "https://acme.com/careers",
    "https://careers.acme.com",
    "not a url at all",
    "",
    "https://evilgreenhouse.io/acme",  # must not match on substring alone
    "https://greenhouse.io.evil.com/acme",  # must not match on prefix trick
])
def test_returns_none_for_unrecognized_or_invalid(url):
    assert detect_ats_platform(url) is None
