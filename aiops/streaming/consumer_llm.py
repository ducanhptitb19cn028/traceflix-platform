"""
Consumer: tf.telemetry.windows -> LLM binary verdict -> tf.anomalies.

The LLM detector is a *second binary anomaly detector*, running in parallel with
the online ML detector (consumer_detector.py) rather than downstream of it. It reads
the raw signals of each window and answers only "anomalous or not" -- no fault
typing -- and publishes an AnomalyEvent tagged detector="llm", directly comparable
to the ML detector's verdict on the same topic.

    python -m streaming.consumer_llm
or call ``run_llm(bus, ...)`` from the orchestrator.
"""
from __future__ import annotations

import argparse

from ml.models.llm_detector import OLLAMA_MODEL, LLMDetector
from .bus import get_bus
from .schemas import (TOPIC_ANOMALIES, TOPIC_WINDOWS, AnomalyEvent,
                      signal_digest, window_from_json)

GROUP = "llm-detector"


def run_llm(bus, group: str = GROUP, timeout: float = 1.0) -> int:
    det = LLMDetector()
    version = f"llm/{det.model}" + ("" if det.mode == "llm" else "/heuristic")
    print(f"[llm] mode={det.mode} model={det.model}")
    n = 0
    for _key, raw in bus.consume(TOPIC_WINDOWS, group=group, timeout=timeout):
        w = window_from_json(raw)
        digest = signal_digest(w)
        verdict = det.classify_named(digest)
        evt = AnomalyEvent(
            ts=w.ts, service=w.service, detector="llm",
            y_pred=int(bool(verdict["anomaly"])),
            proba=float(verdict["confidence"]),
            model_version=version, signals=digest,
            label=int(w.fault != "normal"),
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
    n = run_llm(bus, timeout=args.timeout)
    print(f"[llm] emitted {n} verdicts (detector=llm) -> {TOPIC_ANOMALIES} "
          f"via {bus.backend} bus")


if __name__ == "__main__":
    main()
