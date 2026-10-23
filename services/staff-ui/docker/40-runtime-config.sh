#!/bin/sh
# Renders config.js from environment variables at container start, so one
# image serves every environment. Written to /tmp because the root
# filesystem is read-only in Kubernetes; nginx serves it at /config.js.
set -eu
cat > /tmp/config.js <<CONFIG
window.__HCWAVE_CONFIG__ = {
  apiBaseUrl: "${API_BASE_URL:-}",
  authMode: "${AUTH_MODE:-msal}",
  clientId: "${ENTRA_CLIENT_ID:-}",
  tenantId: "${ENTRA_TENANT_ID:-}",
  apiScope: "${STAFF_API_SCOPE:-}",
  pollSeconds: ${POLL_SECONDS:-5}
};
CONFIG
