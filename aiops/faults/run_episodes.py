#!/usr/bin/env python3
"""
Live experiment runner: orchestrates fault episodes against the real cluster and
records ground-truth labels with exact timestamps.

For each scheduled episode it:
  1. (optionally) applies a Chaos Mesh scenario via kubectl
  2. records start time, the injected fault, and the targeted root-cause service
  3. waits the episode duration while the load-generator drives traffic
  4. deletes the chaos resource and records end time
  5. appends a row to a labels CSV

The labels CSV is later joined against telemetry windows pulled by the live
collectors (collectors/telemetry.py with TF_LIVE=1) to build the supervised
dataset for the C1-C4 analysis.

Usage:
    python faults/run_episodes.py --episodes 30 --labels data/labels.csv
    python faults/run_episodes.py --dry-run        # print plan, touch nothing
"""
from __future__ import annotations

import argparse
import csv
import random
import subprocess
import time
from pathlib import Path

# fault -> (chaos manifest, target service that is the injected root cause)
SCENARIOS = {
    "cpu_saturation": ("faults/scenarios/cpu-saturation.yaml", "actor-service"),
    "memory_leak": ("faults/scenarios/memory-leak.yaml", "movie-service"),
    "latency_spike": ("faults/scenarios/latency-spike.yaml", "review-service"),
    "pod_kill": ("faults/scenarios/pod-kill.yaml", "actor-service"),
    "network_partition": ("faults/scenarios/network-partition.yaml", "movie-service"),
}
NS = "on-demand-observability"


def kubectl(args: list[str], dry: bool) -> None:
    cmd = ["kubectl", *args]
    if dry:
        print("   would run:", " ".join(cmd))
        return
    subprocess.run(cmd, check=False)


def write_label(path: str, fault: str, root: str, start: float, end: float) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with p.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["fault", "root_cause", "start_ts", "end_ts"])
        w.writerow([fault, root, f"{start:.3f}", f"{end:.3f}"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--episode-seconds", type=float, default=180)
    ap.add_argument("--gap-seconds", type=float, default=120,
                    help="normal-traffic gap between episodes (negative samples)")
    ap.add_argument("--normal-ratio", type=float, default=0.4)
    ap.add_argument("--labels", default="data/labels.csv")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    faults = list(SCENARIOS)
    print(f"[*] Planning {args.episodes} episodes "
          f"({args.episode_seconds}s each, {args.gap_seconds}s gaps)")

    for ep in range(args.episodes):
        if rng.random() < args.normal_ratio:
            # NORMAL window: no chaos, just record a labelled quiet period.
            start = time.time()
            print(f"[{ep:02d}] NORMAL for {args.gap_seconds}s")
            if not args.dry_run:
                time.sleep(args.gap_seconds)
            end = time.time()
            write_label(args.labels, "normal", "", start, end)
            continue

        fault = rng.choice(faults)
        manifest, root = SCENARIOS[fault]
        print(f"[{ep:02d}] INJECT {fault} -> root={root}")
        kubectl(["apply", "-f", manifest], args.dry_run)
        start = time.time()
        if not args.dry_run:
            time.sleep(args.episode_seconds)
        end = time.time()
        kubectl(["delete", "-f", manifest, "--ignore-not-found"], args.dry_run)
        write_label(args.labels, fault, root, start, end)
        print(f"      cleared; recovery gap {args.gap_seconds}s")
        if not args.dry_run:
            time.sleep(args.gap_seconds)

    print(f"[*] Done. Labels -> {args.labels}")


if __name__ == "__main__":
    main()
