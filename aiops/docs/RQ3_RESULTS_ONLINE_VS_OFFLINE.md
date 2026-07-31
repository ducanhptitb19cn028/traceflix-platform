# Online vs Offline Model Pipeline: Consolidated Results (RQ1, RQ2, RQ3)

> ### Provenance and standing qualifications — read before quoting any number
>
> Every figure below is regenerated from the committed CSVs in
> [`../data/results/`](../data/results/) and its sibling `results_*` directories, and
> matches the paper's Evaluation section. Four qualifications apply throughout:
>
> 1. **The results are generated, not measured.** They come from the synthetic
>    generator (`_synth` in [`../collectors/telemetry.py`](../collectors/telemetry.py)),
>    not the live cluster. Only the *ordering* transfers — see
>    [How the data is generated](../../README.md#how-the-data-is-generated-read-this-first).
>    The one exception is §10, a 12-episode live-replay pilot.
> 2. **The RQ1 trace increment is discounted** — the generator both sharpens the trace
>    signal and exempts it from drift (`_DRIFT_FIELDS` in [`../ml/drift.py`](../ml/drift.py)),
>    so its magnitude is partly constructed rather than measured.
> 3. **The paradigm comparison is confounded with model family** — `offline_static` and
>    `offline_periodic` are Random Forests, `online_adaptive` is a normalised linear
>    model. The clean, unconfounded contrast is **static vs periodic** (same family,
>    same features, differing only in whether it refits): **0.36 → 0.92**.
> 4. **RQ2's first attempt was circular** (§3) — the ranking feature was derived from
>    the ground-truth label. The generator was rebuilt and the experiment re-run; the
>    reported result lives in `rq2_localisation_propagating.csv` and
>    [`DemoRQ2.md`](../../DemoRQ2.md).

This document collects **all** experimental results for the anomaly-detection
study: detection completeness across telemetry configurations (**RQ1**),
root-cause localisation (**RQ2**), and the head-to-head comparison between the
**offline (batch)** and **online (streaming)** pipelines across all four
configurations and four operating regimes (**RQ3**) — followed by the four controls
that decide how much of RQ3 may actually be claimed (§§8–10). It ends with a single
overall conclusion.

- **Source data:** `../data/results/` (`rq1_completeness.csv`, `rq3_online_vs_offline.csv`,
  `rq3_cost.csv`, `rq3_timeline.csv`, `rq3_baselines.csv`, `rq3_seeds.csv`,
  `rq4_model_family.csv`, `summary.json`, `rq3_summary.json`, `rq3_cost_summary.json`),
  plus `../data/results_drift_sweep/`, `../data/results_baselines_scaled/`,
  `../data/results_ablation/`, `../data/results_live/`
- **Conceptual background:** [`ONLINE_VS_OFFLINE.md`](ONLINE_VS_OFFLINE.md),
  [`ONLINE_PIPELINE.md`](ONLINE_PIPELINE.md)
- **What each artefact is:** [`../data/results/README.md`](../data/results/README.md)

---

## 1. Experiment setup

| Parameter | Value |
|--|--|
| Mode | Synthetic, prequential (test-then-train) |
| Episodes | 320 (80 per regime) |
| Services | 9 (`gateway`, `auth`, `catalog`, `movie`, `actor`, `review`, `search`, `recommendation`, `user`) |
| Windows evaluated | **34,560** (8,640 warm-up R0 + **25,920** future) |
| Regimes | R0 baseline → R1 latency regression → R2 scale-out → R3 combined load |
| Periodic retrain | every 500 windows (**51 refits**), on a 2,880-window training buffer |
| Anomaly prevalence (scored stream) | 0.171 → **always-alarm floor F1 = 0.292** |
| Seed | 42 (headline repeated over seeds 42–46, §7) |

### Telemetry configurations (feature sets)

| Config | Name | Features |
|--|--|--|
| **C1** | Metrics-Only | 10 |
| **C2** | Metrics + Logs | 14 |
| **C3** | Metrics + Logs + Traces | 18 |
| **C4** | Full MELT | 23 |

### Models compared

| Model | Family | Learning |
|--|--|--|
| `offline_static` | RandomForest | Train once on R0, then frozen |
| `offline_periodic` | RandomForest | Re-fit every 500 windows on a 2,880-window buffer |
| `online_adaptive` | `OnlineModel` (SGD + EW normalisation + champion bandit) | `partial_fit`, one window at a time |
| `offline_full` | RandomForest | Oracle — trained on a random split across all regimes (reference ceiling) |

> `offline_full` is scored on its own random 30% split spanning **all** regimes
> (`overall_allregimes`, n = 10,368), not on the future stream. It is a *reference*,
> not a competitor: no deployment can train on the operational future.

---

## 2. RQ1 — Detection completeness vs telemetry richness

Does adding more telemetry (metrics → logs → traces → full MELT) improve detection?
Two settings from the *identical* pipeline, varying only the configuration: the
held-out stationary slice (`rq1_completeness.csv`) and the drifted stream measured on
the continual-learning detector one would actually deploy.

| Config | Name | Feat. | Precision | Recall | F1 (held-out) | AUC-ROC | **F1 (drifted)** |
|--|--|--|--|--|--|--|--|
| **C1** | Metrics-Only | 10 | 0.9424 | 0.8546 | 0.8964 | 0.9783 | 0.8130 |
| **C2** | Metrics + Logs | 14 | 0.9517 | 0.8816 | 0.9153 | 0.9849 | 0.8274 |
| **C3** | + Traces | 18 | 0.9869 | 0.9823 | 0.9846 | 0.9985 | **0.9737** |
| **C4** | Full MELT | 23 | 0.9887 | 0.9823 | **0.9855** | 0.9984 | **0.9755** |

**Reading:** detection F1 rises **monotonically** with richness in *both* settings —
0.896 → 0.986 held-out, 0.813 → 0.976 drifted. The decisive increment is distributed
traces (C2→C3), and it is **larger under drift** (+0.146 against +0.069): spans carry
cross-service causal structure that aggregate metrics and unstructured logs cannot
reconstruct, and an error rate is more nearly scale-free than a latency percentile.
Logs add less; events and history (C3→C4) leave detection essentially unchanged.

⚠️ **The trace magnitude is discounted, not the direction.** Two generator properties
act on the C2→C3 step: error spans are emitted cleanly by faulty origin services, and
they are held *outside* the drift transformation, so they survive the regime shifts
that displace latency and volume. Those choices largely *construct* the finding that
traces are the decisive pillar. Nothing in RQ3 depends on it — the static model's
collapse is flat across all four configurations (§4).

---

## 3. RQ2 — Root-cause localisation (top-k accuracy)

> **The first table below is RQ2's circular first attempt and must not be cited.** The
> C3 figure is **circular**: the feature the localiser ranks on (`traces.error_spans`)
> is assigned in the base generator by the rule `(fault != "normal" and is_origin)`,
> and `is_origin` **is** the ground-truth label the localiser is being asked to
> recover. The feature is the answer key, so a perfect score is arithmetic rather than
> evidence.
>
> **The reported RQ2 result** comes from `ml/experiments/rq2_localisation.py` on the
> propagating generator (`ml/dataset.py::generate_rca_run`), output
> `rq2_localisation_propagating.csv` — the second table. Cite that. Full account in
> [`DemoRQ2.md`](../../DemoRQ2.md) and §5.2 of the dissertation.

The superseded numbers (`rq2_localisation.csv`, single seed):

| Approach | top-1 | top-2 | top-3 |
|--|--|--|--|
| metrics + logs (C2) | ~~0.7692~~ | ~~0.8974~~ | ~~0.9487~~ |
| metrics + logs + traces (C3) | ~~1.0000~~ | ~~1.0000~~ | ~~1.0000~~ |

**The reported result** (`rq2_localisation_propagating.csv`; errors propagate up the
call path attenuating 0.6/hop; 5 seeds × ~120 fault episodes; random-guess floor
0.111). `bg` (β) is the per-episode probability of an unrelated off-path incident:

| Approach | bg 0.0 | bg 0.1 | bg 0.25 | bg 0.5 |
|--|--|--|--|--|
| metrics + logs (C2), flat | 0.387 | 0.359 | 0.337 | 0.340 |
| metrics + logs + traces (C3), flat | 0.626 | **0.563** | 0.496 | 0.456 |
| metrics + logs (C2), graph-aware | 0.446 | 0.391 | 0.274 | 0.207 |
| metrics + logs + traces (C3), graph-aware | *1.000* | **0.736** | 0.486 | 0.335 |

**Reading — the answer to RQ2:** traces buy **+0.20 top-1** at bg = 0.1 and stay ahead
at every noise level, with no metrics-and-logs arm passing 0.45. Nothing saturates —
the best realistic arm reaches 0.736 top-1 (0.948 top-3). The 1.000 at bg = 0.0 is a
boundary condition (one error path ⇒ one root by construction), not a result, and the
graph-aware rule *inverts* against flat ranking by bg = 0.5, because it rewards any
erroring service with clean dependencies and a background incident is exactly that.
Answered in direction; magnitudes remain generated, so only the ordering is claimed.

---

## 4. RQ3 — Headline result: F1 on the future (drifted) stream

F1 over the 25,920 post-warm-up windows (`overall_future`). Higher is better.

| Config | offline_static | offline_periodic | online_adaptive | Δ vs static | Δ vs periodic | `offline_full` (ref.) |
|--|--|--|--|--|--|--|
| **C1** Metrics-Only | 0.3602 | 0.8204 | 0.8130 | +0.4528 | −0.0074 | 0.8124 |
| **C2** Metrics+Logs | 0.3609 | 0.8323 | 0.8274 | +0.4665 | −0.0049 | 0.8166 |
| **C3** +Traces | 0.3701 | 0.9247 | **0.9737** | +0.6036 | **+0.0490** | 0.9294 |
| **C4** Full MELT | 0.3705 | 0.9255 | **0.9755** | +0.6050 | **+0.0500** | 0.9267 |

**Reading — and note what is *not* claimed.** The frozen batch model collapses to
**F1 ≈ 0.36** on the drifted stream *regardless* of telemetry: metrics-only to full
MELT moves it by barely a point (0.3602 → 0.3705). Read against the always-alarm floor
of **0.292**, that is less a degraded detector than one that has nearly stopped
discriminating.

The adaptive policies recover almost the whole gap, but **which one leads depends on
richness**:

- **C1/C2 — online and periodic are tied.** The gaps (−0.007, −0.005) are smaller than
  the five-seed spread of either policy (§7), so neither leads. With few signals the
  online normaliser has little to re-centre on, and much of the drift is virtual (§5).
- **C3/C4 — online leads clearly**, by ~0.05 and roughly nine standard deviations.
- **Against `offline_full`**, the same standard applies: online exceeds it decisively
  at C3/C4 (+0.044, +0.049) — a single boundary is the wrong *object* however well
  fitted — while the +0.001/+0.011 margins at C1/C2 sit at or below the noise floor
  and are counted as a **match**, not a win.

Telemetry richness barely moves the static model (+0.010 from C1 to C4, within seed
noise) but strongly helps the online one (+0.163). **Completeness and adaptation are
complementary:** richer signal raises the attainable ceiling; only adaptation realises it.

### Precision, recall and the stale-normal signature

| Config | Policy | P | R | AUC |
|--|--|--|--|--|
| C1 | static | 0.221 | 0.980 | 0.767 |
| C1 | periodic | 0.806 | 0.836 | 0.952 |
| C1 | online | 0.873 | 0.761 | 0.950 |
| C2 | static | 0.221 | 0.983 | 0.754 |
| C2 | periodic | 0.813 | 0.852 | 0.960 |
| C2 | online | 0.878 | 0.782 | 0.955 |
| C3 | static | 0.227 | 0.999 | 0.858 |
| C3 | periodic | 0.879 | 0.976 | 0.991 |
| C3 | online | 0.985 | 0.962 | 0.998 |
| C4 | static | 0.227 | 1.000 | 0.858 |
| C4 | periodic | 0.880 | 0.976 | 0.991 |
| C4 | online | 0.987 | 0.964 | 0.998 |

The static model shows the **stale-normal signature** in its purest form: recall near
perfect (0.98–1.00), precision collapsed to ≈ 0.22 at *every* configuration. The frozen
boundary still fires on true anomalies, but the post-drift normal has moved into the
region it labels anomalous, so it fires on healthy traffic too and most alerts are
false. The online model shows the opposite profile — a little recall traded for a large
precision gain (0.87–0.99), the desirable direction given alert fatigue.

**A subtlety hides in the AUC column.** The static model's thresholded F1 is flat, yet
its AUC-ROC *rises* with telemetry (0.77 → 0.86), the gain concentrated at the trace
increment. Richer telemetry does improve the frozen model's **ranking** of windows —
but that is invisible at a fixed threshold calibrated to a distribution that no longer
holds. More telemetry sharpens the score, not the stale **cut-point**. §6 measures what
that is worth.

---

## 5. RQ3 — Per-regime F1 breakdown

F1 by policy × regime, per configuration (8,640 windows per regime). Bold marks the
best realisable learner in each regime.

### C1 — Metrics-Only
| Regime | offline_static | offline_periodic | online_adaptive |
|--|--|--|--|
| R1 latency regression | 0.3166 | 0.7627 | **0.7925** |
| R2 scale-out | 0.4916 | **0.8534** | 0.8251 |
| R3 combined load | 0.3291 | **0.8487** | 0.8202 |

### C2 — Metrics + Logs
| Regime | offline_static | offline_periodic | online_adaptive |
|--|--|--|--|
| R1 latency regression | 0.3177 | 0.7801 | **0.8060** |
| R2 scale-out | 0.4908 | **0.8582** | 0.8456 |
| R3 combined load | 0.3295 | **0.8606** | 0.8301 |

### C3 — Metrics + Logs + Traces
| Regime | offline_static | offline_periodic | online_adaptive |
|--|--|--|--|
| R1 latency regression | 0.3018 | 0.8578 | **0.9724** |
| R2 scale-out | 0.5965 | 0.9676 | **0.9774** |
| R3 combined load | 0.3299 | 0.9533 | **0.9718** |

### C4 — Full MELT
| Regime | offline_static | offline_periodic | online_adaptive |
|--|--|--|--|
| R1 latency regression | 0.3017 | 0.8587 | **0.9753** |
| R2 scale-out | 0.5990 | 0.9702 | **0.9789** |
| R3 combined load | 0.3302 | 0.9527 | **0.9731** |

**Reading:** the online model is best in **8 of the 12** regime × config cells. All
four exceptions fall under the **thinnest telemetry** (C1, C2), in **scale-out (R2)**
and **combined load (R3)**, where periodic narrowly leads. That is coherent rather than
anomalous: those regimes are predominantly **virtual** drift — feature baselines shift
but the meaning of "anomalous" does not — so a batch refit recovers the boundary as
well as continuous updating, and with thin telemetry the online normaliser has fewer
signals to re-centre.

By contrast **R1 latency regression is real concept drift**, and the online model wins
it at *every* configuration. R1 is also where the static model is hurt most (F1 ≈ 0.30,
its lowest, against 0.49–0.60 in the scale-out regime it can partly survive). **The
static deficit is widest exactly where drift is conceptual rather than distributional.**

---

## 6. RQ3 — The trivial floor and the recalibration control

The AUC observation in §4 is the premise of the strongest objection to the conclusion,
and it deserves a measurement rather than an argument: *if the frozen model still ranks
windows well (AUC 0.86) and only its cut-point is stale, why not re-tune a threshold
instead of learning online?*

From `rq3_baselines.csv` (seed 42):

| Detector (drifted stream) | C1 | C2 | C3 | C4 |
|--|--|--|--|--|
| Always-alarm (trivial floor) | 0.292 | 0.292 | 0.292 | 0.292 |
| Static, frozen threshold | 0.360 | 0.361 | 0.370 | 0.371 |
| Static + ***oracle*** re-threshold | 0.446 | 0.437 | 0.552 | 0.553 |
| Periodic retraining | 0.820 | 0.832 | 0.925 | 0.925 |
| Online-adaptive | 0.813 | 0.827 | **0.974** | **0.976** |

The **oracle re-threshold** sweeps every candidate cut-point *on the drifted stream
itself* and keeps the one that scores best against that stream's true labels. **No
deployment can do this** — it would have to choose a cut-point from labels it has not
yet seen — so it is used only as an **upper bound** on any threshold-tracking scheme,
never as a headline.

It recovers the frozen model to **0.446 (C1)** and **0.552 (C3)**, against the online
detector's 0.813 and 0.974. **Recalibration is not a substitute for re-learning:**
granted the best cut-point that exists, chosen by an oracle that has seen the future,
the frozen boundary still recovers less than half the distance to a detector that
refits. A scalar threshold slides the boundary but cannot change its **shape**, and a
shape fitted to R0's normal is wrong for R3's.

This is the cleanest statement of the central claim, immune to the qualifications
attaching to the trace pillar: same model, same features, same stream, varying only
whether the decision surface may change shape.

---

## 7. RQ3 — Seed variance

Five independent seeds, each regenerating the stream, fault schedule and models from
scratch (`rq3_seeds.csv`, mean ± sd):

| Config | static | periodic | online | online − periodic |
|--|--|--|--|--|
| C1 Metrics-Only | 0.359 ± 0.020 | 0.808 ± 0.012 | 0.811 ± 0.006 | +0.003 *(tied)* |
| C2 Metrics+Logs | 0.360 ± 0.021 | 0.821 ± 0.013 | 0.822 ± 0.006 | +0.001 *(tied)* |
| C3 +Traces | 0.363 ± 0.017 | 0.918 ± 0.006 | **0.974 ± 0.002** | **+0.055** |
| C4 Full MELT | 0.365 ± 0.017 | 0.919 ± 0.006 | **0.976 ± 0.002** | **+0.057** |

Three things follow.

1. **The central result is robust.** Static sits at 0.36 ± 0.02 and the adaptive
   policies at 0.81–0.98 — a collapse twenty to ninety standard deviations wide. The
   *flatness* of the static row survives too: its variation with configuration (0.006)
   is smaller than its variation with seed (0.020), which is the quantitative form of
   "telemetry does not help a frozen model".
2. **The online advantage at C3/C4 is real** — +0.055 and +0.057 against sd 0.006.
3. **It corrected a single-seed claim.** On seed 42 periodic led by 0.007 at C1; across
   five seeds the mean difference is +0.003 the *other* way, well inside a spread of
   0.012. Below the trace increment the two adaptive policies are **tied**, and the
   choice is decided on the operational grounds of §9, not on accuracy.

---

## 8. RQ3 — How far must the baseline move? (the drift-magnitude sweep)

Everything above is measured at **one** drift amplitude — and that amplitude was set
comparably to the fault signatures themselves (`REGIME_FACTORS` moves p99 latency by
2.2×; `_FAULT_SHIFT` moves it by 2.3×). A boundary fitted on R0 *must* fail there, so
§4's collapse is entailed by the parameterisation rather than measured. A single point
cannot distinguish "drift defeats frozen detectors" from "we set the drift equal to the
fault".

`scaled_regime_factors(α)` rescales every multiplier toward 1 — preserving which fields
each regime moves and in what proportion, varying only how far. Labels are assigned
before the factors are applied and the generator draws the same random numbers either
way, so **the fault schedule is identical at every α**. From
`../data/results_drift_sweep/rq3_drift_sweep.csv`:

| α | R3 shift | C1 static | C1 per. | C1 onl. | C4 static | C4 per. | C4 onl. |
|--|--|--|--|--|--|--|--|
| 0.00 | 1.00× | **0.890** | 0.885 | 0.815 | **0.989** | 0.985 | 0.977 |
| 0.15 | 1.15× | 0.830 | **0.880** | 0.815 | 0.933 | **0.982** | 0.977 |
| 0.30 | 1.29× | 0.682 | **0.867** | 0.815 | 0.769 | 0.974 | **0.977** |
| 0.50 | 1.49× | 0.511 | **0.852** | 0.814 | 0.546 | 0.954 | **0.976** |
| 0.70 | 1.68× | 0.421 | **0.837** | 0.813 | 0.438 | 0.938 | **0.976** |
| 0.85 | 1.83× | 0.383 | **0.826** | 0.813 | 0.395 | 0.931 | **0.976** |
| 1.00 | 1.97× | 0.360 | 0.820 | 0.813 | 0.370 | 0.925 | **0.976** |
| 1.30 | 2.26× | 0.333 | 0.813 | 0.813 | 0.341 | 0.921 | **0.976** |

Four things follow, none visible from a single operating point.

1. **Adaptation is not free.** On a stationary stream (α = 0) the frozen model *equals
   or beats* periodic retraining and the online detector trails both — by 0.075 at C1.
   Continual updating is worth having because the stream drifts, not because it is
   continual.
2. **The failure is gradual.** Static F1 at C4 falls 0.989 → 0.370 as the shift grows
   1.00× → 1.97×. "Collapse" describes where the curve arrives, not how it travels: by
   1.29× a detector has lost a fifth of its F1 while still looking serviceable.
3. **The decision threshold is a number, not an assertion.** Refitting begins to pay by
   a **1.15×** shift, and the frozen model drops below **twice** the always-alarm floor
   between **1.29× and 1.49×**. The reported campaign sits at 1.97×, well beyond that —
   which is precisely why §4's collapse could not be read as a measurement.
4. **The two adaptive policies differ in kind, not degree.** Online F1 at C4 varies by
   0.001 across the entire sweep; periodic decays steadily 0.985 → 0.921, exposed to
   whatever accumulates between refits. Richness separates them too: at C4 online
   overtakes periodic once the shift passes ~1.3×, whereas at C1 periodic leads or ties
   at *every* amplitude tested. **Neither dominates** — which to deploy depends on how
   rich the telemetry is and how fast the baseline moves.

`α = 1` reproduces the §4 table to four decimals; treat that as the sweep's regression
check.

---

## 9. RQ3 — Cost, and what the adaptive machinery is worth

### 9.1 Operational cost (periodic vs online)

From the dedicated cost-profiling run (`rq3_cost.csv`, `rq3_cost_summary.json`), whose
F1 reconciles to §4:

| Config | Model | F1 | Max ms/win | p99 ms/win | Model KB | Retained win. | Total s |
|--|--|--|--|--|--|--|--|
| C1 | offline_periodic | 0.8204 | 725.3 | 0.22 | 5833.3 | 2880 | 31.47 |
| C1 | online_adaptive | 0.8130 | 59.5 | 12.09 | 14.9 | 0 | 142.93 |
| C2 | offline_periodic | 0.8323 | 710.8 | 0.16 | 5777.5 | 2880 | 32.17 |
| C2 | online_adaptive | 0.8274 | 14.8 | 8.63 | 15.2 | 0 | 132.01 |
| C3 | offline_periodic | 0.9247 | 666.9 | 0.19 | 1990.5 | 2880 | 30.59 |
| C3 | online_adaptive | 0.9737 | 20.5 | 8.76 | 15.4 | 0 | 131.29 |
| C4 | offline_periodic | 0.9255 | 581.6 | 0.14 | 2287.7 | 2880 | 29.40 |
| C4 | online_adaptive | 0.9755 | 15.5 | 8.48 | 15.7 | 0 | 129.66 |

| Config | F1 gain (online−periodic) | Max-latency ratio | Model-size ratio | Retained win. | Total CPU (online/periodic) |
|--|--|--|--|--|--|
| C1 | −0.0074 | 12.2× | 391.5× | 2880 vs 0 | 4.5× |
| C2 | −0.0049 | 47.9× | 380.1× | 2880 vs 0 | 4.1× |
| C3 | +0.0490 | 32.5× | 129.3× | 2880 vs 0 | 4.3× |
| C4 | +0.0500 | 37.4× | 145.7× | 2880 vs 0 | 4.4× |

- **Tail latency:** periodic produces per-window spikes of 580–880 ms when a refit
  lands — **10–48× worse** than the online model, which never exceeded 78 ms across
  five seeds. Online's cost profile is smooth; batch retraining is bursty.
- **Footprint:** the online model is **~120–390× smaller** (≈15 KB vs 2–6 MB) and
  retains **zero** historical windows, against periodic's 2,880-window labelled buffer
  — a memory *and* data-governance liability.
- **Total CPU:** online pays **4.1–4.8×** the aggregate, updating on every one of
  25,920 windows rather than 51 batch refits — but spends it *smoothly*, never stalling
  the pipeline with a multi-hundred-millisecond spike that lands exactly when a regime
  shifts.

> The wall-clock columns are properties of one workstation and a single pass. The
> **structural** columns — refit count, footprint, retained windows — follow from the
> policy and reproduce exactly. The cost argument rests on those plus the
> order-of-magnitude tail gap, not on any particular millisecond.

### 9.2 Adaptation events

From `rq3_summary.json` (`per_config`):

| Config | Features | Periodic retrains | Online adapt events | Final champion (eta0, alpha) |
|--|--|--|--|--|
| C1 | 10 | 51 | 7 | eta0 = 0.10, alpha = 1e-3 |
| C2 | 14 | 51 | 3 | eta0 = 0.01, alpha = 1e-4 |
| C3 | 18 | 51 | 0 | eta0 = 0.05, alpha = 1e-4 |
| C4 | 23 | 51 | 0 | eta0 = 0.01, alpha = 1e-4 |

Richer telemetry needs **fewer** corrective adapt events — seven at C1, three at C2,
**none** once traces are added — whereas periodic refits a fixed 51 times regardless.
Richer signal stabilises adaptation, more of the drift being absorbed by the
normaliser's ordinary tracking. The events are **diagnostic, not load-bearing**:
suppressing them changes F1 by at most 0.0014 (§9.3).

### 9.3 Streaming baselines and the component ablation

Whether the detector's machinery earns its complexity is testable, and was tested
(`../data/results_baselines_scaled/`, `../data/results_ablation/`).

**Off-the-shelf incremental learners, with and without a running standardiser** —
three canonical linear learners scored prequentially on the identical stream:

| Arm | C1 | C2 | C3 | C4 |
|--|--|--|--|--|
| passive-aggressive, raw | 0.304 | 0.304 | 0.305 | 0.305 |
| perceptron, raw | 0.302 | 0.302 | 0.303 | 0.303 |
| SGD-logistic, raw | 0.308 | 0.308 | 0.306 | 0.306 |
| passive-aggressive, **scaled** | 0.760 | 0.790 | **0.971** | **0.970** |
| perceptron, **scaled** | 0.783 | 0.799 | 0.959 | 0.960 |
| SGD-logistic, **scaled** | **0.796** | **0.815** | 0.966 | 0.967 |
| `online_adaptive` (full detector) | 0.813 | 0.827 | 0.974 | 0.976 |

Unnormalised, all three sit at **0.302–0.308 at every configuration** — barely above
the always-alarm floor, and flat in richness. Standardised, the *same* learners reach
0.760–0.796 at C1 and 0.959–0.971 at C3, and track completeness as the full detector
does (plain SGD gains +0.170 from C1→C4 against the detector's +0.163). **Adaptive
normalisation is what carries the online policy.**

**Switching the detector's own mechanisms off in turn** confirms the attribution:

| Mechanism | C1 | C2 | C3 | C4 |
|--|--|--|--|--|
| Champion re-election (`no_drift` − `no_drift_no_champion`) | +0.013 | +0.005 | −0.001 | −0.000 |
| Drift monitor (`full` − `no_drift`) | −0.0014 | −0.0005 | 0.0000 | 0.0000 |
| **Detector − best off-the-shelf scaled arm** | **+0.017** | **+0.012** | **+0.003** | **+0.005** |

The champion pool is worth at most +0.013 (C1) and nothing beyond C2; the drift monitor
is worth nothing anywhere. The detector's whole remaining margin over the best
off-the-shelf arm is +0.017 at C1 and +0.003 at C3 — the latter inside the seed spread.

**The honest read-out: a standardised incremental learner is a close substitute for the
whole detector.** This does not weaken RQ3 — the clean, unconfounded contrast was
always static-vs-periodic within one family — but it does bound what the detector's
extra machinery may be credited with, and it is the reason §4 attributes the C3/C4 lead
to *normalised incremental learning*, not to the pool or the monitor.

> Gaussian NB is also in the CSV and is **not** counted above: unscaled it looks like
> the best raw arm (0.62–0.81) but degenerates completely at C4 (`nan_scores` = 25,920,
> F1 0.0), and every scaled arm emits 8,749 NaN scores floored to 0.5 before metrics.
> The three linear learners emit **zero** NaNs in every cell.

---

## 10. The live-replay pilot — the one measured result

`ml/experiments/live_replay.py` joins the ground truth written by
`faults/run_episodes.py` to *historical* PromQL: `collect_metrics_live(service, at=ts)`
evaluates each query at the instant its window represents, so a recorded campaign is
reconstructed rather than filled with present-moment telemetry.

| | Value |
|--|--|
| Source / config / model | live / C1 / RandomForest |
| Episodes, windows, test windows | 12, 450, 135 |
| Prevalence → always-alarm floor | 0.078 → **0.144** |
| Precision / Recall / F1 / AUC | 0.700 / 0.700 / **0.700** / 0.967 |

**Its scope is narrow on purpose, and the narrowness is the point.**

- **C1 only.** Only the metric collector is time-parameterised; the Loki, Tempo and
  Kubernetes-event collectors would silently mix present-moment values into a past
  window. So this pilot says **nothing** about the trace increment — the one RQ1
  magnitude the write-up discounts.
- **Origin-only labelling.** A window is anomalous iff its service is the injected root
  cause; ancestors degraded by the fault are labelled normal. Conservative by
  construction — it can only depress apparent precision.
- **Twelve episodes.** A feasibility measurement, far too small to carry a confidence
  interval, and no replacement for the 320-episode campaign.

F1 0.700 at nearly five times its own floor, on measured telemetry, at the
configuration the synthetic campaign scores 0.896. That is evidence the pipeline works
end to end on genuine data; it is **not** evidence about any number above. A full
*drifted* live campaign remains the study's principal outstanding experiment.

---

## 11. Conclusion

**RQ1 (completeness)** establishes that detection F1 climbs monotonically with
telemetry richness in both the stationary and the drifted setting, with the largest
increment at traces. That increment is **discounted** — the generator both sharpens the
trace signal and exempts it from drift, so its magnitude is partly a modelling choice.
**RQ2 (localisation) is answered on the rebuilt propagating generator**: traces are
worth about +0.20 top-1 at a realistic background-error rate and lead at every level
tested, with no arm saturating. The first attempt was circular and was rebuilt rather
than reported (§3).

What RQ1 measures is in any case a *stationary* ceiling. RQ3 shows what happens once
the stream drifts — and that is where the study's finding lives.

1. **Accuracy.** Online F1 runs **0.813 → 0.976** against **0.360 → 0.371** for the
   frozen batch model and **0.820 → 0.925** for scheduled retraining. Online is best in
   **8 of 12** regime × config cells; the four exceptions are all virtual-drift regimes
   under thin telemetry, where the two adaptive policies are **tied**. At C3/C4 online
   also exceeds the all-regime reference (0.976 vs 0.927).
2. **Drift is the deciding factor, and only within a measured band.** The static
   collapse is structural, not a tuning problem: precision craters to ≈ 0.22 while
   recall stays near 1.0 — the classic stale-normal failure. But the sweep (§8) bounds
   the claim in *both* directions: refitting starts to pay only past a **1.15×**
   baseline shift, the frozen model stops discriminating between **1.29× and 1.49×**,
   and **below that band the frozen model is the best of the three**.
3. **Re-thresholding is not a substitute for re-learning.** An *oracle* cut-point drawn
   from the drifted stream's own labels recovers the frozen model only to 0.45–0.55
   against the online detector's 0.97 (§6). The boundary is the wrong **shape**, not
   merely in the wrong **place**.
4. **More telemetry helps, but only with adaptation.** C1 → C4 lifts online F1 by
   +0.163 and the static model by +0.010. Completeness and continual learning are
   complementary; neither alone suffices.
5. **Operational cost favours online** — 10–48× better tail latency, ~120–390× smaller,
   zero retained data — at 4.1–4.8× higher *steady* CPU, spent smoothly rather than in
   a stall.
6. **The margin is attributable, and modest.** Adaptive normalisation carries the
   policy; the champion pool is worth ≤ +0.013 and the drift monitor nothing (§9.3). A
   standardised incremental learner is a close substitute for the full detector.

**Bottom line:** for a non-stationary observability stream whose baseline moves by more
than ~1.15×, continual adaptation is the right production design — static detection is
unsafe there, and periodic retraining is a laggy, bursty, buffer-hoarding patch. Below
that band, and under thin telemetry at any amplitude, a scheduled refit remains
competitive and sometimes better. The claim that survives every qualification is the
narrow one: **within a single model family, refitting raises F1 from 0.36 to 0.92, and
no amount of telemetry or re-thresholding substitutes for it.**
