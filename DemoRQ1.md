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
C1      Metrics-Only               10          0.951      0.866    0.906   0.974
C2      Metrics + Logs             14          0.960      0.908    0.933   0.985
C3      Metrics + Logs + Traces    18          0.985      0.992    0.988   0.999
C4      Full MELT                  23          0.994      0.993    0.994   0.999
```

**Operative result — the *drifted future stream*** (the deployable online detector,
from `rq3_online_vs_offline.csv`, the `online_adaptive` / `overall_future` rows):

```
config                       online_adaptive F1 (drifted)
C1 Metrics-Only                     0.817
C2 + Logs                           0.835
C3 + Traces                         0.982   ← +0.147 from traces
C4 Full MELT                        0.983
```

---

## Why this happens (talking points)

- **Detection F1 rises monotonically with completeness** on both the held-out slice
  (0.906 → 0.994) and the drifted stream (0.817 → 0.983). More observability genuinely
  raises the attainable ceiling.
- **Traces are the single most valuable pillar.** On the held-out slice the
  metrics→logs step adds +0.027 F1, but adding traces adds **+0.055** (0.933 → 0.988);
  on the *drifted* stream the trace increment is even more dramatic at **+0.147**
  (0.835 → 0.982), dwarfing logs and events. Spans carry per-request, cross-service
  structure that aggregate metrics and unstructured logs cannot reconstruct.
- **Events + history (C4) add little on top of traces** (+0.006 / +0.001) — useful for
  RCA and rare OOM modes, but near-saturating for raw detection once traces are present.
- **The headline subtlety (sets up RQ3):** completeness only *pays off for a detector
  that keeps learning.* A frozen model given full MELT still collapses under drift
  (see DemoRQ3) — so RQ1's gain is real but **conditional on adaptation**.

---

## Artifacts produced

| File | Shows |
|------|-------|
| `aiops/data/results/rq1_completeness.csv` | Held-out detection F1/precision/recall/AUC per C1–C4 |
| `aiops/data/results/rq3_online_vs_offline.csv` | Drifted-stream F1 per config (the operative RQ1 column) |
| `aiops/data/results/figures/*.png` | Completeness bars for the write-up |

**Bottom line:** richer telemetry helps, monotonically, and **distributed traces give
the largest marginal jump** — but the benefit is only realised by a detector that
adapts (RQ3).
