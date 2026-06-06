#!/usr/bin/env bash
# End-to-end LIVE run against the deployed TraceFlix + observability stack.
# Prereqs: on-demand-observability.yaml applied, Chaos Mesh installed,
#          VictoriaMetrics applied (k8s/victoriametrics.yaml), port-forwards up.
set -euo pipefail
cd "$(dirname "$0")/.."

NS=on-demand-observability
echo "[*] Port-forwarding Prometheus/Loki/Tempo (background)..."
kubectl port-forward -n "$NS" svc/prometheus 9090:9090 &>/dev/null &
kubectl port-forward -n "$NS" svc/loki       3100:3100 &>/dev/null &
kubectl port-forward -n "$NS" svc/tempo      3200:3200 &>/dev/null &
kubectl port-forward -n devops-agent svc/victoriametrics 8428:8428 &>/dev/null &
sleep 5

echo "[*] Driving fault episodes + recording ground-truth labels..."
python faults/run_episodes.py --episodes "${1:-30}" --labels data/labels.csv

echo "[*] Running C1-C4 analysis over live telemetry..."
TF_LIVE=1 PROM_URL=http://localhost:9090 LOKI_URL=http://localhost:3100 \
  TEMPO_URL=http://localhost:3200 VM_URL=http://localhost:8428 \
  python -m ml.experiments.run_experiment --labels data/labels.csv --out data/results
python -m ml.eval.plots data/results
