# The Online ML Pipeline (RQ4)

The online ML pipeline is the **streaming, self-adapting anomaly detector** that
answers **RQ4** — *"does anomaly detection need to be online in a non-stationary
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

- `rq4_online_vs_offline.csv` — precision/recall/f1/auc per (config, segment, model)
- `rq4_timeline.csv` — block-wise rolling F1 over the stream, all models
- `rq4_summary.json` — headline numbers + drift/adaptation events

## The headline result

F1 on the *operational future* (regimes R1–R3), all models on identical features:

| config | offline_static | offline_periodic | online_adaptive | offline_full (oracle) |
|--------|:--:|:--:|:--:|:--:|
| C1 Metrics-Only | 0.489 | 0.757 | 0.817 | 0.812 |
| C2 + Logs | 0.492 | 0.778 | 0.835 | 0.834 |
| C3 + Traces | 0.510 | 0.890 | 0.982 | 0.940 |
| C4 Full MELT | 0.511 | 0.891 | 0.983 | 0.939 |

- **Static batch collapses to F1 ≈ 0.5 under drift even with full MELT**
  (precision ≈ 0.34 — false alarms on the new normal). Richer observability does
  not rescue it: the failure is the *learning paradigm*, not signal.
- **Scheduled retraining is not enough either.** `offline_periodic` recovers a
  lot of the loss but still trails online by 6–9 F1 points and never reaches the
  oracle — every regime shift opens a **drift-response gap** until the next
  refresh (the sawtooth in `rq4_timeline.png`), and each refresh is a full batch
  re-fit.
- **Online recovers to oracle level** (0.82 → 0.98) updating per sample, and
  *exceeds* the all-regime oracle under C3/C4 because tracking the evolving
  normal beats a single static split.

## Cost angle — `ml/experiments/cost_compare.py`

Measures the honest trade-off (C4, 8640 future windows):

| | offline_periodic | online_adaptive |
|--|:--:|:--:|
| F1 | 0.890 | 0.983 |
| train events | 17 full refits | 8640 updates |
| worst-case latency / window | ~450 ms (refit stall) | ~12 ms |
| p99 latency / window | 0.34 ms | 6.6 ms |
| model size | 3.3 MB | 16 KB |
| labelled windows retained | 2880 | 0 |
| total CPU over the stream | 1.0× (baseline) | ~4.5× |

Online is **not cheaper in total CPU** (~4.5× the aggregate compute), but it
wins on every dimension that matters operationally: ~38× lower worst-case
latency, ~214× smaller model, zero retained training data, *and* higher F1. It
converts a bursty, stateful, blocking retrain pipeline into a smooth,
bounded-latency, stateless stream.

## Run it

```bash
cd aiops
./scripts/run_online_offline.sh 320   # -> rq4_*.csv, rq4_cost.csv, figures
```

This runs `online_vs_offline` (detection) + `cost_compare` (cost) + `ml.eval.plots`.
