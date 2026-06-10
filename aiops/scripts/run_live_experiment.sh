#!/usr/bin/env bash
# End-to-end LIVE run against the deployed TraceFlix + observability stack.
# Prereqs: on-demand-observability.yaml applied, Chaos Mesh installed,
#          VictoriaMetrics applied (k8s/victoriametrics.yaml), port-forwards up.
set -euo pipefail
cd "$(dirname "$0")/.."

# Resolve a Python interpreter (name differs across shells: python / py / python3).
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for c in python python3 py; do
    command -v "$c" >/dev/null 2>&1 && { PYTHON="$c"; break; }
  done
fi
[ -n "$PYTHON" ] || {
  echo "ERROR: no Python interpreter found (tried python, python3, py)." >&2
  echo "       Add Python to PATH, or run with an explicit one:" >&2
  echo "         PYTHON=/c/Python314/python.exe bash $0 ${*:-}" >&2
  exit 1
}

NS=on-demand-observability
echo "[*] Port-forwarding Prometheus/Loki/Tempo (background)..."
kubectl port-forward -n "$NS" svc/prometheus 9090:9090 &>/dev/null &
kubectl port-forward -n "$NS" svc/loki       3100:3100 &>/dev/null &
kubectl port-forward -n "$NS" svc/tempo      3200:3200 &>/dev/null &
kubectl port-forward -n devops-agent svc/victoriametrics 8428:8428 &>/dev/null &
sleep 5

echo "[*] Driving fault episodes + recording ground-truth labels..."
"$PYTHON" faults/run_episodes.py --episodes "${1:-30}" --labels data/labels.csv

echo "[*] Running C1-C4 analysis over live telemetry..."
TF_LIVE=1 PROM_URL=http://localhost:9090 LOKI_URL=http://localhost:3100 \
  TEMPO_URL=http://localhost:3200 VM_URL=http://localhost:8428 \
  "$PYTHON" -m ml.experiments.run_experiment --labels data/labels.csv --out data/results
"$PYTHON" -m ml.eval.plots data/results
