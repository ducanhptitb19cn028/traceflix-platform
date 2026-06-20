#!/usr/bin/env python3
"""
RQ-O: Observability-cost optimisation for detection.

The dissertation's core question is "does observability matter for detection?".
RQ1-style ablations answer "more is better"; RQ-O turns that into an *optimisation*:
telemetry is not free (traces especially -- see the sampling literature), so given a
budget, which observability configuration buys the most detection per unit cost?

Decision space = (which modalities to collect) x (trace-sampling rate). Metrics are
always on; logs / traces / events are each on/off; if traces are on they may be
sampled at rate s. Each configuration has:
  * a telemetry COST (traces are the most expensive pillar and scale with the
    sampling rate; events are cheap), and
  * a detection F1 from a RandomForest trained on exactly that configuration
    (trace sampling degrades the trace signal via the RQ-A degradation operator).

We then compute the F1-vs-cost Pareto front and ask: is full MELT actually
cost-optimal, or is a cheaper configuration (e.g. metrics+logs+sampled-traces)
Pareto-dominant? The knee of the front is the recommended minimum-viable
observability for detection.

Run:
    python -m ml.experiments.optimise --episodes 200 --out data/results
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from ..configs import ObsConfig
from ..dataset import generate_run
from ..features.build import build_features, split_xy
from ..models.detectors import BaselineModel
from .run_experiment import _metrics
from .robustness import _degrade            # reuse RQ-A trace-sampling degradation

# per-window telemetry cost units (traces dominate; events cheap) -- consistent
# with the observability-cost literature (tracing is the costliest pillar).
COST = {"metrics": 1.0, "logs": 1.5, "traces": 5.0, "events": 0.3}
SAMPLES = (1.0, 0.5, 0.25, 0.1)


def _short(signals):
    return "+".join({"metrics": "M", "logs": "L", "traces": "T",
                     "events": "E"}[s] for s in signals)


def _configs():
    out = []
    for logs in (0, 1):
        for traces in (0, 1):
            for events in (0, 1):
                sig = (("metrics",) + (("logs",) if logs else ())
                       + (("traces",) if traces else ())
                       + (("events",) if events else ()))
                for s in (SAMPLES if traces else (1.0,)):
                    out.append((sig, s))
    return out


def _cost(signals, s):
    return sum(COST[p] * (s if p == "traces" else 1.0) for p in signals)


def _evaluate(windows, signals, s, rng, seed=0):
    wins = windows
    if "traces" in signals and s < 1.0:
        wins = _degrade(windows, "sampling", s, rng)
    cfg = ObsConfig("cust", _short(signals), tuple(signals), (), "")
    X, yb, _, _ = split_xy(build_features(wins, cfg))
    X, yb = np.asarray(X, float), np.asarray(yb)
    idx = np.arange(len(yb))
    tr, te = train_test_split(idx, test_size=0.3, random_state=seed, stratify=yb)
    m = BaselineModel("rf", "binary").fit(X[tr], yb[tr])
    proba = m.predict_proba(X[te])
    pos = proba[:, 1] if proba.shape[1] > 1 else proba.ravel()
    return _metrics(yb[te], m.predict(X[te]), pos)


def _pareto(df):
    """A config is Pareto-optimal if no other has >= F1 and <= cost (one strict)."""
    flags = []
    for i, a in df.iterrows():
        dominated = any(
            (b.f1 >= a.f1 and b.cost <= a.cost) and (b.f1 > a.f1 or b.cost < a.cost)
            for _, b in df.iterrows())
        flags.append(not dominated)
    return flags


def run(windows, seed=0):
    rng = random.Random(seed)
    rows = []
    for sig, s in _configs():
        r = _evaluate(windows, sig, s, rng, seed)
        rows.append({"config": _short(sig),
                     "sampling": (s if "traces" in sig else float("nan")),
                     "cost": round(_cost(sig, s), 2),
                     "f1": round(r["f1"], 4), "auc_roc": round(r["auc_roc"], 4)})
    df = pd.DataFrame(rows).sort_values("cost").reset_index(drop=True)
    df["pareto"] = _pareto(df)
    df["f1_per_cost"] = (df.f1 / df.cost).round(4)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    print(f"[*] RQ-O observability-cost optimisation: generating {args.episodes} episodes ...")
    windows, _ = generate_run(n_episodes=args.episodes, seed=args.seed)
    df = run(windows, seed=0)
    df.to_csv(out / "rqO_obs_cost.csv", index=False)

    full = df[(df.config == "M+L+T+E") & (df.sampling == 1.0)]
    full = full.iloc[0] if len(full) else df.sort_values("cost").iloc[-1]
    fmax = df.f1.max()
    # cheapest config within 1% of the best F1 = the recommended knee
    near = df[df.f1 >= 0.99 * fmax].sort_values("cost").iloc[0]
    pareto = df[df.pareto].sort_values("cost")

    print(df[["config", "sampling", "cost", "f1", "auc_roc", "pareto", "f1_per_cost"]]
          .to_string(index=False))
    print(f"\n[*] full MELT (cost {full.cost}): F1={full.f1}  | best F1={fmax:.4f}")
    print(f"[*] knee (cheapest within 1% of best F1): {near.config} "
          f"s={near.sampling} cost={near.cost} F1={near.f1} "
          f"-> {(1 - near.cost / full.cost) * 100:.0f}% cheaper than full MELT")
    summary = {
        "experiment": "RQ-O observability-cost optimisation",
        "episodes": args.episodes,
        "full_MELT": {"cost": float(full.cost), "f1": float(full.f1)},
        "best_f1": float(fmax),
        "knee_config": {"config": near.config, "sampling": float(near.sampling),
                        "cost": float(near.cost), "f1": float(near.f1),
                        "cheaper_than_full_MELT_pct": round((1 - near.cost / full.cost) * 100, 1)},
        "full_MELT_is_pareto_optimal": bool(full.pareto) if "pareto" in full else None,
        "pareto_front": pareto[["config", "sampling", "cost", "f1"]].to_dict("records"),
    }
    (out / "rqO_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[*] Results -> {out}/rqO_obs_cost.csv")


if __name__ == "__main__":
    main()
