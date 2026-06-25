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

`services/mesh-service/` is one generic Spring Boot service (Java 21, same OTel
java-agent wiring as the originals). It is deployed **once per topology node**; the
call graph is wired entirely by the `DOWNSTREAM_URLS` env var — adding a node is a
compose entry, not new code.

```bash
# build all services incl. the new module
cd services && mvn clean package -DskipTests
docker build -t traceflix/mesh-service:1.0.0 services/mesh-service

# deploy the mesh overlay on VM2 (additive on the base compose)
cd deploy/virtfusion/vm2-services
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
| `services/mesh-service/` | new generic OTel-instrumented service (one image, N nodes) |
| `services/pom.xml` | registers the `mesh-service` module |
| `deploy/virtfusion/vm2-services/docker-compose.mesh.yml` | wires the 6 new nodes + gateway load-gen |
| `deploy/virtfusion/vm2-services/inject-fault.sh` | Pumba fault injection for any of the 9 |
| `tests/test_pipeline.py` | topology + multi-hop propagation invariants |
