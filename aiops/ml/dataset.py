"""
Dataset assembly for the real TraceFlix topology.

A run alternates normal and fault episodes. In a fault episode exactly one
service is the injected root cause; because movie-service calls actor and review
synchronously, a fault at a downstream service propagates a *secondary* latency
symptom upstream to movie-service. This is encoded via is_origin=False so that
only the true origin accumulates originating error spans -- the property RCA
exploits and RQ3 measures.

In LIVE mode this module is bypassed: windows come from collectors with TF_LIVE=1
joined to the labels CSV produced by faults/run_episodes.py. The synthetic path
here mirrors that join so the pipeline is identical offline and online.
"""
from __future__ import annotations

import random

import pandas as pd

from .configs import DEPENDENCIES, ENTRYPOINT, FAULT_TYPES, SERVICES
from collectors.telemetry import Window, collect_window

# reverse edges: which callers depend on a given callee (for upstream symptoms)
_CALLERS = {svc: [c for c, deps in DEPENDENCIES.items() if svc in deps]
            for svc in SERVICES}


def generate_run(n_episodes: int = 120, windows_per_episode: int = 12,
                 normal_ratio: float = 0.4, seed: int = 42):
    rng = random.Random(seed)
    all_windows: list[Window] = []
    rca_episodes: list[tuple[list[Window], str]] = []
    ts = 0.0
    fault_pool = [f for f in FAULT_TYPES if f != "normal"]

    for _ in range(n_episodes):
        if rng.random() < normal_ratio:
            fault, root = "normal", None
        else:
            fault = rng.choice(fault_pool)
            root = rng.choice(SERVICES)

        # services that will show a secondary (upstream) symptom this episode
        secondary = set(_CALLERS.get(root, [])) if root else set()

        episode: list[Window] = []
        for _ in range(windows_per_episode):
            ts += 10.0
            for svc in SERVICES:
                if fault == "normal":
                    svc_fault, is_origin = "normal", False
                elif svc == root:
                    svc_fault, is_origin = fault, True
                elif svc in secondary:
                    # upstream caller inherits latency, not originating errors
                    svc_fault, is_origin = "latency_spike", False
                else:
                    svc_fault, is_origin = "normal", False
                w = collect_window(svc, svc_fault, ts, rng, is_origin)
                episode.append(w)
                all_windows.append(w)

        if root is not None:
            rca_episodes.append((episode, root))

    return all_windows, rca_episodes
