# Mesh Expansion — 9 services, deeper RCA

Grows the system under observation from the original 3-service chain to a **9-service
graph**, so anomaly detection sees more telemetry and root-cause localisation (RQ2)
becomes *discriminating* instead of saturating. The original movie/actor/review
subtree is **unchanged**; a ring of generic OTel-instrumented services wraps it.

## Topology

```
gateway-service (entry) ─┬─▶ movie-service ─┬─▶ actor-service        (ORIGINAL,
                         │                  └─▶ review-service        unchanged)
                         ├─▶ user-service  ─┬─▶ recommendation-service ─▶ catalog-service
                         │                  └─▶ auth-service
                         └─▶ search-service ───────────────────────────▶ catalog-service
```

- **Depth 4** (gateway→user→recommendation→catalog), fan-out at gateway/user, and a
  **shared fan-in** at `catalog-service` (reached by both search and recommendation).
- Single source of truth: `ml/configs.py` (`SERVICES`, `ENTRYPOINT`, `DEPENDENCIES`).
  Everything downstream — dataset, RCA localiser, collectors, streaming backbone,
  webui, online detector — derives the mesh from there; no other file hardcodes a
  service count.

## Why it matters (RQ2)

On the deep graph a fault propagates a **secondary latency symptom up every ancestor**
on the call path (multi-hop, `ml/dataset.py::ancestors`), so many services look
anomalous — but only the true origin carries **originating error spans**. That gap is
exactly what trace-based RCA exploits. Measured (200 synthetic episodes, seed 42):

| RCA features | Top-1 | Top-3 |
|--------------|-------|-------|
| metrics + logs (C2) | **0.77** | 0.95 |
| + traces (C3)       | **1.00** | 1.00 |

The old 3-service mesh saturated (Top-2 → 1.0; only Top-1 discriminated). Now Top-1
is a wide, meaningful gap and Top-3 is informative too — traces clearly drive
localisation on a realistic graph.

> **Paper note.** `paper/sn-article.tex` (RQ2 table + the "three-service topology"
> caption) reports the *old* 3-service numbers. Re-run `run_experiment.py` and
> `online_vs_offline.py` on the 9-service mesh, then recompile, to update them — left
> as a deliberate follow-up so committed results and the manuscript stay in sync.

## Real instrumented services

Each of the six new nodes is its **own** Spring Boot module under `services/` (Java 21,
same OTel java-agent wiring as the originals), each with **real business logic** in the
movie/actor/review style — not a generic shell. Data owners persist with Spring Data
JPA + H2 + `data.sql`; orchestrators are stateless and call downstreams with `RestClient`:

| Service | Role | Domain / endpoints |
|---------|------|--------------------|
| `catalog-service` | leaf, data hub | `Title(name,genre,year,rating)`; `GET /api/catalog`, `/{id}`, `/search?q=` |
| `auth-service` | leaf, data owner | `Account(username,role,token)`; `GET /api/auth/validate?token=`, `/{userId}` |
| `user-service` | data owner + caller | `Profile(name,email,tier)`; `GET /api/users/{id}` → enriches with **auth** role + **recommendation** list |
| `recommendation-service` | orchestrator | `GET /api/recommendations?userId=` → pulls **catalog**, ranks top-5 |
| `search-service` | orchestrator | `GET /api/search?q=` → queries **catalog**, ranks hits |
| `gateway-service` | entry, aggregator | `GET /api/browse?userId=` → fans out to **movie + user + search**, composes a home page |

The call graph is therefore real domain traffic, exactly the edges the topology needs.
Downstream URLs default to the compose DNS names in each `application.properties`
(overridable via `*_SERVICE_URL` env). The load-generator drives `GET /api/browse?userId=`
on the gateway, exercising the whole graph.

```bash
# build everything (3 originals + 6 new modules), then images
cd services && mvn clean package -DskipTests
for s in catalog auth user search recommendation gateway; do
  docker build -t "traceflix/$s-service:1.0.0" "$s-service"
done

# deploy the mesh overlay on VM2 (additive on the base compose)
cd ../deploy/virtfusion/vm2-services
docker compose -f docker-compose.yml -f docker-compose.mesh.yml --env-file ../.env up -d
```

The OTel collector + Prometheus need **no change**: metrics arrive via OTLP tagged by
`service_name`, so the six new services appear in PromQL/Grafana automatically, and
the live collectors (`collectors/telemetry.py`, `TF_LIVE=1`) query all 9.

## Fault injection on the new services

```bash
# Pumba-based, writes the same labels CSV as the k8s harness
deploy/virtfusion/vm2-services/inject-fault.sh catalog-service cpu_saturation 120
deploy/virtfusion/vm2-services/inject-fault.sh recommendation-service pod_kill
```

Offline, the synthetic generator already injects at all 9 services (random root over
`SERVICES`), so RQ1–RQ4 reproduce on the deep mesh with no cluster.

## Files

| File | Change |
|------|--------|
| `ml/configs.py` | 9-service DAG (gateway entry; original subtree intact) |
| `ml/dataset.py` | `ancestors()` — transitive multi-hop upstream propagation |
| `ml/drift.py` | uses the shared `ancestors()` helper |
| `services/{catalog,auth,user}-service/` | data owners — JPA + H2 + `data.sql`, real domain entities/endpoints |
| `services/{recommendation,search,gateway}-service/` | orchestrators — stateless, call downstreams via `RestClient` |
| `services/pom.xml` | registers the six new service modules |
| `deploy/virtfusion/vm2-services/docker-compose.mesh.yml` | wires the 6 new nodes + gateway load-gen |
| `deploy/virtfusion/vm2-services/inject-fault.sh` | Pumba fault injection for any of the 9 |
| `tests/test_pipeline.py` | topology + multi-hop propagation invariants |
