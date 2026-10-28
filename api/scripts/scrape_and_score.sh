#!/usr/bin/env bash
# Manual job scrape + industry backfill + scoring, run against a local dev backend.
#
# Usage:
#   cd api
#   ./scripts/scrape_and_score.sh <user-email> [backend-url] [sources] [efc_locations]
#
# backend-url defaults to http://localhost:8001 (this project's current local dev port).
# sources optionally restricts which aggregators run, comma-separated
# (e.g. "mycareersfuture" or "mycareersfuture,efinancialcareers");
# omitted runs all of them.
# efc_locations optionally restricts which eFinancialCareers countries are
# searched, comma-separated (e.g. "singapore"); omitted searches all
# configured ones. Ignored unless efinancialcareers is in sources.

# Note: scrape requests run inside the backend process, so the details of a
# failed request (exception type, resolved IPs) land in the backend's own
# server log. The scrape response carries per-run counts of attempted and
# failed MCF queries, which scripts.scrape_result turns into a summary and an
# exit status. The classify and score steps run as direct subprocesses of this
# script, so their output is checked here for PIPELINE_ERROR: lines.
set -uo pipefail

USER_EMAIL="${1:?Usage: scrape_and_score.sh <user-email> [backend-url] [sources] [efc_locations]}"
BACKEND_URL="${2:-http://localhost:8001}"
SOURCES="${3:-}"
EFC_LOCATIONS="${4:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(dirname "$SCRIPT_DIR")"
cd "$API_DIR"

echo "== Checking backend at $BACKEND_URL =="
if ! curl -s -o /dev/null -w "%{http_code}" "$BACKEND_URL/docs" | grep -q "^200$"; then
  echo "Backend not reachable at $BACKEND_URL/docs — start it first (make dev)." >&2
  exit 1
fi

SCRAPE_URL="$BACKEND_URL/api/v1/research/scrape"
QUERY=""
if [ -n "$SOURCES" ]; then
  QUERY="sources=${SOURCES}"
fi
if [ -n "$EFC_LOCATIONS" ]; then
  QUERY="${QUERY:+${QUERY}&}efc_locations=${EFC_LOCATIONS}"
fi
if [ -n "$QUERY" ]; then
  SCRAPE_URL="${SCRAPE_URL}?${QUERY}"
fi

echo "== Scraping ($([ -n "$SOURCES" ] && echo "$SOURCES" || echo "all sources")) for $USER_EMAIL =="
SCRAPE_RESULT=$(curl -s -X POST \
  -H "X-User-Email: $USER_EMAIL" \
  -H "Content-Type: application/json" \
  "$SCRAPE_URL")
echo "$SCRAPE_RESULT"
SCRAPE_SUMMARY=$(poetry run python -m scripts.scrape_result "$SCRAPE_RESULT")
SCRAPE_STATUS=$?
echo "$SCRAPE_SUMMARY"
echo "(exception types and resolved IPs for failed requests are in the backend server's own log)"

echo "== Classifying industries for newly scraped jobs =="
CLASSIFY_OUTPUT=$(poetry run python -m app.pipeline.industry_backfill 2>&1)
echo "$CLASSIFY_OUTPUT"

echo "== Scoring idle jobs =="
SCORE_OUTPUT=$(poetry run python -m scripts.score_idle_jobs 2>&1)
echo "$SCORE_OUTPUT"

echo "== Done =="

ERROR_LINES=$(printf '%s\n%s\n%s\n' "$SCRAPE_SUMMARY" "$CLASSIFY_OUTPUT" "$SCORE_OUTPUT" | grep "PIPELINE_ERROR:" || true)
if [ -n "$ERROR_LINES" ] || [ "$SCRAPE_STATUS" -ne 0 ]; then
  echo ""
  echo "== Errors =="
  echo "$ERROR_LINES"
  exit 1
fi
