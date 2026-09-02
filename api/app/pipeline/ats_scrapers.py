"""
Scrapers for company career pages, keyed by ATS (applicant tracking system)
platform. A watched company is identified only by its careers page URL — the
platform is detected from the URL's hostname, never asked of the user.
"""
from urllib.parse import urlparse

_PLATFORM_HOST_SUFFIXES: dict[str, str] = {
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "myworkdayjobs.com": "workday",
}


def detect_ats_platform(url: str) -> str | None:
    """
    Identify the ATS platform a careers page URL belongs to, based on its
    hostname. Returns None if the URL doesn't match a known platform —
    callers must treat that as "not yet supported", not guess further.
    """
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()

    for suffix, platform in _PLATFORM_HOST_SUFFIXES.items():
        if host == suffix or host.endswith("." + suffix):
            return platform
    return None
