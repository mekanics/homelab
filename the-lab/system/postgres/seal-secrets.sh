#!/usr/bin/env bash
# Generates and seals Kubernetes Secrets for each database in values.yaml.
#
# Safe to re-run: already-sealed databases are skipped, so existing passwords
# are never rotated unless you explicitly pass --rotate <owner>.
#
# Prerequisites:
#   - kubeseal installed and kubeconfig pointing at the cluster
#   - Run from the repo root or this directory
#
# Usage:
#   bash seal-secrets.sh                   # seal only new databases
#   bash seal-secrets.sh --rotate n8n      # rotate password for one database
#   bash seal-secrets.sh --rotate-all      # rotate all passwords (breaks running apps)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="postgres"
OUTPUT="${SCRIPT_DIR}/templates/sealed-secret.yaml"
TEMP_SECRET=$(mktemp /tmp/pg-secrets-XXXXXX.yaml)

trap 'rm -f "${TEMP_SECRET}"' EXIT

# --- Parse arguments ---------------------------------------------------------
ROTATE_OWNER=""
ROTATE_ALL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rotate)
      ROTATE_OWNER="$2"; shift 2 ;;
    --rotate-all)
      ROTATE_ALL=true; shift ;;
    *)
      echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# --- Parse databases from values.yaml ----------------------------------------
mapfile -t OWNERS < <(
  awk '
    /^databases:/ { in_db=1; next }
    in_db && /^[^ ]/ { in_db=0 }
    in_db && /owner:/ { gsub(/.*owner:[[:space:]]*/, ""); print }
  ' "${SCRIPT_DIR}/values.yaml"
)

if [[ ${#OWNERS[@]} -eq 0 ]]; then
  echo "ERROR: No databases found in values.yaml" >&2
  exit 1
fi

# --- Determine which owners already have a sealed secret ---------------------
already_sealed() {
  local owner="$1"
  [[ -f "${OUTPUT}" ]] && grep -q "name: pg-${owner}-credentials" "${OUTPUT}"
}

needs_sealing=()
skipped=()

for OWNER in "${OWNERS[@]}"; do
  if $ROTATE_ALL || [[ "${ROTATE_OWNER}" == "${OWNER}" ]]; then
    needs_sealing+=("${OWNER}")
  elif already_sealed "${OWNER}"; then
    skipped+=("${OWNER}")
  else
    needs_sealing+=("${OWNER}")
  fi
done

if [[ ${#skipped[@]} -gt 0 ]]; then
  echo "Skipping (already sealed): ${skipped[*]}"
fi

if [[ ${#needs_sealing[@]} -eq 0 ]]; then
  echo "All databases already have sealed secrets. Nothing to do."
  echo "Use --rotate <owner> or --rotate-all to regenerate."
  exit 0
fi

echo "Sealing: ${needs_sealing[*]}"
echo ""

# --- Generate plain secrets for only the owners that need sealing ------------
> "${TEMP_SECRET}"

for OWNER in "${needs_sealing[@]}"; do
  PASSWORD=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32)

  cat >> "${TEMP_SECRET}" << EOF
---
apiVersion: v1
kind: Secret
metadata:
  name: pg-${OWNER}-credentials
  namespace: ${NAMESPACE}
type: kubernetes.io/basic-auth
stringData:
  username: ${OWNER}
  password: ${PASSWORD}
EOF

  echo "  pg-${OWNER}-credentials  password: ${PASSWORD}"
done

echo ""

# --- Seal new secrets and merge with existing file ---------------------------
NEW_SEALED=$(kubeseal --format yaml --namespace "${NAMESPACE}" < "${TEMP_SECRET}")

if [[ -f "${OUTPUT}" ]] && [[ ${#skipped[@]} -gt 0 ]]; then
  # Remove existing entries for the owners we are re-sealing, then append new ones.
  # This handles --rotate without losing untouched sealed secrets.
  FILTERED=$(awk -v owners="${needs_sealing[*]}" '
    BEGIN { split(owners, arr, " "); for (k in arr) skip[arr[k]] = 1 }
    /^---$/ { block = "---\n"; next }
    { block = block $0 "\n" }
    /name: pg-/ {
      match($0, /pg-([^-]+)-credentials/, m)
      current = m[1]
    }
    /^$/ {
      if (!(current in skip)) printf "%s", block
      block = ""; current = ""
    }
    END { if (block != "" && !(current in skip)) printf "%s", block }
  ' "${OUTPUT}")

  {
    printf '%s\n' "${FILTERED}"
    printf '%s\n' "${NEW_SEALED}"
  } > "${OUTPUT}"
else
  # No existing file or rotating all: write fresh
  printf '%s\n' "${NEW_SEALED}" > "${OUTPUT}"
fi

echo "Written to templates/sealed-secret.yaml"
echo ""
echo "The plain-text passwords above are NOT stored anywhere."
echo "Save them in your password manager before closing this terminal."
