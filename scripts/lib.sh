#!/usr/bin/env bash
# Shared helpers for hcwave scripts.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_ROOT

log() { printf '\033[1;34m[hcwave]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[hcwave] %s\033[0m\n' "$*" >&2; exit 1; }

require() {
  for tool in "$@"; do command -v "$tool" >/dev/null 2>&1 || die "missing tool: $tool"; done
}

# Reads one output of the last subscription deployment for an environment.
deployment_output() {
  local env="$1" key="$2"
  az deployment sub show --name "hcwave-${env}" --query "properties.outputs.${key}.value" -o tsv
}
