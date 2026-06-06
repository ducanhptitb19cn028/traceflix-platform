#!/usr/bin/env bash
# Reproduce RQ1-RQ3 with the synthetic generator (no cluster required).
set -euo pipefail
cd "$(dirname "$0")/.."
python -m ml.experiments.run_experiment --episodes "${1:-200}" --out data/results
python -m ml.eval.plots data/results
