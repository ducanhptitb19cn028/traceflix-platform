# TraceFlix — Platform Demo (the application, not the experiments)

A presentation-grade walkthrough of the **TraceFlix platform as a running product**:
the nine-service Spring Boot mesh, its real business logic, the on-demand
observability stack, distributed traces end-to-end, fault injection, and every way
to deploy it.

> This demo is deliberately **about the system**, not the research. For the empirical
> study (RQ1–RQ4, drift, cost, the LLM detector) see [`fullDemo.md`](fullDemo.md) and
> [`DEMO.md`](DEMO.md). Nothing here runs the `aiops/` experiment layer.

Presenter notes are marked **🗣 Say:**, commands **▶ Run:**, and outputs **✔ Expect:**.

---

## The one-sentence pitch

> TraceFlix is a movie-catalogue application built as a **nine-service call graph**
> with genuine business logic at every node — auto-instrumented with OpenTelemetry so
> a single API request fans out across services and shows up as one distributed trace,
> full metrics, and correlated logs in Grafana.

## What you'll demo

```
services/                         observability/
9 Spring Boot microservices  ──►  OTel Collector ──► Tempo (traces)
(OTel Java agent, MELT)                          ├─► Prometheus (metrics)
gateway → … → catalog                            └─► Loki (logs)  →  Grafana
```

| Part | Shows | ~Time | Needs |
|------|-------|-------|-------|
| 0 | Build the platform | 3 min | JDK 21 + Maven |
| 1 | The nine-service mesh + its business logic | 5 min | — |
| 2 | Run it locally & tour every API | 6 min | the built jars |
| 3 | Observability: one request → one trace | 6 min | Docker (Compose) or k8s |
| 4 | Break it on purpose (fault injection) | 4 min | Docker or k8s |
| 5 | Deploy it (k8s / Compose / 4-VM) | 6 min | kubectl or Docker |
| 6 | Operate it (`make status`, teardown) | 2 min | kubectl |

---

## Prerequisites

| Tool | Version | Needed for |
|------|---------|-----------|
| JDK | 21 (Temurin) | building & running the services |
| Maven | 3.9+ | the multi-module build |
| curl / Postman | any | the API tour (Postman collection in `postman/`) |
| Docker | recent | images, Compose, the observability stack |
| kubectl | optional | the Kubernetes path |

`make help` lists every target; this demo uses the `JAVA`, `KUBERNETES`, `COMPOSE`,
and `FAULTS/LIVE` groups only.

---

# Part 0 — Build the platform

**▶ Run:**

```bash
make build-services        # mvn -q clean package -DskipTests -> nine fat jars
```

**✔ Expect:** `services/*/target/*.jar` for all nine modules. Data owners
(`catalog`, `auth`, `user`) are ~52 MB (JPA + H2 + seed data); orchestrators
(`gateway`, `search`, `recommendation`, `movie`) and leaves (`actor`, `review`) are
lighter.

> 🗣 Say: "It's one Maven reactor — `services/pom.xml` builds all nine modules, and
> the six generic nodes share `services/mesh-core` for their fan-out logic, so the
> call graph is real code, not stubs."

---

# Part 1 — The nine-service mesh

```
gateway ─┬─► movie ──► actor, review            (original TraceFlix subtree)
         ├─► user ───► recommendation ─► catalog
         │        └─► auth
         └─► search ─────────────────► catalog   (shared fan-in; depth 4)
```

| Service | Role | Persists? | Business logic |
|---------|------|-----------|----------------|
| gateway | orchestrator (entry) | no | `/api/browse` fans out to movie + user + search, assembles one payload |
| movie | orchestrator | no | movie details, enriched from actor + review |
| user | orchestrator | H2/JPA | profile, `role` from auth, recs from recommendation |
| search | orchestrator | no | query → catalog lookups |
| recommendation | orchestrator | no | per-user recs → catalog |
| catalog | leaf (**shared fan-in**) | H2/JPA | the catalogue of titles; search + recommendation both call it |
| auth | leaf | H2/JPA | token validation, role lookup |
| actor | leaf | in-memory | actor details by id |
| review | leaf | in-memory | reviews by movieId |

> 🗣 Say: "A request to the gateway touches up to four hops. A fault deep in the graph
> — say `catalog`, which both `search` and `recommendation` depend on — pushes latency
> up **every** ancestor at once, so several services look unhealthy simultaneously.
> That fan-in is exactly what makes distributed traces worth having: they point at the
> *originating* service instead of the symptoms."

**Behaviour built in for observability** (inherited from the original TraceFlix):
- movie ids **1–7** → fast/normal, **8–9** → simulated slow, **10** → always errors.

---

# Part 2 — Run it locally and tour every API

Each service defaults to port `8080` and wires downstreams by container DNS, so for a
single-host local run we set ports + downstream URLs to the scheme the Postman
collection uses (gateway `8080`, movie `8081` … recommendation `8088`).

**▶ Run — bring up the whole mesh (leaves first, gateway last):**

```bash
cd services
J() { java -jar "$1"-service/target/*.jar "${@:2}"; }   # tiny helper

# leaves
J catalog --server.port=8084 &
J auth    --server.port=8086 &
J actor   --server.port=8082 &
J review  --server.port=8083 &
# orchestrators
J movie   --server.port=8081 \
   --actor-service.url=http://localhost:8082/api/actors/ \
   --review-service.url=http://localhost:8083/api/reviews &
J recommendation --server.port=8088 --catalog-service.url=http://localhost:8084 &
J search  --server.port=8085 --catalog-service.url=http://localhost:8084 &
J user    --server.port=8087 \
   --auth-service.url=http://localhost:8086 \
   --recommendation-service.url=http://localhost:8088/api/recommendations &
# entry point
J gateway --server.port=8080 \
   --movie-service.url=http://localhost:8081 \
   --user-service.url=http://localhost:8087 \
   --search-service.url=http://localhost:8085 &
```

**▶ Run — the API tour** (mirrors `postman/traceflix-platform.postman_collection.json`):

```bash
# 1) the entry point — one call, three-way fan-out
curl -s "http://localhost:8080/api/browse?userId=1"

# 2) the original subtree: movie -> actor + review
curl -s http://localhost:8081/api/movies/2          # fast
curl -s http://localhost:8081/api/movies/9          # simulated slow
curl -s -o /dev/null -w '%{http_code}\n' \
        http://localhost:8081/api/movies/10         # simulated error -> 5xx

# 3) the composite user: profile + auth role + recommendation -> catalog
curl -s http://localhost:8087/api/users/1

# 4) leaves directly
curl -s http://localhost:8082/api/actors/1
curl -s "http://localhost:8083/api/reviews?movieId=2"
curl -s http://localhost:8084/api/catalog
curl -s "http://localhost:8084/api/catalog/search?q=a"
curl -s "http://localhost:8086/api/auth/validate?token=tok-alice"
curl -s "http://localhost:8085/api/search?q=a"
curl -s "http://localhost:8088/api/recommendations?userId=1"
```

**✔ Expect** — `user/1` assembled across three services:

```json
{"id":1,"name":"Alice Adams","email":"alice@traceflix.test","tier":"PREMIUM",
 "role":"PREMIUM","recommendations":[{"id":1,"name":"The Shawshank Redemption",...}]}
```

> 🗣 Say: "`user` owns the profile in H2, stamps `role` from **auth**, and pulls
> recommendations from **recommendation → catalog** — a real three-hop call in one
> response. `gateway /api/browse` does the same one level up across movie, user, and
> search. Every field you see crossed a service boundary."

**Import into Postman:** load `postman/traceflix-platform.postman_collection.json` +
`postman/traceflix-local.postman_environment.json` and run the collection — same
requests, one click, with the `localhost:808x` environment already set.

**Stop the mesh:** `pkill -f 'target/'` (or close the terminal).

---

# Part 3 — Observability: one request → one trace

The four MELT pillars — **M**etrics (Prometheus), **E**vents, **L**ogs (Loki),
**T**races (Tempo) — are collected by the **OTel Collector** the services export to
over OTLP. Each service auto-instruments via the OpenTelemetry Java agent (an
initContainer downloads it in k8s; the image bakes it in Compose) — **no application
code is changed to emit telemetry.**

The simplest way to see it is the Kubernetes stack, which ships services + backends +
Grafana pre-wired:

**▶ Run:**

```bash
make images        # build all nine traceflix/*-service:1.0.0 images
make k8s-deploy    # services + on-demand-observability + load-gen (namespace: on-demand-observability)
make status        # watch pods reach Running
```

**▶ Run — port-forward Grafana and the entry point:**

```bash
kubectl port-forward svc/grafana -n on-demand-observability 3000:3000 &
kubectl port-forward svc/gateway-service -n on-demand-observability 8080:8080 &
curl -s "http://localhost:8080/api/browse?userId=1" >/dev/null
```

**✔ Expect —** open **http://localhost:3000** (`admin` / `admin`), pre-wired to:

- **Tempo** — search recent traces: one `GET /api/browse` shows the full span tree
  `gateway → movie → {actor, review}`, `gateway → user → {auth, recommendation → catalog}`,
  `gateway → search → catalog`. Click a span to see per-hop latency.
- **Prometheus** — `Explore` the OTLP metrics, tagged by `service_name`.
- **Loki** — the correlated logs for the same request.

```
services (OTel Java agent) ──OTLP:4317──► otel-collector ─┬─ traces  → Tempo
                                                          ├─ metrics → Prometheus (:8889 scrape)
                                                          └─ logs    → Loki           → Grafana
```

> 🗣 Say: "This is the whole point of the platform: a single business request becomes
> one trace across nine services, plus metrics and logs, without touching a line of
> the Java. In Tempo you can literally watch the fan-out and see which hop owns the
> latency."

*(Prefer Docker over k8s? `make deploy-up` brings up the same mesh + telemetry via
Compose — see Part 5.)*

---

# Part 4 — Break it on purpose (fault injection)

The platform is designed to be observed **under stress**. Inject a fault into any
service and watch the trace/metric change.

**Docker Compose (Pumba, targets any service by name):**

```bash
make inject SVC=catalog-service FAULT=cpu_saturation DUR=120
make inject SVC=recommendation-service FAULT=pod_kill
```

**Kubernetes (Chaos Mesh):**

```bash
make chaos-install                 # install Chaos Mesh into the cluster
```

**✔ Expect:** after a `catalog` fault, `/api/browse` latency rises and — because
`search` **and** `recommendation` both call `catalog` — several ancestors light up in
Grafana at once, while the trace pins the added time to the `catalog` span.

> 🗣 Say: "Fault it at the shared fan-in and the symptoms spread up the graph, but the
> trace still points home. That's the difference between metrics-only alerting ('five
> services are slow') and trace-aware root cause ('catalog is the cause')."

---

# Part 5 — Deploy it

### A. Kubernetes (the original path)

```bash
make images            # build the nine images (imagePullPolicy: Never)
make k8s-deploy        # kubectl apply services + observability + load-gen
make status            # all pods Running in namespace on-demand-observability
# ... port-forward grafana / gateway as in Part 3 ...
make k8s-delete        # tear the namespace down
```

`make bootstrap` chains build + deploy + Chaos Mesh in one shot. Full runbook:
[`services/HOW-TO-RUN.md`](services/HOW-TO-RUN.md).

### B. Docker Compose (single host)

```bash
make deploy-up         # telemetry backends + the nine-service mesh overlay
make status            # (k8s) — for Compose: docker compose ps in deploy/virtfusion/vm2-services
make deploy-down
```

The `mesh-load-generator` drives `GET /api/browse?userId=1..5` continuously, so real
OTel telemetry flows the moment the stack is up.

### C. Four-VM production topology (VirtFusion + WireGuard)

`deploy/virtfusion/` spreads the platform over four VMs (services / telemetry /
gateway / GPU-AIOps) joined by a WireGuard mesh, with TLS + basic-auth at a public
nginx edge. Full runbook: [`deploy/virtfusion/README.md`](deploy/virtfusion/README.md).

> 🗣 Say: "Same images, three deployment shapes — a laptop (Compose), a cluster (k8s),
> or a hardened multi-VM topology. The observability wiring is identical in all three."

---

# Part 6 — Operate it

```bash
make status            # kubectl get pods -n on-demand-observability -o wide
make help              # the whole project's target map
```

**Teardown:**

```bash
make deploy-down       # Compose mesh + telemetry
make k8s-delete        # Kubernetes namespace
pkill -f 'target/'     # any locally-run service jars
```

---

# Appendix A — Service / port / endpoint reference

| Service | Local port | Key endpoint | Calls |
|---------|-----------|--------------|-------|
| gateway | 8080 | `GET /api/browse?userId=` | movie, user, search |
| movie | 8081 | `GET /api/movies/{id}` | actor, review |
| actor | 8082 | `GET /api/actors/{id}` | — |
| review | 8083 | `GET /api/reviews?movieId=` | — |
| catalog | 8084 | `GET /api/catalog`, `/api/catalog/search?q=` | — |
| search | 8085 | `GET /api/search?q=` | catalog |
| auth | 8086 | `GET /api/auth/validate?token=`, `/api/auth/{id}` | — |
| user | 8087 | `GET /api/users/{id}` | auth, recommendation |
| recommendation | 8088 | `GET /api/recommendations?userId=` | catalog |

In k8s/Compose every service listens on `8080` and resolves downstreams by name
(`http://<name>-service:8080`); the ports above are the local-run scheme used by the
Postman environment.

# Appendix B — Special movie ids (observability demo)

| id | Behaviour |
|----|-----------|
| 1–7 | normal / fast |
| 8, 9 | simulated slow response |
| 10 | always errors (5xx) |

Use these to produce clean fast / slow / error traces in Tempo on demand.

# Appendix C — Where the details live

| Doc | Covers |
|-----|--------|
| [`README.md`](README.md) | repo layout, quick start |
| [`services/HOW-TO-RUN.md`](services/HOW-TO-RUN.md) | k8s manifest deploy, port-forwards |
| [`services/README.md`](services/README.md) | original TraceFlix subtree + movie-id behaviour |
| [`deploy/virtfusion/README.md`](deploy/virtfusion/README.md) | four-VM production topology |
| [`aiops/docs/MESH_EXPANSION.md`](aiops/docs/MESH_EXPANSION.md) | how the 3-service app became a 9-service mesh |
| [`fullDemo.md`](fullDemo.md), [`DEMO.md`](DEMO.md) | the **research** demo (RQ1–RQ4) — out of scope here |
