# TraceFlix — Live Demo Guide

TraceFlix is a 3-service Spring Boot application used to demonstrate **distributed tracing with OpenTelemetry** on Kubernetes.
All services auto-instrument via the OTel Java agent, export traces to **Tempo**, metrics to **Prometheus**, and everything is visualised in **Grafana**.

---

## Architecture

```
Browser / curl
      │
      ▼
movie-service (:8080)          ← entry point
  ├── GET /api/actors/{id}     → actor-service (:8080)
  └── GET /api/reviews?movieId → review-service (:8080)
             │
             ▼
      otel-collector (:4317 gRPC)
        ├── traces  → Tempo (:3200)
        └── metrics → Prometheus (:9090) via scrape :8889
             │
             ▼
          Grafana (:3000)  ← dashboards
```

---

## Prerequisites

| Tool | Version |
|------|---------|
| Java | 24+ |
| Maven | 3.9+ |
| Docker Desktop | running, Kubernetes enabled |
| kubectl | configured to `docker-desktop` context |

---

## Step 1 — Build JARs

```bash
cd 01-trace-flix
mvn clean package -DskipTests
cd ..
```

---

## Step 2 — Build Docker Images

```bash
# Build and load images into local Docker
docker build --load -t traceflix/actor-service:1.0.0  01-trace-flix/actor-service
docker build --load -t traceflix/review-service:1.0.0 01-trace-flix/review-service
docker build --load -t traceflix/movie-service:1.0.0  01-trace-flix/movie-service
```

### Import into Kubernetes node containerd (Docker Desktop)

Docker Desktop Kubernetes uses a separate containerd — images must be imported explicitly:

```bash
docker save traceflix/actor-service:1.0.0  | docker exec -i desktop-control-plane ctr -n k8s.io images import -
docker save traceflix/review-service:1.0.0 | docker exec -i desktop-control-plane ctr -n k8s.io images import -
docker save traceflix/movie-service:1.0.0  | docker exec -i desktop-control-plane ctr -n k8s.io images import -
```

Verify:
```bash
docker exec desktop-control-plane crictl images | grep traceflix
```

---

## Step 3 — Deploy Everything

```bash
kubectl apply -f on-demand-observability.yaml
```

This creates the `on-demand-observability` namespace and deploys:

| Pod | Image |
|-----|-------|
| otel-collector | `otel/opentelemetry-collector-contrib:0.110.0` |
| tempo | `grafana/tempo:2.5.0` |
| loki | `grafana/loki:2.9.8` |
| prometheus | `prom/prometheus:v2.54.1` |
| grafana | `grafana/grafana:11.1.4` |
| actor-service | `traceflix/actor-service:1.0.0` |
| review-service | `traceflix/review-service:1.0.0` |
| movie-service | `traceflix/movie-service:1.0.0` |

---

## Step 4 — Wait for All Pods

```bash
kubectl get pods -n on-demand-observability -w
```

Expected (all `Running`):
```
NAME                              READY   STATUS    RESTARTS
actor-service-xxx                 1/1     Running   0
grafana-xxx                       1/1     Running   0
loki-xxx                          1/1     Running   0
movie-service-xxx                 1/1     Running   0
otel-collector-xxx                1/1     Running   0
prometheus-xxx                    1/1     Running   0
review-service-xxx                1/1     Running   0
tempo-xxx                         1/1     Running   0
```

> The microservice pods show `Init:0/1` first while downloading the OTel Java agent (~20 MB).

---

## Step 5 — Access Services

> **Port 3000 conflict** — Two services in this repo both listen on port 3000:
>
> | Service | Namespace | Purpose |
> |---------|-----------|---------|
> | `grafana` | `on-demand-observability` | Observability dashboards (Tempo, Prometheus, Loki) |
> | `devops-dashboard` | `devops-agent` | DevOps agent UI |
>
> You cannot port-forward both to `localhost:3000` at the same time.
> Map one of them to a different local port (e.g. `3001`) as shown below.

### movie-service API

```bash
kubectl port-forward svc/movie-service -n on-demand-observability 8080:8080
```

### Grafana (traces, metrics, logs)

```bash
# Forward Grafana to localhost:3000
kubectl port-forward svc/grafana -n on-demand-observability 3000:3000
```

Open **http://localhost:3000** — login: `admin / admin`

Pre-wired data sources:
- **Prometheus** — `http://prometheus:9090`
- **Tempo** — `http://tempo:3200`
- **Loki** — `http://loki:3100`

### DevOps Agent Dashboard

```bash
# Forward devops-dashboard to localhost:3001 (avoids conflict with Grafana on 3000)
kubectl port-forward svc/devops-dashboard -n devops-agent 3001:3000
```

Open **http://localhost:3001**

> If you need both UIs open simultaneously, keep both port-forward commands running in separate terminals.

### Prometheus UI

```bash
kubectl port-forward svc/prometheus -n on-demand-observability 9090:9090
```

Open **http://localhost:9090**

---

## Step 6 — Generate Traces

With movie-service port-forwarded on `:8080`:

```bash
# Normal fast responses (movie IDs 1–7)
curl http://localhost:8080/api/movies/1
curl http://localhost:8080/api/movies/2
curl http://localhost:8080/api/movies/5

# Simulated slow response
curl http://localhost:8080/api/movies/8
curl http://localhost:8080/api/movies/9

# Simulated error (always 500)
curl http://localhost:8080/api/movies/10
```

### Sample Response (movie 2)

```json
{
  "id": 2,
  "title": "The Godfather",
  "releaseYear": 1972,
  "actors": [
    { "id": 3, "name": "Marlon Brando" },
    { "id": 4, "name": "Al Pacino" }
  ],
  "reviews": [
    { "id": 3, "rating": 5, "comment": "A flawless classic. The tension and performances are unmatched.", "reviewer": "Sophie" },
    { "id": 4, "rating": 4, "comment": "Great film, but a bit long for my taste.", "reviewer": "Leo" }
  ]
}
```

---

## Step 7 — View Traces in Grafana

1. Open **http://localhost:3000**
2. Go to **Explore** (compass icon)
3. Select **Tempo** as the data source
4. Click **Search** tab → Run query
5. You will see distributed traces spanning `movie-service → actor-service` and `movie-service → review-service`

Click any trace to see the full span tree with timing for each hop.

---

## Trace Flow

```
movie-service  GET /api/movies/{id}
  │
  ├── [span] GET /api/actors/{actorId}     → actor-service
  │
  └── [span] GET /api/reviews?movieId={id} → review-service
        │
        └── all spans exported via OTLP gRPC → otel-collector → Tempo
```

---

## Supported Movie IDs

| ID | Behaviour |
|----|-----------|
| 1–7 | Normal, fast response |
| 8–9 | Simulated slow response (latency) |
| 10 | Always throws 500 error |

---

## OTel Sampler Configuration

The sampler is configured per deployment via env vars. Current config: `parentbased_traceidratio` at `1.0` (100% sampling).

To change at runtime, edit the deployment env vars:

```bash
kubectl set env deployment/movie-service -n on-demand-observability \
  OTEL_TRACES_SAMPLER=parentbased_traceidratio \
  OTEL_TRACES_SAMPLER_ARG=0.2
```

Sampler options:
- `always_on` — trace every request
- `always_off` — no traces
- `parentbased_traceidratio` + `OTEL_TRACES_SAMPLER_ARG=0.2` — 20% sampling

---

## Teardown

```bash
kubectl delete namespace on-demand-observability
```

Removes all pods, services, configmaps, and the namespace.
