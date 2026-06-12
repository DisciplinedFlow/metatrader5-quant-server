#!/usr/bin/env bash
# Deploy the full stack to K3s. Run from the repo root after build-images.sh.
# Requires: .env in repo root (cp .env.example .env, fill in real values).
set -euo pipefail
cd "$(dirname "$0")/../.."

[ -f .env ] || { echo "ERROR: .env not found in repo root"; exit 1; }

# 1. Namespace first (secret needs it)
kubectl apply -f k8s/namespace.yaml

# 2. Secret from .env — single source of truth, same file compose uses
kubectl -n mt5-quant create secret generic app-env \
  --from-env-file=.env \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Core workloads
kubectl apply -k k8s/

# 4. Ingress, rendered from .env domains
set -a; source .env; set +a
export DASHBOARD_DOMAIN=${DASHBOARD_DOMAIN:-dashboard.mt5.example.com}
envsubst '${DJANGO_DOMAIN} ${API_DOMAIN} ${VNC_DOMAIN} ${DASHBOARD_DOMAIN}' \
  < k8s/ingress.template.yaml | kubectl apply -f -

echo
echo "✓ deployed. Watch startup with:"
echo "    kubectl -n mt5-quant get pods -w"
echo "  MT5 cold start (Wine init + terminal install) can take ~10 minutes."
