"""
Telemetry collectors for the real TraceFlix stack.

Two interchangeable backends return an identical `Window` schema so the ML
pipeline is agnostic to source:

  * LIVE  (TF_LIVE=1): issues PromQL / LogQL / TraceQL against the deployed
    Prometheus, Loki and Tempo. Metric names are those produced by the
    OpenTelemetry Java agent v2.12.0 and surfaced through the collector's
    Prometheus exporter (dots become underscores, units suffixed), e.g.:
        http.server.request.duration  -> http_server_request_duration_seconds_*
        jvm.memory.used               -> jvm_memory_used_bytes
        jvm.cpu.recent_utilization    -> jvm_cpu_recent_utilization_ratio
    Because OTEL_METRICS_EXPORTER=otlp, these arrive via OTLP -> collector ->
    Prometheus exporter, so the `job="otel-collector"` series carry a
    `service_name` label (resource_to_telemetry_conversion is enabled).

  * SYNTHETIC (default): statistically plausible signals with modest, overlapping
    fault shifts -- lets the full C1-C4 analysis run with no cluster.

Run live once a port-forward (or in-cluster DNS) is available:
    TF_LIVE=1 PROM_URL=http://localhost:9090 LOKI_URL=... TEMPO_URL=... \
      python -m ml.experiments.run_experiment
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field

import numpy as np

from ml.configs import LOKI_URL, PROM_URL, TEMPO_URL, VM_URL

LIVE = os.getenv("TF_LIVE", "0") == "1"


@dataclass
class Window:
    ts: float
    service: str
    fault: str                       # ground-truth label
    metrics: dict = field(default_factory=dict)
    logs: dict = field(default_factory=dict)
    traces: dict = field(default_factory=dict)
    events: dict = field(default_factory=dict)


# ===========================================================================
# LIVE collectors
# ===========================================================================
def _prom_instant(query: str, base: str = PROM_URL) -> float:
    import httpx

    try:
        r = httpx.get(f"{base}/api/v1/query", params={"query": query}, timeout=10)
        res = r.json().get("data", {}).get("result", [])
        return float(res[0]["value"][1]) if res else 0.0
    except Exception:
        return 0.0


def collect_metrics_live(service: str) -> dict:
    """PromQL over OTel-agent metrics. `service_name` is the resource label the
    Prometheus exporter emits when resource_to_telemetry_conversion is on."""
    s = f'service_name="{service}"'
    w = "2m"
    return {
        # request throughput / errors from the HTTP server histogram count
        "req_rate": _prom_instant(
            f"sum(rate(http_server_request_duration_seconds_count{{{s}}}[{w}]))"
        ),
        "err_rate": _prom_instant(
            f'sum(rate(http_server_request_duration_seconds_count{{{s},'
            f'http_response_status_code=~"5.."}}[{w}]))'
        ),
        "p50_latency": _prom_instant(
            f"histogram_quantile(0.5, sum(rate("
            f"http_server_request_duration_seconds_bucket{{{s}}}[{w}])) by (le))"
        ),
        "p99_latency": _prom_instant(
            f"histogram_quantile(0.99, sum(rate("
            f"http_server_request_duration_seconds_bucket{{{s}}}[{w}])) by (le))"
        ),
        # JVM metrics from the agent
        "cpu": _prom_instant(f"avg(jvm_cpu_recent_utilization_ratio{{{s}}})"),
        "mem": _prom_instant(f"sum(jvm_memory_used_bytes{{{s}}})"),
        "gc_pause": _prom_instant(
            f"sum(rate(jvm_gc_duration_seconds_sum{{{s}}}[{w}]))"
        ),
        "threads": _prom_instant(f"avg(jvm_thread_count{{{s}}})"),
        # historical baseline (C4): mem over a long window from VictoriaMetrics
        "mem_baseline_1h": _prom_instant(
            f"avg_over_time(jvm_memory_used_bytes{{{s}}}[1h])", base=VM_URL
        ),
    }


def collect_logs_live(service: str) -> dict:
    import httpx

    def count(expr: str) -> float:
        try:
            r = httpx.get(
                f"{LOKI_URL}/loki/api/v1/query",
                params={"query": f"sum(count_over_time({expr}[2m]))"},
                timeout=10,
            )
            res = r.json().get("data", {}).get("result", [])
            return float(res[0]["value"][1]) if res else 0.0
        except Exception:
            return 0.0

    base = f'{{service_name="{service}"}}'
    return {
        "log_volume": count(base),
        "error_logs": count(base + ' |~ "(?i)error|exception"'),
        "warn_logs": count(base + ' |~ "(?i)warn"'),
        # the controllers log "received headers" per request -> request proxy
        "request_logs": count(base + ' |= "received headers"'),
    }


def collect_traces_live(service: str) -> dict:
    """TraceQL via Tempo search API. error_spans counts spans whose status is
    error AND whose service is this one (origin), which is the trace-only signal
    distinguishing a root cause from a service merely on the latency path."""
    import httpx

    try:
        r = httpx.get(
            f"{TEMPO_URL}/api/search",
            params={"q": f'{{ resource.service.name = "{service}" }}', "limit": 200},
            timeout=10,
        )
        traces = r.json().get("traces", [])
        durs = [t.get("durationMs", 0) for t in traces]
        err = sum(1 for t in traces if str(t.get("rootTraceName", "")).lower()
                  .startswith("error") or t.get("error"))
        return {
            "trace_count": float(len(traces)),
            "mean_span_ms": float(np.mean(durs)) if durs else 0.0,
            "p99_span_ms": float(np.percentile(durs, 99)) if durs else 0.0,
            "error_spans": float(err),
        }
    except Exception:
        return {"trace_count": 0.0, "mean_span_ms": 0.0,
                "p99_span_ms": 0.0, "error_spans": 0.0}


def collect_events_live(service: str) -> dict:
    """K8s events (OOMKilled / CrashLoopBackOff / restarts) via the API server.
    Requires in-cluster RBAC or a kubeconfig; degrades to zeros otherwise."""
    try:
        from kubernetes import client, config  # type: ignore

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        v1 = client.CoreV1Api()
        from ml.configs import NAMESPACE

        evs = v1.list_namespaced_event(NAMESPACE).items
        rel = [e for e in evs if service in (e.involved_object.name or "")]
        return {
            "oomkilled": float(sum(1 for e in rel if e.reason == "OOMKilling")),
            "crashloop": float(sum(1 for e in rel if "CrashLoop" in (e.reason or ""))),
            "pod_restarts": float(sum(1 for e in rel if e.reason == "BackOff")),
            "unhealthy": float(sum(1 for e in rel if e.reason == "Unhealthy")),
        }
    except Exception:
        return {"oomkilled": 0.0, "crashloop": 0.0,
                "pod_restarts": 0.0, "unhealthy": 0.0}


# ===========================================================================
# SYNTHETIC collectors (offline) -- same schema, fault-dependent shifts
# ===========================================================================
_FAULT_SHIFT = {
    "normal": {},
    "cpu_saturation": {"cpu": 2.4, "p99_latency": 1.6, "threads": 1.4, "gc_pause": 1.5},
    "memory_leak": {"mem": 2.0, "gc_pause": 2.2, "err_rate": 1.2},
    "latency_spike": {"p50_latency": 2.0, "p99_latency": 2.3, "threads": 1.5},
    "pod_kill": {"err_rate": 2.4, "req_rate": 0.5, "restart": 1.0},
    "network_partition": {"err_rate": 2.2, "req_rate": 0.5, "request_logs": 0.5},
}


def _synth(service: str, fault: str, ts: float, rng: random.Random,
           is_origin: bool = True) -> Window:
    sh = _FAULT_SHIFT.get(fault, {})
    g = lambda base, key, noise=0.35: max(
        0.0, base * sh.get(key, 1.0) * (1 + rng.gauss(0, noise))
    )
    metrics = {
        "req_rate": g(20, "req_rate"),
        "err_rate": g(0.3, "err_rate"),
        "p50_latency": g(0.03, "p50_latency"),
        "p99_latency": g(0.15, "p99_latency"),
        "cpu": g(0.25, "cpu"),
        "mem": g(180e6, "mem"),
        "gc_pause": g(0.05, "gc_pause"),
        "threads": g(30, "threads"),
        "mem_baseline_1h": 180e6,  # stable baseline; leak deviates from it
    }
    logs = {
        "log_volume": g(120, "req_rate"),
        "error_logs": g(1.0, "err_rate", 0.5),
        "warn_logs": g(2.0, "warn_logs", 0.5),
        "request_logs": g(20, "req_rate"),
    }
    traces = {
        "trace_count": g(20, "req_rate"),
        "mean_span_ms": g(30, "p50_latency") * 1000,
        "p99_span_ms": g(150, "p99_latency") * 1000,
        "error_spans": (g(5.0, "err_rate", 0.3)
                        if (fault != "normal" and is_origin)
                        else g(0.2, "err_rate", 0.4)),
    }
    events = {
        "oomkilled": 1.0 if (fault == "memory_leak" and rng.random() < 0.3) else 0.0,
        "crashloop": 1.0 if fault == "pod_kill" else 0.0,
        "pod_restarts": 1.0 if sh.get("restart") else 0.0,
        "unhealthy": 1.0 if fault in {"memory_leak", "pod_kill"} else 0.0,
    }
    return Window(ts, service, fault, metrics, logs, traces, events)


def collect_window(service: str, fault: str, ts: float, rng: random.Random,
                   is_origin: bool = True) -> Window:
    if LIVE:
        return Window(
            ts, service, fault,
            metrics=collect_metrics_live(service),
            logs=collect_logs_live(service),
            traces=collect_traces_live(service),
            events=collect_events_live(service),
        )
    return _synth(service, fault, ts, rng, is_origin)
