#!/usr/bin/env bash
# RQ4: online (self-adapting) vs offline (frozen batch) anomaly detection on a
# non-stationary stream. No cluster required -- the drift generator is synthetic.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m ml.experiments.online_vs_offline --episodes "${1:-320}" \
    --configs "${2:-C1,C2,C3,C4}" --out data/results
python -m ml.experiments.cost_compare --episodes "${1:-320}" \
    --configs "${3:-C1,C4}" --out data/results
python -m ml.eval.plots data/results
