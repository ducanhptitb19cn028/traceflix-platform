# TraceFlix Platform — Whole-Project Demo

A guided, end-to-end walkthrough of the dissertation *"Does Observability
Matter? An Empirical Study of Real-Time Anomaly Detection in Cloud-Native
Systems"* — from the running microservices to the empirical result that
**static anomaly detection is insufficient in a modern distributed system, and
operations matter.**

```
services/  ──►  observability/  ──►  aiops/
3 Spring Boot   Tempo · Loki ·       fault injection + ML
microservices   Prometheus · Grafana C1–C4 + RQ1–RQ4 + cost
```

There are two tracks:

| Track | Needs a cluster? | Time | Shows |
|-------|------------------|------|-------|
| **A — Offline** | No | ~5 min | The full empirical story (RQ1–RQ4 + cost), reproducibly, on synthetic telemetry that mirrors the live schema |
| **B — Live** | Yes (Docker Desktop K8s) | ~20 min | The real services, real traces in Grafana, and the same experiments against live PromQL/LogQL/TraceQL |

Start with Track A — it is the demo that proves the thesis and runs anywhere.

---

## The thesis in one sentence

On clean, stationary data every model looks great (F1 ≈ 0.99). The moment the
system *operates* — a deploy regresses latency, autoscaling changes throughput,
data growth raises memory — the telemetry baseline drifts, and a detector
trained once on a snapshot decays. The demo makes that failure visible and shows
what fixes it.

---

# Track A — Offline demo (no cluster)

## A0. Setup

```bash
cd aiops
pip install -r requirements.txt          # numpy, pandas, scikit-learn, matplotlib
```

> Windows PowerShell: set `('$env:PYTHONPATH = (Resolve-Path .).Path')` once so
> `python -m ...` resolves the package, or just run the commands from `aiops/`.

Sanity check:

```bash
pytest tests/ -q                         # 7 passed
```

## A1. RQ1–RQ3 — observability completeness & RCA (the stationary baseline)

```bash
./scripts/run_offline.sh 200
# or: python -m ml.experiments.run_experiment --episodes 200 --out data/results
```

What you'll see (synthetic, seed 42, 3-service topology):

```
RQ1  C1 F1=0.906   C2 0.933   C3 0.988   C4 0.994     (completeness helps; traces drive the jump)
RQ2  RF 0.994 / GB 0.991 / XGB 0.991 F1; fusion high-precision; LSTM needs torch
RQ3  Top-1 RCA: metrics+logs 0.91  ->  +traces 1.00
```

**Talking points**

- **RQ1** — detection F1 climbs as you add pillars (metrics → +logs → +traces →
  +events). Traces give the biggest jump.
- **RQ2** — tree ensembles (RF/GB/XGB) dominate on tabular MELT features.
- **RQ3** — distributed tracing isolates the *root cause*: a downstream fault
  shows elevated latency everywhere, but only the origin accumulates originating
  error spans. Top-1 RCA goes 0.92 → 1.00 once traces are included.

This is the "observability matters" half — **and every model here is trained
once on a static split.** That assumption is what Track A breaks next.

## A2. RQ4 — why static detection is not enough (the headline)

```bash
./scripts/run_online_offline.sh 320
# runs: online_vs_offline (detection) + cost_compare (cost) + plots
```

Detection F1 on the **operational future** (regimes R1–R3 after a deploy/scale/
data-growth baseline shift), all models on identical features:

```
config            offline_static   offline_periodic   online_adaptive   offline_full (oracle)
C1 Metrics-Only       0.489             0.757              0.817               0.812
C2 + Logs             0.492             0.778              0.835               0.834
C3 + Traces           0.510             0.890              0.982               0.940
C4 Full MELT          0.511             0.891              0.983               0.939
```

**Talking points**

- **`offline_static` (the traditional approach) collapses to F1 ≈ 0.5 under
  drift — even with full MELT.** It flags the *new normal* as anomalous
  (precision ≈ 0.34). More observability does **not** rescue it: the failure is
  the *learning paradigm*, not signal availability.
- **`offline_periodic` (scheduled retrain) helps but is not enough** — it
  recovers a lot (0.51 → 0.89) yet still trails by 6–9 F1 points, because each
  regime shift opens a **drift-response gap** until the next refresh. See the
  sawtooth in `data/results/figures/rq4_timeline.png`.
- **`online_adaptive` recovers to oracle level** (0.82 → 0.98) updating *per
  sample* — adaptive normalisation tracks the evolving normal, incremental
  learning + a self-selecting hyper-parameter pool keep it calibrated, no batch
  re-fit. It even *exceeds* the all-regime oracle under C3/C4.
- **`offline_full`** is an unrealistic oracle (trained on the future) shown only
  to prove the static decay is caused by **non-stationarity, not model
  capacity.**

Open the figures:

```
data/results/figures/rq4_timeline.png          # rolling F1 over the drifting stream
data/results/figures/rq4_online_vs_offline.png # F1 bars: static < periodic < online ≈ oracle
```

## A3. Cost — is online affordable? (the honest follow-up)

The console also prints the cost comparison (from `cost_compare.py`):

```
C4, 8640 future windows           offline_periodic     online_adaptive
F1                                      0.890               0.983
train events                            17 full refits      8640 updates
worst-case latency / window          ~450 ms (refit stall)  ~12 ms
model size                              3.3 MB              16 KB
labelled windows retained to train      2880                0
total CPU over the stream               1.0x (baseline)     ~4.5x
```

**Talking points (state the trade-off honestly)**

- Online is **not cheaper in total CPU** — it does a little work every window,
  ~4.5× the aggregate of 17 RandomForest refits. That cost is real.
- But it wins where it operationally counts: **~38× lower worst-case latency**
  (a full refit *blocks* the detector for ~450 ms — and that stall lands exactly
  when a regime shifts and detection matters most), a **~214× smaller model**,
  and **zero retained training data** (periodic must keep a 2880-window labelled
  buffer) — *and* higher accuracy.
- Net: online converts a **bursty, stateful, blocking retrain pipeline** into a
  **smooth, bounded-latency, stateless stream** — higher steady CPU, but lower
  operational risk, smaller footprint, and better detection.

That is the empirical case that **operations matter**.

---

# Track B — Live demo (Docker Desktop Kubernetes)

## B0. One-command bootstrap (build + deploy everything)

`scripts/bootstrap.sh` automates the whole bring-up — it builds the three Java
services, builds their Docker images, deploys the observability stack + the two
gap fixes, and installs Chaos Mesh. Run it from the **repo root** (it locates the
root itself, so it works from anywhere):

```bash
bash scripts/bootstrap.sh          # Git Bash / WSL on Windows; or any bash shell
```

Prerequisites: `kubectl` pointing at a running cluster (`kubectl get nodes`
works), plus `mvn`, `docker`, and `bash` on PATH. If you use minikube, run
`minikube start` first — the script auto-detects it and targets its Docker
daemon. It uses `set -euo pipefail`, so it aborts on the first error (the
Chaos Mesh step is non-fatal).

When it finishes:

```bash
kubectl get pods -n on-demand-observability -w     # wait until all Running
cd aiops && bash ./scripts/run_live_experiment.sh 30    # run the live C1–C4 experiment
```

If you would rather bring the system up step by step (and view traces in Grafana
along the way), follow B1–B2 below instead.

## B1. Bring up the real system

Follow **`services/DEMO.md`** to build the three Spring Boot services, deploy the
`on-demand-observability` stack (otel-collector, Tempo, Loki, Prometheus,
Grafana), generate traffic, and view distributed traces in Grafana. That
establishes the live MELT telemetry this layer consumes.

Then apply the two gap fixes the aiops layer ships (documented in
`aiops/README.md`):

```bash
kubectl apply -f aiops/k8s/load-generator-fixed.yaml   # correct review query path
kubectl apply -f aiops/k8s/victoriametrics.yaml        # C4 historical baseline store
```

## B2. Inject faults and run the experiment against live telemetry

```bash
cd aiops
bash ./scripts/install_chaos_mesh.sh        # fault-injection engine
bash ./scripts/run_live_experiment.sh 30    # drives episodes, records ground-truth labels,
                                       # then pulls live PromQL/LogQL/TraceQL
```

The collectors (`collectors/telemetry.py`) issue the real queries — OTel-agent
metric names, Loki LogQL, Tempo TraceQL — and emit the **same `Window` schema**
the offline generator mirrors, so the entire RQ1–RQ4 analysis runs unchanged on
live data. Set `TF_LIVE=1` with the backend URLs to point the harness at your
cluster:

```bash
TF_LIVE=1 PROM_URL=http://localhost:9090 LOKI_URL=http://localhost:3100 \
  TEMPO_URL=http://localhost:3200 VM_URL=http://localhost:8428 \
  python -m ml.experiments.run_experiment --labels data/labels.csv
```

---

## Artifacts produced

| File | What it shows |
|------|---------------|
| `aiops/data/results/rq1_completeness.csv` | RQ1 detection vs C1–C4 |
| `aiops/data/results/rq2_algorithms.csv` | RQ2 algorithm comparison |
| `aiops/data/results/rq3_rca.csv` | RQ3 Top-k RCA, traces excluded vs included |
| `aiops/data/results/rq4_online_vs_offline.csv` | RQ4 per-regime detection, all 4 models |
| `aiops/data/results/rq4_timeline.csv` | RQ4 rolling F1 over the drifting stream |
| `aiops/data/results/rq4_cost.csv` | RQ4 cost: latency, model size, retained buffer |
| `aiops/data/results/*_summary.json` | machine-readable headlines |
| `aiops/data/results/figures/*.png` | publication-ready figures for the write-up |

## One-command reproduction

```bash
cd aiops && pip install -r requirements.txt
./scripts/run_offline.sh 200            # RQ1–RQ3
./scripts/run_online_offline.sh 320     # RQ4 detection + cost + figures
pytest tests/ -q                        # 7 passed
```

## Teardown (Track B)

```bash
kubectl delete namespace on-demand-observability
```
