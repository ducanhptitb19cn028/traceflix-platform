#!/usr/bin/env python3
"""
RQ-D (reframed): does richer OBSERVABILITY buy earlier detection?

The independent variable is the observability *configuration* (C1 metrics-only ->
C2 +logs -> C3 +traces -> C4 full MELT), not the detector. We hold the detector
constant -- a standard reactive RandomForest classifier -- and ask, for each
configuration, how many windows *before* a service-level objective (SLO) is
breached it can raise the alarm. The question is therefore "how much *lead time*
does each observability configuration deliver, and which signals deliver it?".

To make "early" meaningful, faults have a *gradual onset*: within a fault episode
the intensity alpha ramps 0 -> 1, so the p99 latency climbs and eventually crosses
the SLO threshold `SLO_P99` at a well-defined *breach window*. A detector trained
on a given configuration alarms when its (masked) feature vector first looks
anomalous; the lead time is breach_window - alarm_window (positive = warned early).
Richer telemetry can surface the developing fault earlier -- in particular the
originating-error-span trace signal climbs faster than the aggregate latency
metric -- so lead time is expected to grow with completeness, with the largest
jump when traces are added (C3). Normal episodes (no ramp) give the false-alarm
rate per configuration.

Run:
    python -m ml.experiments.early_detection --episodes 320 --out data/results
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

from ..configs import CONFIGS
from ..features.build import build_features, split_xy
from ..models.detectors import BaselineModel
from collectors.telemetry import Window, _FAULT_SHIFT

SLO_P99 = 0.24            # latency SLO on p99 (s); base p99=0.15, full spike~0.345
RAMP_FAULT = "latency_spike"
KEYS = ["C1", "C2", "C3", "C4"]
ORIGIN = "movie-service"
PERSIST = 2              # consecutive anomalous windows required to raise an alarm

_P99_BASE, _P99_FULL = 0.15, _FAULT_SHIFT[RAMP_FAULT]["p99_latency"]


def _expected_p99(alpha: float) -> float:
    return _P99_BASE * (1.0 + alpha * (_P99_FULL - 1.0))


def _synth_ramp(service, ts, rng, alpha, noise=0.15) -> Window:
    """`_synth` for `RAMP_FAULT` with the fault shift scaled by intensity alpha."""
    sh = _FAULT_SHIFT[RAMP_FAULT]
    eff = lambda key: 1.0 + alpha * (sh.get(key, 1.0) - 1.0)
    g = lambda base, key: max(0.0, base * eff(key) * (1 + rng.gauss(0, noise)))
    metrics = {
        "req_rate": g(20, "req_rate"), "err_rate": g(0.3, "err_rate"),
        "p50_latency": g(0.03, "p50_latency"), "p99_latency": g(0.15, "p99_latency"),
        "cpu": g(0.25, "cpu"), "mem": g(180e6, "mem"), "gc_pause": g(0.05, "gc_pause"),
        "threads": g(30, "threads"), "mem_baseline_1h": 180e6,
    }
    logs = {"log_volume": g(120, "req_rate"), "error_logs": g(1.0, "err_rate"),
            "warn_logs": g(2.0, "warn_logs"), "request_logs": g(20, "req_rate")}
    traces = {"trace_count": g(20, "req_rate"),
              "mean_span_ms": g(30, "p50_latency") * 1000,
              "p99_span_ms": g(150, "p99_latency") * 1000,
              "error_spans": g(0.2, "err_rate") + alpha * g(5.0, "err_rate")}
    events = {"oomkilled": 0.0, "crashloop": 0.0, "pod_restarts": 0.0,
              "unhealthy": 1.0 if alpha > 0.7 else 0.0}
    label = RAMP_FAULT if alpha > 0.0 else "normal"
    return Window(ts, service, label, metrics, logs, traces, events)


def _episode(rng, is_fault, W=24, ramp_start=6, ramp_len=10):
    wins, alphas = [], []
    for t in range(W):
        alpha = min(1.0, max(0.0, (t - ramp_start) / ramp_len)) if is_fault else 0.0
        wins.append(_synth_ramp(ORIGIN, t * 10.0, rng, alpha))
        alphas.append(alpha)
    breach = next((t for t, a in enumerate(alphas) if _expected_p99(a) > SLO_P99), None)
    return wins, breach


def _train(rng, cfg, n=600):
    """RandomForest for one configuration, tuned for *early* detection.

    The positive class is the *developing* fault (intensity alpha drawn from the
    early-to-mid band), not the fully-developed fault, so the detector learns to
    recognise the fault signature while it is still building rather than only once
    it is severe. This is the appropriate training regime for a timeliness study,
    and it makes the late-firing k8s-events signal (zero until alpha>0.7)
    uninformative during training, so configurations are separated by the signals
    that actually carry early information.
    """
    neg = [_synth_ramp(ORIGIN, 0, rng, 0.0) for _ in range(n)]
    pos = [_synth_ramp(ORIGIN, 0, rng, rng.uniform(0.20, 0.60)) for _ in range(n)]
    X, yb, _, _ = split_xy(build_features(neg + pos, cfg))
    return BaselineModel("rf", "binary").fit(np.asarray(X, float), np.asarray(yb))


def _features(wins, cfg):
    return np.asarray(split_xy(build_features(wins, cfg))[0], dtype=float)


def _first_alarm(scores, thr=0.5, persist=PERSIST):
    """First window beginning a run of `persist` consecutive scores above `thr`."""
    run = 0
    for t, s in enumerate(scores):
        if s > thr:
            run += 1
            if run >= persist:
                return t - persist + 1
        else:
            run = 0
    return None


def run(n_episodes, seed=42):
    rng = random.Random(seed)
    detectors = {k: _train(rng, CONFIGS[k]) for k in KEYS}
    n_fault = n_episodes // 2
    rows = []
    for ei in range(n_episodes):
        is_fault = ei < n_fault
        wins, breach = _episode(rng, is_fault)
        for k in KEYS:
            proba = detectors[k].predict_proba(_features(wins, CONFIGS[k]))
            s = proba[:, 1] if (proba.ndim > 1 and proba.shape[1] > 1) else proba.ravel()
            alarm = _first_alarm(s)
            lead = (breach - alarm) if (is_fault and breach is not None
                                        and alarm is not None) else np.nan
            rows.append({
                "episode": ei, "config": k, "is_fault": int(is_fault),
                "breach_t": breach if breach is not None else -1,
                "alarm_t": alarm if alarm is not None else -1,
                "lead": lead,
            })
    return pd.DataFrame(rows)


def _summ(df):
    out = {"experiment": "RQ-D observability completeness vs detection earliness",
           "n_episodes": int(df.episode.nunique()), "SLO_p99": SLO_P99,
           "persist": PERSIST,
           "median_breach_window": float(df[df.is_fault == 1].breach_t.median()),
           "by_config": {}}
    for k in KEYS:
        c = df[df.config == k]
        f = c[c.is_fault == 1]
        n = c[c.is_fault == 0]
        lead = f.lead.dropna()
        out["by_config"][k] = {
            "name": CONFIGS[k].name,
            "detected_fraction": round(float((f.alarm_t >= 0).mean()), 3),
            "median_lead_windows": round(float(lead.median()), 2) if len(lead) else None,
            "mean_lead_windows": round(float(lead.mean()), 2) if len(lead) else None,
            "early_warning_rate": round(float((f.lead > 0).mean()), 3),
            "false_alarm_rate": round(float((n.alarm_t >= 0).mean()), 3),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=320)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    print(f"[*] RQ-D earliness vs observability completeness: {args.episodes} episodes "
          f"(half ramped latency faults), SLO p99={SLO_P99}s, persist={PERSIST}")
    df = run(args.episodes, args.seed)
    df.to_csv(out / "rqD_leadtime.csv", index=False)
    s = _summ(df)
    (out / "rqD_summary.json").write_text(json.dumps(s, indent=2))
    print(f"    median breach at window {s['median_breach_window']:.0f}")
    for k in KEYS:
        a = s["by_config"][k]
        print(f"    {k} {a['name']:<22}: median lead = {a['median_lead_windows']} win, "
              f"early-warning {a['early_warning_rate']*100:.0f}%, "
              f"false-alarm {a['false_alarm_rate']*100:.0f}%")
    print(f"[*] Results -> {out}/rqD_leadtime.csv")


if __name__ == "__main__":
    main()
