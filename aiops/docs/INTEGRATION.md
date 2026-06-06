# Integration with the real TraceFlix stack

## Data flow

```
 load-generator ─► movie-service ─┬─► actor-service   (N sequential RestClient calls)
                                  └─► review-service  (?movieId= query)
        │ all three auto-instrumented by the OTel Java agent (initContainer)
        ▼  OTLP gRPC :4317
   otel-collector 0.110.0
        ├── traces  ─► Tempo 2.5.0
        ├── metrics ─► Prometheus exporter :8889 ─► Prometheus ─► remote_write ─► VictoriaMetrics
        └── logs    ─► Loki 2.9.8
        ▼
   Grafana 11.1.4 (Tempo + Prometheus + Loki)

   ── this layer ──────────────────────────────────────────────
   Chaos Mesh ─► faults on the 3 pods
   faults/run_episodes.py ─► applies chaos + writes data/labels.csv (ground truth)
   collectors/telemetry.py (TF_LIVE=1) ─► PromQL / LogQL / TraceQL / K8s events
   ml/ ─► features (C1–C4) ─► detectors ─► RCA ─► metrics + figures
```

## Metric-name mapping (OTel Java agent → PromQL)

The agent emits OTLP metrics; the collector's Prometheus exporter renames them
(dots→underscores, unit suffixes) and, with
`resource_to_telemetry_conversion: enabled`, attaches resource attributes such
as `service_name` as labels.

| Semantic | OTel instrument | PromQL series used |
|----------|-----------------|--------------------|
| Request rate / errors | `http.server.request.duration` (histogram) | `http_server_request_duration_seconds_count{service_name=…}` (+ `http_response_status_code=~"5.."`) |
| Latency p50/p99 | same histogram | `histogram_quantile(…, http_server_request_duration_seconds_bucket)` |
| JVM CPU | `jvm.cpu.recent_utilization` | `jvm_cpu_recent_utilization_ratio` |
| JVM heap | `jvm.memory.used` | `jvm_memory_used_bytes` |
| GC pause | `jvm.gc.duration` | `jvm_gc_duration_seconds_sum` |
| Threads | `jvm.thread.count` | `jvm_thread_count` |
| Historical mem (C4) | `jvm.memory.used` over 1h | `avg_over_time(jvm_memory_used_bytes[1h])` from VictoriaMetrics |

If your build surfaces slightly different names (agent version / Micrometer
bridge differences), adjust the queries in `collectors/telemetry.py`; they are
all in one place.

## Logs (LogQL)

The collector's loki exporter sets resource labels `service.name`,
`service.namespace`. Both `movie-service` and `review-service` log
`"received headers: {…}"` per request, which the collector forwards; this is
used as a request-count proxy and to distinguish error/warn volume.

## Traces (TraceQL) and why they matter for RCA

`movie-service` calls `actor-service` and `review-service` **synchronously**, so
a fault at a downstream service raises latency on `movie-service` too. Metrics
and logs alone therefore implicate both services. Tempo lets the localiser count
spans whose error **originates** at a service (`error_spans`): only the true
root cause accumulates them, so weighting that signal resolves the ambiguity —
the HolisticRCA finding (Han et al., 2024) and the substance of RQ3.

## Fault → service injection plan

| Fault | Chaos kind | Target | Why this target |
|-------|-----------|--------|-----------------|
| cpu_saturation | StressChaos (cpu) | actor-service | leaf → clean root cause |
| memory_leak | StressChaos (memory 300MB) | movie-service | + memory-limit patch → OOMKilled |
| latency_spike | NetworkChaos (delay) | review-service | propagates upstream → tests RQ3 |
| pod_kill | PodChaos (pod-kill) | actor-service | → CrashLoopBackOff / restart events |
| network_partition | NetworkChaos (partition) | movie↛actor | partial-failure trace signature |

`faults/run_episodes.py` records, per episode, the injected fault and the
intended root-cause service, so the labels CSV is the supervised ground truth
joined against collected windows.

## Offline ↔ live parity

`collectors/telemetry.py` exposes one `collect_window`; LIVE issues real queries,
SYNTHETIC generates the same `Window` schema with modest, overlapping,
high-noise fault shifts. Everything downstream (features, models, RCA, harness)
is identical, so the offline reproduction and the live run share a single code
path — only the data source changes.
