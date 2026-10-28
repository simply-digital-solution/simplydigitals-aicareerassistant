"""
Interpret the JSON that POST /api/v1/research/scrape returns, for scrape_and_score.sh.

The endpoint answers 200 even when every aggregator request failed, so the script
can't tell a failed scrape from one that found nothing new unless it reads
`mcf_queries_attempted` / `mcf_queries_failed`.

Usage:
  poetry run python -m scripts.scrape_result '<json from the scrape call>'
Exit status: 0 = scrape ran (possibly with some failed queries), 1 = scrape failed outright.
"""
import json
import sys


def summarize(raw: str) -> tuple[str, int]:
    """Return (message, exit_code) for the scrape endpoint's response body."""
    try:
        result = json.loads(raw)
    except (TypeError, ValueError):
        return "PIPELINE_ERROR: scrape response was not valid JSON — the scrape may not have run", 1
    if not isinstance(result, dict) or "inserted" not in result:
        return f"PIPELINE_ERROR: unexpected scrape response: {raw!r}", 1

    attempted = result.get("mcf_queries_attempted", 0)
    failed = result.get("mcf_queries_failed", 0)
    if attempted and failed == attempted:
        return (
            f"PIPELINE_ERROR: all {attempted} MyCareersFuture queries failed — "
            "nothing was fetched (see the backend log for the exception types and resolved IPs)",
            1,
        )
    if failed:
        return (
            f"WARNING: {failed} of {attempted} MyCareersFuture queries failed — "
            "this run is incomplete (see the backend log)",
            0,
        )
    return f"MyCareersFuture queries: {attempted} attempted, 0 failed", 0


if __name__ == "__main__":
    message, code = summarize(sys.argv[1] if len(sys.argv) > 1 else "")
    print(message)
    sys.exit(code)
