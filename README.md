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
> - **Read the thesis in ~6 minutes, no setup:** the [Reproduce everything](#reproduce-everything)
>   section regenerates every number and figure in Chapter 5 with `make experiments`.
> - **Just want the results?** They are committed under
>   [`aiops/data/results/`](aiops/data/results/) (CSV datasets + PNG figures) — see
>   [Where the evidence lives](#where-the-evidence-lives).
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
nine-service microservice mesh, injects controlled faults and drift, and shows
empirically that **telemetry completeness raises the attainable ceiling, but only
continual (online) learning realises it** — and that distributed tracing is the
single decisive signal for both detection and root-cause localisation.

### Research questions (each is runnable code)

| RQ | Question | Where |
|----|----------|-------|
| **RQ1** | Does richer telemetry (metrics → +logs → +traces → +events, C1–C4) improve detection under non-stationarity? | `aiops/ml/experiments/run_experiment.py` |
| **RQ2** | What does distributed tracing add to root-cause localisation on a deep call graph? | `aiops/ml/experiments/run_experiment.py` |
| **RQ3** | Does the *learning paradigm* matter under drift — static vs. periodic-retrain vs. online-adaptive? (+ operational cost) | `aiops/ml/experiments/online_vs_offline.py`, `cost_compare.py` |
| **RQ4** | Which model family (RF / GB / XGBoost / LSTM / multimodal fusion) best exploits full MELT? | `aiops/ml/experiments/run_experiment.py` |

## Headline results

Deterministic single run (fixed seed, nine-service mesh); these are the numbers
reported in Chapter 5.

**RQ1 — detection F1 rises with completeness; traces are the decisive increment.**

| Config | Held-out reference | Drifted future stream (deployable detector) |
|--------|:---:|:---:|
| C1 Metrics-only | 0.896 | 0.813 |
| C2 + Logs | 0.915 | 0.827 |
| C3 + Traces | **0.985** | **0.974** |
| C4 Full MELT | 0.986 | 0.976 |

**RQ2 — traces perfect localisation.** Top-1 root-cause accuracy rises from
**0.769** (metrics + logs) to **1.000** (+traces) on the deep mesh, where a
downstream fault raises latency in every ancestor.

**RQ3 — the learning paradigm is what matters under drift** (F1 on the drifted
future stream, 25,920 windows):

| Config | Static (traditional) | Periodic retrain | **Online adaptive** | Oracle (all-regimes) |
|--------|:---:|:---:|:---:|:---:|
| C1 Metrics-only | 0.360 | 0.820 | 0.813 | 0.812 |
| C2 + Logs | 0.361 | 0.832 | 0.827 | 0.817 |
| C3 + Traces | 0.370 | 0.925 | **0.974** | 0.929 |
| C4 Full MELT | 0.371 | 0.925 | **0.976** | 0.927 |

The frozen static model collapses to ≈ 0.36 **regardless of how much telemetry it
is given** — the failure is the paradigm, not the signal. Online adaptation
recovers the gap and, once traces are present, *exceeds* the all-regimes oracle.
Online costs more steady-state CPU but delivers far lower worst-case (refit-stall)
latency, a ~100× smaller model, and zero retained training data
(`aiops/data/results/rq3_cost.csv`).

**RQ4 — ensemble trees lead on full MELT (C4):** GB 0.988, RF 0.986, XGB 0.984
(statistically tied); multimodal fusion 0.891 (high-precision); LSTM 0.236 (weak
on this windowed representation).

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
```

> Windows PowerShell: run from `aiops/` (or set `$env:PYTHONPATH = (Resolve-Path .).Path`)
> so `python -m …` resolves the package.

All models use a fixed random seed and an identical train/test protocol, so
cross-cell differences reflect configuration and learning policy, not stochastic
training variation.

## Where the evidence lives

Outputs are written to (and a frozen copy is committed under)
[`aiops/data/results/`](aiops/data/results/):

| File | Underpins |
|------|-----------|
| `rq1_completeness.csv` | Table 5.1 (detection vs C1–C4) |
| `rq2_localisation.csv` | Table 5.2 (top-*k* RCA, traces excluded vs included) |
| `rq3_online_vs_offline.csv` | Tables 5.3–5.5 (per-regime F1 by policy) |
| `rq3_cost.csv` | Table 5.6 (latency, model size, retained buffer, CPU) |
| `rq3_timeline.csv` | Figure 5.2 (rolling F1 over the drifting stream) |
| `rq4_model_family.csv` | Table 5.7 (model-family comparison on C4) |
| `observability_melt.csv` | raw MELT window dataset the analysis consumes |
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

## Further documentation

- [`DEMO.md`](DEMO.md) — guided three-track walkthrough of the whole project.
- [`aiops/README.md`](aiops/README.md) — the experiment layer in depth.
- [`aiops/docs/`](aiops/docs/) — integration/data-flow, mesh expansion, the online
  pipeline, and the Kafka/LLM architecture.

## Author

Ngoc Duc Anh Nguyen — MSc Advanced Computer Science, Leeds Beckett University.
Supervised by Dr Satish Kumar. All third-party tooling is open-source.
