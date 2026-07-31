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

F1 on the operational future (R1–R3, **25,920 windows**), all models on identical
features, seed 42. Read every number against the **always-alarm floor of F1 = 0.292**
(prevalence 0.171 — flag every window and score that):

```
config            offline_static   offline_periodic   online_adaptive   offline_full (ref.)
C1 Metrics-Only       0.360             0.820              0.813               0.812
C2 + Logs             0.361             0.832              0.827               0.817
C3 + Traces           0.370             0.925              0.974               0.929
C4 Full MELT          0.371             0.926              0.976               0.927
```

### Why this happens (talking points)

- **The frozen batch model collapses to F1 ≈ 0.36 — *regardless of telemetry*.**
  Even full MELT (C4) cannot rescue `offline_static`; C1→C4 moves it by 0.010, less
  than its seed spread. The decision boundary was fitted to R0's "normal"; once drift
  moves the normal, the detector flags the *new normal* as anomalous. Precision craters
  to **0.22** while recall stays at 0.98–1.00 — the classic **stale-normal failure**
  (firing on everything). At 0.36 against a 0.292 floor it has nearly stopped
  discriminating. The problem is the *learning paradigm*, not signal availability.
- **Periodic retraining recovers most of the gap** (0.36 → 0.93 at C4) but is bursty:
  every abrupt regime shift opens a **drift-response gap** until the next scheduled
  refit. See the sawtooth in `figures/rq3_timeline.png`.
- **Online leads only once telemetry is rich — say this plainly.** At **C1/C2 the two
  adaptive policies are tied**: the −0.007 and −0.005 gaps are smaller than the
  five-seed spread of either policy, and over five seeds the difference is +0.003 the
  *other* way. At **C3/C4 online leads by ~0.05**, roughly nine standard deviations,
  and exceeds the all-regime reference (0.976 vs 0.927) because a single boundary is
  the wrong object however well fitted.
- **And you cannot fix the frozen model by moving the threshold.** Granting it the best
  cut-point obtainable *on the drifted stream itself* — an **oracle** that has seen the
  test labels, which no deployment can — recovers it only to **0.446 (C1)** and
  **0.552 (C3)**. The boundary is the wrong **shape**, not merely in the wrong
  **place**. This is the control that answers the strongest objection to the thesis.
- **The interaction is the real finding (RQ1 × RQ3).** Completeness only pays off *for
  a detector that keeps learning*: C1→C4 is **+0.163** for `online_adaptive` but
  **+0.010** for `offline_static`. **Richer signals raise the ceiling; only adaptation
  realises it.**
- **Regime-level:** online wins **8 of 12** config×regime cells. All four exceptions
  are under thin telemetry (C1/C2) in **R2 scale-out** and **R3 combined load**, where
  a fresh refit narrowly edges online on predominantly *virtual* drift. In **R1 latency
  regression** — *real* concept drift — online wins at **every** configuration, and it
  is there the static model is hurt most (F1 ≈ 0.30, its lowest).

---

## Part B — Operational cost (the honest follow-up)

Is online affordable? From `rq3_cost.csv` (C4, drifted stream):

```
C4                                   offline_periodic     online_adaptive
F1                                        0.9255              0.9755
train events                              51 full refits      25,920 updates
worst-case latency / window               581.6 ms (stall)    15.5 ms
p99 latency / window                        0.14 ms            8.5 ms
model size                                2287.7 KB           15.7 KB
labelled windows retained to train        2880                0
total CPU over the stream                 29.4 s (1.0x)     129.7 s (~4.4x)
```

(Ratios from `rq3_cost_summary.json`: 37× lower tail latency, 146× smaller model, 4.4×
higher total CPU at C4; over five seeds the model is **~120–390× smaller** and tail latency
**10–48× better**, at **4.1–4.8×** the aggregate CPU.)

### Why this is still the right trade-off

- **Online is *not* cheaper in total CPU** — it does a little work every window, 4.1–4.8×
  the aggregate of the periodic refits. That cost is real; state it plainly.
- **But it wins where it operationally counts:** a periodic refit *blocks* the detector
  for 580–880 ms — and that stall lands exactly when a regime shifts and detection
  matters most. Online converts a **bursty, stateful, blocking retrain pipeline** into a
  **smooth, bounded-latency, stateless stream**: 10–48× lower tail latency, ~120–390×
  smaller model, **zero retained training data** (periodic must keep a 2880-window
  labelled buffer) — *and* higher accuracy once traces are present.
- **State the caveat before someone else does:** the wall-clock columns are properties
  of one workstation and a single pass. The **structural** columns — 51 refits vs 25,920
  updates, 2880 retained windows vs 0, kilobytes vs megabytes — follow from the policy
  and reproduce exactly. The argument rests on those.
- **`offline_full` is an unrealisable reference** (trained on a split spanning the
  future), shown only to prove the static collapse is caused by **non-stationarity, not
  model capacity** — online matches or beats it without ever seeing the future.

---

## Part C — How far must the baseline move? (the sweep)

The obvious objection to Part A: the drift multipliers were set comparably to the fault
signatures themselves (R3 moves p99 latency 2.2×; a `latency_spike` fault moves it
2.3×). A boundary fitted on R0 *must* fail there — so the collapse is entailed by the
parameterisation rather than measured. One operating point cannot separate "drift
defeats frozen detectors" from "we set the drift equal to the fault".

```bash
python -u -m ml.experiments.drift_sweep --episodes 320 --configs C1,C4 --out data/results_drift_sweep
```

`scaled_regime_factors(α)` interpolates every multiplier toward 1, preserving which
fields each regime moves and in what proportion. Labels are assigned *before* the
factors are applied and the generator draws the same random numbers either way, so the
**fault schedule is identical at every α** — only the healthy baseline moves.

```
       R3 shift   C1: static periodic online   C4: static periodic online
a=0.00   1.00x       0.890    0.885    0.815      0.989    0.985    0.977
a=0.15   1.15x       0.830    0.880    0.815      0.933    0.982    0.977
a=0.30   1.29x       0.682    0.867    0.815      0.769    0.974    0.977
a=0.50   1.49x       0.511    0.852    0.814      0.546    0.954    0.976
a=1.00   1.97x       0.360    0.820    0.813      0.370    0.925    0.976   <- Part A
a=1.30   2.26x       0.333    0.813    0.813      0.341    0.921    0.976
```

- **Adaptation is not free.** At α = 0 (stationary) the frozen model is the *best* of
  the three and the online detector the *worst* — by 0.075 at C1. Continual updating is
  worth having because the stream drifts, not because it is continual.
- **The failure is gradual.** Static C4 falls 0.989 → 0.370; by a 1.29× shift a detector
  has lost a fifth of its F1 while still looking serviceable.
- **The threshold is a number.** Refitting starts to pay at **1.15×**; the frozen model
  drops below twice the always-alarm floor between **1.29× and 1.49×**. Part A sits at
  1.97×, well beyond — which is exactly why its collapse cannot be read as a measurement.
- **The adaptive policies differ in kind.** Online C4 varies by 0.001 across the whole
  sweep; periodic decays 0.985 → 0.921, exposed to whatever accumulates between refits.
  At C1 periodic leads or ties at *every* amplitude. **Neither dominates.**

α = 1 reproduces Part A to four decimals — the sweep's own regression check.

---

## Part D — What is the adaptive machinery actually worth?

Two experiments build a ladder underneath the online detector, so its margin is
attributed rather than assumed.

```bash
python -u -m ml.experiments.baseline_streaming --episodes 320 --out data/results_baselines_scaled
python -u -m ml.experiments.ablate_online      --episodes 320 --out data/results_ablation
```

**Normalisation carries the policy.** Three canonical linear learners
(passive-aggressive, perceptron, plain SGD) scored prequentially on the identical
stream:

```
arm                              C1      C2      C3      C4
raw (unnormalised)             0.302-0.308 at EVERY configuration -- flat
+ running StandardScaler        0.760   0.790   0.971   0.970   (passive-aggressive)
                                0.796   0.815   0.966   0.967   (SGD-logistic)
online_adaptive (full detector) 0.813   0.827   0.974   0.976
```

Unnormalised they sit barely above the 0.292 floor and do not respond to telemetry at
all. Standardise the *same* learner and it tracks completeness the way the detector does
(plain SGD +0.170 from C1→C4, against the detector's +0.163).

**The detector's own mechanisms are close to free.** Switching them off in turn:
champion re-election is worth **+0.013 (C1)**, +0.005 (C2), **nothing** at C3/C4; the
drift monitor is worth **nothing anywhere** (its adapt events are diagnostic, not
load-bearing). The whole remaining margin over the best off-the-shelf scaled arm is
**+0.017 at C1** and **+0.003 at C3** — the latter inside the seed spread.

**Say the read-out honestly: a standardised incremental learner is a close substitute
for the whole detector.** That does not weaken RQ3, because the clean, unconfounded
contrast was always *static vs periodic within one Random-Forest family* — but it does
bound what the extra machinery may be credited with.

---

## Artifacts produced

| File | Shows |
|------|-------|
| `aiops/data/results/rq3_online_vs_offline.csv` | Per-config, per-regime F1 for all 4 policies |
| `aiops/data/results/rq3_timeline.csv` | Rolling F1 over the drifting stream (the sawtooth) |
| `aiops/data/results/rq3_cost.csv` | Latency, model size, retained buffer, CPU |
| `aiops/data/results/rq3_baselines.csv`, `rq3_seeds.csv` | Trivial floor, oracle re-threshold, five-seed variance |
| `aiops/data/results_drift_sweep/rq3_drift_sweep.csv` | F1 against operating-point shift (Part C) |
| `aiops/data/results_baselines_scaled/`, `results_ablation/` | Streaming baselines and the component ablation (Part D) |
| `aiops/data/results/figures/rq3_timeline.png` | Static collapse vs periodic sawtooth vs online tracking |

**Bottom line:** under drift the RQ1 picture **inverts** — a frozen model collapses to
F1 ≈ 0.36 (barely above a 0.292 floor) no matter how much telemetry it has, an oracle
re-threshold recovers it only to 0.45–0.55, and periodic retraining recovers most of
the rest at a bursty, buffer-hoarding cost. The online detector matches periodic under
thin telemetry and leads by ~0.05 once traces are present, at 10–48× better tail
latency and ~120–390× smaller. **All of that holds inside a measured band** — past a
1.15× baseline shift, and not on a stationary stream, where the frozen model wins.
**This is the empirical case that operations matter, stated with its limits attached.**
