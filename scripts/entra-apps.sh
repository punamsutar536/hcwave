#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Creates the Microsoft Entra app registrations used by the platform:
#   * hcwave-staff-api     – audience for staff tokens, with app roles
#                            FrontOffice, PatientRelations, UnitHead, Admin
#   * hcwave-staff-ui      – SPA (MSAL) that requests the staff API scope
#   * hcwave-internal-api  – audience for Logic Apps/Functions → job API
#   * hcwave-functions     – audience protecting the Function App
# Usage: scripts/entra-apps.sh <env> <staff-ui-url>
# Prints the values to put in the generated environment file.
# -----------------------------------------------------------------------------
source "$(dirname "$0")/lib.sh"
require az jq
ENV="${1:?environment}"; UI_URL="${2:?staff UI URL, e.g. https://staff.hospital.example}"

roles_json=$(jq -n '[
  {allowedMemberTypes:["User"],description:"Front-office staff: WhatsApp inbox, front desk",displayName:"Front office",value:"FrontOffice",isEnabled:true,id:"'"$(uuidgen)"'"},
  {allowedMemberTypes:["User"],description:"Patient relations: complaints and inbox",displayName:"Patient relations",value:"PatientRelations",isEnabled:true,id:"'"$(uuidgen)"'"},
  {allowedMemberTypes:["User"],description:"Unit head: dashboard",displayName:"Unit head",value:"UnitHead",isEnabled:true,id:"'"$(uuidgen)"'"},
  {allowedMemberTypes:["User"],description:"Platform administrator",displayName:"Admin",value:"Admin",isEnabled:true,id:"'"$(uuidgen)"'"}
]')

create_api() {
  local name="$1" uri="$2"
  local app_id
  app_id=$(az ad app list --display-name "$name" --query "[0].appId" -o tsv)
  if [[ -z "$app_id" ]]; then
    app_id=$(az ad app create --display-name "$name" --sign-in-audience AzureADMyOrg --query appId -o tsv)
    az ad sp create --id "$app_id" >/dev/null
  fi
  az ad app update --id "$app_id" --identifier-uris "$uri" >/dev/null
  echo "$app_id"
}

log "staff API"
STAFF_API_ID=$(create_api "hcwave-${ENV}-staff-api" "api://hcwave-${ENV}-staff-api")
az ad app update --id "$STAFF_API_ID" --app-roles "$roles_json" >/dev/null || true
scope_id=$(uuidgen)
az ad app update --id "$STAFF_API_ID" --set api="{\"oauth2PermissionScopes\":[{\"adminConsentDescription\":\"Access the hcwave staff API\",\"adminConsentDisplayName\":\"Access hcwave\",\"id\":\"${scope_id}\",\"isEnabled\":true,\"type\":\"User\",\"value\":\"access\"}],\"requestedAccessTokenVersion\":2}" >/dev/null || true

log "internal job API and Functions audiences"
INTERNAL_API_ID=$(create_api "hcwave-${ENV}-internal-api" "api://hcwave-${ENV}-internal-api")
FUNCTIONS_ID=$(create_api "hcwave-${ENV}-functions" "api://hcwave-${ENV}-functions")

log "staff UI (SPA)"
SPA_ID=$(az ad app list --display-name "hcwave-${ENV}-staff-ui" --query "[0].appId" -o tsv)
if [[ -z "$SPA_ID" ]]; then
  SPA_ID=$(az ad app create --display-name "hcwave-${ENV}-staff-ui" --sign-in-audience AzureADMyOrg --query appId -o tsv)
  az ad sp create --id "$SPA_ID" >/dev/null
fi
az ad app update --id "$SPA_ID" --set spa="{\"redirectUris\":[\"${UI_URL}\",\"http://localhost:5173\"]}" >/dev/null

cat <<OUT
# ---- add to deploy/generated/${ENV}.env ----
STAFF_API_AUDIENCE=api://hcwave-${ENV}-staff-api
STAFF_API_SCOPE=api://hcwave-${ENV}-staff-api/access
ENTRA_SPA_CLIENT_ID=${SPA_ID}
INTERNAL_API_AUDIENCE=api://hcwave-${ENV}-internal-api
FUNCTIONS_AUDIENCE=api://hcwave-${ENV}-functions
# Assign users/groups to app roles in Enterprise applications → hcwave-${ENV}-staff-api.
# Add a "hospital_ids" claim (directory extension or claims mapping) listing each user's hospital IDs.
OUT
