#!/usr/bin/env bash
# Build the three app images and import them into K3s' containerd.
# Run ON the K3s VM (amd64 — Wine/MT5 is x86-only) from the repo root.
set -euo pipefail
cd "$(dirname "$0")/../.."

TAG=${1:-latest}

docker build --platform linux/amd64 -t mt5-quant/mt5:"$TAG" backend/mt5
docker build --platform linux/amd64 -t mt5-quant/django:"$TAG" backend/django
docker build --platform linux/amd64 -t mt5-quant/dashboard:"$TAG" backend/dashboard

# K3s uses containerd, not the Docker daemon — import explicitly.
for img in mt5 django dashboard; do
  docker save mt5-quant/$img:"$TAG" | sudo k3s ctr images import -
done

echo "✓ images built and imported into k3s containerd (tag: $TAG)"
