"""
Dataset assembly for the real TraceFlix topology.

A run alternates normal and fault episodes. In a fault episode exactly one
service is the injected root cause; because movie-service calls actor and review
synchronously, a fault at a downstream service propagates a *secondary* latency
symptom upstream to movie-service.

Two generators live here, and the difference matters:

* ``generate_run`` -- the BASE generator, used by the detection experiments
  (RQ1/RQ3/RQ4). Ancestors inherit latency only, and error spans are gated on
  ``is_origin``. Because ``is_origin`` is the ground-truth label, this generator
  **cannot support a localisation experiment**: the error-span feature is the
  answer key, and any localiser weighting it scores a perfect 1.0 by
  construction rather than by inference.
* ``generate_rca_run`` -- the PROPAGATING generator, used by the localisation
  experiment (RQ2). The fault's errors travel up the call path and attenuate,
  so every service on the path emits error spans and the origin is identifiable
  only as the root of the error tree.

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


def ancestors(root: str | None) -> set[str]:
    """All services transitively upstream of ``root`` (its callers, their callers,
    ... up to the entrypoint). On a deep mesh a fault deep down propagates a
    *secondary* latency symptom to every ancestor on the call path, not just the
    immediate caller -- so many services look anomalous and only the true origin
    carries originating error spans. That gap is exactly what trace-based RCA
    (RQ2) exploits, and what makes Top-k localisation discriminating on a graph
    larger than three nodes."""
    if not root:
        return set()
    seen: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        for caller in _CALLERS.get(node, []):
            if caller not in seen:
                seen.add(caller)
                stack.append(caller)
    return seen


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

        # services that will show a secondary (upstream) symptom this episode:
        # every ancestor on the call path inherits latency (multi-hop propagation)
        secondary = ancestors(root)

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


def hop_distances(root: str) -> dict[str, int]:
    """Ancestors of ``root`` mapped to their *minimum* hop distance up the call
    path. Breadth-first, so a service reachable by two paths (e.g. gateway
    reaches catalog via both search and recommendation) takes the shorter one."""
    from collections import deque

    dist: dict[str, int] = {}
    q = deque([(root, 0)])
    seen = {root}
    while q:
        node, d = q.popleft()
        for caller in _CALLERS.get(node, []):
            if caller not in seen:
                seen.add(caller)
                dist[caller] = d + 1
                q.append((caller, d + 1))
    return dist


def generate_rca_run(n_episodes: int = 200, windows_per_episode: int = 12,
                     normal_ratio: float = 0.4, seed: int = 42,
                     attenuation: float = 0.6, background_errors: float = 0.0):
    """Fault episodes from the *propagating* generator, for the localisation
    experiment (RQ2).

    Differs from ``generate_run`` in one respect that decides whether RQ2 is a
    real experiment. There, a caller inherits only *latency* and error spans are
    switched on by ``is_origin`` -- the ground-truth label -- so the origin is
    the unique emitter and any localiser weighting error spans scores 1.0 by
    construction. Here the fault's errors travel *up* the call path, attenuating
    by ``attenuation`` per hop, so every service on the path emits error spans
    and the origin is identifiable only as the *root of the error tree*.

    The declared modelling assumption: errors attenuate upward (a caller retries
    or falls back, so it errors less than its failing dependency). The origin
    therefore has the highest *expected* error-span count, but the hop-to-hop
    ratio is 0.6 against a noise sigma of 0.45, so adjacent hops overlap heavily
    and magnitude alone does not identify the origin.

    ``background_errors`` is the per-episode probability that a service *off* the
    fault's call path errors on its own account. It is the honesty knob. At 0.0
    the mesh contains exactly one error path, which makes the root of the error
    tree recoverable almost surely -- a property of this generator, not of
    tracing. Raising it introduces spurious competing roots, which is what a real
    mesh presents and what the localiser must survive.

    Returns a list of ``(episode_windows, true_origin_service)``.
    """
    rng = random.Random(seed)
    rca_episodes: list[tuple[list[Window], str]] = []
    ts = 0.0
    fault_pool = [f for f in FAULT_TYPES if f != "normal"]

    for _ in range(n_episodes):
        if rng.random() < normal_ratio:
            ts += windows_per_episode * 10.0   # a normal episode has no origin
            continue
        fault = rng.choice(fault_pool)
        root = rng.choice(SERVICES)
        hops = hop_distances(root)
        # Background incidents are drawn once per episode, not per window: an
        # unrelated error lasts for the episode rather than flickering away.
        background = {
            svc: rng.uniform(0.5, 1.0) for svc in SERVICES
            if svc != root and svc not in hops
            and rng.random() < background_errors
        }

        episode: list[Window] = []
        for _ in range(windows_per_episode):
            ts += 10.0
            for svc in SERVICES:
                if svc == root:
                    svc_fault, level = fault, 1.0
                elif svc in hops:
                    svc_fault, level = "downstream_errors", attenuation ** hops[svc]
                elif svc in background:
                    svc_fault, level = "background_errors", background[svc]
                else:
                    svc_fault, level = "normal", 0.0
                # NB: err_span_level is set from hop distance; the origin flag is
                # not passed and is not consulted by the propagating path.
                episode.append(collect_window(svc, svc_fault, ts, rng,
                                              err_span_level=level))
        rca_episodes.append((episode, root))

    return rca_episodes
