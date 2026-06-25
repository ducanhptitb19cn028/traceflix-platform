"""
Producer: telemetry windows -> tf.telemetry.windows.

Source mirrors the rest of the project:
  * default    -> synthetic generate_run() (no cluster)
  * TF_LIVE=1  -> live collect_window() against Prometheus/Loki/Tempo

Run standalone:
    python -m streaming.producer_collector --episodes 40
or call ``produce_run(bus, ...)`` from the orchestrator.
"""
from __future__ import annotations

import argparse

from ml.dataset import generate_run
from .bus import get_bus
from .schemas import TOPIC_WINDOWS, window_to_json


def produce_run(bus, episodes: int = 40, seed: int = 42) -> int:
    """Generate one run and publish every window in timestamp order."""
    windows, _ = generate_run(n_episodes=episodes, seed=seed)
    windows.sort(key=lambda w: w.ts)
    for w in windows:
        bus.produce(TOPIC_WINDOWS, key=w.service, value=window_to_json(w))
    bus.flush()
    return len(windows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    bus = get_bus()
    n = produce_run(bus, args.episodes, args.seed)
    print(f"[producer] published {n} windows to {TOPIC_WINDOWS} "
          f"via {bus.backend} bus")


if __name__ == "__main__":
    main()
