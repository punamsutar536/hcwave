#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Post-deployment smoke test.
# Usage: scripts/smoke-test.sh https://api.hospital.example [internal-token]
#   Local: scripts/smoke-test.sh http://localhost:8000 dev-internal-token
# -----------------------------------------------------------------------------
set -euo pipefail
BASE="${1:?base URL}"; TOKEN="${2:-}"
curl -fsS "$BASE/healthz" && echo " ✓ liveness"
curl -fsS "$BASE/readyz" && echo " ✓ database reachable"
if curl -fsS -o /dev/null "$BASE/dev/simulate" -X POST -H 'content-type: application/json' -d '{"text":"hi"}' 2>/dev/null; then
  echo " ✓ assistant answered (dev routes enabled)"
fi
if [[ -n "$TOKEN" ]]; then
  INTERNAL="${BASE%:8000}:8001"
  curl -fsS -X POST "$INTERNAL/internal/jobs/maintenance" -H "X-Internal-Token: $TOKEN" && echo " ✓ internal job API"
fi
