"""
Per-window driver for the webui Streaming page.

Drives the in-memory event backbone one window at a time and yields a snapshot per
window, so the dashboard can show three things live:

  * Topics -- the backbone topics (tf.telemetry.windows, tf.anomalies) and their
              growing message counts, plus the latest verdict feed.
  * MELT   -- the four observability pillars (Metrics / Events / Logs / Traces) of
              the current window, the raw signals each detector sees.
  * LLM    -- the LLM binary detector's verdict next to the online ML detector's,
              with running accuracy / F1 and their agreement.

Analogous to ml/online_sim.run_simulation, but it exercises the real
streaming/ bus + schemas + detectors rather than the online-vs-offline simulation.
"""
from __future__ import annotations

from collections import defaultdict

from ml.configs import CONFIGS
from ml.dataset import generate_run
from ml.features.build import build_features, split_xy
from ml.models.llm_detector import LLMDetector
from ml.models.online import OnlineModel
from .bus import InMemoryBus
from .schemas import (TOPIC_ANOMALIES, TOPIC_WINDOWS, AnomalyEvent,
                      signal_digest, window_to_json)

_PILLARS = ("metrics", "events", "logs", "traces")


class _Score:
    """Running confusion counts -> accuracy + F1 for one detector."""

    __slots__ = ("tp", "fp", "fn", "tn")

    def __init__(self):
        self.tp = self.fp = self.fn = self.tn = 0

    def add(self, y_pred: int, y: int) -> None:
        self.tp += (y_pred == 1 and y == 1)
        self.fp += (y_pred == 1 and y == 0)
        self.fn += (y_pred == 0 and y == 1)
        self.tn += (y_pred == 0 and y == 0)

    def f1(self) -> float:
        d = 2 * self.tp + self.fp + self.fn
        return round(2 * self.tp / d, 4) if d else 0.0

    def acc(self) -> float:
        n = self.tp + self.fp + self.fn + self.tn
        return round((self.tp + self.tn) / n, 4) if n else 0.0


def _vector(window):
    """One window -> the C4 feature vector the online detector expects."""
    X, yb, _, feats = split_xy(build_features([window], CONFIGS["C4"]))
    return X[0], int(yb[0]), feats


def stream_backbone(episodes: int = 40, seed: int = 42, max_windows: int = 2000):
    """Yield one snapshot dict per window flowing through the backbone."""
    bus = InMemoryBus()
    windows, _ = generate_run(n_episodes=episodes, seed=seed)
    windows.sort(key=lambda w: w.ts)
    windows = windows[:max_windows]
    total = len(windows)

    ml_models: dict[str, OnlineModel] = {}
    llm = LLMDetector()
    ml_score, llm_score = _Score(), _Score()
    agree = 0

    for i, w in enumerate(windows, start=1):
        # 1. produce the raw window
        bus.produce(TOPIC_WINDOWS, w.service, window_to_json(w))
        digest = signal_digest(w)

        # 2. online ML detector (prequential test-then-train)
        x, y, feats = _vector(w)
        m = ml_models.get(w.service) or ml_models.setdefault(
            w.service, OnlineModel(n_features=len(feats)))
        ml_pred, ml_proba = m.process_one(x, y)
        ml_pred = int(ml_pred)
        bus.produce(TOPIC_ANOMALIES, w.service, AnomalyEvent(
            ts=w.ts, service=w.service, detector="online_sgd", y_pred=ml_pred,
            proba=float(ml_proba), model_version="online_sgd/v1",
            signals=digest, label=y).to_json())

        # 3. LLM binary detector (parallel, independent)
        verdict = llm.classify_named(digest)
        llm_pred = int(bool(verdict["anomaly"]))
        bus.produce(TOPIC_ANOMALIES, w.service, AnomalyEvent(
            ts=w.ts, service=w.service, detector="llm", y_pred=llm_pred,
            proba=float(verdict["confidence"]),
            model_version=f"llm/{llm.model}" + ("" if llm.mode == "llm" else "/heuristic"),
            signals=digest, label=y).to_json())

        # 4. running stats
        ml_score.add(ml_pred, y)
        llm_score.add(llm_pred, y)
        agree += int(ml_pred == llm_pred)

        yield {
            "processed": i,
            "total": total,
            "ts": w.ts,
            "service": w.service,
            "label": "anomaly" if y else "normal",
            "label_fault": w.fault,
            "melt": {p: {k: round(float(v), 4) for k, v in getattr(w, p).items()}
                     for p in _PILLARS},
            "topics": [
                {"name": TOPIC_WINDOWS, "messages": len(bus._log[TOPIC_WINDOWS]),
                 "role": "telemetry (MELT windows)"},
                {"name": TOPIC_ANOMALIES, "messages": len(bus._log[TOPIC_ANOMALIES]),
                 "role": "detector verdicts (online_sgd + llm)"},
            ],
            "ml": {"pred": ml_pred, "proba": round(float(ml_proba), 3),
                   "f1": ml_score.f1(), "acc": ml_score.acc()},
            "llm": {"pred": llm_pred, "proba": round(float(verdict["confidence"]), 3),
                    "f1": llm_score.f1(), "acc": llm_score.acc(),
                    "mode": llm.mode, "model": llm.model,
                    "explanation": verdict.get("explanation", "")},
            "agreement": round(agree / i, 4),
        }


def backbone_info() -> dict:
    """Static catalogue for the page header (renders before a run starts)."""
    llm = LLMDetector()
    return {
        "topics": [
            {"name": TOPIC_WINDOWS, "role": "telemetry (MELT windows)",
             "producer": "producer_collector", "consumers": ["online_sgd", "llm"]},
            {"name": TOPIC_ANOMALIES, "role": "binary detector verdicts",
             "producer": "online_sgd + llm", "consumers": ["dashboard"]},
        ],
        "pillars": list(_PILLARS),
        "llm": {"model": llm.model, "mode": llm.mode},
        "detectors": ["online_sgd", "llm"],
    }
