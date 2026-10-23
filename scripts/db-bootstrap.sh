#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Creates the PostgreSQL role for the workload identity (Entra auth, no
# password) and grants it the app's privileges. Run once per environment by a
# member of the Entra admin group, from a machine with VNet access (or via
# `az aks command invoke`).
# Usage: scripts/db-bootstrap.sh <env>
# -----------------------------------------------------------------------------
source "$(dirname "$0")/lib.sh"
require az psql
ENV="${1:?environment}"
set -a; source "$REPO_ROOT/deploy/generated/${ENV}.env"; set +a
ADMIN_USER="${HCWAVE_ADMIN_GROUP_NAME:-hcwave-admins}"
export PGPASSWORD; PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)

psql "host=${POSTGRES_HOST} dbname=postgres user=${ADMIN_USER} sslmode=require" -v ON_ERROR_STOP=1 <<SQL
SELECT * FROM pgaadauth_create_principal('${WORKLOAD_IDENTITY_NAME}', false, false)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${WORKLOAD_IDENTITY_NAME}');
SQL

psql "host=${POSTGRES_HOST} dbname=${POSTGRES_DB} user=${ADMIN_USER} sslmode=require" -v ON_ERROR_STOP=1 <<SQL
-- The workload identity owns the schema so Alembic migrations can run as it.
GRANT ALL ON SCHEMA public TO "${WORKLOAD_IDENTITY_NAME}";
ALTER DATABASE ${POSTGRES_DB} OWNER TO "${WORKLOAD_IDENTITY_NAME}";
CREATE EXTENSION IF NOT EXISTS vector;
SQL
log "database principal ready for ${WORKLOAD_IDENTITY_NAME}"
