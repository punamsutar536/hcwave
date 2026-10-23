#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Writes optional third-party secrets to Key Vault (values read from your
# shell, never from files). Most Azure services need no secret at all.
# Usage: META_APP_SECRET=... MSG91_AUTH_KEY=... scripts/kv-secrets.sh <env>
# Then add the names to secrets.azureKeyVault.objects in Helm values.
# -----------------------------------------------------------------------------
source "$(dirname "$0")/lib.sh"
require az
ENV="${1:?environment}"
set -a; source "$REPO_ROOT/deploy/generated/${ENV}.env"; set +a
for var in META_ACCESS_TOKEN META_APP_SECRET META_VERIFY_TOKEN MSG91_AUTH_KEY ANTHROPIC_FOUNDRY_API_KEY HIS_API_TOKEN AZURE_OPENAI_API_KEY; do
  if [[ -n "${!var:-}" ]]; then
    az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "${var//_/-}" --value "${!var}" -o none
    log "stored ${var//_/-}"
  fi
done
