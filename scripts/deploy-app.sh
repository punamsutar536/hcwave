#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Builds images in ACR (no local Docker needed) and deploys the Helm chart.
# Usage: scripts/deploy-app.sh <env> [image-tag]
# -----------------------------------------------------------------------------
source "$(dirname "$0")/lib.sh"
require az helm kubectl
ENV="${1:?environment}"; TAG="${2:-$(git -C "$REPO_ROOT" rev-parse --short HEAD)}"
set -a; source "$REPO_ROOT/deploy/generated/${ENV}.env"; set +a
export IMAGE_TAG="$TAG"

log "building images ${TAG} in ${ACR_NAME}"
az acr build -r "$ACR_NAME" -t "hcwave/backend:${TAG}" -f services/backend/Dockerfile "$REPO_ROOT"
az acr build -r "$ACR_NAME" -t "hcwave/staff-ui:${TAG}" "$REPO_ROOT/services/staff-ui"

"$REPO_ROOT/scripts/render-values.sh" "$ENV"
log "helm upgrade"
helm upgrade --install hcwave "$REPO_ROOT/deploy/helm/hcwave" -n hcwave --create-namespace \
  -f "$REPO_ROOT/deploy/helm/hcwave/values-azure.yaml" \
  -f "$REPO_ROOT/deploy/helm/hcwave/values-${ENV}.generated.yaml" \
  --wait --timeout 15m
kubectl -n hcwave get pods
