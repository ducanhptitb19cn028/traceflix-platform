# TraceFlix Platform

A single repository combining the three things needed for the MSc dissertation
*"Does Observability Matter? An Empirical Study of Real-Time Anomaly Detection
in Cloud-Native Systems"*:

```
traceflix-platform/
├── services/          ← your TraceFlix microservices (Spring Boot 3.5.4 / Java 21)
│   ├── movie-service      (entry point; calls actor + review)
│   ├── actor-service      (leaf)
│   ├── review-service     (leaf)
│   ├── pom.xml            (multi-module build)
│   └── deployment.yaml
├── observability/     ← your on-demand observability stack
│   └── on-demand-observability.yaml   (otel-collector, Tempo, Loki, Prometheus, Grafana, load-gen)
└── aiops/             ← the experiment layer (fault injection + ML + C1–C4 harness)
    ├── faults/            Chaos Mesh scenarios + episode runner (ground-truth labels)
    ├── collectors/        live PromQL/LogQL/TraceQL collectors (+ synthetic mirror)
    ├── ml/                features (C1–C4), detectors, RCA, experiment harness
    ├── k8s/               gap fixes: fixed load-gen, VictoriaMetrics, mem-limit patch
    └── scripts/           one-command offline + live runs
```

The three layers are decoupled on purpose: `services/` and `observability/` are
your original work, untouched; `aiops/` sits beside them and consumes their
telemetry without modifying a line of the Java code.

## How the parts connect

```
services (OTel Java agent) ──telemetry──► observability (Tempo/Loki/Prometheus)
                                                  ▲                 │
            aiops/faults ──inject faults──────────┘                 │
            aiops/collectors ──PromQL/LogQL/TraceQL──────────────────┘
                     │
            aiops/ml ──► C1–C4 detection + root-cause analysis (RQ1–RQ3)
```

## Quick start

### Offline — reproduce RQ1–RQ3 with no cluster

```bash
cd aiops
pip install -r requirements.txt
./scripts/run_offline.sh 200        # results + figures in aiops/data/results/
pytest tests/ -q
```

### Live — against a real cluster

```bash
# build the Java services (from repo root)
cd services && mvn clean package -DskipTests && cd ..
eval $(minikube docker-env)         # Docker Desktop K8s: skip this line
docker build -t traceflix/movie-service:1.0.0  services/movie-service
docker build -t traceflix/actor-service:1.0.0  services/actor-service
docker build -t traceflix/review-service:1.0.0 services/review-service

# deploy your stack + the gap fixes
kubectl apply -f observability/on-demand-observability.yaml
kubectl apply -f aiops/k8s/load-generator-fixed.yaml
kubectl apply -f aiops/k8s/victoriametrics.yaml

# fault engine + experiment
cd aiops
./scripts/install_chaos_mesh.sh
./scripts/run_live_experiment.sh 30
```

`scripts/bootstrap.sh` (repo root) chains the build + deploy steps for you.

## What each layer documents

- `services/README.md`, `services/HOW-TO-RUN.md`, `services/DEMO.md` — your originals.
- `aiops/README.md` — the experiment layer overview and the two gap fixes.
- `aiops/docs/INTEGRATION.md` — data flow, OTel→PromQL metric-name mapping, and
  the fault-to-service injection plan.

## Research questions (all in `aiops/ml/experiments/run_experiment.py`)

- **RQ1** — detection across observability completeness C1→C4.
- **RQ2** — RF / GB / XGBoost / LSTM / multimodal fusion under full MELT (C4).
- **RQ3** — Top-k root-cause localisation, traces excluded vs included.

Representative offline numbers: detection F1 climbs C1→C4 (~0.91 → ~0.99); Top-1
RCA rises sharply with traces. The mesh is now a **9-service graph** (gateway +
the original movie/actor/review subtree + user/search/recommendation/auth/catalog
— see `aiops/docs/MESH_EXPANSION.md`): on it, Top-1 RCA is **~0.77 (metrics+logs)
→ 1.00 (+traces)**, a wide, discriminating gap (the old 3-service mesh saturated at
Top-2). Set the topology in `aiops/ml/configs.py`; everything else derives from it.
