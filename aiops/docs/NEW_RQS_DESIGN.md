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

## RQ-O — Observability for performance optimisation  *(feasibility: Medium–Hard — new subsystem)*

**RQ-O.** *Beyond detecting failures, can observability data be used to **optimise** system
performance — i.e., to guide configuration/resource decisions toward better latency–cost
outcomes — and does telemetry-guided optimisation beat telemetry-blind baselines?*

This deliberately echoes the dissertation's structural template (Chen & Li, *"Do Performance
Aspirations Matter for Guiding Software Configuration Tuning?"*, TOSEM 2023): a multi-objective
(latency vs cost) search where the question is whether observed signals should *guide* the search.

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
