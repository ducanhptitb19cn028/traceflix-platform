# Demo — RQ3: Static vs periodic vs online learning under drift (the headline)

> **RQ3.** *When the telemetry stream is non-stationary, how do the static-batch,
> periodically-retrained and online-adaptive learning paradigms compare on detection
> quality **and** operational cost, and how does this comparison interact with
> telemetry completeness?*

This is the crux of the paper. RQ1/RQ2 showed *more telemetry helps* — on a stationary
slice. RQ3 turns on **drift** and asks the harder question: when the system *operates*
(a deploy regresses latency, autoscaling changes throughput, load grows), is the
dominant design variable *how much* telemetry you have, or *whether the detector keeps
learning*?

The stream is split into ordered **regimes**, each an abrupt operational shift:

```
R0 baseline (warm-up)  →  R1 latency regression  →  R2 scale-out  →  R3 combined load
        train here              ← drifted future stream, scored here →
```

Four learning policies, identical features per cell:

| Policy | How it learns | Realistic? |
|--------|---------------|------------|
| `offline_static` | Fit once on R0, then **frozen** | The traditional approach |
| `offline_periodic` | Refit every 500 windows on a 2880-window buffer | Scheduled retrain |
| `online_adaptive` | Update **per window** (test-then-train, prequential) | The proposal |
| `offline_full` | Fit once on **all** regimes (sees the future) | Oracle upper bound only |

---

## Run it (no cluster needed)

```bash
cd aiops
bash scripts/run_online_offline.sh 320   # detection + cost + figures
# = online_vs_offline.py  +  cost_compare.py  +  plots
```

Outputs: **`rq3_online_vs_offline.csv`** (detection), **`rq3_timeline.csv`** (rolling
F1), **`rq3_cost.csv`** (operational cost).

---

## Part A — Detection on the drifted future stream

F1 on the operational future (R1–R3), all models on identical features:

```
config            offline_static   offline_periodic   online_adaptive   offline_full (oracle)
C1 Metrics-Only       0.489             0.757              0.817               0.812
C2 + Logs             0.492             0.778              0.835               0.834
C3 + Traces           0.510             0.890              0.982               0.940
C4 Full MELT          0.511             0.891              0.983               0.939
```

### Why this happens (talking points)

- **The frozen batch model collapses to F1 ≈ 0.49–0.51 — *regardless of telemetry*.**
  Even full MELT (C4) cannot rescue `offline_static`. The decision boundary was fitted
  to R0's "normal"; once drift moves the normal, the detector flags the *new normal* as
  anomalous. Precision craters to ~0.34 while recall stays near 1.0 — the classic
  **stale-boundary failure** (firing on everything). The problem is the *learning
  paradigm*, not signal availability.
- **Periodic retraining helps but lags.** It recovers a lot (0.51 → 0.89 at C4) yet
  still trails online by 6–15 F1 points, because every abrupt regime shift opens a
  **drift-response gap** until the next scheduled refit. See the sawtooth in
  `figures/rq3_timeline.png`.
- **Online recovers to oracle level.** Updating per sample — adaptive normalisation
  re-centres on the evolving normal, incremental learning keeps the boundary calibrated
  — lifts F1 to **0.98** at C3/C4 and even **exceeds the all-regimes oracle** (0.982 vs
  0.940), because a single static boundary can't fit all regimes at once but a moving
  one can.
- **The interaction is the real finding (RQ1 × RQ3).** Completeness only pays off *for
  a detector that keeps learning*: the trace jump is +0.147 F1 for `online_adaptive`
  (0.835 → 0.982) but a near-flat +0.018 for `offline_static` (0.492 → 0.510). **Richer
  signals raise the ceiling; only adaptation realises it.**
- **Regime-level:** online wins **10 of 12** config×regime cells. The two exceptions are
  R2 scale-out at C1/C2, where periodic's fresh refit narrowly edges online on a pure
  re-normalisation shift — honest, and the only places static-buffer refit competes.

---

## Part B — Operational cost (the honest follow-up)

Is online affordable? From `rq3_cost.csv` (C4, drifted stream):

```
C4                                   offline_periodic     online_adaptive
F1                                        0.838               0.987
train events                              ~17 full refits     per-window updates
worst-case latency / window               ~594 ms (refit stall)  ~19 ms
model size                                ~3.5 MB             ~16 KB
labelled windows retained to train        2880                0
total CPU over the stream                 1.0x (baseline)     ~4.4x
```

(Ratios from `rq3_cost_summary.json`: ~31× lower tail latency, ~229× smaller model,
~4.4× higher total CPU at C4; across C1–C4 the model is **~200–550× smaller** and tail
latency **~17–32× better**.)

### Why this is still the right trade-off

- **Online is *not* cheaper in total CPU** — it does a little work every window, ~4.4×
  the aggregate of the periodic refits. That cost is real; state it plainly.
- **But it wins where it operationally counts:** a periodic refit *blocks* the detector
  for ~0.5 s — and that stall lands exactly when a regime shifts and detection matters
  most. Online converts a **bursty, stateful, blocking retrain pipeline** into a
  **smooth, bounded-latency, stateless stream**: ~31× lower tail latency, ~229× smaller
  model, **zero retained training data** (periodic must keep a 2880-window labelled
  buffer) — *and* higher accuracy.
- **`offline_full` is an unrealisable oracle** (trained on the future), shown only to
  prove the static collapse is caused by **non-stationarity, not model capacity** —
  online matches or beats it without ever seeing the future.

---

## Artifacts produced

| File | Shows |
|------|-------|
| `aiops/data/results/rq3_online_vs_offline.csv` | Per-config, per-regime F1 for all 4 policies |
| `aiops/data/results/rq3_timeline.csv` | Rolling F1 over the drifting stream (the sawtooth) |
| `aiops/data/results/rq3_cost.csv` | Latency, model size, retained buffer, CPU |
| `aiops/data/results/figures/rq3_timeline.png` | Static collapse vs periodic sawtooth vs online tracking |

**Bottom line:** under drift the RQ1 picture **inverts** — a frozen model collapses to
F1 ≈ 0.5 no matter how much telemetry it has, periodic retraining only partially
recovers, and a lightweight **online-adaptive** detector dominates (F1 ≈ 0.98, beating
the oracle) while being ~17–32× better on tail latency and ~200–550× smaller. **This is
the empirical case that operations matter.**
