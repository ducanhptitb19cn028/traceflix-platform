# Reframed Dissertation: Three New Research Questions (RQ-D, RQ-A, RQ-O)

**Decision:** replace the previous RQ1–RQ4 framing (completeness / algorithms / traces /
online-vs-offline) with three *totally different* research questions, each supported by an
experiment that Claude Code develops on the existing `aiops/` codebase, and ~23 verified
2022–2026 references each (~70 total).

**Reframed thesis.** The old thesis asked *"does observability matter for detecting failures?"*.
The new thesis broadens from **detection accuracy** to the **operational value of observability
across three axes a practitioner actually cares about**: *how early* it warns (timeliness),
*how gracefully it degrades* when telemetry is imperfect (robustness), and *whether the same
signals can be turned from diagnosis into action* (optimisation).

> **Proposed broadened title:** *"From Signal to Action: An Empirical Study of Observability for
> Early, Robust and Optimisation-Driven Operations in Cloud-Native Systems."*
> (Working title — the dissertation keeps the TraceFlix testbed; RQ1–4 become legacy / appendix.)

The three RQs map to three implemented experiments and three reference clusters.

---

## Codebase backbone (reused by all three)

From the capability audit (`Explore`):

- **Generator:** `collectors/telemetry.py::_synth()` (per-window MELT), `ml/dataset.py::generate_run()`
  (episodes×windows×services), `ml/drift.py::generate_drifting_run()` + `apply_regime()`
  (the **in-place per-field perturbation hook** we reuse heavily).
- **Faults:** `ml/configs.py::FAULT_TYPES` (5: cpu_saturation, memory_leak, latency_spike,
  pod_kill, network_partition); shifts in `collectors/telemetry.py::_FAULT_SHIFT`.
- **Features:** `ml/features/build.py::build_features()/split_xy()`; configs `ml/configs.py::CONFIGS`
  (C1 metrics … C4 full MELT) — already a modality-ablation axis.
- **Models:** `ml/models/detectors.py::BaselineModel._make()` (RF/GB/XGB; clean fit/predict/proba
  registry), `TemporalModel` (lazy-torch), `MultimodalFusion`; `ml/models/online.py::OnlineModel`.
- **Harness/metrics/plots:** `ml/experiments/run_experiment.py` (`_metrics()`),
  `online_vs_offline.py`, `cost_compare.py`; figures `ml/eval/plots.py`.

New code goes under `ml/experiments/` (RQ-A, RQ-D) and a new `ml/optimise/` (RQ-O); all outputs
land in `aiops/data/results/` as CSV + `figures/`, consistent with the existing flow.

---

## RQ-A — Robustness to telemetry degradation  *(feasibility: Easy)*

**RQ-A.** *How robust is observability-driven anomaly detection to realistic telemetry
degradation — reduced trace sampling, missing modalities, and noisy or delayed signals — and
which telemetry signals are the most fragile?*

Sub-questions: (A1) graceful vs cliff-edge degradation per degradation type; (A2) signal
**fragility ranking** (which pillar's loss hurts F1 most); (A3) does richer telemetry (C4) buy
robustness, or just a higher clean-ceiling?

**Hypotheses.** H-A1: detection degrades *gracefully* with sampling but *sharply* once traces
fall below a threshold (traces were the decisive signal in the old RQ3). H-A2: traces are the
most fragile (highest ΔF1 per unit loss); metrics the most robust.

**Experiment** (`ml/experiments/robustness.py`): a degradation operator built on the
`apply_regime` pattern with four independent knobs, swept one at a time on a fixed C4 detector:
| Knob | Levels | Mechanism |
|---|---|---|
| trace sampling rate `s` | 1.0, 0.5, 0.25, 0.1, 0.05 | scale/zero `trace.*` (esp. `trace_count`, `error_spans`) per window with prob `1-s` |
| modality dropout | {–logs, –traces, –events, none} | zero a pillar's feature block (or pass a smaller `ObsConfig`) |
| Gaussian noise `σ` | 0, 0.05, 0.1, 0.2, 0.4 | additive noise on metric/log/trace values via `_synth` `g()` noise arg |
| label/feature delay `d` | 0,1,2,4 windows | shift features vs labels on the join |

Train on clean, evaluate on degraded (and a train-on-degraded variant for A3). Metric: F1/AUC
vs level; **fragility = −dF1/d(level)** per signal. Output: `rqA_robustness.csv`, figures
`rqA_*` (degradation curves + fragility bar).

**References (~23):** trace sampling (Mint, Trace Sampling 2.0 — already in lib), missing/incomplete
multimodal learning, robustness to noisy/adversarial inputs in AD, data-quality & sensor
degradation, telemetry-cost vs fidelity.

---

## RQ-D — Early detection / lead-time  *(feasibility: Hard — most net-new generator work)*

**RQ-D.** *How early, before a service-level objective (SLO) is breached, can observability-driven
detection raise an alarm, and what is the trade-off between detection accuracy and lead time across
reactive and proactive (forecasting) approaches?*

Sub-questions: (D1) lead-time distribution of a reactive classifier vs a proactive forecaster;
(D2) the accuracy↔earliness trade-off (earlier alarms = more false alarms); (D3) which signals
give the most warning.

**Hypotheses.** H-D1: a forecasting detector achieves positive median lead time (warns *before*
breach) where the reactive classifier fires at/after breach. H-D2: earliness trades against
precision along a tunable curve.

**Experiment** (generator change + `ml/experiments/early_detection.py`):
1. **Gradual fault onset** — extend `ml/dataset.py`/`ml/drift.py` so a fault episode *ramps* the
   fault signal from 0→full over `k` windows (instead of instant onset), and define an
   **SLO-breach window** per episode (first window where p95 latency > threshold `T`).
2. **Lead-time metric** — `lead = t_breach − t_detect` (positive = early warning); plus
   early-warning precision/recall over the pre-breach ramp.
3. **Approaches:** reactive (current RF on the window) vs **proactive forecaster** (forecast
   latency `h` steps ahead — Holt/AR or a small regressor on recent windows — alarm if the
   *forecast* breaches `T`). Sweep the alarm threshold to trace the earliness/precision curve.

Output: `rqD_leadtime.csv` (per-approach lead-time stats, early-warning P/R, ROC), figures
`rqD_*`. Reuses `Window`/features/`_metrics`; new = ramp generator, SLO timestamp, lead metric,
forecaster.

**References (~23):** predictive/proactive monitoring, time-series forecasting for AD, failure
prediction, early/online change detection, remaining-useful-life, SLO/SLA & error-budget
management, alerting lead time.

---

## RQ-O — Observability-cost optimisation for detection  *(on-topic; reuses RQ-A + cost)*

**RQ-O.** *Given a telemetry/instrumentation budget, which observability configuration —
modality mix (metrics/logs/traces/events) and trace-sampling rate — maximises detection quality
per unit cost; and is full MELT actually cost-optimal, or is a cheaper configuration
Pareto-dominant?*

This keeps RQ-O squarely on the **anomaly-detection** topic: it optimises *the observability the
thesis is about* rather than the system, turning the "does observability matter?" ablation into a
multi-objective **detection-F1 vs telemetry-cost** Pareto study (echoing the Chen & Li
"performance aspirations" template). Implementation reuses the RQ-A trace-sampling operator and the
C1–C4 feature gating; traces are weighted as the expensive pillar, scaled by the sampling rate.

Sub-questions: (O1) does an observability-guided optimiser reach a target SLO with fewer trials
than telemetry-blind search? (O2) Pareto-front quality (latency–cost hypervolume) guided vs blind;
(O3) which telemetry features are most informative for the surrogate.

**Hypotheses.** H-O1: a telemetry-guided surrogate optimiser reaches the latency–cost target with
a meaningful speed-up over random/grid search. H-O2: the guided optimiser dominates the blind
Pareto front.

**Experiment** (`ml/optimise/`):
1. **Config→performance model** — a synthetic but plausible mapping from configuration knobs
   (replicas `r`, CPU/mem limit `m`, the `movie→actor×N` concurrency, cache on/off) to outcomes
   (p95 latency `L`, throughput `X`, cost `$`) *plus* the MELT telemetry those configs would emit
   (reuse `_synth` conditioned on the config, not just the fault). Defines a Pareto trade-off
   (minimise `L` and `$`).
2. **Observability-guided optimiser** — a surrogate/Bayesian or contextual-bandit search that uses
   the *observed telemetry* of evaluated configs to predict promising next configs.
3. **Baselines** — telemetry-blind: default config, random search, grid; (and the surrogate
   without telemetry features, as an ablation).
4. **Metrics** — trials-to-target-SLO (speed-up), Pareto hypervolume, regret vs the known optimum.

Output: `rqO_optimisation.csv`, `rqO_pareto.png`. Largest net-new surface; isolated under
`ml/optimise/` so it does not disturb the detection pipeline.

**References (~23):** observability-/telemetry-driven performance engineering, software
configuration tuning (incl. the template), autoscaling & resource right-sizing, self-adaptive
systems (MAPE-K), Bayesian optimisation / RL / bandits for systems, multi-objective & Pareto
optimisation, AIOps for optimisation (not just detection).

---

## Build order & status

1. **RQ-A** (Easy) — implement first; validates the degradation harness + plotting.
2. **RQ-D** (Hard) — generator ramp + SLO timestamp + forecaster + lead-time metric.
3. **RQ-O** (Medium–Hard) — new `ml/optimise/` subsystem.
4. **References** — ~70 verified (WebSearch→DBLP/Crossref), per the clusters above.
5. **Dissertation reframe** — new title/aim, RQ statements, methodology + results chapters; RQ1–4
   demoted to legacy/appendix.

Each experiment writes CSV+figure into `aiops/data/results/` and is runnable via a documented CLI,
consistent with the existing `run_experiment` / `online_vs_offline` harnesses.

---

## Results so far (experiments implemented & run)

All three experiment modules are implemented and produce real, thesis-supporting results.

### RQ-A — robustness (`ml/experiments/robustness.py` → `rqA_robustness.csv`)
Clean C4 F1 = **0.993**. Detection degrades **gracefully** with trace sampling
(F1 0.99→0.81 from 100%→5% sampling) and noise (robust to σ=0.2, falls at σ=0.4), but the
**modality-dropout fragility ranking is decisive: traces ΔF1 = 0.18, logs 0.001, events 0.000**.
→ *The single most valuable signal (traces) is also the most fragile* — a new, citable finding
that complements the old RQ3.

### RQ-D — early detection / lead-time (`ml/experiments/early_detection.py` → `rqD_leadtime.csv`)
With a gradual fault ramp and SLO breach at median window 11: the **reactive** detector gives a
median **1-window** lead (66% early-warning, 0% false alarms); the **proactive forecaster** gives a
median **2-window** lead (89% early-warning) at the cost of a **9%** false-alarm rate.
→ *Forecasting buys earlier warning along a clear earliness↔precision trade-off.*

### RQ-O — observability-cost optimisation for detection (`ml/experiments/optimise.py` → `rqO_obs_cost.csv`)
*(Reframed to stay directly on the detection topic: optimise the **observability configuration**,
not the system.)* Sweep 20 configurations = modality subset (metrics always on; logs/traces/events
on/off) × trace-sampling rate, scoring detection F1 against a telemetry cost (traces are the
expensive pillar, scaled by sampling). Findings on the **F1-vs-cost Pareto front**:
- **Full MELT is Pareto-optimal but only at the extreme** (cost 7.8, F1 0.994 — the highest F1).
- **Knee = metrics+traces** (cost 6.0, F1 0.991) — **23% cheaper than full MELT for −0.003 F1**.
- **Logs never reach the efficient frontier** (M+L configs are dominated); **traces dominate**.
- **Sampling slashes cost cheaply**: M+T+E at 10% trace sampling reaches F1 0.96 at cost 1.8 —
  **~97% of full-MELT F1 at ~23% of its cost**.
→ *"More observability is better" is true only at the high-F1 extreme; for almost any budget a
traces-centric, sampled configuration dominates.* This answers the dissertation's core question as
a cost-optimisation and yields a concrete minimum-viable-observability recommendation.

**Run all three:**
```
python -m ml.experiments.robustness      --episodes 200 --out data/results
python -m ml.experiments.early_detection --episodes 300 --out data/results
python -m ml.experiments.optimise        --episodes 200 --out data/results
```
