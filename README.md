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
> - **Reproduce them:** [Reproduce everything](#reproduce-everything) regenerates
>   every number and figure in Chapter 5 with `make experiments`.
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
| `error_spans` is high **iff** `(fault != "normal" and is_origin)` | [`aiops/collectors/telemetry.py`](aiops/collectors/telemetry.py) | `is_origin` **is** the ground-truth label RQ2 must predict, so the ranking feature is the answer key. **RQ2 is withdrawn** — see below. |

The corrected experiments are the first items of future work: a **live campaign**
through the `TF_LIVE=1` path, and a generator in which error spans **propagate**
along the call path so the origin is identifiable only as the *root of the error
tree*, and only noisily.

### Research questions (each is runnable code)

| RQ | Question | Where |
|----|----------|-------|
| **RQ1** | Does richer telemetry (metrics → +logs → +traces → +events, C1–C4) improve detection under non-stationarity? | `aiops/ml/experiments/run_experiment.py` |
| **RQ2** | What does distributed tracing add to root-cause localisation on a deep call graph? ⚠️ **withdrawn — circular** | `aiops/ml/experiments/run_experiment.py` |
| **RQ3** | Does the *learning paradigm* matter under drift — static vs. periodic-retrain vs. online-adaptive? (+ operational cost) | `aiops/ml/experiments/online_vs_offline.py`, `cost_compare.py` |
| **RQ3+** | Trivial floor, oracle threshold-recalibration control, and seed variance | `aiops/ml/experiments/baselines_and_seeds.py` |
| **RQ4** | Which model family (RF / GB / XGBoost / LSTM / multimodal fusion) best exploits full MELT? | `aiops/ml/experiments/run_experiment.py` |

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

**RQ2 — ⚠️ WITHDRAWN.** The reported result (top-1 localisation 0.769 → **1.000**
with traces) is **circular**: the ranking feature `error_spans` is assigned by the
generator from `is_origin`, which *is* the ground-truth label the localiser must
recover. A perfect score at every *k* is arithmetic, not evidence. It measures the
generator, not the method, and no conclusion about distributed tracing may be drawn
from it. The files are retained so the defect is inspectable. What survives is the
C2 row (0.769 top-1, not saturating even at top-3 on *n* = 39 episodes), which does
show that a depth-four topology makes latency-based attribution genuinely ambiguous.

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

**RQ4 — ensemble trees lead on full MELT (C4):** GB 0.988, RF 0.986, XGB 0.984
(differences smaller than the seed spread — no ordering claimed); multimodal fusion
0.891 (high-precision, low-recall). The **LSTM (0.259) is a mis-specified
comparison, not a negative result**: it scores *below* the always-alarm floor,
because the stream interleaves per-service windows and so carries almost no temporal
structure for a sequential model to exploit. A per-service sequential representation
was not evaluated. No claim is made about temporal models.

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
| **Experiments** — RQ1 / RQ2 / RQ4 | [`aiops/ml/experiments/run_experiment.py`](aiops/ml/experiments/) |
| **Experiments** — RQ3 online-vs-offline + cost | [`aiops/ml/experiments/online_vs_offline.py`](aiops/ml/experiments/), [`cost_compare.py`](aiops/ml/experiments/) |
| **Experiments** — trivial floor, oracle recalibration control, seed variance | [`aiops/ml/experiments/baselines_and_seeds.py`](aiops/ml/experiments/) |
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
make setup          # install Python dependencies (aiops/requirements.txt)
make experiments    # RQ1, RQ2, RQ4 + RQ3 online-vs-offline + cost + figures
make test           # invariant tests (8) + microservice tests (35)
# faster smoke run:  make quick
```

Equivalent without `make`:

```bash
cd aiops && pip install -r requirements.txt
bash ./scripts/run_offline.sh 200          # RQ1 + RQ2 + RQ4
bash ./scripts/run_online_offline.sh 320   # RQ3 detection + cost + figures
pytest tests/ -q                           # 8 passed

# the supplementary controls (trivial floor, oracle recalibration, 5 seeds)
python -m ml.experiments.baselines_and_seeds --seeds 42,43,44,45,46 --configs C1,C2,C3,C4
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
TF_LIVE=1 PROM_URL=http://localhost:9090 LOKI_URL=... TEMPO_URL=... \
  python -m ml.experiments.run_experiment
```

This collects genuine telemetry through PromQL/LogQL/TraceQL instead of generating
it. **A full drifted campaign through this path is the study's principal outstanding
experiment** — it is what would test the generator's load-bearing assumption that the
error signals do not drift, measure what distributed tracing actually contributes, and
establish how much of the static model's collapse survives production noise.

## Where the evidence lives

Outputs are written to (and a frozen copy is committed under)
[`aiops/data/results/`](aiops/data/results/):

| File | Underpins |
|------|-----------|
| `rq1_completeness.csv` | Table 5.1 (detection vs C1–C4) |
| `rq2_localisation.csv` | Table 5.2 (top-*k* RCA) — ⚠️ **withdrawn result**; retained so the defect is inspectable |
| `rq3_online_vs_offline.csv` | Tables 5.3–5.5 (per-regime F1 by policy) |
| `rq3_baselines.csv` | Table 5.7 (always-alarm floor + **oracle threshold-recalibration control**) |
| `rq3_seeds.csv`, `rq3_seeds_summary.json` | Table 5.6 (seed variance over 5 runs) |
| `rq3_cost.csv` | Table 5.8 (latency, model size, retained buffer, CPU) |
| `rq3_timeline.csv` | Figure 5.2 (rolling F1 over the drifting stream) |
| `rq4_model_family.csv` | Table 5.9 (model-family comparison on C4) |
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
