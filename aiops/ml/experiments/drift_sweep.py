#!/usr/bin/env python3
"""Drift-magnitude sweep: where does a frozen detector actually stop working?

``online_vs_offline`` reports one point on a curve. It applies the drift
multipliers of ``ml/drift.REGIME_FACTORS``, which are of the same magnitude as
the fault signatures in ``collectors.telemetry._FAULT_SHIFT`` -- R3 moves p99
latency by 2.2x and CPU by 1.8x, while a latency_spike fault moves p99 by 2.3x
and cpu_saturation moves CPU by 2.4x. Under that setting the post-drift healthy
operating point sits on top of the fault signature the static model was fit to
detect, so its collapse to F1 ~0.36 is entailed by the parameterisation rather
than measured. The single point cannot distinguish "drift breaks frozen models"
from "we set the drift equal to the fault".

This experiment sweeps the amplitude. ``scaled_regime_factors(alpha)``
interpolates every multiplier toward 1, preserving which fields each regime
moves and in what proportion, and varying only how far. alpha=0 is a stationary
stream, alpha=1 reproduces the reported campaign, alpha>1 extrapolates past it.
Labels are computed before the regime factors are applied and the generator
consumes the same random draws either way, so the fault schedule is *identical*
at every alpha: the only thing that varies across the sweep is how far the
healthy operating point has moved.

The output is the curve the paper needs -- static, periodic and online F1 as a
function of operating-point shift -- from which the practitioner question can be
answered: how far can the baseline move before a frozen boundary must be refit?

    python -u -m ml.experiments.drift_sweep --episodes 320 --seed 42
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..configs import CONFIGS
from ..drift import (REGIME_FACTORS, generate_drifting_run, mean_amplitude,
                     scaled_regime_factors)
from .online_vs_offline import run_config

DEFAULT_ALPHAS = "0,0.15,0.3,0.5,0.7,0.85,1.0,1.3"


def always_alarm_f1(prevalence: float) -> float:
    """F1 of the trivial detector that flags every window."""
    return 2.0 * prevalence / (1.0 + prevalence)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=320)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--configs", default="C1,C4")
    ap.add_argument("--alphas", default=DEFAULT_ALPHAS)
    ap.add_argument("--retrain-every", type=int, default=500)
    ap.add_argument("--train-window", type=int, default=2880)
    ap.add_argument("--out", default="data/results_drift_sweep")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    alphas = [float(a) for a in args.alphas.split(",") if a.strip()]
    cfg_keys = [c.strip() for c in args.configs.split(",") if c.strip()]

    print(f"[*] drift-magnitude sweep: alpha in {alphas}")
    print(f"    configs {cfg_keys}, {args.episodes} episodes, seed {args.seed}")

    # Each (alpha, config) point costs ~3.5 min, so the whole sweep is a
    # multi-hour job that an interruption must not discard. Checkpoint after
    # every point and skip on restart whatever is already present, keyed by
    # (alpha, config) -- the same pattern score_llm.py uses for the same reason.
    ckpt = out / "rq3_drift_sweep.csv"
    rows = []
    done: set[tuple[float, str]] = set()
    if ckpt.exists():
        prev = pd.read_csv(ckpt)
        rows = prev.to_dict("records")
        done = {(float(r["alpha"]), str(r["config"])) for r in rows}
        print(f"[*] resuming: {len(done)} point(s) already scored")

    t0 = time.time()
    for ai, alpha in enumerate(alphas):
        if all((alpha, k) in done for k in cfg_keys):
            print(f"    alpha={alpha}: all configs already scored, skipping")
            continue
        factors = scaled_regime_factors(alpha)
        # amplitude of the most-drifted regime, as a plain multiplier
        amp = mean_amplitude(factors[-1])
        windows, regimes = generate_drifting_run(
            n_episodes=args.episodes, seed=args.seed, factors=factors)

        for k in cfg_keys:
            if (alpha, k) in done:
                continue
            res, _tl, info = run_config(
                k, windows, regimes, args.retrain_every, args.train_window)
            df = pd.DataFrame(res)
            fut = df[df.segment == "overall_future"]
            rec = {"alpha": alpha, "r3_amplitude": round(amp, 4), "config": k,
                   "n_future": int(info["n_future"]),
                   "adapt_events": int(info["adapt_events"])}
            for model in ("offline_static", "offline_periodic",
                          "online_adaptive"):
                r = fut[fut.model == model].iloc[0]
                rec[f"{model}_f1"] = round(float(r.f1), 4)
                rec[f"{model}_precision"] = round(float(r.precision), 4)
                rec[f"{model}_recall"] = round(float(r.recall), 4)
                rec[f"{model}_auc"] = round(float(r.auc_roc), 4)
            rows.append(rec)
            done.add((alpha, k))
            # write through after every point -- an interruption then costs at
            # most the point in flight
            pd.DataFrame(rows).sort_values(["config", "alpha"]).to_csv(
                ckpt, index=False)
            el = time.time() - t0
            tot = len(alphas) * len(cfg_keys)
            print(f"    [{len(done)}/{tot}] alpha={alpha:<5} amp={amp:.2f}x {k}: "
                  f"static {rec['offline_static_f1']:.4f} | "
                  f"periodic {rec['offline_periodic_f1']:.4f} | "
                  f"online {rec['online_adaptive_f1']:.4f} "
                  f"({el/60:.1f} min elapsed)", flush=True)

    res = pd.DataFrame(rows).sort_values(["config", "alpha"])
    res.to_csv(ckpt, index=False)

    # prevalence is a property of the fault schedule, which alpha does not touch
    prev = 0.170833
    floor = always_alarm_f1(prev)

    # knee: the largest alpha at which the frozen model still holds a stated
    # margin over the trivial floor
    summary = {"experiment": "RQ3_drift_magnitude_sweep",
               "episodes": args.episodes, "seed": args.seed,
               "alphas": alphas, "configs": cfg_keys,
               "always_alarm_f1": round(floor, 4),
               "note": "alpha=1 reproduces the reported campaign; the fault "
                       "schedule is identical at every alpha",
               "per_config": {}}
    for k in cfg_keys:
        sub = res[res.config == k].sort_values("alpha")
        holds = sub[sub.offline_static_f1 >= 2 * floor]
        summary["per_config"][k] = {
            "static_f1_by_alpha": dict(zip(sub.alpha.astype(str),
                                           sub.offline_static_f1)),
            "online_f1_by_alpha": dict(zip(sub.alpha.astype(str),
                                           sub.online_adaptive_f1)),
            "largest_alpha_static_above_2x_floor":
                float(holds.alpha.max()) if len(holds) else None,
            "amplitude_there":
                float(holds.r3_amplitude.max()) if len(holds) else None,
        }
    (out / "rq3_drift_sweep_summary.json").write_text(
        json.dumps(summary, indent=2))

    print(f"\n[*] sweep -> {out}/rq3_drift_sweep.csv")
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
