# The Online ML Pipeline (RQ3)

The online ML pipeline is the **streaming, self-adapting anomaly detector** that
answers **RQ3** — *"does anomaly detection need to be online in a non-stationary
system?"* Its purpose is to contrast a continuously-adapting detector against
traditional frozen-batch detection on a telemetry stream whose definition of
"normal" keeps drifting.

## The setup it runs against — drift (`ml/drift.py`)

The stream is split into 4 operational **regimes** `R0 → R3` that mimic
*operations*, not faults:

| Regime | Meaning |
|--------|---------|
| **R0** | Baseline — what the offline model trains on |
| **R1** | A release regresses latency; CPU/GC climb |
| **R2** | Scale-out: throughput and log/trace volume double, memory grows |
| **R3** | Combined heavy load (everything has moved) |

Each regime multiplies the *operating-point* fields (latency, CPU, volume,
memory) **identically for normal and faulty windows**, so the feature
distribution shifts **without changing the ground-truth label**. Error-rate and
originating-error-span signals are deliberately left on their native scale — an
error is an error regardless of traffic — which is why trace-based RCA stays
drift-robust while metric-threshold detection decays.

`R0` is the regime the offline model is trained on; `R1..R3` are the operational
future it never saw.

## The online model — `ml/models/online.py::OnlineModel`

A prequential (test-then-train) binary detector with four adaptation mechanisms:

1. **Adaptive normalisation** (`_EWStandardizer`) — an exponentially-weighted
   running mean/variance that tracks *today's* normal operating point. It is
   updated **only from windows revealed to be normal** (`if y == 0`), so a fault
   always stays a large z-score deviation in any regime. A 150-window burn-in
   (`warm`) sets the initial feature scale so the first z-scores are `O(1)` and
   the constant-rate SGD doesn't diverge on raw JVM-memory magnitudes (~1e8).

2. **Incremental learning** — `SGDClassifier(loss="log_loss")` trained per
   sample with `partial_fit` under the prequential protocol: predict the window,
   then learn from its revealed label.

3. **Dynamic parameter optimisation** — a pool of 6 candidate learners
   (3 learning rates × 2 regularisations) runs in parallel. The **champion**
   serving predictions is re-elected each step by recent windowed **F1** (not
   accuracy — under class imbalance accuracy would reward a trivial always-normal
   predictor), so the effective hyper-parameters re-tune themselves as the data
   pattern changes (online model selection / bandit).

4. **Drift-triggered acceleration** (`_DriftDetector`) — a two-window
   prequential-error monitor. When the recent error jumps above the reference by
   more than `delta`, the model enters a 60-step "boost" that raises the
   normaliser decay 8× to re-centre quickly on the new regime. Drift firings are
   logged in `adapt_events`.

**Label availability:** the protocol assumes ground-truth arrives with delay —
realistic here via chaos-engineering fault injection, and in production via
operator-confirmed/dismissed alerts. Reference: Gama et al. (2014), *"A survey
on concept drift adaptation"*.

## The experiment harness — `ml/experiments/online_vs_offline.py`

Scores four paradigms on **identical features** (so the only variable is the
*learning paradigm*, not signal availability). All are warmed/fit on `R0` then
scored on the `R1–R3` future:

| Paradigm | What it is |
|----------|-----------|
| `offline_static` | RandomForest fit once on R0, then frozen — the traditional "train a snapshot, ship it" deployment |
| `offline_periodic` | RandomForest refit every `--retrain-every` (500) windows on the last `--train-window` (~2880) labelled windows — the realistic production compromise |
| `online_adaptive` | The `OnlineModel` — updates per sample, no batch re-fit |
| `offline_full` | RF on a random split across *all* regimes — an unrealistic oracle ceiling, included only to isolate drift (not model capacity) as the cause of decay |

**Outputs** (to `--out`, default `data/results`):

- `rq3_online_vs_offline.csv` — precision/recall/f1/auc per (config, segment, model)
- `rq3_timeline.csv` — block-wise rolling F1 over the stream, all models
- `rq3_summary.json` — headline numbers + drift/adaptation events

## The headline result

F1 on the *operational future* (regimes R1–R3, **25,920 windows**), all models on
identical features, seed 42. Read against the **always-alarm floor of F1 = 0.292**
(prevalence 0.171 — flag every window):

| config | offline_static | offline_periodic | online_adaptive | offline_full (ref.) |
|--------|:--:|:--:|:--:|:--:|
| C1 Metrics-Only | 0.360 | 0.820 | 0.813 | 0.812 |
| C2 + Logs | 0.361 | 0.832 | 0.827 | 0.817 |
| C3 + Traces | 0.370 | 0.925 | **0.974** | 0.929 |
| C4 Full MELT | 0.371 | 0.926 | **0.976** | 0.927 |

- **Static batch collapses to F1 ≈ 0.36 under drift even with full MELT**
  (precision ≈ 0.22 — it fires on the new normal), barely above the trivial
  floor. Richer observability does not rescue it: the failure is the *learning
  paradigm*, not signal availability.
- **Scheduled retraining recovers most of the gap** (0.36 → 0.82–0.93) but is
  bursty: every regime shift opens a **drift-response gap** until the next
  refresh (the sawtooth in `rq3_timeline.png`), and each refresh is a full batch
  re-fit that blocks the detector.
- **Online leads only once telemetry is rich.** At **C1/C2 the two adaptive
  policies are tied** — the −0.007/−0.005 gaps are smaller than the five-seed
  spread of either. At C3/C4 online leads by ~0.05 (roughly nine standard
  deviations) and *exceeds* the all-regime reference, because tracking the
  evolving normal beats fitting one boundary across every regime.
- **And you cannot fix the frozen model by moving the threshold.** An *oracle*
  cut-point chosen on the drifted stream itself — knowing the test labels, which no
  deployment can — recovers it only to 0.44–0.55. The boundary is the wrong
  **shape**, not merely in the wrong **place**.

## Cost angle — `ml/experiments/cost_compare.py`

Measures the honest trade-off (C4, 25,920 future windows):

| | offline_periodic | online_adaptive |
|--|:--:|:--:|
| F1 | 0.9255 | 0.9755 |
| train events | 51 full refits | 25,920 updates |
| worst-case latency / window | 581.6 ms (refit stall) | 15.5 ms |
| p99 latency / window | 0.14 ms | 8.5 ms |
| model size | 2287.7 KB | 15.7 KB |
| labelled windows retained | 2880 | 0 |
| total CPU over the stream | 29.4 s (1.0×) | 129.7 s (~4.4×) |

Online is **not cheaper in total CPU** (4.1–4.8× the aggregate across C1–C4), but it
wins on every dimension that matters operationally: **10–48× lower worst-case
latency**, a **~120–390× smaller model**, zero retained training data, *and* higher
F1 once traces are present. It converts a bursty, stateful, blocking retrain pipeline
into a smooth, bounded-latency, stateless stream.

> Wall-clock columns are properties of one workstation and a single pass; the
> structural columns (refit count, footprint, retained windows) follow from the policy
> and reproduce exactly. The argument rests on those and on the order-of-magnitude
> tail gap, not on any particular millisecond.

## What the machinery is actually worth

The detector's own mechanisms were ablated rather than assumed
(`ml/experiments/baseline_streaming.py`, `ablate_online.py`):

- **Adaptive normalisation carries the policy.** Three canonical linear learners
  (passive-aggressive, perceptron, plain SGD) reach F1 **0.302–0.308 unnormalised at
  every configuration**; put a running standardiser in front of the *same* learner and
  they reach **0.760–0.796 at C1** and **0.959–0.971 at C3**.
- **The pool and the monitor are close to free.** Champion re-election is worth +0.013
  (C1), +0.005 (C2), nothing at C3/C4; the drift monitor is worth nothing anywhere, so
  its `adapt_events` are diagnostic rather than load-bearing.
- The full detector's remaining margin over the best off-the-shelf scaled arm is
  **+0.017 at C1 and +0.003 at C3** — the latter inside the seed spread. A standardised
  incremental learner is a close substitute for the whole thing.

## How far must the baseline move?

The headline is measured at one drift amplitude, and that amplitude is comparable to
the fault signatures themselves — so a frozen boundary *must* fail at it.
`ml/experiments/drift_sweep.py` rescales every regime multiplier toward 1 with
`scaled_regime_factors(α)`, holding the fault schedule byte-identical, and reports the
curve: refitting begins to pay at a **1.15×** operating-point shift, the frozen model
falls below twice the always-alarm floor between **1.29× and 1.49×**, and **below that
band the frozen model is the best of the three** while the online detector is the
worst. The reported campaign sits at 1.97×.

## Run it

```bash
# from the repo root
make rq3 cost plots       # detection + cost + figures  (minutes)
make controls             # = seeds + sweep + baselines + ablation  (hours)

# or from aiops/, without make
./scripts/run_online_offline.sh 320   # -> rq3_*.csv, rq3_cost.csv, figures
python -m ml.experiments.baselines_and_seeds --seeds 42,43,44,45,46 --configs C1,C2,C3,C4
python -u -m ml.experiments.drift_sweep --episodes 320 --configs C1,C4 --out data/results_drift_sweep
python -u -m ml.experiments.baseline_streaming --episodes 320 --out data/results_baselines_scaled
python -u -m ml.experiments.ablate_online --episodes 320 --out data/results_ablation
```

`run_online_offline.sh` runs `online_vs_offline` (detection) + `cost_compare` (cost) +
`ml.eval.plots`. Each control writes to its **own** directory, so none of them can
overwrite the committed artefacts in `data/results/`. Full result catalogue: [`../data/results/README.md`](../data/results/README.md);
full analysis: [`RQ3_RESULTS_ONLINE_VS_OFFLINE.md`](RQ3_RESULTS_ONLINE_VS_OFFLINE.md).
