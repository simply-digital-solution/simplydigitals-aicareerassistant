#!/usr/bin/env bash
# Manual job scrape + industry backfill + scoring, run against a local dev backend.
#
# Usage:
#   cd api
#   ./scripts/scrape_and_score.sh <user-email> [backend-url]
#
# backend-url defaults to http://localhost:8001 (this project's current local dev port).

set -euo pipefail

USER_EMAIL="${1:?Usage: scrape_and_score.sh <user-email> [backend-url]}"
BACKEND_URL="${2:-http://localhost:8001}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(dirname "$SCRIPT_DIR")"
cd "$API_DIR"

echo "== Checking backend at $BACKEND_URL =="
if ! curl -s -o /dev/null -w "%{http_code}" "$BACKEND_URL/docs" | grep -q "^200$"; then
  echo "Backend not reachable at $BACKEND_URL/docs — start it first (make dev)." >&2
  exit 1
fi

echo "== Scraping MyCareersFuture for $USER_EMAIL =="
SCRAPE_RESULT=$(curl -s -X POST \
  -H "X-User-Email: $USER_EMAIL" \
  -H "Content-Type: application/json" \
  "$BACKEND_URL/api/v1/research/scrape")
echo "$SCRAPE_RESULT"

echo "== Classifying industries for newly scraped jobs =="
poetry run python -m app.pipeline.industry_backfill

echo "== Scoring idle jobs =="
poetry run python -m scripts.score_idle_jobs

echo "== Done =="
