"""
Consumer: tf.telemetry.windows -> OnlineModel verdict -> tf.anomalies.

Preserves the prequential (test-then-train) protocol of ml/models/online.py:
predict the window with the pre-update champion, publish the verdict, *then* learn
from the window's revealed label. One OnlineModel is kept per service.

Run standalone (after a producer has filled the windows topic):
    python -m streaming.consumer_detector
or call ``run_detector(bus, ...)`` from the orchestrator.
"""
from __future__ import annotations

import argparse

from ml.configs import CONFIGS
from ml.features.build import build_features, split_xy
from ml.models.online import OnlineModel
from .bus import get_bus
from .schemas import (TOPIC_ANOMALIES, TOPIC_WINDOWS, AnomalyEvent,
                      signal_digest, window_from_json)

GROUP = "detector"
MODEL_VERSION = "online_sgd/v1"


def _vector(window):
    """One window -> the C4 feature vector OnlineModel expects (label stripped)."""
    df = build_features([window], CONFIGS["C4"])
    X, yb, _, feats = split_xy(df)
    return X[0], int(yb[0]), feats


def run_detector(bus, group: str = GROUP, timeout: float = 1.0) -> int:
    models: dict[str, OnlineModel] = {}
    n = 0
    for _key, raw in bus.consume(TOPIC_WINDOWS, group=group, timeout=timeout):
        w = window_from_json(raw)
        x, y, feats = _vector(w)
        m = models.get(w.service)
        if m is None:
            m = models[w.service] = OnlineModel(n_features=len(feats))
        pred, proba = m.process_one(x, y)   # test-then-train, honest pre-update pred
        evt = AnomalyEvent(
            ts=w.ts, service=w.service, detector=MODEL_VERSION.split("/")[0],
            y_pred=int(pred), proba=float(proba), model_version=MODEL_VERSION,
            signals=signal_digest(w), label=y,
        )
        bus.produce(TOPIC_ANOMALIES, key=w.service, value=evt.to_json())
        n += 1
    bus.flush()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=2.0)
    args = ap.parse_args()
    bus = get_bus()
    n = run_detector(bus, timeout=args.timeout)
    print(f"[detector] processed {n} windows -> {TOPIC_ANOMALIES} "
          f"via {bus.backend} bus")


if __name__ == "__main__":
    main()
