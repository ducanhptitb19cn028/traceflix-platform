# `data/results/` — generated artefacts

Everything in this directory is **generated output** — produced by the
experiment scripts, not hand-edited. Regenerate it any time with the commands in
[`../../README.md`](../../README.md) (offline) or the per-experiment commands
below. Files are keyed by research question (RQ1–RQ4).

> ### ⚠️ Data source — the committed results are **generated, not measured**
>
> The files committed here were produced by the **synthetic generator** (`_synth` in
> [`../../collectors/telemetry.py`](../../collectors/telemetry.py)), which is the
> **default** backend. The *live* path (`TF_LIVE=1`,
> `scripts/run_live_experiment.sh`) queries the deployed Prometheus / Loki / Tempo
> and emits the identical `Window` schema — but the reported campaign was **not**
> run through it.
>
> The RQ3 files use the **non-stationary drift stream** (regimes R0→R3;
> [`../../ml/drift.py`](../../ml/drift.py)), because the online-vs-offline contrast
> requires a drifting baseline.
>
> **Two generator properties bear directly on the results and are declared in §3.3
> of the dissertation:**
>
> 1. `_DRIFT_FIELDS` (in `drift.py`) **excludes the error / error-span signals** from
>    the drift transformation. This is largely why traces appear drift-robust in RQ1
>    and RQ3. It is a modelling assumption — an **input**, not a finding.
> 2. Two generators live in `ml/dataset.py`, and RQ2 depends on which one it runs on.
>    In the **base** generator (`generate_run`, used by the detection RQs) `error_spans`
>    is high **iff** `(fault != "normal" and is_origin)` — and `is_origin` **is** the
>    ground-truth label a localiser must recover, so the RQ2 ranking feature was the
>    answer key. **`rq2_localisation.csv` is therefore RQ2's circular first attempt**,
>    superseded and retained only so the defect is inspectable. The **propagating**
>    generator (`generate_rca_run`) is the rebuild: errors travel up the call path
>    attenuating 0.6 per hop, so every service on the path emits spans and the origin
>    must be inferred as the root of the error tree.
>    `rq2_localisation_propagating.csv` is the **reported** RQ2 result. Its attenuation
>    rate and background-error rate are **inputs** — the ordering transfers, the
>    magnitudes do not.
>
> Judge these results by reading `telemetry.py` and `drift.py` **before** the models.

## Observability input data (what the models consume)

| File | Description |
|------|-------------|
| `observability_data.xlsx` | The raw **MELT** telemetry behind RQ3, 3 sheets: **MELT_Windows** (11,520 windows × every metric/log/trace/event field + label + regime), **Features_C4** (the engineered feature matrix actually fed to the models), **Regime_Legend** (R0–R3 meanings). |
| `observability_melt.csv` | Flat CSV of the `MELT_Windows` sheet — same per-window telemetry, one row per (service, time-window). |

Produced by: `python -m ml.eval.export_observability --episodes 320 --out data/results`

## RQ1, RQ4 — completeness and model family (held-out reference)

| File | Description |
|------|-------------|
| `rq1_completeness.csv` | RQ1: detection metrics as observability grows C1→C4 (metrics → +logs → +traces → +events). The **trace increment is discounted** in the write-up — see the data-source note above. |
| `rq4_model_family.csv` | RQ4: model-family comparison (RF / GB / XGBoost / LSTM / fusion) under C4. The LSTM row is a **mis-specified comparison**, not a negative result — it scores below the always-alarm floor because the interleaved per-service stream carries almost no temporal structure. |
| `rq2_localisation.csv` | RQ2's **circular first attempt**, superseded by the propagating run below. The C3 rows (1.000 at every *k*) are an artefact: the ranking feature is derived from the label. Retained for inspection only; draw no conclusion from them. Even the C2 rows are flattered — ancestors there inherit latency but almost no errors. |
| `summary.json` | Machine-readable headline numbers for RQ1, RQ4 (and RQ2's first attempt). |

Produced by: `bash ./scripts/run_offline.sh 200`

## RQ2 — root-cause localisation on the propagating generator

| File | Description |
|------|-------------|
| `rq2_localisation_propagating.csv` | Top-*k* accuracy per (background rate, seed, arm). Four arms crossed: signal (**C2** metrics+logs vs **C3** +traces) × ranking (**flat** vs **graph-aware** root-of-the-error-tree), over 5 seeds and 4 background-incident rates (0.0 / 0.1 / 0.25 / 0.5). |
| `rq2_propagating_summary.json` | Mean ± sd per arm, plus generator settings (attenuation 0.6/hop, episodes, seeds) and the 1/9 = 0.111 random-guess floor. |

**How to read it.** `background` is the per-episode probability that a service *off*
the fault's call path errors on its own account — the realism knob. At `0.0` the mesh
carries exactly one error path, so its root is unique **by construction**; the C3 +
graph-aware 1.000 in that column is a boundary condition, not a result. Report
`background ≥ 0.1`. Headline top-1 there: C2 0.359, **C3 0.563** (flat); C2 0.391,
**C3 0.736** (graph-aware). Traces contribute a positive lift at every background
rate — the answer to RQ2, in direction. Graph-awareness helps only while the mesh is
quiet, and *inverts* against flat ranking by `background = 0.5` (0.335 vs 0.456)
because it cannot distinguish a real root from a spurious one.

Produced by:
`python -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46 --episodes 200`

## RQ3 — offline vs online detection under drift

| File | Description |
|------|-------------|
| `rq3_offline_vs_online_comparison.xlsx` | **The headline comparison**, 6 sheets: **Summary**/**Detection_F1** (config × model F1 + online-gain columns), **Detection_All** (precision/recall/F1/AUC per model), **PerRegime_F1** (F1 by regime R1–R3), **Cost** (latency/model-size/retained-data trade-off), **Timeline** (rolling F1 over the stream). |
| `rq3_online_vs_offline.csv` | Per-(config, segment, model) detection metrics — the raw table behind the workbook. |
| `rq3_timeline.csv` | Block-wise rolling F1 over the drifting stream, all models, tagged by regime. |
| `rq3_summary.json` | Headline F1 on the operational future + drift/adaptation event counts. |
| `rq3_cost.csv` | Cost comparison: per-window latency, train events, model size, retained training windows. |
| `rq3_cost_summary.json` | Machine-readable cost headlines. |

The four models compared: `offline_static` (train once on R0, frozen),
`offline_periodic` (scheduled retrain), `online_adaptive` (the streaming
`OnlineModel`), `offline_full` (oracle ceiling — trained across all regimes).

> **The paradigm comparison is confounded with model family.** `offline_static` and
> `offline_periodic` are Random Forests; `online_adaptive` is a linear SGD model with
> an adaptive normaliser — it *must* be, since no batch learner can be updated one
> window at a time. So `online` vs `periodic` compares two **detectors**, not two
> paradigms in the abstract. The clean, unconfounded contrast is
> **`offline_static` vs `offline_periodic`** (same family, same features, same
> preprocessing, differing only in whether it refits): **0.36 → 0.92**. That is the
> contrast the dissertation's central claim rests on.

Produced by: `bash ./scripts/run_online_offline.sh 320`, then
`python -m ml.eval.to_excel data/results` for the workbook.

## RQ3 supplementary — trivial floor, recalibration control, seed variance

| File | Description |
|------|-------------|
| `rq3_baselines.csv` | Per (seed, config): class **prevalence**, the **always-alarm** floor (flag every window), the frozen static model, and **static + oracle re-threshold** — the frozen model given the best decision threshold obtainable *on the drifted test stream itself*, chosen with knowledge of the test labels. |
| `rq3_seeds.csv` | Per (seed, config, policy): precision / recall / F1 / AUC over five independent seeds. |
| `rq3_seeds_summary.json` | Mean ± sd of the headline F1 per (config, policy), plus the floor and the recalibration means. |

**Why these exist.** Two controls the headline RQ3 comparison needed but did not report:

1. **The trivial floor.** Prevalence is 0.171, so always-alarm scores **F1 = 0.292**.
   Without it, "the static model collapses to 0.36" has no yardstick — it is in fact
   barely above a detector that ignores the data entirely.
2. **The recalibration control**, which answers the strongest objection to the thesis:
   *if the frozen model still ranks windows well (AUC 0.86) and only its cut-point is
   stale, why not just re-tune a threshold instead of learning online?* Measured rather
   than argued: an **oracle** threshold — unattainable in deployment, and an upper bound
   on any recalibration scheme — recovers the frozen model only to **0.44–0.56**, against
   the online detector's 0.97. The boundary is the wrong **shape**, not merely in the
   wrong **place**. Re-thresholding is not a substitute for re-learning.

Seed variance also corrected one single-seed claim: under **thin** telemetry (C1, C2)
online and periodic are **tied** (mean difference +0.003 and +0.001, well inside a
spread of ~0.012), not "periodic narrowly ahead". The online advantage is real only at
C3/C4 (+0.055, +0.057 — roughly nine standard deviations).

Produced by:
`python -m ml.experiments.baselines_and_seeds --seeds 42,43,44,45,46 --configs C1,C2,C3,C4`

## Figures

| File | Description |
|------|-------------|
| `figures/rq1_completeness.png` | RQ1 detection vs C1–C4. |
| `figures/rq2_localisation.png` | Top-k RCA from RQ2's **first attempt** — not the reported result. |
| `figures/rq4_model_family.png` | RQ4 model-family comparison. |
| `figures/rq3_online_vs_offline.png` | RQ3 F1 bars: static < periodic < online ≈ oracle. |
| `figures/rq3_timeline.png` | RQ3 rolling F1 over the drifting stream (the sawtooth = periodic's drift-response gap). |

Produced by: `python -m ml.eval.plots data/results`
