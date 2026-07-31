# TraceFlix Platform — Whole-Project Demo

A guided, end-to-end walkthrough of the dissertation/paper *"Learning Under
Drift: Online vs Offline Anomaly Detection over Multimodal Observability Streams
in Cloud-Native Systems."* It runs from a real nine-service microservice mesh to
the empirical result that **a detector trained once decays the moment the system
operates — completeness raises the ceiling, but only continual learning realises
it.**

```
services/        ─► observability/      ─► aiops/            ─► streaming/ + llm/
9 Spring Boot       Tempo · Loki ·          fault injection      Kafka event backbone +
microservices       Prometheus · Grafana    + ML (RQ1–RQ4)       Qwen2.5-3B LLM detector
(gateway→…→catalog)                         + cost + webui
```

There are three tracks; each stands alone.

| Track | Needs a cluster / GPU? | Time | Shows |
|-------|------------------------|------|-------|
| **A — Offline results** | No | ~6 min | The full empirical story (RQ1–RQ4 + cost) on the nine-service synthetic mesh that mirrors the live schema |
| **B — Streaming, mesh & LLM** | No (broker & GPU optional) | ~10 min | The nine real microservices, the Kafka event backbone, the local-LLM detector, and the streaming dashboard — all with in-memory/heuristic fallbacks |
| **C — Live deployment** | Yes (Docker) | ~20 min | The real mesh under Docker Compose, real traces in Grafana, Pumba fault injection, and the experiments against live PromQL/LogQL/TraceQL |

Start with Track A — it proves the thesis and runs anywhere.

---

## The thesis in one sentence

On clean, stationary data every model looks great (F1 ≈ 0.99). The moment the
system *operates* — a deploy regresses latency, autoscaling changes throughput,
data growth raises memory — the telemetry baseline drifts, and a detector trained
once on a snapshot decays (F1 ≈ 0.36). The demo makes that failure visible and
shows what fixes it.

---

## The nine-service mesh

```
gateway ─┬─► movie ──► actor, review            (original subtree, unchanged)
         ├─► user ───► recommendation ─► catalog
         │         └─► auth
         └─► search ─────────────────► catalog   (shared fan-in; depth 4)
```

Data owners (`catalog`, `auth`, `user`) persist with Spring Data JPA + H2 + seed
data; orchestrators (`gateway`, `search`, `recommendation`) call downstreams with
`RestClient`. Every service has real business logic, so the call graph is real
domain traffic — and a fault deep in the graph propagates latency up *every*
ancestor, which is what makes root-cause attribution non-trivial. The synthetic
generator and the live collectors emit an identical `Window` schema, so the entire
RQ1–RQ4 analysis runs unchanged offline or live. The topology lives in one file:
`aiops/ml/configs.py`.

---

# Track A — Offline empirical story (no cluster)

## A0. Setup

```bash
cd aiops
pip install -r requirements.txt          # numpy, pandas, scikit-learn, matplotlib, httpx
```

> Windows PowerShell: run the commands from `aiops/` (or set
> `$env:PYTHONPATH = (Resolve-Path .).Path`) so `python -m …` resolves the package.

Sanity check (invariants binding the pipeline to the nine-service topology):

```bash
pytest tests/ -q                         # 8 passed  (pip install pytest if needed)
```

## A1. RQ1 + RQ4 — completeness and model family (the stationary baseline)

```bash
./scripts/run_offline.sh 200
# = python -m ml.experiments.run_experiment --episodes 200 --out data/results  (+ plots)
```

What you'll see (synthetic, seed 42, nine-service mesh):

```
RQ1  held-out F1:   C1 0.896   C2 0.915   C3 0.985   C4 0.986   (traces drive the jump)
RQ2  top-1 RCA:     metrics+logs 0.77  ->  +traces 1.00   (first attempt — see A1b)
RQ4  GB 0.988 / RF 0.986 / XGB 0.984 F1; fusion 0.891 (hi-precision); LSTM 0.227 (weak)
```

**Talking points**

- **RQ1 (completeness)** — detection F1 climbs as pillars are added
  (metrics→+logs→+traces→+events). Distributed **traces give the biggest jump**;
  events/history (C3→C4) add almost nothing to detection. ⚠️ The **trace magnitude is
  discounted**: the generator both sharpens the trace signal and exempts it from drift,
  so its size is partly constructed. Direction credible, magnitude not claimed.
- **RQ2 line printed above — the circular first attempt.** This script still runs the
  *original* localisation experiment, whose perfect 1.000 came from a ranking feature
  the generator derived from the label. It is kept so the defect stays inspectable.
  **The RQ2 answer comes from A1b**, on the rebuilt generator.
- **RQ4 (model family)** — ensemble trees lead (GB 0.988, RF 0.986, XGB 0.984); their
  mutual differences are smaller than the seed spread, so no ordering is claimed. The
  **LSTM (0.227) is mis-specified, not a negative result** — it scores below the
  always-alarm floor because the interleaved per-service stream carries almost no
  temporal structure. A sixth family, the local **LLM detector** (Qwen2.5-3B on *raw*
  signals, `make llm`), reaches **0.440**: above the floor, far below every tree — a
  working detector, not a competitive one. The six-family table is scored on a common
  3,000-window subsample, since the LLM costs seconds per window.

## A1b. RQ2 — what traces contribute to localisation

Detection says *something is wrong*; localisation says *which service*. The first
attempt at this experiment was circular, so the generator was rebuilt: errors now
**propagate up the call path** and attenuate per hop, every service on the path emits
error spans, and the origin is identifiable only as the **root of the error tree** —
which must be inferred from the topology. A `--backgrounds` knob (β) adds unrelated
off-path incidents, so the mesh is not unrealistically silent.

```bash
python -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46 --episodes 200
```

Top-1 accuracy vs the background-incident rate (mean of 5 seeds; random floor 0.111):

```
approach                                bg=0.0   bg=0.1   bg=0.25  bg=0.5
Metrics+Logs (C2)                        0.387    0.359    0.337    0.340
Metrics+Logs+Traces (C3)                 0.626    0.563    0.496    0.456
Metrics+Logs (C2), graph-aware           0.446    0.391    0.274    0.207
Metrics+Logs+Traces (C3), graph-aware    1.000    0.736    0.486    0.335
```

**Talking points**

- **Traces contribute, and the contribution is robust — this is the answer to RQ2.**
  +0.20 top-1 at bg = 0.1 (0.359 → 0.563), positive at every background level, against
  seed spreads of 0.02–0.05. No metrics+logs arm passes 0.45. Direction earned;
  magnitude bounded, since it moves with the generator's parameters.
- **Nothing saturates.** Best realistic arm: top-1 0.736, top-3 0.948. Without traces
  top-1 sits near 0.36 — about three times the guess floor on nine services. The
  depth-four fan-in ambiguity is real.
- **The 1.000 at bg = 0.0 is a boundary condition, not a result** — a mesh with a
  single error path has a unique root by construction. One unrelated incident in ten
  drops it to 0.736. Report bg ≥ 0.1.
- **Structural reasoning is not free.** The graph-aware rule adds +0.11 at bg = 0.1
  but *inverts* against flat ranking by bg = 0.5 (0.335 vs 0.456) — it rewards any
  erroring service with clean dependencies, and a background incident is exactly
  that. Whether the call graph helps or hurts depends on how noisy the mesh is.

Full analysis, including the circular first attempt: [`DemoRQ2.md`](DemoRQ2.md).

Every model in A1 is **trained once on a static split.** That assumption is what
A2 breaks.

## A2. RQ3 — why static detection is not enough (the headline)

```bash
./scripts/run_online_offline.sh 320
# runs: online_vs_offline (detection) + cost_compare (cost) + plots
```

Detection F1 on the **operational future** (regimes R1–R3 after a deploy/scale/
data-growth baseline shift), all models on identical features:

```
config            offline_static   offline_periodic   online_adaptive   offline_full (oracle)
C1 Metrics-Only       0.360             0.820              0.813               0.812
C2 + Logs             0.361             0.832              0.827               0.817
C3 + Traces           0.370             0.925              0.974               0.929
C4 Full MELT          0.371             0.926              0.976               0.927
```

**Talking points**

- **`offline_static` (the traditional approach) collapses to F1 ≈ 0.36 under
  drift — even with full MELT.** It flags the *new normal* as anomalous
  (precision ≈ 0.22). More observability does **not** rescue it: the failure is
  the *learning paradigm*, not signal availability.
- **`offline_periodic` (scheduled retrain) recovers most of the gap** (0.36 →
  ~0.93) but pays for it (see A3); it leads online narrowly only under **thin**
  telemetry (C1/C2), where the drift is mostly virtual.
- **`online_adaptive` dominates once telemetry is rich** (C3/C4: 0.974/0.976,
  beating periodic by ~0.05 and even *exceeding* the all-regime oracle). It
  updates *per sample* — adaptive normalisation tracks the evolving normal,
  incremental learning + a self-selecting hyper-parameter pool keep it calibrated,
  no batch re-fit. The online advantage over periodic **grows with richness**,
  crossing from parity (thin) to dominance (rich).
- **`offline_full`** is an unrealistic oracle (trained on the future), shown only
  to prove the static decay is **non-stationarity, not model capacity.**

Figures:

```
data/results/figures/rq3_timeline.png          # rolling F1 over the drifting stream (sawtooth = periodic refits)
data/results/figures/rq3_online_vs_offline.png # F1 bars: static < periodic < online ≈/> oracle
```

## A3. Cost — is online affordable? (the honest follow-up)

From `cost_compare.py` (C4, 25,920 future windows):

```
                                    offline_periodic     online_adaptive
F1                                       0.9255              0.9755
train events over the stream          51 full refits      25,920 updates
worst-case latency / window            581.6 ms (stall)     15.5 ms
p99 latency / window                     0.14 ms             8.5 ms
model size                              2287.7 KB           15.7 KB
labelled windows retained to train       2880                 0
total CPU over the stream               29.4 s (1.0x)      129.7 s (~4.4x)
```

**State the trade-off honestly**

- Online is **not cheaper in total CPU** — a little work every window, 4.1–4.8× the
  aggregate of the periodic refits across C1–C4. That cost is real.
- But it wins where it operationally counts: **10–48× lower worst-case latency** (a
  refit *blocks* the detector for 580–880 ms — exactly when a regime shifts and
  detection matters most; the online update never exceeded 78 ms over five seeds), a
  **~120–390× smaller model** (≈15 KB vs 2–6 MB), and **zero retained training data**
  (periodic must keep a 2880-window labelled buffer) — *and* higher accuracy once
  telemetry is rich.
- Net: online converts a **bursty, stateful, blocking retrain pipeline** into a
  **smooth, bounded-latency, stateless stream.**
- Say the caveat out loud: the wall-clock columns belong to this workstation and one
  pass. The **structural** columns — refit count, footprint, retained windows — follow
  from the policy and reproduce exactly, and the argument rests on those.

That is the empirical case that **operations matter.**

## A4. The three controls that decide how much of A2 you may claim

Run these before defending the RQ3 headline — each answers an objection the headline
cannot answer by itself.

```bash
python -u -m ml.experiments.drift_sweep        --episodes 320 --configs C1,C4 --out data/results_drift_sweep
python -u -m ml.experiments.baseline_streaming --episodes 320 --out data/results_baselines_scaled
python -u -m ml.experiments.ablate_online      --episodes 320 --out data/results_ablation
```

**1. "You set the drift as large as the fault."** Correct — and the sweep says by how
much that matters. Rescaling every regime multiplier toward 1 (fault schedule held
identical) traces the curve: refitting starts to pay at a **1.15×** operating-point
shift, the frozen model stops discriminating between **1.29× and 1.49×**, and the
reported campaign sits at **1.97×**. Below that band the frozen model is the **best**
of the three and the online detector the **worst** — adaptation is not free.

**2. "The online margin is just the extra machinery."** Mostly it is the *normaliser*.
Three off-the-shelf incremental learners reach F1 **0.302–0.308 unnormalised at every
configuration**; behind a running standardiser the same learners reach **0.760–0.796
(C1)** and **0.959–0.971 (C3)**. The full detector keeps only +0.017 (C1) and +0.003
(C3, inside the seed spread) over the best of them.

**3. "Which mechanism earns its place?"** The ablation: champion re-election is worth
+0.013 at C1, +0.005 at C2, **nothing** at C3/C4; the drift monitor **nothing
anywhere**. Its adapt events are diagnostic, not load-bearing.

The point of saying all three out loud: the claim that survives them is the narrow one
— **within a single model family, refitting raises F1 from 0.36 to 0.92** — and that is
the claim the dissertation rests on.

## A5. The one measured result — live replay (optional, needs Prometheus)

Everything above is generated. This is not:

```bash
TF_LIVE=1 PROM_URL=http://localhost:9090 \
  python -u -m ml.experiments.live_replay --labels data/labels_live.csv --out data/results_live
```

```
source config model  P      R      F1     AUC    n_test  prevalence  floor
live   C1     rf     0.700  0.700  0.700  0.967  135     0.078       0.144
```

It replays a *recorded* fault-injection campaign against historical PromQL — each query
evaluated at the instant its window represents. **C1 only** (the log/trace/event
collectors are not time-parameterised, so it says nothing about the trace increment),
origin-only labelled, twelve episodes. Show it as proof the pipeline runs end-to-end on
genuine telemetry — never as a number to compare with A1 or A2.

---

# Track B — Streaming, the mesh services, and the LLM detector (no cluster)

Everything here runs with **no broker and no GPU**: Kafka falls back to an
in-memory bus, the LLM to a clearly-marked heuristic. Design docs:
`aiops/docs/MESH_EXPANSION.md`, `aiops/docs/KAFKA_LLM_ARCHITECTURE.md`.

## B1. Build and exercise the mesh

```bash
cd services
mvn clean package -DskipTests          # builds all nine services
```

Run a 3-hop slice locally and watch the graph fan out:

```bash
java -jar catalog-service/target/*.jar        --server.port=8091 &
java -jar auth-service/target/*.jar           --server.port=8094 &
java -jar recommendation-service/target/*.jar --server.port=8092 \
     --catalog-service.url=http://localhost:8091 &
java -jar user-service/target/*.jar           --server.port=8093 \
     --auth-service.url=http://localhost:8094 \
     --recommendation-service.url=http://localhost:8092/api/recommendations &

curl -s "http://localhost:8093/api/users/1"
```

Returns the composite — profile + role from **auth** + recommendations from
**recommendation→catalog** (a real 3-hop call):

```json
{"id":1,"name":"Alice Adams","email":"alice@traceflix.test","tier":"PREMIUM",
 "role":"PREMIUM","recommendations":[{"id":1,"name":"The Shawshank Redemption",...}]}
```

## B2. The Kafka event backbone

```bash
cd ../aiops
python -m streaming.run_pipeline --episodes 20
```

Telemetry windows flow through the backbone to two detectors **in parallel**
(20 episodes × 12 windows × 9 services = 2160 windows):

```
[pipeline] bus backend = memory
[pipeline] tf.telemetry.windows: produced 2160 windows
[pipeline] tf.anomalies: ML detector emitted 2160 verdicts
[llm] mode=heuristic model=qwen2.5:3b
[pipeline] tf.anomalies: LLM detector emitted 2160 verdicts
[pipeline] llm          acc=0.910 f1=0.717 (n=2160)
[pipeline] online_sgd   acc=0.880 f1=0.447 (n=2160)
```

Both detectors publish a binary verdict per window to `tf.anomalies`, tagged by
detector. To use a **real Kafka broker** (single-node KRaft) + Ollama:

```bash
docker compose -f ../deploy/virtfusion/vm1-gpu/docker-compose.kafka-llm.yml up -d
TF_KAFKA_BOOTSTRAP=localhost:9092 python -m streaming.run_pipeline --episodes 20
```

## B3. The local-LLM detector (Qwen2.5-3B)

Without Ollama the detector reports a **clearly-marked heuristic** (`mode=heuristic`
above) — never silently mistaken for the model. To run the real model as an RQ4
model family, head-to-head with RF/GB/XGB/LSTM/fusion:

```bash
ollama serve &  ;  ollama pull qwen2.5:3b
ENABLE_LLM=1 OLLAMA_URL=http://localhost:11434 OLLAMA_MODEL=qwen2.5:3b \
  python -m ml.experiments.run_experiment --episodes 200
```

LoRA fine-tune it to this mesh's fault signatures (GPU), then re-evaluate:

```bash
pip install -r llm/requirements-llm.txt
python -m llm.build_dataset --episodes 400 --out llm/data
python -m llm.train_lora    --data llm/data --out llm/adapters/qwen2.5-3b-traceflix
bash  llm/export_ollama.sh
OLLAMA_MODEL=qwen2.5-3b-traceflix ENABLE_LLM=1 \
  python -m ml.experiments.run_experiment --episodes 200
```

> The LLM is a **second binary detector / on-demand triage layer**, not the primary
> per-window detector — a 3B forward pass per window is far heavier than the linear
> online model (cf. the paper's methods + threats sections).

## B4. The streaming dashboard — MELT · Topics · LLM

```bash
cd aiops
python -m uvicorn webui.backend.app:app --port 8000
# open http://localhost:8000/streaming  →  press "Start backbone"
```

The page drives the backbone window-by-window and shows three live views:
**Topics** (growing message counts on `tf.telemetry.windows` / `tf.anomalies`),
**MELT** (the current window's Metrics / Events / Logs / Traces), and **LLM** (the
LLM vs ML detector verdicts, their agreement, and a rolling-F1 chart). Flips
`heuristic → llm` automatically if `OLLAMA_URL` is reachable.

## B5. Run the service tests

```bash
cd services
mvn -pl catalog-service,auth-service,user-service,search-service,recommendation-service,gateway-service test
# 35 tests: service-layer (Mockito) + controller (@WebMvcTest), 0 failures
```

---

# Track C — Live deployment (Docker Compose)

Brings up the real nine-service mesh with OpenTelemetry instrumentation, the
telemetry backends, and Pumba fault injection. This is the additive
`deploy/virtfusion/` overlay; see `deploy/virtfusion/README.md` for the full
multi-VM (WireGuard) setup — below is the single-host shape.

## C1. Build the images

```bash
cd services && mvn clean package -DskipTests
# original three
for s in movie actor review; do docker build -t traceflix/$s-service:1.0.0 $s-service; done
# the six new mesh services
for s in catalog auth user search recommendation gateway; do
  docker build -t "traceflix/$s-service:1.0.0" "$s-service"; done
```

## C2. Bring up telemetry + the mesh

```bash
cd ../deploy/virtfusion
cp .env.example .env        # set VM*_IP to 127.0.0.1 for a single host (see README)

# telemetry backends: Prometheus, VictoriaMetrics, Loki, Tempo, Grafana
docker compose -f vm3-telemetry/docker-compose.yml --env-file .env up -d

# the nine-service mesh + co-located OTel collector (base + mesh overlay)
cd vm2-services
docker compose -f docker-compose.yml -f docker-compose.mesh.yml --env-file ../.env up -d
docker compose ps           # gateway/movie/actor/review/user/search/recommendation/auth/catalog Up
```

The `mesh-load-generator` drives `GET /api/browse?userId=1..5` on the gateway, so
traffic continuously exercises the whole call graph and produces real MELT
telemetry. View distributed traces in **Grafana → Tempo**.

## C3. Inject faults and run the live experiment

```bash
# Pumba targets ANY of the nine services by name; writes the same labels CSV as the k8s harness
./inject-fault.sh catalog-service cpu_saturation 120
./inject-fault.sh recommendation-service pod_kill

# run the RQ1–RQ4 analysis against live PromQL/LogQL/TraceQL
cd ../../../aiops
TF_LIVE=1 PROM_URL=http://localhost:9090 LOKI_URL=http://localhost:3100 \
  TEMPO_URL=http://localhost:3200 VM_URL=http://localhost:8428 \
  python -m ml.experiments.run_experiment --labels data/labels.csv
```

The collectors (`collectors/telemetry.py`) issue the real queries — OTel-agent
metric names, Loki LogQL, Tempo TraceQL — and emit the **same `Window` schema** the
offline generator mirrors, so the entire analysis runs unchanged on live data.

---

## Artifacts produced

| File | What it shows |
|------|---------------|
| `aiops/data/results/rq1_completeness.csv` | RQ1 detection vs C1–C4 (held-out reference) |
| `aiops/data/results/rq2_localisation_propagating.csv` | RQ2 top-*k* RCA on the propagating generator — 4 arms × 4 background rates × 5 seeds |
| `aiops/data/results/rq2_propagating_summary.json` | RQ2 mean ± sd per arm + generator settings |
| `aiops/data/results/rq2_localisation.csv` | RQ2 first attempt — circular, superseded; retained for inspection |
| `aiops/data/results/rq4_model_family.csv` | RQ4 model-family comparison on C4 |
| `aiops/data/results/rq3_online_vs_offline.csv` | RQ3 per-regime detection, all four learners |
| `aiops/data/results/rq3_timeline.csv` | RQ3 rolling F1 over the drifting stream |
| `aiops/data/results/rq3_cost.csv` | RQ3 cost: latency, model size, retained buffer, CPU |
| `aiops/data/results/*_summary.json` | machine-readable headlines |
| `aiops/data/results/figures/*.png` | result figures |

## One-command reproduction (Track A)

The repo-root **`Makefile`** automates the whole pipeline (run `make help` for all targets):

```bash
make setup           # install Python deps
make experiments     # RQ1/RQ4 + RQ3 + cost + figures  -> aiops/data/results/
make test            # aiops invariants (8) + service tests (35)
# faster smoke run:  make quick      (EPISODES=60 DRIFT_EPISODES=120)
# streaming / paper: make streaming  |  make paper
```

Equivalent without make:

```bash
cd aiops && pip install -r requirements.txt
bash ./scripts/run_offline.sh 200            # RQ1 + RQ4 (+ RQ2's first attempt)
bash ./scripts/run_online_offline.sh 320     # RQ3 detection + cost + figures
python -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46   # RQ2
pytest tests/ -q                             # 8 passed
```

## Teardown (Track C)

```bash
cd deploy/virtfusion/vm2-services && docker compose -f docker-compose.yml -f docker-compose.mesh.yml down
cd ../vm3-telemetry && docker compose down
# Kafka/Ollama (if started): docker compose -f ../vm1-gpu/docker-compose.kafka-llm.yml down
```
