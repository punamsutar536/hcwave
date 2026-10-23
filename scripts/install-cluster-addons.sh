#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# One-time cluster add-ons:
#   * ALB controller for Application Gateway for Containers (Gateway API)
#   * cert-manager (Let's Encrypt certificates for the gateway) – optional
#   * AKS Backup extension + trusted access – optional
# Usage: scripts/install-cluster-addons.sh <env> [--with-cert-manager] [--with-backup]
# -----------------------------------------------------------------------------
source "$(dirname "$0")/lib.sh"
require az kubectl helm kubelogin
ENV="${1:?environment}"; shift || true
set -a; source "$REPO_ROOT/deploy/generated/${ENV}.env"; set +a

az aks get-credentials -g "$RESOURCE_GROUP" -n "$AKS_NAME" --overwrite-existing
kubelogin convert-kubeconfig -l azurecli

log "ALB controller (Application Gateway for Containers)"
helm upgrade --install alb-controller oci://mcr.microsoft.com/application-lb/charts/alb-controller \
  --namespace azure-alb-system --create-namespace --version 1.7.9 \
  --set albController.namespace=azure-alb-system \
  --set albController.podIdentity.clientID="$ALB_CONTROLLER_CLIENT_ID"

for arg in "$@"; do
  case "$arg" in
    --with-cert-manager)
      log "cert-manager"
      helm repo add jetstack https://charts.jetstack.io >/dev/null && helm repo update >/dev/null
      helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
        --version v1.16.1 --set crds.enabled=true --set config.enableGatewayAPI=true ;;
    --with-backup)
      log "AKS Backup extension"
      az k8s-extension create --name azure-aks-backup --extension-type microsoft.dataprotection.kubernetes \
        --scope cluster --cluster-type managedClusters --cluster-name "$AKS_NAME" -g "$RESOURCE_GROUP" \
        --release-train stable ;;
  esac
done
kubectl create namespace hcwave --dry-run=client -o yaml | kubectl apply -f -
log "cluster add-ons ready"
