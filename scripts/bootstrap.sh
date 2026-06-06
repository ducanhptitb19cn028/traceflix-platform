#!/usr/bin/env bash
# One-command build + deploy of the full TraceFlix platform.
# Run from repo root. Assumes kubectl points at a running cluster and Maven + Docker are installed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[1/4] Building Java services (Maven)..."
( cd services && mvn -q clean package -DskipTests )

echo "[2/4] Building Docker images..."
if command -v minikube >/dev/null 2>&1; then eval "$(minikube docker-env)"; fi
docker build -t traceflix/movie-service:1.0.0  services/movie-service
docker build -t traceflix/actor-service:1.0.0  services/actor-service
docker build -t traceflix/review-service:1.0.0 services/review-service

echo "[3/4] Deploying observability stack + gap fixes..."
kubectl apply -f observability/on-demand-observability.yaml
kubectl apply -f aiops/k8s/load-generator-fixed.yaml
kubectl apply -f aiops/k8s/victoriametrics.yaml

echo "[4/4] Installing Chaos Mesh (fault engine)..."
bash aiops/scripts/install_chaos_mesh.sh || true

echo
echo "Done. Next:"
echo "  kubectl get pods -n on-demand-observability -w     # wait for Running"
echo "  cd aiops && ./scripts/run_live_experiment.sh 30    # run the C1-C4 experiment"
