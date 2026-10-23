#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Deploys the Logic Apps Standard workflows and the Durable Functions app
# (zip deploy). Both are private; run from CI with VNet access or enable
# temporary deployment access per your policy.
# Usage: scripts/deploy-workflows.sh <env>
# -----------------------------------------------------------------------------
source "$(dirname "$0")/lib.sh"
require az zip
ENV="${1:?environment}"
set -a; source "$REPO_ROOT/deploy/generated/${ENV}.env"; set +a
TMP="$(mktemp -d)"

if [[ -n "${LOGIC_APP_NAME:-}" ]]; then
  log "Logic Apps workflows → ${LOGIC_APP_NAME}"
  (cd "$REPO_ROOT/workflows/logic-apps" && zip -qr "$TMP/logic.zip" . -x README.md)
  az logicapp deployment source config-zip -g "$RESOURCE_GROUP" -n "$LOGIC_APP_NAME" --src "$TMP/logic.zip"
fi
if [[ -n "${FUNCTION_APP_NAME:-}" ]]; then
  log "Durable Functions → ${FUNCTION_APP_NAME}"
  (cd "$REPO_ROOT/services/functions" && zip -qr "$TMP/func.zip" function_app.py host.json requirements.txt)
  az functionapp deployment source config-zip -g "$RESOURCE_GROUP" -n "$FUNCTION_APP_NAME" --src "$TMP/func.zip" --build-remote true
fi
rm -rf "$TMP"
