"""
Experiment constants, bound to the *real* TraceFlix deployment.

Services and the call graph come directly from the Java code:
    movie-service  -> actor-service (N sequential RestClient calls)
                   -> review-service
    actor-service  : leaf
    review-service : leaf

Telemetry sources are the on-demand-observability stack:
    metrics -> Prometheus (OTel collector Prometheus exporter, :8889 scrape)
            -> VictoriaMetrics (remote_write, long-range -> used only by C4)
    logs    -> Loki   (collector loki exporter, service.name/service.namespace labels)
    traces  -> Tempo  (collector otlp/tempo exporter)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# --- service topology (from the Spring Boot source) ------------------------
SERVICES = ["movie-service", "actor-service", "review-service"]
ENTRYPOINT = "movie-service"

# directed dependency edges (caller -> callee), used by RCA propagation logic
DEPENDENCIES = {
    "movie-service": ["actor-service", "review-service"],
    "actor-service": [],
    "review-service": [],
}

# --- backend endpoints (override via env for in-cluster vs port-forward) ----
PROM_URL = os.getenv("PROM_URL", "http://localhost:9090")
VM_URL = os.getenv("VM_URL", "http://localhost:8428")
LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100")
TEMPO_URL = os.getenv("TEMPO_URL", "http://localhost:3200")
NAMESPACE = os.getenv("TF_NAMESPACE", "on-demand-observability")

# --- fault taxonomy (proposal §3.3), realisable against these 3 services ----
FAULT_TYPES = [
    "normal",
    "cpu_saturation",
    "memory_leak",          # -> can escalate to OOMKilled at the pod memory limit
    "latency_spike",
    "pod_kill",             # -> CrashLoopBackOff under repeated kills
    "network_partition",
]


@dataclass(frozen=True)
class ObsConfig:
    key: str
    name: str
    signals: tuple[str, ...]   # subset of {metrics, logs, traces, events}
    sources: tuple[str, ...]
    represents: str


CONFIGS: dict[str, ObsConfig] = {
    "C1": ObsConfig("C1", "Metrics-Only", ("metrics",),
                    ("prometheus", "victoriametrics"),
                    "Basic infrastructure monitoring"),
    "C2": ObsConfig("C2", "Metrics + Logs", ("metrics", "logs"),
                    ("prometheus", "loki"),
                    "Intermediate observability maturity"),
    "C3": ObsConfig("C3", "Metrics + Logs + Traces", ("metrics", "logs", "traces"),
                    ("prometheus", "loki", "tempo"),
                    "Full three-pillar observability"),
    "C4": ObsConfig("C4", "Full MELT", ("metrics", "events", "logs", "traces"),
                    ("prometheus", "loki", "tempo", "k8s-events", "victoriametrics"),
                    "Advanced observability with historical context"),
}
