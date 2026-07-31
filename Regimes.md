# Drift Regimes — what they are and why they exist

> **Source of truth:** `aiops/ml/drift.py` (`REGIME_FACTORS`, `REGIME_NAMES`,
> `apply_regime`, `generate_drifting_run`). This document explains that code and how
> the regimes are used by RQ3 (the learning-paradigm-under-drift experiment).

---

## The idea in one paragraph

A *stationary* stream (the held-out reference used by RQ1/RQ2/RQ4) keeps the normal
operating point fixed, so a model trained once stays calibrated forever. Real
cloud-native systems are **not** stationary: deployments, autoscaling and traffic
growth continuously move the telemetry baseline. **A regime is a controlled
operational shift of that baseline.** The stream is cut into ordered regimes
`R0 → R1 → R2 → R3`; each regime multiplies the *operating-point* telemetry fields by
a regime-specific factor. Crucially the multiplier is applied **identically to normal
and faulty windows**, so it moves the feature distribution *without changing the
ground-truth label* — a fault is still a fault, it just now rides on a higher
baseline. That is exactly the condition (**concept drift**) under which a frozen
detector silently decays, and the reason RQ3 exists.

---

## The four regimes

The offline models train on **R0**; **R1–R3** are the *operational future* they never
saw and on which every learner is scored prequentially.

| Regime | Name | Operational story | What moves (multipliers from `REGIME_FACTORS`) | Drift type |
|--------|------|-------------------|-----------------------------------------------|------------|
| **R0** | Baseline | The deployment the static/periodic models are fit on, and the warm-up the online model is calibrated on. | *nothing* — native operating point | — (reference) |
| **R1** | Latency regression | A release regresses latency; CPU and GC climb. | `p50_latency ×1.8`, `p99_latency ×1.9`, `cpu ×1.5`, `threads ×1.3`, `gc_pause ×1.4`, `mean_span_ms ×1.8`, `p99_span_ms ×1.9` | **Real** concept drift |
| **R2** | Scale-out | Autoscaling + traffic growth: throughput and log/trace volume double, memory grows. | `req_rate ×2.0`, `log_volume ×2.0`, `request_logs ×2.0`, `warn_logs ×1.6`, `trace_count ×2.0`, `mem ×1.6`, `mem_baseline_1h ×1.6`, plus mild latency (`p50 ×1.3`, `p99 ×1.4`, spans ×1.3–1.4) | predominantly **virtual** drift |
| **R3** | Combined load | A traffic surge superimposed on the previous shifts — the hardest, most-drifted regime; *everything* has moved at once. | latency ×2.0–2.2, `cpu ×1.8`, `threads ×1.5`, `gc_pause ×1.7`, `mem ×1.9`, `req_rate ×2.2`, `log_volume ×2.2`, `trace_count ×2.2`, spans ×2.0–2.2, etc. | **both** (real + virtual) |

The factors are **cumulative in spirit** (each later regime represents a system that
has drifted further from R0), but in code each regime applies its *own* absolute
multiplier dictionary to the R0-native field values — they are not chained.

---

## What drifts, and what deliberately does *not*

`apply_regime` scales only the fields listed in `_DRIFT_FIELDS` — the
**operating-point** signals:

- **metrics:** `req_rate`, `p50_latency`, `p99_latency`, `cpu`, `mem`, `gc_pause`,
  `threads`, `mem_baseline_1h`
- **logs:** `log_volume`, `warn_logs`, `request_logs`
- **traces:** `trace_count`, `mean_span_ms`, `p99_span_ms`

**Left on their native scale on purpose:** error-rate signals and the error-span
count (the trace RCA feature). An error is an error regardless of how much traffic
flows. This asymmetry is the mechanism behind a key result: because the *failure*
signals don't drift while the *volume/latency* signals do, **trace-derived signals
are comparatively drift-robust while metric-threshold detection is not** — which is
why traces matter even more under drift (RQ1) and why the online normaliser can
absorb the drift it does see (RQ3).

> ⚠️ **This exemption is an input, not a finding.** It is largely *why* traces look
> drift-robust, and the RQ1 trace magnitude is discounted accordingly. Whether real
> error signals hold their scale across regimes is exactly what a live campaign
> (`TF_LIVE=1`) would settle. Note also that the RQ2 localisation experiment runs on
> a *separate* generator (`generate_rca_run`, errors propagating up the call path) —
> see [`DemoRQ2.md`](DemoRQ2.md).

---

## Virtual vs. real drift — why the distinction drives the results

The streaming-learning literature splits drift into two kinds, and the regimes are
designed to induce both so that no single coping strategy suffices alone:

- **Virtual drift** — the feature distribution `P(x)` moves but the meaning of
  "anomalous" (`P(y|x)`) does **not**. *Scale-out (R2)* is the canonical case: more
  replicas shift per-pod resource baselines, but a fault is still a fault. A **periodic
  refit on recent data** restores the boundary here, which is exactly why periodic
  retraining narrowly edges the online model in the four thin-telemetry cells (C1/C2 ×
  R2/R3) — the only cells it wins.
- **Real (concept) drift** — `P(y|x)` itself changes: a latency level that *was*
  anomalous becomes the new normal. *Latency regression (R1)* is the canonical case,
  and it is where the static model is hurt most (F1 ≈ 0.30, its lowest, against
  0.49–0.60 in the scale-out regime it can partly survive) because the decision
  *boundary*, not merely the input scaling, is now wrong. The online model wins R1 at
  **every** configuration: **the static deficit is widest exactly where drift is
  conceptual rather than distributional.**
- **R3** superimposes both. Only the online detector — whose exponentially-weighted
  normaliser re-centres every feature continuously while incremental fitting tracks the
  conceptual change — neutralises the virtual component *and* the real one together.

The regime transitions are **abrupt** (a step change at each boundary), which is the
hard case for periodic retraining: the lag between drift onset and the next scheduled
refit is maximally exposed (the sawtooth in `rq3_timeline`).

---

## How the regimes are generated and scored

`generate_drifting_run(n_episodes=320, windows_per_episode=12, n_regimes=4, seed=42)`:

- Episodes are split evenly across regimes: `regime = min(n_regimes-1, int(ei/per))`
  with `per = n_episodes / n_regimes` → **80 episodes per regime**.
- Each window is emitted for all **9** services of the mesh, so totals are:

| Quantity | Count |
|----------|-------|
| Episodes | 320 (80 per regime) |
| Windows per episode | 12 × 9 services = 108 |
| Total windows | **34,560** |
| R0 warm-up windows | **8,640** |
| R1–R3 future (scored) windows | **25,920** |
| Anomaly prevalence on the scored stream | 0.171 (→ always-alarm floor F1 = 0.292) |

- Within an episode, ~45% of episodes are pure `normal`; the rest pick a fault and a
  root-cause service, and downstream callers exhibit secondary `latency_spike`
  (realistic propagation for RCA). Then `apply_regime` scales the operating-point
  fields by that episode's regime factor — **labels untouched**.
- **Fair evaluation:** offline models are fit on the R0 prefix; the online model is
  warmed (test-then-train, unscored) over the same R0 prefix; all are then scored on
  the identical post-R0 stream (R1–R3). This is what licenses attributing any
  reversal of conclusions to *drift*, not to a change of data, model, or split.

---

## The amplitude is a free parameter — so it is swept

`REGIME_FACTORS` moves p99 latency by 2.2× and CPU by 1.8× under R3. `_FAULT_SHIFT` in
`collectors/telemetry.py` moves p99 by 2.3× for `latency_spike` and CPU by 2.4× for
`cpu_saturation`. **The drift amplitude and the fault amplitude are the same size.**
Under R3 the healthy operating point therefore lands on top of the fault signature the
static model was fit to detect, so its collapse to F1 ≈ 0.36 is *entailed by that
choice* rather than measured. One operating point cannot separate "drift defeats frozen
detectors" from "we set the drift as large as the fault".

`scaled_regime_factors(alpha)` (same module) answers it by turning the point into a
curve. It interpolates every multiplier toward 1 —

```python
{k: 1.0 + alpha * (v - 1.0) for k, v in regime.items()}
```

— so *which* fields a regime moves and *in what proportion* is preserved, and only how
far varies. `alpha=0` is a stationary stream, `alpha=1` reproduces the reported
campaign, `alpha>1` extrapolates. **Labels are assigned before the factors are applied
and the generator draws the same random numbers either way, so the fault schedule is
byte-identical at every alpha** — the only thing that varies across the sweep is how far
the healthy baseline has moved. `mean_amplitude()` reports the geometric-mean multiplier
of R3, so the x-axis reads as an *operating-point shift* rather than an abstract scale.

```bash
python -u -m ml.experiments.drift_sweep --episodes 320 --configs C1,C4 \
  --out data/results_drift_sweep
```

What the curve says (C4): refitting begins to pay at a **1.15×** shift, the frozen model
falls below twice the always-alarm floor between **1.29× and 1.49×**, and the reported
campaign sits at **1.97×**. Below that band the frozen model is the **best** of the
three (0.989 at α = 0) and the online detector the **worst** — *adaptation is not free,
and the regimes are not a demonstration that it always pays.* Full table:
[`DemoRQ3.md`](DemoRQ3.md) Part C and
[`aiops/docs/RQ3_RESULTS_ONLINE_VS_OFFLINE.md`](aiops/docs/RQ3_RESULTS_ONLINE_VS_OFFLINE.md) §8.

## Where the regimes show up downstream

- **`rq3_online_vs_offline.csv`** — per-config, per-regime F1 for static / periodic /
  online / oracle. The per-regime breakdown (paper Table `tab:rq3-regime`) is what
  reveals the R2-scale-out exception.
- **`rq3_timeline.csv`** — rolling F1 tagged by regime, showing the static collapse,
  the periodic sawtooth, and the online tracking line across `R0→R3`.
- **`rq3_drift_sweep.csv`** (in `aiops/data/results_drift_sweep/`) — the same three
  policies against the *rescaled* regime factors, plus the resulting R3 amplitude at
  each sweep point.
- **Paper:** `\S sec:method-regimes` (definitions), `\S sec:prob-drift` (virtual vs.
  real formalism), and the design figure `fig:design` (the `R0→R3` drift timeline).

**Bottom line:** the regimes are not faults — they are *new normals*. They exist to
manufacture concept drift in a controlled, attributable way so the experiment can
measure the one thing a stationary single-snapshot evaluation cannot: whether a
detector keeps working after the system it watches has moved on.
