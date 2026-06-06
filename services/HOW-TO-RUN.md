# How to Run on-demand-observability.yaml

This manifest deploys the full **TraceFlix** observability stack plus all three microservices
into a dedicated `on-demand-observability` namespace on a local Kubernetes cluster (Minikube or Docker Desktop K8s).

## What Gets Deployed

| Component | Image | Purpose |
|---|---|---|
| otel-collector | `otel/opentelemetry-collector-contrib:0.110.0` | Receives OTLP traces & metrics, exports to Tempo/Prometheus |
| tempo | `grafana/tempo:2.5.0` | Distributed tracing backend |
| loki | `grafana/loki:2.9.8` | Log aggregation |
| prometheus | `prom/prometheus:v2.54.1` | Metrics storage (scrapes otel-collector:8889) |
| grafana | `grafana/grafana:11.1.4` | Dashboards (pre-wired to all three data sources) |
| actor-service | `traceflix/actor-service:1.0.0` | TraceFlix microservice |
| review-service | `traceflix/review-service:1.0.0` | TraceFlix microservice |
| movie-service | `traceflix/movie-service:1.0.0` | TraceFlix microservice (calls actor + review) |

The three microservices use an **initContainer** to download the OpenTelemetry Java agent at startup
and auto-instrument themselves via `JAVA_TOOL_OPTIONS`.

---

## Prerequisites

- `kubectl` configured and pointing at a running cluster
- Docker (Minikube or Docker Desktop Kubernetes enabled)
- The three `traceflix/*` Docker images built locally with `imagePullPolicy: Never`

---

## Step 1 — Build the Service Images (Minikube)

```bash
# Point your shell at Minikube's Docker daemon so images are visible to the cluster
eval $(minikube docker-env)

# Build from the repo root (one command per service)
docker build -t traceflix/actor-service:1.0.0  01-trace-flix/actor-service
docker build -t traceflix/review-service:1.0.0 01-trace-flix/review-service
docker build -t traceflix/movie-service:1.0.0  01-trace-flix/movie-service
```

> **Docker Desktop K8s** — skip `eval $(minikube docker-env)` and build normally;
> images are shared between Docker and the cluster automatically.

---

## Step 2 — Build the Service Images (Maven)

Before building Docker images, compile the JARs:

```bash
cd 01-trace-flix
mvn clean package -DskipTests
cd ..
```

---

## Step 3 — Apply the Manifest

```bash
kubectl apply -f on-demand-observability.yaml
```

This creates:
1. The `on-demand-observability` namespace
2. ConfigMaps for each component
3. Deployments + Services for otel-collector, tempo, loki, prometheus, grafana
4. Deployments + Services for actor-service, review-service, movie-service

---

## Step 4 — Wait for All Pods to Be Ready

```bash
kubectl get pods -n on-demand-observability -w
```

All pods should reach `Running` status. The microservice pods will first show
`Init:0/1` while the initContainer downloads the OTel Java agent (~20 MB).

---

## Step 5 — Access the Services

### Grafana (dashboards)

```bash
kubectl port-forward svc/grafana -n on-demand-observability 3000:3000
```

Open **http://localhost:3000** — login `admin / admin`.

Pre-configured data sources:
- **Prometheus** → `http://prometheus:9090`
- **Tempo** → `http://tempo:3200`
- **Loki** → `http://loki:3100`

### movie-service API (entry point)

```bash
kubectl port-forward svc/movie-service -n on-demand-observability 8080:8080
```

```bash
curl http://localhost:8080/api/movies/1
```

This triggers a distributed trace through movie-service → actor-service + review-service.

### Prometheus UI

```bash
kubectl port-forward svc/prometheus -n on-demand-observability 9090:9090
```

Open **http://localhost:9090**

---

## Trace Flow

```
movie-service
  ├── GET /api/actors/{id}   → actor-service
  └── GET /api/reviews?movieId={id} → review-service
        │
        ▼
  otel-collector (OTLP gRPC :4317)
  ├── traces  → Tempo
  └── metrics → Prometheus (scrapes :8889)
```

All services export traces only (`OTEL_METRICS_EXPORTER=none`, `OTEL_LOGS_EXPORTER=none`).
Metrics reach Prometheus via the collector's Prometheus exporter endpoint.

---

## Teardown

```bash
kubectl delete namespace on-demand-observability
```

This removes all resources created by the manifest.
