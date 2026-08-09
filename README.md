# TraceFlix — Supporting Evidence for the MSc Dissertation

**_Does Observability Matter in Cloud-Native Systems? An Empirical Study on
Real-Time Anomaly Detection_**
Ngoc Duc Anh Nguyen · Supervisor: Dr Satish Kumar · School of Built Environment,
Engineering and Computing, Leeds Beckett University · MSc Advanced Computer
Science · July 2026

---

> ### 📋 For the supervisor / examiner
>
> This repository **is the submitted evidence** for the dissertation — the source
> code, the experiment harness, the raw and analysed data, and the result figures
> — all in one place and reproducible with a single command. The dissertation
> refers you here in place of a bulky code appendix.
>
> - **⚠️ Read [How the data is generated](#how-the-data-is-generated-read-this-first) first.**
>   The reported results are produced by a **telemetry simulator**, not collected
>   from the running cluster. That is a deliberate design choice with real costs,
>   and it is declared here, in §3.3 of the dissertation, and on slide 7 of the viva.
> - **Just want the results?** They are committed under
>   [`aiops/data/results/`](aiops/data/results/) (CSV datasets + PNG figures) — see
>   [Where the evidence lives](#where-the-evidence-lives).
> - **Reproduce them:** [Reproduce everything](#reproduce-everything). `make experiments`
>   regenerates the RQ1/RQ2/RQ3/cost tables and the figures in minutes; `make controls`
>   adds the four supplementary controls (floor + seeds, drift sweep, streaming
>   baselines, component ablation) and takes hours. `make experiments-full` runs both.
> - **Want the full guided tour?** [`DEMO.md`](DEMO.md) walks the whole project
>   end-to-end across three self-contained tracks.
> - Every claim in Chapter 5 maps to a file here — see the [evidence map](#repository-structure--evidence-map).

---

## The study in one paragraph

On clean, stationary telemetry every anomaly detector looks excellent
(F1 ≈ 0.99). The moment a cloud-native system *operates* — a deploy regresses
latency, autoscaling changes throughput, data growth raises memory — the
telemetry baseline **drifts**, and a detector trained once on a snapshot decays
to F1 ≈ 0.36, flagging the *new normal* as anomalous. This project builds a real
nine-service microservice mesh on Kubernetes, and a simulator calibrated to the
telemetry that mesh emits, and uses the simulator to cross **telemetry
completeness** (C1–C4) with the **learning paradigm** (static / periodic / online)
under controlled fault injection and controlled drift. The finding: **telemetry
completeness raises the attainable ceiling, but only continual (online) learning
realises it.** A frozen model collapses to ≈ 0.36 — barely above the 0.29 an
*always-alarm* detector scores — and it collapses by the same amount whether you
give it 10 features or 23. Telemetry cannot compensate for staleness, and neither
can re-thresholding.

## How the data is generated (read this first)

The pipeline has **two interchangeable telemetry backends behind one `Window`
schema** ([`aiops/collectors/telemetry.py`](aiops/collectors/telemetry.py)):

- **`LIVE`** (`TF_LIVE=1`) — issues PromQL / LogQL / TraceQL against the deployed
  Prometheus, Loki and Tempo. Implemented and working.
- **`_synth`** (**the default**) — emits the same schema from a parameterised
  model: each fault type applies a fixed multiplicative shift to the affected
  signals, each drift regime applies a fixed shift to the operating-point signals,
  both with Gaussian noise.

**Every number reported in the dissertation comes from `_synth`.** The results are
*generated*, not *measured*. The nine-service Kubernetes mesh is real and runs —
it supplies the schema, the topology, the propagation structure and the fault
taxonomy, and the live path proves the pipeline works end-to-end on genuine
telemetry — but the reported campaign was not collected through it.

**Why.** The design needs 16 cells that each see an *identical* fault schedule and
an *identical* drift onset. Real drift is unscheduled and real faults do not recur
identically, so on live data a reversal between cells could never be attributed to
the manipulated factors. Internal validity was bought deliberately, and paid for in
external validity: **the absolute numbers are optimistic and do not transfer — only
the ordering does.**

**Two generator choices participate in the findings, and are discounted in the write-up:**

| Choice | Where | Consequence |
|---|---|---|
| The error / error-span signals are held **outside** the drift transformation (`_DRIFT_FIELDS`) | [`aiops/ml/drift.py`](aiops/ml/drift.py) | This is largely *why* traces look drift-robust. A defensible assumption — an error rate is more nearly scale-free than a latency percentile — but it is an **input**, not a discovery. RQ1's trace magnitude is discounted accordingly. |
| In the **base** generator (`generate_run`, used for detection) `error_spans` is high **iff** `(fault != "normal" and is_origin)` | [`aiops/collectors/telemetry.py`](aiops/collectors/telemetry.py) | `is_origin` **is** the ground-truth label, so on this generator a localisation feature is the answer key. RQ2's circular first attempt ran here; it is superseded. Detection (RQ1/RQ3/RQ4) never ranks services, so it is unaffected. |
| In the **propagating** generator (`generate_rca_run`, used for RQ2) errors attenuate 0.6 per hop up the call path | [`aiops/ml/dataset.py`](aiops/ml/dataset.py) | The rebuild: every service on the path emits error spans and the origin must be *inferred* as the root of the error tree. Attenuation rate and the background-error rate β are **inputs** — RQ2's magnitudes move with them, so RQ2 is answered in **direction** and bounded in magnitude. |

The outstanding experiment is the first item of future work: a **live campaign**
through the `TF_LIVE=1` path, which is what would test the generator's load-bearing
assumption that the error signals do not drift, and locate a real mesh on RQ2's β
sweep — the single measurement that would turn RQ2's direction into a magnitude.

**One measured result now exists, and it is deliberately small.**
`aiops/ml/experiments/live_replay.py` reconstructs a recorded fault-injection campaign
from historical PromQL — each query evaluated *at* the instant its window represents —
and scores a RandomForest at C1 on it: **F1 0.700** (AUC 0.967) over 450 windows from
12 episodes, against that campaign's own always-alarm floor of 0.144. It is **C1 only**
(the log, trace and event collectors are not time-parameterised, so it says *nothing*
about the contested trace increment), origin-only labelled, and far too short to carry
a confidence interval. Treat it as proof the pipeline runs end-to-end on genuine
telemetry — not as evidence about any number below.

### Research questions (each is runnable code)

| RQ | Question | Where |
|----|----------|-------|
| **RQ1** | Does richer telemetry (metrics → +logs → +traces → +events, C1–C4) improve detection under non-stationarity? | `aiops/ml/experiments/run_experiment.py` |
| **RQ2** | What does distributed tracing add to root-cause localisation on a deep call graph? (rebuilt on the propagating generator after a circular first attempt) | `aiops/ml/experiments/rq2_localisation.py` |
| **RQ3** | Does the *learning paradigm* matter under drift — static vs. periodic-retrain vs. online-adaptive? (+ operational cost) | `aiops/ml/experiments/online_vs_offline.py`, `cost_compare.py` |
| **RQ3+** | Trivial floor, oracle threshold-recalibration control, and seed variance | `aiops/ml/experiments/baselines_and_seeds.py` |
| **RQ3+** | *How far* must the baseline move before a frozen boundary must be refit? | `aiops/ml/experiments/drift_sweep.py` |
| **RQ3+** | Which of the online detector's mechanisms earns its place? | `aiops/ml/experiments/baseline_streaming.py`, `ablate_online.py` |
| **RQ1+** | Does any of it hold on *measured* telemetry? (C1 pilot) | `aiops/ml/experiments/live_replay.py` |
| **RQ4** | Which model family (RF / GB / XGBoost / LSTM / fusion / local LLM) best exploits full MELT? | `aiops/ml/experiments/run_experiment.py`, `score_llm.py` |

## Headline results

Deterministic run (seed 42), with the RQ3 headline additionally repeated over
**five seeds**; these are the numbers reported in Chapter 5. Anomaly prevalence on
the scored stream is **0.171**, so an *always-alarm* detector scores **F1 = 0.292**
— that is the floor every number below should be read against.

**RQ1 — detection F1 rises with completeness.**

| Config | Held-out reference | Drifted future stream (deployable detector) |
|--------|:---:|:---:|
| C1 Metrics-only | 0.896 | 0.813 |
| C2 + Logs | 0.915 | 0.827 |
| C3 + Traces | **0.985** | **0.974** |
| C4 Full MELT | 0.986 | 0.976 |

Logs add little; events + history (C3→C4) add essentially nothing. The **trace
increment is discounted** — the generator both sharpens the trace signal and
exempts it from drift, so its magnitude is partly constructed. Direction credible,
magnitude not claimed as a measurement.

**RQ2 — traces help localisation, but nothing is perfect** (top-1 accuracy, 5 seeds,
~120 fault episodes each; random-guess floor **0.111**):

| Ranking | Signal | quiet mesh (bg 0.0) | bg 0.1 | bg 0.25 | bg 0.5 |
|---|---|:---:|:---:|:---:|:---:|
| flat | C2 metrics+logs | 0.387 | 0.359 | 0.337 | 0.340 |
| flat | C3 + traces | 0.626 | **0.563** | 0.496 | 0.456 |
| graph-aware | C2 metrics+logs | 0.446 | 0.391 | 0.274 | 0.207 |
| graph-aware | C3 + traces | *1.000* | **0.736** | 0.486 | 0.335 |

**Traces contribute, and the contribution is robust** — +0.20 top-1 at a 10 %
background-incident rate, positive at every rate against seed spreads of 0.02–0.05,
and no metrics-and-logs arm passes 0.45. That is the answer to RQ2, reached by a
controlled ablation rather than by varying the model. `bg` (β) is the per-episode
probability that a service *off* the fault's call path errors on its own account —
the realism knob. The *1.000* at bg = 0.0 is a **boundary condition, not a result**:
a mesh with a single error path has a unique root by construction, and one unrelated
incident in ten drops it to 0.736. And **structural reasoning is not free** —
graph-awareness dominates on a quiet mesh but *inverts* against flat ranking by
bg = 0.5 (0.335 vs 0.456), because it rewards any erroring service with clean
dependencies and a background incident is exactly that. RQ2 is therefore **answered
in direction and bounded in magnitude**: the magnitudes belong to the
parameterisation, and β's production value is unknown.

> **RQ2 took two attempts, and the first is on the record.** It reported top-1
> 0.769 → **1.000** with traces and was **circular**: it ran on the *base* generator,
> where `error_spans` is gated on `is_origin` — the ground-truth label the localiser
> must recover — so the ranking feature was the answer key. The generator was rebuilt
> (`generate_rca_run`: errors propagate up the call path, attenuating 0.6 per hop)
> and the experiment re-run; the table above is that re-run. `rq2_localisation.csv`
> is retained so the defect stays inspectable. Full account:
> [`DemoRQ2.md`](DemoRQ2.md); §5.2 of the dissertation reports it the same way.

**RQ3 — the learning paradigm is what matters under drift** (F1 on the drifted
future stream, 25,920 windows):

| Config | Always-alarm | Static (frozen) | Static + **oracle** re-threshold | Periodic retrain | **Online adaptive** |
|--------|:---:|:---:|:---:|:---:|:---:|
| C1 Metrics-only | 0.292 | 0.360 | 0.446 | 0.820 | 0.813 |
| C2 + Logs | 0.292 | 0.361 | 0.437 | 0.832 | 0.827 |
| C3 + Traces | 0.292 | 0.370 | 0.552 | 0.925 | **0.974** |
| C4 Full MELT | 0.292 | 0.371 | 0.553 | 0.925 | **0.976** |

The frozen static model collapses to ≈ 0.36 **regardless of how much telemetry it
is given** — the failure is the paradigm, not the signal.

**And you cannot fix it by moving the threshold.** Granting the frozen model the
*best decision threshold obtainable on the drifted stream itself* — chosen knowing
the test labels, an **oracle** no deployment could achieve — recovers it only to
0.45–0.55. The boundary is the wrong **shape**, not merely in the wrong **place**;
drift *deforms* the normal region, and no scalar undoes a deformation. This is the
control that answers the strongest objection to the thesis
(`rq3_baselines.csv`).

**Seed variance** (5 seeds, `rq3_seeds.csv`) — the ordering is not seed-dependent:

| Config | static | periodic | online | online − periodic |
|---|:---:|:---:|:---:|:---:|
| C1 | 0.359 ± 0.020 | 0.808 ± 0.012 | 0.811 ± 0.006 | +0.003 *(tied)* |
| C2 | 0.360 ± 0.021 | 0.821 ± 0.013 | 0.822 ± 0.006 | +0.001 *(tied)* |
| C3 | 0.363 ± 0.017 | 0.918 ± 0.006 | 0.974 ± 0.002 | **+0.055** |
| C4 | 0.365 ± 0.017 | 0.919 ± 0.006 | 0.976 ± 0.002 | **+0.057** |

The static-vs-adaptive collapse is 20–90 σ wide. Under **thin** telemetry online and
periodic are **tied** (the single-seed 0.007 gap was noise); the online advantage is
real only once traces are present. Online costs more steady-state CPU but delivers
far lower worst-case (refit-stall) latency, a ~100× smaller model, and zero retained
training data (`rq3_cost.csv`).

> **Caveat on the paradigm comparison.** `offline_static` and `offline_periodic` are
> Random Forests; `online_adaptive` is a linear SGD model with an adaptive
> normaliser — it *must* be, since no batch learner updates one window at a time. So
> online-vs-periodic compares two **detectors**, not two paradigms in the abstract.
> The claim rests instead on **static-vs-periodic**: same model family, same
> features, same preprocessing, differing only in whether it refits — **0.36 frozen,
> 0.92 refitted.**

**How far must the baseline move?** (`rq3_drift_sweep.csv`) Every figure above is
measured at *one* drift amplitude — and that amplitude was set comparably to the fault
signatures themselves, so a frozen boundary is bound to fail at it. Rescaling every
regime multiplier toward 1 (holding the fault schedule identical) turns the point into
a curve:

| R3 operating-point shift | 1.00× | 1.15× | 1.29× | 1.49× | 1.97× | 2.26× |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| static (C4) | **0.989** | 0.933 | 0.769 | 0.546 | 0.370 | 0.341 |
| periodic (C4) | 0.985 | **0.982** | 0.974 | 0.954 | 0.925 | 0.921 |
| online (C4) | 0.977 | 0.977 | **0.977** | **0.976** | **0.976** | **0.976** |

Three things this bounds, in both directions. **Refitting starts to pay at a 1.15×
shift**, and the frozen model stops discriminating (falls below twice the trivial
floor) between **1.29× and 1.49×** — a number, not an assertion. **The failure is
gradual**, not a cliff: by 1.29× a detector has lost a fifth of its F1 while still
looking serviceable. And **on a stationary stream the frozen model is the *best* of the
three** while the online detector is the worst (0.815 vs 0.890 at C1). Continual
adaptation earns its cost because the baseline moves, not because it is continual.
The reported campaign sits at 1.97×.

**What the adaptive machinery is worth** (`rq3_streaming_baselines.csv`,
`rq3_online_ablation.csv`) — measured rather than assumed. Three canonical incremental
learners on the identical stream reach F1 **0.302–0.308 unnormalised at every
configuration**; behind a running standardiser the *same* learners reach **0.760–0.796
at C1** and **0.959–0.971 at C3**. **Adaptive normalisation is what carries the online
policy.** The detector's remaining margin over the best off-the-shelf scaled arm is
+0.017 (C1) and +0.003 (C3, inside the seed spread); of its own mechanisms the champion
pool is worth ≤ +0.013 and the drift monitor nothing anywhere. A standardised
incremental learner is a close substitute for the whole detector — which bounds what
the machinery may be credited with, and is why the load-bearing claim is the
static-vs-periodic one above.

**RQ4 — ensemble trees lead on full MELT (C4):** GB 0.988, RF 0.986, XGB 0.984
(differences smaller than the seed spread — no ordering claimed); multimodal fusion
0.891 (high-precision, low-recall). A sixth family, the **local-LLM detector**
(Qwen2.5-3B reading *raw* signals rather than engineered features), reaches **0.440** —
above the always-alarm floor, far below every tree: a working detector here, not a
competitive one. The **LSTM (0.227) is a mis-specified comparison, not a negative
result**: it scores *below* the always-alarm floor, because the stream interleaves
per-service windows and so carries almost no temporal structure for a sequential model
to exploit. A per-service sequential representation was not evaluated. No claim is made
about temporal models.

> The six-family table is scored on a common **3,000-window** subsample
> (`results_uniform/` + `results_llm/`), because the LLM costs seconds per window; the
> five-family numbers quoted above come from the full held-out split in `results/`. A
> family appearing in both differs in the third decimal — expected, not drift.

## The nine-service mesh

```
gateway ─┬─► movie ──► actor, review            (original subtree, unchanged)
         ├─► user ───► recommendation ─► catalog
         │         └─► auth
         └─► search ─────────────────► catalog   (shared fan-in; depth 4)
```

Data owners (`catalog`, `auth`, `user`) persist with Spring Data JPA + H2 + seed
data; orchestrators (`gateway`, `search`, `recommendation`) call downstreams with
`RestClient`. Every service has real business logic, so a fault deep in the graph
propagates latency up *every* ancestor — which is what makes root-cause
attribution non-trivial and RQ2 discriminating. The synthetic generator and the
live collectors emit an identical `Window` schema, so the entire RQ1–RQ4 analysis
runs unchanged offline or live. The topology lives in one file:
[`aiops/ml/configs.py`](aiops/ml/configs.py).

## Repository structure / evidence map

| Evidence (as required by the dissertation) | Location |
|--------------------------------------------|----------|
| **Code** — nine-service microservice mesh (Spring Boot 3.5 / Java 21) | [`services/`](services/) |
| Mesh topology / configuration (single source of truth) | [`aiops/ml/configs.py`](aiops/ml/configs.py) |
| Telemetry feature engineering + `Window` schema; live collectors | [`aiops/ml/`](aiops/ml/), [`aiops/collectors/telemetry.py`](aiops/collectors/) |
| Fault injection (offline + live / Pumba) and ground-truth labelling | [`aiops/faults/`](aiops/faults/), [`deploy/virtfusion/inject-fault.sh`](deploy/virtfusion/) |
| **Experiments** — RQ1 / RQ4 | [`aiops/ml/experiments/run_experiment.py`](aiops/ml/experiments/) |
| **Experiments** — RQ2 localisation on the propagating generator | [`aiops/ml/experiments/rq2_localisation.py`](aiops/ml/experiments/), [`aiops/ml/dataset.py`](aiops/ml/dataset.py) (`generate_rca_run`) |
| **Experiments** — RQ3 online-vs-offline + cost | [`aiops/ml/experiments/online_vs_offline.py`](aiops/ml/experiments/), [`cost_compare.py`](aiops/ml/experiments/) |
| **Experiments** — trivial floor, oracle recalibration control, seed variance | [`aiops/ml/experiments/baselines_and_seeds.py`](aiops/ml/experiments/) |
| **Experiments** — operational cost, one seed and across five | [`aiops/ml/experiments/cost_compare.py`](aiops/ml/experiments/), [`cost_seeds.py`](aiops/ml/experiments/) |
| **Experiments** — drift-magnitude sweep (how far the baseline must move) | [`aiops/ml/experiments/drift_sweep.py`](aiops/ml/experiments/), [`aiops/ml/drift.py`](aiops/ml/drift.py) (`scaled_regime_factors`) |
| **Experiments** — streaming baselines + online-detector component ablation | [`aiops/ml/experiments/baseline_streaming.py`](aiops/ml/experiments/), [`ablate_online.py`](aiops/ml/experiments/) |
| **Experiments** — live replay of a recorded campaign (the one measured result) | [`aiops/ml/experiments/live_replay.py`](aiops/ml/experiments/), [`aiops/data/labels_live.csv`](aiops/data/labels_live.csv) |
| **⚠️ The data-generating process** — judge the results here first | [`aiops/collectors/telemetry.py`](aiops/collectors/telemetry.py) (`_synth`), [`aiops/ml/drift.py`](aiops/ml/drift.py) (`_DRIFT_FIELDS`, `REGIME_FACTORS`) |
| **Data analysis** — result datasets (CSV) + figures (PNG) | [`aiops/data/results/`](aiops/data/results/) |
| Streaming (Kafka backbone) + local-LLM (Qwen2.5-3B) detector | [`aiops/streaming/`](aiops/streaming/), [`aiops/llm/`](aiops/llm/) |
| Streaming dashboard (web UI) | [`aiops/webui/`](aiops/webui/) |
| **Tests** — pipeline invariants (8) + service tests (35) | [`aiops/tests/`](aiops/tests/), `services/**/src/test` |
| Live deployment (Docker Compose, OTel, Prometheus/Loki/Tempo/Grafana) | [`deploy/virtfusion/`](deploy/virtfusion/), [`observability/`](observability/) |
| Guided end-to-end walkthrough | [`DEMO.md`](DEMO.md) |

## Reproduce everything

The repo-root **`Makefile`** automates the full pipeline (`make help` for all
targets). Requires Python 3 only — no cluster, no GPU.

```bash
make setup             # install Python dependencies (aiops/requirements.txt)
make experiments       # = rq124 + rq2 + rq3 + cost + plots      (minutes)
make controls          # = seeds + sweep + baselines + ablation  (hours)
make experiments-full  # both, in order
make test              # invariant tests (8) + microservice tests (35)
# faster smoke run:  make quick
```

The **controls** are separate from `make experiments` because they cost hours where
`experiments` costs minutes — `sweep` alone regenerates the drift stream eight times
per configuration. Run them individually when that is what you need:

| Target | Regenerates | Writes to |
|---|---|---|
| `make seeds` | always-alarm floor, oracle re-threshold, five-seed variance | `data/results/rq3_{baselines,seeds}*` |
| `make sweep` | the drift-magnitude curve | `data/results_drift_sweep/` |
| `make baselines` | off-the-shelf incremental learners, raw vs standardised | `data/results_baselines_scaled/` |
| `make ablation` | the detector with its own mechanisms switched off | `data/results_ablation/` |
| `make live-replay` | the C1 live pilot (needs `TF_LIVE` + a reachable Prometheus) | `data/results_live/` |
| `make cost-seeds` | the five-seed cost **ranges** (`cost_compare` once per seed) | `data/results/rq3_cost_seeds*`, `data/results_cost_seeds/` |
| `make cost-seeds-agg` | re-derives those ranges from per-seed tables already on disk — seconds, fits nothing | `data/results/rq3_cost_seeds*` |

Each control writes to its **own** directory, so none of them can overwrite the
committed artefacts in `data/results/` by accident.

> **Wall-clock does not reproduce, and is not claimed to.** `make cost-seeds` re-times
> everything on your machine, so `tail_ratio` and `cpu_ratio` will not match the
> committed numbers to the decimal — which is exactly why the write-up quotes an
> order-of-magnitude tail gap rather than a millisecond. The structural columns (refit
> count, retained windows, model size) do reproduce exactly, and `make cost-seeds-agg`
> is fully deterministic: against the committed per-seed tables it reproduces
> `rq3_cost_seeds.csv` and its summary **byte-for-byte**.

Equivalent without `make`:

```bash
cd aiops && pip install -r requirements.txt
bash ./scripts/run_offline.sh 200          # RQ1 + RQ4 (+ RQ2's first attempt)
bash ./scripts/run_online_offline.sh 320   # RQ3 detection + cost + figures
pytest tests/ -q                           # 8 passed

# RQ2 — propagating generator, 4 arms x 4 background rates x 5 seeds
python -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46 --episodes 200

# the supplementary controls (trivial floor, oracle recalibration, 5 seeds)
python -m ml.experiments.baselines_and_seeds --seeds 42,43,44,45,46 --configs C1,C2,C3,C4

# RQ3 controls — how far the baseline must move, and what the machinery is worth
python -u -m ml.experiments.drift_sweep        --episodes 320 --configs C1,C4 --out data/results_drift_sweep
python -u -m ml.experiments.baseline_streaming --episodes 320 --out data/results_baselines_scaled
python -u -m ml.experiments.ablate_online      --episodes 320 --out data/results_ablation
```

> Windows PowerShell: run from `aiops/` (or set `$env:PYTHONPATH = (Resolve-Path .).Path`)
> so `python -m …` resolves the package.

Within a seed the stream is generated deterministically, and the feature extractor,
fault schedule, load profile, regime sequence and seed are identical across all 16
cells — so cross-cell differences reflect configuration and learning policy, not
stochastic training variation. The RQ3 headline is additionally repeated over five
seeds (above).

### Running it against the *real* cluster

The live path is implemented. Bring the mesh up (see [`DEPLOYMENT.md`](DEPLOYMENT.md)),
then:

```bash
# collect live telemetry now, through PromQL/LogQL/TraceQL instead of generating it
TF_LIVE=1 PROM_URL=http://localhost:9090 LOKI_URL=... TEMPO_URL=... \
  python -m ml.experiments.run_experiment

# or replay a *recorded* campaign: historical PromQL joined to the injected labels
TF_LIVE=1 PROM_URL=http://localhost:9090 \
  python -u -m ml.experiments.live_replay --labels data/labels_live.csv \
  --out data/results_live
```

The replay path exists because `run_experiment`'s live branch collects *present-moment*
telemetry: without the `at` timestamp now threaded through `collect_metrics_live`, every
window of a past episode would be filled with current values and silently mislabelled.
Only the **metric** collector is time-parameterised, so replay is **C1 only** —
attempting C2–C4 would mix present values into a past window with nothing downstream to
catch it.

**A full drifted campaign through this path is still the study's principal outstanding
experiment** — it is what would test the generator's load-bearing assumption that the
error signals do not drift, measure what distributed tracing actually contributes, and
establish how much of the static model's collapse survives production noise. The
12-episode C1 pilot above establishes feasibility, and nothing more.

## Where the evidence lives

Outputs are written to (and a frozen copy is committed under)
[`aiops/data/results/`](aiops/data/results/):

| File | Underpins |
|------|-----------|
| `rq1_completeness.csv` | Table 5.1 (detection vs C1–C4) |
| `rq2_localisation_propagating.csv`, `rq2_propagating_summary.json` | Table 5.2 (top-*k* RCA, propagating generator × background rate × 5 seeds) |
| `rq2_localisation.csv` | RQ2's circular first attempt — superseded, retained so the defect is inspectable |
| `rq3_online_vs_offline.csv` | Tables 5.3–5.5 (per-regime F1 by policy) |
| `rq3_baselines.csv` | Table 5.7 (always-alarm floor + **oracle threshold-recalibration control**) |
| `rq3_seeds.csv`, `rq3_seeds_summary.json` | Table 5.6 (seed variance over 5 runs) |
| `rq3_cost.csv` | Table 5.8 (latency, model size, retained buffer, CPU) — **seed 42** |
| `rq3_cost_seeds.csv`, `rq3_cost_seeds_summary.json` | the five-seed cost spread — the source of every cost **range** quoted above (580–880 ms, ≤78 ms, 10–48×, ~120–390×, 4.1–4.8×) |
| `rq3_timeline.csv` | Figure 5.2 (rolling F1 over the drifting stream) |
| `rq4_model_family.csv` | Table 5.9 (model-family comparison on C4) |
| `../results_drift_sweep/rq3_drift_sweep.csv` | the drift-magnitude sweep — F1 against operating-point shift |
| `../results_baselines_scaled/rq3_streaming_baselines.csv` | off-the-shelf incremental learners, raw vs standardised |
| `../results_ablation/rq3_online_ablation.csv` | the online detector with its own mechanisms switched off |
| `../results_live/rq1_live_c1.csv` | the live-replay pilot — the one result measured, not generated |
| `../results_uniform/` + `../results_llm/` | the six-family RQ4 table, all scored on the same 3,000-window subsample |
| `observability_melt.csv` | the generated MELT window dataset the analysis consumes |
| `figures/*.png` | the Chapter 5 result figures |

## Beyond offline — streaming, LLM, and live deployment

- **Streaming & LLM (no broker / GPU needed):** a Kafka event backbone feeds two
  detectors in parallel (online ML + a local Qwen2.5-3B LLM), with in-memory /
  heuristic fallbacks. See [`aiops/docs/KAFKA_LLM_ARCHITECTURE.md`](aiops/docs/KAFKA_LLM_ARCHITECTURE.md)
  and Track B of [`DEMO.md`](DEMO.md).
- **Live deployment (Docker):** the real nine-service mesh under Docker Compose
  with OpenTelemetry, Grafana/Tempo/Loki/Prometheus, Pumba fault injection, and
  the experiments run against live PromQL/LogQL/TraceQL — see
  [`deploy/virtfusion/README.md`](deploy/virtfusion/README.md) and Track C of
  [`DEMO.md`](DEMO.md).
- **Live deployment (local Kubernetes, one command):** bring up the full
  nine-service mesh + observability stack in the `on-demand-observability`
  namespace on Docker Desktop's Kubernetes with `make run-platform` — see
  [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Further documentation

- [`DEPLOYMENT.md`](DEPLOYMENT.md) — one-command local Kubernetes bring-up
  (Windows / Docker Desktop): the nine-service mesh + observability stack.
- [`DEMO.md`](DEMO.md) — guided three-track walkthrough of the whole project.
- [`aiops/README.md`](aiops/README.md) — the experiment layer in depth.
- [`aiops/docs/`](aiops/docs/) — integration/data-flow, mesh expansion, the online
  pipeline, and the Kafka/LLM architecture.

## Author

Ngoc Duc Anh Nguyen — MSc Advanced Computer Science, Leeds Beckett University.
Supervised by Dr Satish Kumar. All third-party tooling is open-source.

## Licence

Released under the MIT Licence — see [`LICENSE`](LICENSE). Third-party
dependencies remain under their own licences.
