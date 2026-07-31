# Learning policies — `offline_static`, `offline_periodic`, `online_adaptive`

> **Source of truth:** `aiops/ml/experiments/online_vs_offline.py` (the four learners
> and the scoring protocol) and `aiops/ml/models/online.py` (the online detector).
> These are the **learning-paradigm axis** of the study — RQ3 in the paper. They are
> compared on the drifting stream defined in [`Regimes.md`](Regimes.md).

---

## The idea in one paragraph

All four learners consume the **identical feature vectors** for a given telemetry
configuration, so the *only* variable is **how, and how often, the model updates** as
the stream drifts (`online_vs_offline.py:11-13`). Detection quality is therefore
attributable to the learning paradigm, not to signal availability. Three of the four
are realistic deployments; the fourth (`offline_full`) is an unrealisable oracle kept
only as a ceiling. The headline result: under drift the *paradigm* — not the telemetry
— decides whether the detector works.

> **Naming note.** The code and its docstrings still say **"RQ4"** (it predates the RQ
> reorder), but the output files are named `rq3_*` and this *is* the paper's **RQ3**.
> `online_vs_offline.py` → `rq3_online_vs_offline.csv`, `rq3_timeline.csv`,
> `rq3_summary.json`.

---

## The fair evaluation protocol (what makes the comparison honest)

Every learner is given the same starting knowledge and scored on the same future
(`online_vs_offline.py:36-38, 150-155`):

- **Train/warm region = `R0`** (the baseline regime, `n_warm = 8,640` windows). The
  offline models are *fit* here; the online model is *warmed* here prequentially
  (test-then-train, **unscored**).
- **Scored region = `R1–R3`** (the drifted future, `25,920` windows) — the operational
  future no offline model ever trained on. Anomaly prevalence there is **0.171**, so an
  *always-alarm* detector scores **F1 = 0.292**: the floor every number below is read
  against.

Because the warm-up is unscored and identical for all, any divergence on `R1–R3` is the
paradigm's doing.

---

## The four learners at a glance

| Learner | Family | How it learns | Realistic? | Code |
|---------|--------|---------------|------------|------|
| `offline_static` | Random Forest | Fit once on `R0`, then **frozen** | Traditional "train a snapshot, ship it" | `online_vs_offline.py:157-161` |
| `offline_periodic` | Random Forest | **Refit every 500 windows** on the most recent 2,880 labelled windows | The common production compromise | `online_vs_offline.py:95-117` |
| `online_adaptive` | SGD logistic + adaptive norm + bandit | **Per-window** `partial_fit`, prequential | The proposal | `models/online.py` |
| `offline_full` | Random Forest | Fit once on a random split spanning **all** regimes | **Oracle only** (sees the future) | `online_vs_offline.py:172-178` |

---

## `offline_static` — fit once on R0, then frozen

```python
static = BaselineModel("rf", "binary").fit(Xtr, ytr)   # Xtr,ytr = R0 only
s_pred = static.predict(Xte)                            # predict all of R1..R3
```
(`online_vs_offline.py:157-161`)

**What it is.** The traditional AIOps deployment: train a Random Forest on a historical
snapshot (`R0`), freeze it, and serve it forever.

**Why it collapses under drift.** The decision boundary is calibrated to `R0`'s
"normal." Once a regime shift moves the normal (latency regression, scale-out — see
`Regimes.md`), the *new* normal falls into the region the frozen boundary labels
anomalous. The model keeps firing on healthy traffic. This is the **stale-normal
signature**: recall stays near-perfect (it still catches real faults) while **precision
collapses** (everything healthy is flagged too). No amount of extra telemetry fixes it,
because the failure is the boundary's *location*, not the features' informativeness.

---

## `offline_periodic` — scheduled batch retrain

```python
model = BaselineModel("rf", "binary").fit(X[:n_warm], y[:n_warm])   # initial R0 fit
i = n_warm
while i < n:
    j = min(n, i + retrain_every)          # serve the current model for a segment …
    preds[i:j] = model.predict(X[i:j])
    if j < n:                              # … then refit on the most recent window
        lo = max(0, j - train_window)
        model = BaselineModel("rf", "binary").fit(X[lo:j], y[lo:j])
    i = j
```
(`online_vs_offline.py:95-117`)

**What it is.** The same Random Forest on a **scheduled-retrain** pipeline. It predicts
a whole segment with the currently deployed model (test), then re-fits from scratch on
the most recent `train_window` labelled windows (train) — prequential at *segment*
granularity.

**Parameters** (`online_vs_offline.py:229-233`, paper Appendix B):

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `--retrain-every` (`τ`) | 500 windows | Refresh cadence → **51 refits** over the 25,920-window future stream |
| `--train-window` (`B`) | 2,880 windows | Sliding labelled buffer to refit on (≈ one regime) |

**The trade-off it exposes.** It *does* track drift, but only **at its cadence**. Every
abrupt regime shift opens a **drift-response gap** — a degraded window that lasts until
the next scheduled refit absorbs enough new-normal (the sawtooth in `rq3_timeline`).
Two further costs are structural: each refresh is a **full batch re-fit** (a bursty
latency spike that lands exactly when a regime shifts), and it must **retain a 2,880-window
labelled buffer** (a memory and data-governance liability).

---

## `online_adaptive` — prequential, self-adapting (`OnlineModel`)

The proposal. It **never re-fits offline**; it adapts continuously, per window, at
`O(d)` cost. The driver loop is plain prequential test-then-train
(`online_vs_offline.py:83-92`); all the machinery is in `models/online.py`. Four
mechanisms work together (`models/online.py:11-35`):

### 1. Adaptive normalisation — `_EWStandardizer` (`online.py:49-81`)
An exponentially-weighted running mean/variance tracks the **current** normal operating
point; each feature is served as a z-score against *today's* normal, not a stale
baseline. Two details matter:
- It is updated **only from windows revealed to be normal** (`y == 0`,
  `online.py:197-199`), so a fault — a large deviation — is never normalised away.
- A **burn-in** of 150 windows seeds the scale before any SGD step
  (`online.py:58-65, 176-181`); without it, large-magnitude features (e.g. JVM memory
  ~1e8) make the first z-scores enormous and the constant-rate SGD diverges.

This is the single mechanism that makes the detector drift-robust: a *virtual*-drift
baseline shift (scale-out) is absorbed by the normaliser instead of corrupting the
boundary.

### 2. Incremental learning — `SGDClassifier.partial_fit` (`online.py:84-110`)
Logistic regression (`loss="log_loss"`) updated one window at a time under the
prequential protocol: **predict the window first (scored), then learn from its revealed
label**. The update touches only the `d` active weights — bounded cost, no dependence on
stream length, no retained history.

### 3. Dynamic parameter optimisation — a champion **bandit** (`online.py:84-122, 203-204`)
Six candidate learners run in parallel — the cross-product
`eta0 ∈ {0.01, 0.05, 0.1} × alpha ∈ {1e-4, 1e-3}` (`online.py:155-159`). The **champion**
serving predictions is whichever candidate has the best **recent windowed F1** (F1, not
accuracy — under class imbalance accuracy would reward a trivial always-normal
predictor; `online.py:112-122`). So the effective hyper-parameters re-tune themselves as
the data pattern changes. The champion is re-elected each step by `argmax` of recent F1
(`online.py:204`); re-selections are logged as **adapt events**.

### 4. Drift-triggered acceleration — `_DriftDetector` (`online.py:125-141, 206-211`)
A deliberately simple two-window error monitor: when the recent prequential error
exceeds the reference error by more than `delta = 0.12`, it fires. On a trigger the
model enters a 60-step **boost** that raises the normaliser's decay **8×**
(`online.py:198`), so it re-centres quickly on the new regime, then relaxes.

**Net effect:** the online model holds F1 high across all regimes because the normaliser
neutralises the *virtual* component of drift while incremental fitting tracks the *real*
(concept) component — the two kinds `Regimes.md` deliberately combines.

---

## `offline_full` — the oracle ceiling (not deployable)

```python
Xo_tr, Xo_te, yo_tr, yo_te = train_test_split(X, y, test_size=0.3, stratify=y)
oracle = BaselineModel("rf", "binary").fit(Xo_tr, yo_tr)   # random split over ALL regimes
```
(`online_vs_offline.py:172-178`)

A Random Forest trained on a random 70/30 split spanning **every** regime, including the
future. It is **unrealisable** — you cannot train on the operational future — and is
included for exactly one purpose: to prove the static model's collapse is caused by
**non-stationarity, not model capacity**. Because even this all-seeing batch model is
beaten by `online_adaptive` at C3/C4 (a single static boundary can't fit all regimes at
once, but a moving one can), the decay is attributable to drift, not to the Random
Forest being too weak.

---

## Why the offline learners are trees but the online one is linear

The offline learners use a Random Forest because the model-family comparison (paper
RQ4) finds ensemble trees strongest on this multimodal *tabular* telemetry. But a Random
Forest **cannot `partial_fit`** — updating it means a full, bursty re-fit, which is
precisely the `offline_periodic` stall. The online setting prizes a **bounded, smooth
per-window update**, which a normalised linear/SGD model delivers (`O(d)` time, kilobyte
footprint), and the configuration-aware features have already done the non-linear work,
leaving a near-linearly-separable surface. So the strongest *batch* model and the
strongest *streaming* model are deliberately **not** the same model.

---

## Operational-cost contrast (the honest follow-up)

The accuracy comparison is only half the decision; the cost profiles are opposite
(profiled separately, surfaced in `rq3_cost.csv` / paper Table `tab:rq3-cost`):

| | `offline_periodic` | `online_adaptive` |
|---|---|---|
| Per-window **tail** latency | 580–880 ms refit spikes (blocking, land at regime shifts) | bounded, ≤ 78 ms over five seeds (15–60 ms at seed 42) |
| Model footprint | 2–6 MB | ~15 KB |
| Retained labelled windows | 2,880 (a governance liability) | **0** |
| Train events over the stream | 51 full refits | 25,920 incremental updates |
| Total CPU over the stream | 1× (baseline) | 4.1–4.8× (spent **smoothly**) |

Online's *only* disadvantage is higher aggregate CPU — but it never stalls the pipeline,
and the stall is what matters behind a per-window SLA.

> The wall-clock rows are properties of one workstation and a single pass. The
> **structural** rows — refit count, footprint, retained windows — follow from the
> policy and reproduce exactly, and the argument rests on those plus the
> order-of-magnitude tail gap.

---

## How much of the online margin is the machinery? (measured, not assumed)

The four mechanisms above are a design, and a design invites the question *which of
them earns its place?* Two experiments answer it on the identical stream
(`ml/experiments/baseline_streaming.py`, `ablate_online.py`).

**Normalisation carries the policy.** Three canonical incremental learners
(passive-aggressive, perceptron, plain SGD — mechanism 2 alone, no pool, no monitor)
reach F1 **0.302–0.308 at *every* configuration** unnormalised: barely above the trivial
floor, and completely unresponsive to telemetry richness. Put a running standardiser in
front of the *same* learner — mechanism 1, in its plainest form — and they reach
**0.760–0.796 at C1** and **0.959–0.971 at C3**, tracking completeness the way the full
detector does (plain SGD +0.170 from C1→C4 against the detector's +0.163).

**Mechanisms 3 and 4 do little measurable work.** Switching them off in turn:

| Mechanism | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| 3. Champion re-election | +0.013 | +0.005 | −0.001 | −0.000 |
| 4. Drift-triggered acceleration | −0.0014 | −0.0005 | 0.0000 | 0.0000 |

The champion pool is worth at most +0.013 (C1) and nothing beyond C2; the drift monitor
nothing anywhere, which makes its `adapt_events` a **diagnostic** — a readout of how
hard the drift is to follow — rather than a load-bearing component. The full detector's
whole remaining margin over the best off-the-shelf scaled arm is **+0.017 at C1** and
**+0.003 at C3**, the latter inside the seed spread.

**Read-out: a standardised incremental learner is a close substitute for the whole
`OnlineModel`.** This does not weaken the study's claim, because the clean, unconfounded
contrast was always `offline_static` vs `offline_periodic` — same family, same features,
differing only in whether the boundary may move (**0.36 → 0.92**). But it does bound
what the adaptive machinery may be credited with, and it is why the C3/C4 lead is
attributed to *normalised incremental learning* rather than to the pool or the monitor.

---

## Where these show up

- **`aiops/data/results/rq3_online_vs_offline.csv`** — precision/recall/F1/AUC per
  `(config, segment, model)` for all four learners (overall future + per regime).
- **`aiops/data/results/rq3_timeline.csv`** — block-wise rolling F1 for the three
  realistic learners (the static collapse, the periodic sawtooth, the online tracking
  line; `online_vs_offline.py:120-141`).
- **`aiops/data/results/rq3_summary.json`** — headline future-stream F1, periodic refit
  count, online adapt-event count, final champion params.
- **`aiops/data/results_baselines_scaled/rq3_streaming_baselines.csv`** — the
  off-the-shelf incremental learners, raw and standardised.
- **`aiops/data/results_ablation/rq3_online_ablation.csv`** — the `OnlineModel` with
  `use_champion` / `use_drift` switched off (both default `True`, so no published RQ3
  number is affected).
- **`aiops/data/results_drift_sweep/rq3_drift_sweep.csv`** — all three policies against
  drift amplitude, which is what bounds *when* each policy is the right one
  (see [`Regimes.md`](Regimes.md)).
- **Paper:** `\S sec:method-learners` (Table `tab:learners`, Algorithm `alg:online`),
  `\S sec:res-rq3` (results), and `DemoRQ3.md`.

---

**Bottom line.** `offline_static` is the past (frozen, collapses to F1 ≈ 0.36 under
drift — barely above a 0.292 floor, and an *oracle* re-threshold recovers it only to
0.45–0.55), `offline_periodic` is the usual compromise (tracks drift but lags, spikes,
and hoards a 2,880-window buffer), and `online_adaptive` is the proposal (per-window
adaptation via a running normaliser + incremental SGD + a self-selecting bandit + drift
boost) — cheaper on every operational axis except steady-state CPU. `offline_full` is
the reference that proves the static collapse is *drift*, not *capacity*.

Two qualifications belong in the same breath, because they are what the controls
measured. **Online is not uniformly more accurate:** under thin telemetry (C1/C2) it is
*tied* with periodic, and on a *stationary* stream it is the **worst** of the three
while the frozen model is the best. **And its margin is mostly one mechanism:**
normalisation, not the pool or the monitor. The claim that survives both is the narrow,
unconfounded one — within a single Random-Forest family, refitting raises F1 from
**0.36 to 0.92**.
