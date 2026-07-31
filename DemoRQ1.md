# Demo — RQ1: Does telemetry completeness improve detection?

> **RQ1.** *Under non-stationary conditions, does the completeness of observability
> data — metrics-only, +logs, +traces, full MELT — improve the accuracy of anomaly
> detection, and which pillar contributes the largest marginal gain?*

This demo sweeps the **telemetry-completeness axis** (C1 → C4) with the detection
model, feature pipeline, fault schedule and seed all held fixed, so the only thing
changing is *how much telemetry the detector can see*.

| Config | Signals | Features | Represents |
|--------|---------|----------|------------|
| **C1** | Metrics only | 10 | Basic infrastructure monitoring |
| **C2** | +Logs | 14 | Intermediate observability |
| **C3** | +Traces | 18 | Full three-pillar observability |
| **C4** | Full MELT (+Events +history) | 23 | Advanced observability |

The configurations are **nested** — each a strict superset of the previous — so the
marginal value of a pillar is just the F1 difference between adjacent columns.

---

## Run it (no cluster needed)

```bash
cd aiops
pip install -r requirements.txt
bash scripts/run_offline.sh 200          # produces rq1_completeness.csv (+ rq2, rq4)
```

> Windows PowerShell: run from `aiops/` and call the module directly if `bash` is
> unavailable:
> `python -m ml.experiments.run_experiment --episodes 200 --out data/results`

The completeness result is written to **`aiops/data/results/rq1_completeness.csv`**.

---

## What you see

**Held-out reference (stationary slice) — `rq1_completeness.csv`:**

```
config  name                       n_features  precision  recall   f1      auc_roc
C1      Metrics-Only               10          0.942      0.855    0.896   0.978
C2      Metrics + Logs             14          0.952      0.882    0.915   0.985
C3      Metrics + Logs + Traces    18          0.987      0.982    0.985   0.998
C4      Full MELT                  23          0.989      0.982    0.986   0.998
```

**Operative result — the *drifted future stream*** (the deployable online detector,
from `rq3_online_vs_offline.csv`, the `online_adaptive` / `overall_future` rows):

```
config                       online_adaptive F1 (drifted)
C1 Metrics-Only                     0.813
C2 + Logs                           0.827
C3 + Traces                         0.974   ← +0.146 from traces
C4 Full MELT                        0.976
```

---

## Why this happens (talking points)

- **Detection F1 rises monotonically with completeness** on both the held-out slice
  (0.896 → 0.986) and the drifted stream (0.813 → 0.976). More observability genuinely
  raises the attainable ceiling.
- **Traces are the single most valuable pillar.** On the held-out slice the
  metrics→logs step adds +0.019 F1, but adding traces adds **+0.069** (0.915 → 0.985);
  on the *drifted* stream the trace increment is larger still at **+0.146**
  (0.827 → 0.974), dwarfing logs and events. Spans carry per-request, cross-service
  structure that aggregate metrics and unstructured logs cannot reconstruct.
- **Events + history (C4) add little on top of traces** (+0.001 / +0.002) — useful for
  RCA and rare OOM modes, but near-saturating for raw detection once traces are present.
- **The headline subtlety (sets up RQ3):** completeness only *pays off for a detector
  that keeps learning.* A frozen model given full MELT still collapses under drift
  (see DemoRQ3) — so RQ1's gain is real but **conditional on adaptation**.

---

## ⚠️ Discount the trace magnitude — the direction is what is claimed

Two properties of the generator act directly on the C2→C3 step, and both are **inputs,
not findings**:

1. **Error spans are emitted cleanly by faulty origin services** — a sharper
   discriminator than a real tracer's.
2. **They are held *outside* the drift transformation** (`_DRIFT_FIELDS` in
   `aiops/ml/drift.py`), so they survive the regime shifts that displace every latency
   and volume feature. This is largely *why* the trace increment is bigger under drift.

Those choices substantially **construct** the finding that traces are the decisive
pillar. The direction is credible on its own terms — traces alone carry cross-service
causal structure, and an error rate is more nearly scale-free than a latency percentile
— but the magnitudes (+0.146 against +0.069) follow *from the assumptions* and are not
a measurement of what tracing is worth. Only a live campaign settles that.

Nothing in RQ3 depends on it: the static model's collapse is flat across all four
configurations, indifferent to how the trace pillar is modelled.

## The live pilot — and what it does *not* cover

`aiops/ml/experiments/live_replay.py` scores a RandomForest on telemetry Prometheus
actually recorded during a 12-episode fault-injection campaign:

```
source config model  P      R      F1     AUC    n_test  prevalence  floor
live   C1     rf     0.700  0.700  0.700  0.967  135     0.078       0.144
```

F1 0.700 at nearly five times its own always-alarm floor, on **measured** telemetry, at
the configuration the synthetic campaign scores 0.896. Note the configuration column:
only the *metric* collector is time-parameterised, so C2–C4 would silently mix
present-moment values into a past window and are not attempted. **The pilot therefore
says nothing about the trace increment** — the exact magnitude this page discounts.

---

## Artifacts produced

| File | Shows |
|------|-------|
| `aiops/data/results/rq1_completeness.csv` | Held-out detection F1/precision/recall/AUC per C1–C4 |
| `aiops/data/results/rq3_online_vs_offline.csv` | Drifted-stream F1 per config (the operative RQ1 column) |
| `aiops/data/results_live/rq1_live_c1.csv` | The C1 live-replay pilot — the one measured result |
| `aiops/data/results/figures/*.png` | Completeness bars for the write-up |

**Bottom line:** richer telemetry helps, monotonically, and **distributed traces give
the largest marginal jump** — in *direction*, with the magnitude discounted as partly
constructed — but the benefit is only realised by a detector that adapts (RQ3).
