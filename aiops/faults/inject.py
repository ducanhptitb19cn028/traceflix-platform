#!/usr/bin/env python3
"""
Single-fault injection against the Kubernetes deployment -- the Chaos Mesh
counterpart of deploy/virtfusion/vm2-services/inject-fault.sh (Pumba/compose).

Where run_episodes.py drives a scheduled sequence from the fixed scenarios in
faults/scenarios/, this injects ONE fault into ANY service in the namespace: the
chaos resource is generated from the service name, so the 9-service mesh
(gateway/user/search/recommendation/auth/catalog) is reachable and not just the
movie/actor/review subtree the static manifests target. It records the identical
ground-truth row -- fault,root_cause,start_ts,end_ts -- so the same C1-C4
analysis joins against it whichever harness produced the episode.

Usage:
    python faults/inject.py <service> <fault> [duration_s]
    python faults/inject.py catalog-service cpu_saturation 120
    python faults/inject.py recommendation-service pod_kill
    python faults/inject.py review-service latency_spike --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

NS = "on-demand-observability"
FAULTS = ("cpu_saturation", "memory_leak", "latency_spike",
          "pod_kill", "network_partition")


def selector(svc: str, ns: str) -> dict:
    return {"namespaces": [ns], "labelSelectors": {"app": svc}}


def manifest(svc: str, fault: str, dur: int, ns: str) -> dict:
    """Build the Chaos Mesh CR for one fault on one service.

    Mirrors the stressor/netem parameters of faults/scenarios/*.yaml so an
    episode injected here is comparable to one injected by run_episodes.py.
    """
    name = f"tf-{fault.replace('_', '-')}-{svc}"
    meta = {"name": name, "namespace": ns}
    sel = selector(svc, ns)
    duration = f"{dur}s"

    if fault == "cpu_saturation":
        spec = {"mode": "all", "selector": sel, "duration": duration,
                "stressors": {"cpu": {"workers": 2, "load": 90}}}
        return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": "StressChaos",
                "metadata": meta, "spec": spec}

    if fault == "memory_leak":
        spec = {"mode": "all", "selector": sel, "duration": duration,
                "stressors": {"memory": {"workers": 1, "size": "300MB"}}}
        return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": "StressChaos",
                "metadata": meta, "spec": spec}

    if fault == "latency_spike":
        spec = {"action": "delay", "mode": "all", "selector": sel,
                "duration": duration,
                "delay": {"latency": "350ms", "jitter": "100ms",
                          "correlation": "50"}}
        return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": "NetworkChaos",
                "metadata": meta, "spec": spec}

    if fault == "network_partition":
        # 100% loss isolates the service from every peer, matching the Pumba
        # path's `netem loss --percent 100` rather than a directed partition.
        spec = {"action": "loss", "mode": "all", "selector": sel,
                "duration": duration,
                "loss": {"loss": "100", "correlation": "0"}}
        return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": "NetworkChaos",
                "metadata": meta, "spec": spec}

    if fault == "pod_kill":
        # One-shot: the pod is killed immediately and the CR carries no
        # duration, so the caller holds the episode window open itself.
        spec = {"action": "pod-kill", "mode": "one", "selector": sel}
        return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": "PodChaos",
                "metadata": meta, "spec": spec}

    raise SystemExit(f"unknown fault: {fault}")


def kubectl(args: list[str], doc: dict | None, dry: bool) -> int:
    cmd = ["kubectl", *args]
    if dry:
        print("   would run:", " ".join(cmd))
        return 0
    payload = json.dumps(doc) if doc is not None else None
    return subprocess.run(cmd, input=payload, text=True).returncode


def write_label(path: str, fault: str, root: str,
                start: float, end: float) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with p.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["fault", "root_cause", "start_ts", "end_ts"])
        w.writerow([fault, root, f"{start:.3f}", f"{end:.3f}"])


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Inject one Chaos Mesh fault and record its ground truth.")
    ap.add_argument("service", help="target service, e.g. catalog-service")
    ap.add_argument("fault", choices=FAULTS)
    ap.add_argument("duration", nargs="?", type=int, default=120,
                    help="episode length in seconds (default 120)")
    ap.add_argument("--labels", default="data/labels.csv")
    ap.add_argument("--namespace", default=NS)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the chaos resource and touch nothing")
    args = ap.parse_args()

    doc = manifest(args.service, args.fault, args.duration, args.namespace)

    if args.dry_run:
        print(json.dumps(doc, indent=2))
        return

    probe = subprocess.run(
        ["kubectl", "get", "deploy", args.service, "-n", args.namespace],
        capture_output=True, text=True)
    if probe.returncode != 0:
        raise SystemExit(
            f"[inject] no deployment {args.service} in {args.namespace}")

    print(f"[inject] {args.fault} -> {args.service} for {args.duration}s", flush=True)
    if kubectl(["apply", "-f", "-"], doc, False) != 0:
        raise SystemExit("[inject] kubectl apply failed")

    start = time.time()
    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        print("\n[inject] interrupted -- clearing the fault early")
    finally:
        end = time.time()
        kubectl(["delete", "-f", "-", "--ignore-not-found"], doc, False)

    write_label(args.labels, args.fault, args.service, start, end)
    print(f"[inject] cleared; labelled -> {args.labels}")


if __name__ == "__main__":
    sys.exit(main())
