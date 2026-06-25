"""
End-to-end backbone driver: producer -> {ML detector, LLM detector} -> anomalies.

Both detectors consume tf.telemetry.windows independently and publish binary
verdicts to tf.anomalies, tagged by ``detector``. On the in-memory bus this runs
the whole chain in one process with no Docker and no Ollama (heuristic LLM). With
TF_KAFKA_BOOTSTRAP set and a broker up, the same code drives a real Kafka backbone;
with OLLAMA_URL reachable the LLM stage uses Qwen2.5-3B.

    python -m streaming.run_pipeline --episodes 40
    TF_KAFKA_BOOTSTRAP=localhost:9092 OLLAMA_URL=http://localhost:11434 \
        python -m streaming.run_pipeline --episodes 40
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from .bus import get_bus
from .consumer_detector import run_detector
from .consumer_llm import run_llm
from .producer_collector import produce_run
from .schemas import TOPIC_ANOMALIES, TOPIC_WINDOWS, AnomalyEvent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout", type=float, default=2.0,
                    help="consumer poll timeout (Kafka mode)")
    args = ap.parse_args()

    bus = get_bus()
    print(f"[pipeline] bus backend = {bus.backend}")

    n_w = produce_run(bus, args.episodes, args.seed)
    print(f"[pipeline] {TOPIC_WINDOWS}: produced {n_w} windows")

    n_ml = run_detector(bus, timeout=args.timeout)
    print(f"[pipeline] {TOPIC_ANOMALIES}: ML detector emitted {n_ml} verdicts")

    n_llm = run_llm(bus, timeout=args.timeout)
    print(f"[pipeline] {TOPIC_ANOMALIES}: LLM detector emitted {n_llm} verdicts")

    if bus.backend == "memory":
        _readout(bus)


def _readout(bus) -> None:
    """Per-detector window accuracy + F1 over the shared anomalies topic
    (labels ride along in the scaffold)."""
    tp = defaultdict(int); fp = defaultdict(int)
    fn = defaultdict(int); correct = defaultdict(int); total = defaultdict(int)
    for _k, raw in bus.consume(TOPIC_ANOMALIES, group="readout"):
        e = AnomalyEvent.from_json(raw)
        if e.label is None:
            continue
        d = e.detector
        total[d] += 1
        correct[d] += int(e.y_pred == e.label)
        tp[d] += int(e.y_pred == 1 and e.label == 1)
        fp[d] += int(e.y_pred == 1 and e.label == 0)
        fn[d] += int(e.y_pred == 0 and e.label == 1)
    for d in sorted(total):
        denom = 2 * tp[d] + fp[d] + fn[d]
        f1 = (2 * tp[d] / denom) if denom else 0.0
        print(f"[pipeline] {d:<12} acc={correct[d]/total[d]:.3f} "
              f"f1={f1:.3f} (n={total[d]})")


if __name__ == "__main__":
    main()
