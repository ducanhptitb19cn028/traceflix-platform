"""
Message schemas for the three backbone topics.

Defined once here so producers and consumers cannot drift. Window (de)serialisation
reuses the existing ``collectors.telemetry.Window`` shape verbatim, so a window that
flows through Kafka is byte-for-byte the same object the offline pipeline builds.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from collectors.telemetry import Window

PREFIX = os.getenv("TF_KAFKA_PREFIX", "tf")

TOPIC_WINDOWS = f"{PREFIX}.telemetry.windows"
TOPIC_ANOMALIES = f"{PREFIX}.anomalies"


# --- tf.telemetry.windows ---------------------------------------------------
def window_to_json(w: Window) -> bytes:
    """Serialise a Window exactly as the pipeline sees it (label rides along so
    the prequential detector can test-then-train; see the architecture doc)."""
    return json.dumps({
        "ts": w.ts,
        "service": w.service,
        "fault": w.fault,
        "metrics": w.metrics,
        "logs": w.logs,
        "traces": w.traces,
        "events": w.events,
    }).encode("utf-8")


def window_from_json(raw: bytes | str) -> Window:
    d = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    return Window(
        ts=d["ts"], service=d["service"], fault=d["fault"],
        metrics=d.get("metrics", {}), logs=d.get("logs", {}),
        traces=d.get("traces", {}), events=d.get("events", {}),
    )


def signal_digest(w: Window) -> dict:
    """Compact, human-readable digest of a window's raw signals -- carried on the
    anomaly message so the LLM consumer reasons without re-joining the windows topic."""
    keep_metrics = ("req_rate", "err_rate", "p50_latency", "p99_latency",
                    "cpu", "mem", "gc_pause", "threads")
    d = {f"metrics.{k}": round(float(w.metrics.get(k, 0.0)), 4) for k in keep_metrics}
    d.update({f"logs.{k}": round(float(v), 2) for k, v in w.logs.items()})
    d.update({f"traces.{k}": round(float(v), 2) for k, v in w.traces.items()})
    d.update({f"events.{k}": float(v) for k, v in w.events.items() if v})
    return d


# --- tf.anomalies -----------------------------------------------------------
@dataclass
class AnomalyEvent:
    """A binary anomaly verdict from one detector. Both the online ML detector
    (detector="online_sgd") and the LLM detector (detector="llm") publish these
    to tf.anomalies, tagged by ``detector`` so they can be compared."""
    ts: float
    service: str
    detector: str            # "online_sgd" | "llm"
    y_pred: int              # 0 normal / 1 anomalous
    proba: float             # anomaly probability / confidence
    model_version: str
    signals: dict = field(default_factory=dict)   # raw-signal digest (for dashboards)
    label: int | None = None  # ground truth (None in production)

    def to_json(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @staticmethod
    def from_json(raw: bytes | str) -> "AnomalyEvent":
        d = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return AnomalyEvent(**d)
