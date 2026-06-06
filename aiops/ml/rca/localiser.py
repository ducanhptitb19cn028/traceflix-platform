"""
Root cause analysis (RQ3: do traces improve localisation?).

RCA here follows HolisticRCA's three dimensions (Han et al., 2024):
  1. entity localisation   : which service is the root cause
  2. feature identification : which signal/feature flags the fault
  3. fault-type classification : what kind of failure

Localisation is scored with Top-k accuracy. The key experimental comparison is
running the same localiser with traces excluded (C2-style features) versus
included (C3/C4), so the contribution of distributed tracing to localisation is
measured directly rather than asserted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from collectors.telemetry import Window


def _anomaly_score(df_service: pd.DataFrame, use_traces: bool) -> float:
    """Per-service anomaly score from feature deviations vs. the window baseline."""
    score = 0.0
    score += df_service.get("metrics.err_rate", pd.Series([0])).mean() * 2.0
    score += df_service.get("metrics.p99_latency", pd.Series([0])).mean() * 1.5
    score += df_service.get("metrics.gc_pause", pd.Series([0])).mean() * 2.0
    score += df_service.get("metrics.cpu", pd.Series([0])).mean() * 1.0
    score += df_service.get("logs.error_logs", pd.Series([0])).mean() * 1.0
    if use_traces:
        # Originating error spans isolate the *source* of a fault: a downstream
        # service shows elevated latency (already counted above) but few
        # originating errors, so weighting error_spans heavily pulls the true
        # root cause to the top without rewarding services that merely inherit
        # latency. This is the crux of RQ3 (Han et al., 2024).
        score += df_service.get("traces.error_spans", pd.Series([0])).mean() * 4.0
    return float(score)


def rank_root_causes(
    features: pd.DataFrame, use_traces: bool
) -> list[tuple[str, float]]:
    """Rank services by anomaly score for a single fault window batch."""
    ranking = []
    for service, grp in features.groupby("label_service"):
        ranking.append((service, _anomaly_score(grp, use_traces)))
    ranking.sort(key=lambda kv: kv[1], reverse=True)
    return ranking


def topk_accuracy(
    episodes: list[tuple[pd.DataFrame, str]], k: int, use_traces: bool
) -> float:
    """episodes: list of (feature_frame_for_episode, true_root_cause_service)."""
    if not episodes:
        return 0.0
    hits = 0
    for feats, truth in episodes:
        ranking = rank_root_causes(feats, use_traces)
        topk = {svc for svc, _ in ranking[:k]}
        hits += int(truth in topk)
    return hits / len(episodes)


def classify_fault_type(window_batch: list[Window]) -> str:
    """Coarse fault-type inference from dominant signal (feature identification)."""
    agg = {"mem": 0.0, "cpu": 0.0, "lat": 0.0, "err": 0.0}
    for w in window_batch:
        agg["mem"] += w.metrics.get("gc_pause", 0) + w.events.get("oomkilled", 0)
        agg["cpu"] += w.metrics.get("cpu", 0)
        agg["lat"] += w.metrics.get("p99_latency", 0)
        agg["err"] += (w.metrics.get("err_rate", 0) + w.logs.get("error_logs", 0)
                       + w.events.get("crashloop", 0))
    dominant = max(agg, key=agg.get)
    return {
        "mem": "memory_leak",
        "cpu": "cpu_saturation",
        "lat": "latency_spike",
        "err": "pod_kill",
    }[dominant]
