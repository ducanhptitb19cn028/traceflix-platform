# TraceFlix — Full Project Demo

A complete, presentation-grade walkthrough of the whole platform: the
nine-service application, its observability, the empirical research (RQ1–RQ4),
the Kafka streaming backbone, the local-LLM detector, the engineering (tests, CI,
automation), deployment, and the paper.

> This is the **guided, narrated** demo. For the terse runbook see
> [`DEMO.md`](DEMO.md); for design details see
> [`aiops/docs/MESH_EXPANSION.md`](aiops/docs/MESH_EXPANSION.md) and
> [`aiops/docs/KAFKA_LLM_ARCHITECTURE.md`](aiops/docs/KAFKA_LLM_ARCHITECTURE.md).

Presenter notes are marked **🗣 Say:**, commands **▶ Run:**, and outputs **✔ Expect:**.

---

## The one-sentence thesis

> On clean, stationary data every model looks great (F1 ≈ 0.99). The moment the
> system **operates** — a deploy regresses latency, autoscaling changes
> throughput, data growth raises memory — the telemetry baseline drifts, and a
> detector trained once on a snapshot **decays to F1 ≈ 0.36**. Completeness raises
> the ceiling; only **continual learning** realises it.

## What you'll demo

```
services/            observability/         aiops/                  streaming/ + llm/
9 Spring Boot   ──►  Tempo · Loki ·    ──►   fault injection   ──►   Kafka event backbone +
microservices       Prometheus · Grafana    + ML (RQ1–RQ4)          Qwen2.5-3B LLM detector
gateway→…→catalog                           + cost + webui          + LoRA harness
```

| Part | Shows | ~Time | Cluster/GPU? |
|------|-------|-------|--------------|
| 0 | Setup | 3 min | No |
| 1 | The nine-service mesh (real business logic) | 5 min | No |
| 2 | Observability + the live streaming dashboard | 4 min | No |
| 3 | **The research: RQ1–RQ4 + cost** | 8 min | No |
| 4 | The Kafka streaming backbone | 4 min | No |
| 5 | The local-LLM detector (Qwen2.5-3B) | 4 min | No (GPU optional) |
| 6 | Engineering: tests, CI, automation | 4 min | No |
| 7 | Deployment (Compose / k8s / faults) | 6 min | Docker |
| 8 | The paper | 3 min | Docker |

**Highlights path (≈10 min, runs anywhere):**

```bash
make setup && make build-services     # deps + the nine services
make experiments                      # the empirical story  → aiops/data/results/
make streaming                        # the Kafka backbone (in-memory)
make webui                            # dashboard → http://localhost:8000/streaming
```

---

## Prerequisites

| Tool | Version | Needed for |
|------|---------|-----------|
| Python | 3.11+ | aiops experiments, streaming, webui |
| JDK | 21 (Temurin) | the nine Spring Boot services |
| Maven | 3.9+ | building / testing the services |
| Docker | recent | images, Compose, Kafka/Ollama, paper compile |
| GNU make | any | the automation entrypoint (recommended) |
| Ollama + GPU | optional | the **real** Qwen2.5-3B (heuristic fallback otherwise) |
| kubectl | optional | the Kubernetes live track |
| Node + npm | 18+ optional | rebuilding the dashboard frontend |

`make help` lists every target; the demo leans on it throughout.

---

# Part 0 — Setup

**▶ Run:**

```bash
make setup            # pip install aiops/requirements.txt
make build-services   # mvn package -> nine Spring Boot fat jars
```

**✔ Expect:** Python deps installed; `services/*/target/*-0.0.1-SNAPSHOT.jar` built
(data owners ~52 MB with JPA+H2, orchestrators ~21 MB).

> 🗣 Say: "One Makefile drives the whole project — Java build, Python experiments,
> streaming, the dashboard, deployment, even the paper. `make help` is the map."

---

# Part 1 — The system under observation: the nine-service mesh

```
gateway ─┬─► movie ──► actor, review            (original subtree, unchanged)
         ├─► user ───► recommendation ─► catalog
         │         └─► auth
         └─► search ─────────────────► catalog   (shared fan-in; depth 4)
```

Data owners (`catalog`, `auth`, `user`) persist with Spring Data JPA + H2 + seed
data; orchestrators (`gateway`, `search`, `recommendation`) call downstreams with
`RestClient`. **Every service has real business logic** — so the call graph is real
domain traffic, not a uniform stub.

**▶ Run** — bring up a 3-hop slice locally and exercise the graph:

```bash
cd services
java -jar catalog-service/target/*.jar        --server.port=8091 &
java -jar auth-service/target/*.jar           --server.port=8094 &
java -jar recommendation-service/target/*.jar --server.port=8092 \
     --catalog-service.url=http://localhost:8091 &
java -jar user-service/target/*.jar           --server.port=8093 \
     --auth-service.url=http://localhost:8094 \
     --recommendation-service.url=http://localhost:8092/api/recommendations &
curl -s http://localhost:8093/api/users/1
```

**✔ Expect** — the composite, assembled across three services:

```json
{"id":1,"name":"Alice Adams","email":"alice@traceflix.test","tier":"PREMIUM",
 "role":"PREMIUM","recommendations":[{"id":1,"name":"The Shawshank Redemption",...}]}
```

> 🗣 Say: "`user` owns the profile (JPA), enriches `role` from **auth**, and pulls
> recommendations from **recommendation → catalog** — a real three-hop call. A
> fault deep in this graph (say `catalog`) propagates latency up *every* ancestor,
> so several services look anomalous at once. That is exactly what makes root-cause
> attribution hard — and what Part 3's RQ2 measures."

Stop the slice when done: `pkill -f target/ ` (or close the terminal).

---

# Part 2 — Observability and the live streaming dashboard

The four MELT pillars — **M**etrics (Prometheus), **E**vents (K8s), **L**ogs
(Loki), **T**races (Tempo) — map onto the four telemetry configurations C1–C4.

**▶ Run** the dashboard (no cluster needed):

```bash
make webui            # uvicorn on :8000
# open http://localhost:8000/streaming  →  press "Start backbone"
```

**✔ Expect** three live panels driven window-by-window:

- **Topics** — message counts growing on `tf.telemetry.windows` / `tf.anomalies`.
- **MELT** — the current window's Metrics / Events / Logs / Traces values.
- **LLM** — the LLM vs ML detector verdicts, their agreement %, and a rolling-F1 chart.

> 🗣 Say: "This is the streaming pipeline made visible: telemetry windows flow
> through Kafka topics to two detectors — the online ML model and the local LLM —
> and the page shows the MELT signal each one sees, side by side. The LLM badge
> reads `heuristic` until a real model is served (Part 5)."

The original Online/Offline/Comparison pages are the offline experiment views.

---

# Part 3 — The research: does the learning paradigm matter under drift?

**▶ Run** the whole offline pipeline:

```bash
make experiments      # RQ1/RQ4  +  RQ3 (drift)  +  cost  +  figures
```

(equivalently `run_offline.sh 200` + `run_online_offline.sh 320`.) Results land in
`aiops/data/results/` (CSVs, `*_summary.json`, `figures/*.png`).

### RQ1 — completeness raises the ceiling

```
held-out F1:   C1 0.896   C2 0.915   C3 0.985   C4 0.986
```

> 🗣 Say: "Detection improves with every pillar, and **traces give the biggest
> jump** (C2→C3). Events/history add almost nothing to *detection* — C3 ≈ C4."

### RQ2 — traces help localisation on a deep mesh, but nothing is perfect

`make experiments` still prints RQ2's **first attempt** (`top-1 0.77 → 1.00`). That
one was circular — do not present it. The reported result comes from the rebuilt
experiment:

```bash
python -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46
```

```
top-1 RCA (5 seeds; random floor 0.111)   bg=0.0   bg=0.1   bg=0.25  bg=0.5
Metrics+Logs (C2)                          0.387    0.359    0.337    0.340
Metrics+Logs+Traces (C3)                   0.626    0.563    0.496    0.456
Metrics+Logs (C2), graph-aware             0.446    0.391    0.274    0.207
Metrics+Logs+Traces (C3), graph-aware      1.000    0.736    0.486    0.335
```

> 🗣 Say: "My first attempt gave a perfect 1.0 with traces, and a perfect score is a
> defect report, not a triumph. It was **circular** — the generator emitted error spans
> only at the fault origin, and the origin is the label I was trying to predict. So I
> rebuilt the generator: errors now **propagate up the call path**, attenuating per hop,
> so every service on the path emits spans and the origin is only identifiable as the
> *root of the error tree* — which has to be inferred from the topology. I also added a
> knob for unrelated background incidents, because a real mesh is never quiet.
>
> Re-run, **traces are worth +0.20 top-1** — 0.36 to 0.56 — and the lift holds at every
> noise level, with no metrics-and-logs arm passing 0.45. **That is my answer to RQ2**,
> and it agrees in direction with the multimodal RCA literature — but I reached it by a
> controlled ablation rather than by swapping models. Nothing saturates: the best arm
> reaches 0.74 top-1.
>
> Two things I did not expect. The 1.000 at zero background noise survives even though
> the label no longer leaks — so it was never about tracing, it was a mesh with a single
> error path. And the graph-aware rule *inverts* once the mesh is noisy: 0.335 against
> the flat ranker's 0.456 at β = 0.5, because it rewards any erroring service with clean
> dependencies, and a background incident is exactly that. Whether the call graph helps
> or hurts depends on how noisy your mesh is.
>
> So: answered in direction, bounded in magnitude. The magnitudes belong to my
> parameterisation, and a live campaign is what would turn the direction into a number."

Full account, including the circular first attempt: [`DemoRQ2.md`](DemoRQ2.md).

### RQ3 — the headline: static detection collapses under drift

Detection F1 on the **operational future** (regimes R1–R3 after a deploy/scale/
data-growth shift), all models on identical features:

```
config            offline_static   offline_periodic   online_adaptive   offline_full (oracle)
C1 Metrics-Only       0.360             0.820              0.813               0.812
C2 + Logs             0.361             0.832              0.827               0.817
C3 + Traces           0.370             0.925              0.974               0.929
C4 Full MELT          0.371             0.926              0.976               0.927
```

> 🗣 Say (the money slide):
> - "**Static (the traditional 'train once, ship it') collapses to F1 ≈ 0.36 — even
>   with full MELT.** It flags the new normal as anomalous; precision ≈ 0.22. More
>   observability does *not* rescue it — the failure is the *learning paradigm*."
> - "**Periodic retraining recovers most of the gap** but is bursty and laggy, and
>   only leads online narrowly under *thin* telemetry (C1/C2)."
> - "**Online adaptive dominates once telemetry is rich** (C3/C4: ~0.975, beating
>   periodic by ~0.05 and even *exceeding* the all-regime oracle). The online edge
>   over periodic **grows with richness** — traces tip the choice decisively."

Show the figures: `aiops/data/results/figures/rq3_timeline.png` (sawtooth = periodic
refits) and `rq3_online_vs_offline.png` (static < periodic < online ≈/> oracle).

### RQ4 — which model family?

```
Gradient Boosting 0.988   Random Forest 0.986   XGBoost 0.984   (ensemble trees lead, tied)
Late fusion 0.891 (hi-precision, low recall)     LSTM 0.259 (weak on windowed repr.)
```

> 🗣 Say: "Ensemble trees win on tabular MELT — *which is why the online detector
> is a lightweight normalised linear model, not a tree*: the streaming setting
> rewards a bounded, cheap per-window update, not raw batch accuracy."

### Cost — is online affordable? (be honest)

```
C4, 25,920 future windows     offline_periodic     online_adaptive
F1                                 0.926               0.976
worst-case latency / window     ~508 ms (refit stall) ~34 ms
model size                         ~2.3 MB            ~16 KB
labelled windows retained           2880                0
total CPU                          1.0× (baseline)     ~4.6×
```

> 🗣 Say: "Online is **not** cheaper in total CPU (~4.6×) — that cost is real. But
> it wins where it counts: **~15× lower worst-case latency** (a refit *blocks* the
> detector for half a second, exactly when a regime shifts), a **~150× smaller
> model**, and **zero retained data**. Bursty/blocking → smooth/bounded. That is the
> empirical case that **operations matter**."

---

# Part 4 — The Kafka streaming backbone

```
collectors ─► tf.telemetry.windows ─┬─► online ML detector ─► tf.anomalies
                                     └─► LLM detector       ─► tf.anomalies  (tagged by detector)
```

**▶ Run** (no broker needed — falls back to an in-memory bus):

```bash
make streaming        # = python -m streaming.run_pipeline --episodes 20
```

**✔ Expect:**

```
[pipeline] bus backend = memory
[pipeline] tf.telemetry.windows: produced 2160 windows
[pipeline] tf.anomalies: ML detector emitted 2160 verdicts
[llm] mode=heuristic model=qwen2.5:3b
[pipeline] tf.anomalies: LLM detector emitted 2160 verdicts
[pipeline] llm          acc=0.910 f1=0.717 (n=2160)
[pipeline] online_sgd   acc=0.880 f1=0.447 (n=2160)
```

> 🗣 Say: "Both detectors consume the same windows in independent consumer groups
> and publish a binary verdict per window to `tf.anomalies`, tagged by detector, so
> they're directly comparable. The transport makes the per-window prequential
> protocol a property of the *system*, not a single process."

Real broker (single-node KRaft) + Ollama:

```bash
make kafka-llm-up                                  # Kafka + Ollama (Docker)
TF_KAFKA_BOOTSTRAP=localhost:9092 make streaming
```

---

# Part 5 — The local-LLM detector (Qwen2.5-3B)

A second binary detector that reads the **raw** MELT signals (not engineered
features): a prompt of fault-signature rules + few-shot exemplars → Qwen2.5-3B
(Ollama) → strict JSON verdict, optionally LoRA-tuned to this mesh.

> 🗣 Say (be precise about evidence): "Without Ollama the detector reports a
> **clearly-marked heuristic** — never silently mistaken for the model (note
> `mode=heuristic` above). We make **no accuracy claim** for the served model yet;
> it's implemented and analysable, and a 3B forward pass per window is far heavier
> than the linear online model, so it's positioned as an **on-demand triage layer**,
> not the primary per-window detector."

Run the **real** model as an RQ4 family (needs Ollama):

```bash
ollama serve & ; ollama pull qwen2.5:3b
make llm OLLAMA_URL=http://localhost:11434         # ENABLE_LLM=1 run_experiment
```

Fine-tune to the mesh (GPU), then re-evaluate:

```bash
make setup-llm
make lora                                          # build SFT data + LoRA train
bash aiops/llm/export_ollama.sh                    # merge → GGUF → ollama create
OLLAMA_MODEL=qwen2.5-3b-traceflix make llm
```

---

# Part 6 — Engineering: tests, CI, automation

**▶ Run the tests:**

```bash
make test             # aiops invariants + service tests
```

**✔ Expect:**

- **aiops:** 8 passed — topology + multi-hop propagation + the RQ3 drift invariants.
- **services:** 35 passed — service-layer (Mockito) + controller (`@WebMvcTest`)
  across the six new services.

> 🗣 Say: "The tests pin the science (e.g. *online must beat frozen-offline under
> drift*) and the system (mapping, ranking, role enrichment, fan-out, HTTP
> contracts). They run in `mvn package`, so the image build validates logic too."

**Automation** — one entrypoint:

```bash
make help             # grouped target list for the whole project
```

**CI** — `.github/workflows/ci.yml` drives the same Makefile on every push/PR: a
**services** job (`build-services` + `test-services`) and an **aiops** job
(`test-aiops` + `make quick` experiment smoke + streaming smoke), uploading the
results as an artifact.

> 🗣 Say: "A green CI means the exact commands in this demo work — CI runs `make`,
> not a parallel script that can drift from the docs."

---

# Part 7 — Deployment

### Docker Compose (the nine-service mesh, single host)

```bash
make images                                        # build all 9 service images
make deploy-up                                     # telemetry stack + the mesh overlay
docker compose -f deploy/virtfusion/vm2-services/docker-compose.yml \
               -f deploy/virtfusion/vm2-services/docker-compose.mesh.yml ps
```

The `mesh-load-generator` drives `GET /api/browse?userId=1..5` on the gateway, so
traffic continuously exercises the whole call graph and emits real OTel telemetry.
View distributed traces in **Grafana → Tempo**.

### Fault injection + the live experiment

```bash
# Pumba targets ANY of the nine services by name; writes the same labels CSV as k8s
make inject SVC=catalog-service FAULT=cpu_saturation DUR=120
make inject SVC=recommendation-service FAULT=pod_kill

make live PROM_URL=http://localhost:9090 TEMPO_URL=http://localhost:3200   # TF_LIVE=1 analysis
```

> 🗣 Say: "The collectors issue real PromQL/LogQL/TraceQL and emit the **same
> `Window` schema** the synthetic generator mirrors — so the entire RQ1–RQ4
> analysis runs unchanged on live telemetry."

### Kubernetes (original path)

```bash
make bootstrap        # build + deploy services + observability + Chaos Mesh
make k8s-deploy       # or apply manifests directly
make chaos-install
make live-episodes    # drive Chaos Mesh episodes, record ground-truth labels
```

---

# Part 8 — The paper

```bash
make paper            # regenerate figures + compile via Docker TeX Live
make paper-pages      # -> 50 pages
```

> 🗣 Say: "*Learning Under Drift* — the manuscript reports RQ1–RQ4 on the
> nine-service mesh, and its architecture section carries three flowcharts that
> match this demo exactly: the **call graph** (Fig. mesh), the **Kafka dataflow**
> (Fig. dataflow), and the **LLM detector pipeline** (Fig. llm). The Kafka backbone
> and the LLM detector are described as the streaming realisation; consistent with
> Part 5, the paper makes no unmeasured accuracy claim for the served LLM."

Contributions: a two-axis methodology (completeness × learning paradigm), the
empirical RQ1–RQ4 findings + cost analysis, and the streaming/LLM system
realisation.

---

# Appendix A — Make target reference (`make help`)

| Area | Targets |
|------|---------|
| Setup | `setup` `setup-llm` |
| Experiments | `experiments` `repro` `quick` `rq124` `rq3` `cost` `plots` `figures` |
| Stream/LLM | `streaming` `llm` `lora` |
| WebUI | `webui` `webui-build` |
| Java | `build-services` `compile-services` `images` `test-services` |
| Tests | `test` `test-aiops` `test-services` |
| Compose | `deploy-up/down` `mesh-up/down` `telemetry-up/down` `kafka-llm-up/down` `gateway-up/down` |
| Kubernetes | `bootstrap` `k8s-deploy` `k8s-delete` `chaos-install` |
| Faults/live | `live` `live-episodes` `inject` |
| Paper/docs | `paper` `paper-pages` `paper-clean` `dissertation` |
| Clean | `clean` `clean-results` `clean-all` |

Knobs: `EPISODES` (200), `DRIFT_EPISODES` (320), `SEED` (42), `CONFIGS`,
`STREAM_EPISODES`, `SVC`/`FAULT`/`DUR` (inject), `PAPER_DIR`.

# Appendix B — Artifacts

| File | Shows |
|------|-------|
| `aiops/data/results/rq1_completeness.csv` | RQ1 detection vs C1–C4 |
| `aiops/data/results/rq2_localisation_propagating.csv` | RQ2 top-*k* RCA — 4 arms × 4 background rates × 5 seeds (reported) |
| `aiops/data/results/rq2_localisation.csv` | RQ2 first attempt — circular, kept for inspection |
| `aiops/data/results/rq4_model_family.csv` | RQ4 model-family comparison (C4) |
| `aiops/data/results/rq3_online_vs_offline.csv` | RQ3 per-regime detection, four learners |
| `aiops/data/results/rq3_timeline.csv` | RQ3 rolling F1 over the drifting stream |
| `aiops/data/results/rq3_cost.csv` | RQ3 cost: latency, size, retained buffer, CPU |
| `aiops/data/results/figures/*.png` | result figures |
| `paper/sn-article.pdf` | the compiled paper (50 pp) |

# Appendix C — Troubleshooting

- **`python -m …` import errors** — run from `aiops/` (the Makefile recipes do).
- **`pytest: command not found`** — `pip install pytest` (it's a dev-only dep).
- **LLM shows `mode=heuristic`** — expected without Ollama; serve `qwen2.5:3b` and
  set `OLLAMA_URL` to use the real model.
- **Streaming `bus backend = memory`** — expected without a broker; set
  `TF_KAFKA_BOOTSTRAP` after `make kafka-llm-up` for real Kafka.
- **`make paper` mount path (Windows)** — override `PAPER_DIR=<windows-path>/paper`.
- **LSTM F1 ≈ 0.26** — expected; it is a deliberately weak baseline on the
  interleaved-per-service windowed representation (ensemble trees lead, RQ4).

# Appendix D — Teardown

```bash
make deploy-down                    # Compose mesh + telemetry
make kafka-llm-down                 # Kafka + Ollama (if started)
make k8s-delete                     # Kubernetes namespace (live track)
make clean clean-results            # build artifacts + generated CSVs/figures
pkill -f 'target/'                  # any locally-run service jars
```
