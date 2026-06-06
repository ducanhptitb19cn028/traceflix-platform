"""
Non-stationary telemetry stream for RQ4 (online vs offline anomaly detection).

`dataset.generate_run` produces a *stationary* stream: the normal operating
point is fixed, so a model trained once stays calibrated forever. Real
distributed systems are not stationary. Their telemetry baseline drifts as
*operations* happen:

    * a release regresses latency / raises CPU         (performance regime shift)
    * autoscaling and traffic growth raise throughput  (volume regime shift)
    * data accumulation grows the JVM memory footprint (capacity regime shift)

None of these are faults -- they are the new *normal*. But a detector whose
decision boundary was fixed on last month's normal will start flagging today's
normal as anomalous (false positives), i.e. it decays. This module injects that
drift so the failure can be measured.

Design: the stream is split into operational regimes R0..R{n-1}. Each regime
multiplies the operating point of the *volume / latency / capacity* telemetry
fields by a regime factor. The multiplier is applied identically to normal and
faulty windows, so it shifts the feature distribution **without changing the
ground-truth label** -- a fault is still a fault, it just rides on a higher
baseline. Error-rate and originating-error-span signals are left on their native
scale (an error is an error regardless of how much traffic flows), which is why
trace-based RCA is comparatively drift-robust while metric-threshold detection
is not.

R0 is the regime the offline model is trained on; R1..R3 are the operational
future it never saw.
"""
from __future__ import annotations

import random

from .configs import FAULT_TYPES, SERVICES
from .dataset import _CALLERS
from collectors.telemetry import Window, collect_window

# Which telemetry fields drift with operations. Error/originating-error signals
# are deliberately excluded -- they encode *failure*, not *operating point*.
_DRIFT_FIELDS = {
    "metrics": ["req_rate", "p50_latency", "p99_latency", "cpu", "mem",
                "gc_pause", "threads", "mem_baseline_1h"],
    "logs": ["log_volume", "warn_logs", "request_logs"],
    "traces": ["trace_count", "mean_span_ms", "p99_span_ms"],
}

# Cumulative operational evolution. R0 == deployment the offline model trains on.
REGIME_FACTORS: list[dict[str, float]] = [
    # R0 -- baseline (what the static model is fit on)
    {},
    # R1 -- a release regresses latency, CPU and GC climb
    {"p50_latency": 1.8, "p99_latency": 1.9, "cpu": 1.5, "threads": 1.3,
     "gc_pause": 1.4, "mean_span_ms": 1.8, "p99_span_ms": 1.9},
    # R2 -- scale-out: throughput and log/trace volume double, memory grows
    {"req_rate": 2.0, "log_volume": 2.0, "request_logs": 2.0, "warn_logs": 1.6,
     "trace_count": 2.0, "mem": 1.6, "mem_baseline_1h": 1.6,
     "p50_latency": 1.3, "p99_latency": 1.4, "mean_span_ms": 1.3,
     "p99_span_ms": 1.4},
    # R3 -- combined heavy regime (everything has moved)
    {"p50_latency": 2.0, "p99_latency": 2.2, "cpu": 1.8, "threads": 1.5,
     "gc_pause": 1.7, "mem": 1.9, "mem_baseline_1h": 1.9, "req_rate": 2.2,
     "log_volume": 2.2, "request_logs": 2.2, "warn_logs": 1.8,
     "trace_count": 2.2, "mean_span_ms": 2.0, "p99_span_ms": 2.2},
]

REGIME_NAMES = ["R0 baseline", "R1 latency regression", "R2 scale-out",
                "R3 combined load"]


def apply_regime(w: Window, factors: dict[str, float]) -> Window:
    """Scale a window's operating-point fields in place; labels untouched."""
    for pillar, fields in _DRIFT_FIELDS.items():
        bag = getattr(w, pillar)
        for col in fields:
            if col in factors and col in bag:
                bag[col] *= factors[col]
    return w


def generate_drifting_run(
    n_episodes: int = 320,
    windows_per_episode: int = 12,
    normal_ratio: float = 0.45,
    n_regimes: int = 4,
    seed: int = 42,
):
    """Time-ordered stream of windows whose normal operating point drifts across
    `n_regimes` operational regimes.

    Returns
    -------
    windows : list[Window]            -- in stream (time) order
    regimes : list[int]               -- regime index per window, aligned to `windows`
    """
    if n_regimes > len(REGIME_FACTORS):
        raise ValueError(f"n_regimes<= {len(REGIME_FACTORS)} supported")
    rng = random.Random(seed)
    windows: list[Window] = []
    regimes: list[int] = []
    ts = 0.0
    fault_pool = [f for f in FAULT_TYPES if f != "normal"]
    per = n_episodes / n_regimes

    for ei in range(n_episodes):
        regime = min(n_regimes - 1, int(ei / per))
        factors = REGIME_FACTORS[regime]

        if rng.random() < normal_ratio:
            fault, root = "normal", None
        else:
            fault = rng.choice(fault_pool)
            root = rng.choice(SERVICES)
        secondary = set(_CALLERS.get(root, [])) if root else set()

        for _ in range(windows_per_episode):
            ts += 10.0
            for svc in SERVICES:
                if fault == "normal":
                    svc_fault, is_origin = "normal", False
                elif svc == root:
                    svc_fault, is_origin = fault, True
                elif svc in secondary:
                    svc_fault, is_origin = "latency_spike", False
                else:
                    svc_fault, is_origin = "normal", False
                w = collect_window(svc, svc_fault, ts, rng, is_origin)
                apply_regime(w, factors)
                windows.append(w)
                regimes.append(regime)

    return windows, regimes
