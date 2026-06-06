"""
Configuration-aware feature engineering.

build_features assembles only the feature families permitted by the active
ObsConfig (C1..C4). Identical windows therefore yield different feature sets per
configuration, isolating *signal availability* as the sole independent variable
(RQ1). Feature names mirror the real telemetry fields collected from the
OTel-agent metrics, Loki logs and Tempo traces.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from collectors.telemetry import Window
from ..configs import ObsConfig

METRIC_FEATS = ["req_rate", "err_rate", "p50_latency", "p99_latency",
                "cpu", "mem", "gc_pause", "threads", "mem_baseline_1h"]
LOG_FEATS = ["log_volume", "error_logs", "warn_logs", "request_logs"]
TRACE_FEATS = ["trace_count", "mean_span_ms", "p99_span_ms", "error_spans"]
EVENT_FEATS = ["oomkilled", "crashloop", "pod_restarts", "unhealthy"]


def _block(windows: list[Window], pillar: str, names: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{f"{pillar}.{n}": float(getattr(w, pillar).get(n, 0.0)) for n in names}
         for w in windows]
    )


def build_features(windows: list[Window], cfg: ObsConfig) -> pd.DataFrame:
    blocks = []
    if "metrics" in cfg.signals:
        blocks.append(_block(windows, "metrics", METRIC_FEATS))
    if "logs" in cfg.signals:
        blocks.append(_block(windows, "logs", LOG_FEATS))
    if "traces" in cfg.signals:
        blocks.append(_block(windows, "traces", TRACE_FEATS))
    if "events" in cfg.signals:
        blocks.append(_block(windows, "events", EVENT_FEATS))

    X = pd.concat(blocks, axis=1) if blocks else pd.DataFrame(index=range(len(windows)))

    if "metrics" in cfg.signals:
        X["metrics.latency_ratio"] = X["metrics.p99_latency"] / (
            X["metrics.p50_latency"] + 1e-6)
        # C4 historical context: deviation of current mem from its 1h baseline
        if "events" in cfg.signals:
            X["metrics.mem_dev"] = (X["metrics.mem"] - X["metrics.mem_baseline_1h"]) / (
                X["metrics.mem_baseline_1h"] + 1e-6)

    X["label_fault"] = [w.fault for w in windows]
    X["label_service"] = [w.service for w in windows]
    X["ts"] = [w.ts for w in windows]
    return X


def split_xy(df: pd.DataFrame):
    feat_cols = [c for c in df.columns if not c.startswith("label_") and c != "ts"]
    X = df[feat_cols].to_numpy(dtype=np.float32)
    y_binary = (df["label_fault"] != "normal").astype(int).to_numpy()
    y_multi = df["label_fault"].to_numpy()
    return X, y_binary, y_multi, feat_cols
