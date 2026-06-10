#!/usr/bin/env python3
"""
RQ4 cost comparison: offline_periodic (scheduled batch retrain) vs
online_adaptive (per-sample update), on the same drifting stream.

The detection-quality result (``online_vs_offline.py``) shows the online model
leads periodic retraining by 6-9 F1 points. The natural follow-up is *at what
compute cost?* -- because periodic retraining could in principle close the gap
by refitting more often. This benchmark measures the operational cost so the
trade-off is explicit.

It replays the post-R0 stream window-by-window and times the **end-to-end work
per window** (inference + any training that fires on that window), which is the
honest per-window cost a real pipeline pays:

  * offline_periodic does cheap inference most windows, then a heavy full
    RandomForest re-fit on every `retrain_every`-th window -- a latency *spike*
    (bad for a real-time detector) plus a large labelled buffer it must retain.
  * online_adaptive does a small constant amount of work every window
    (predict + partial_fit across the candidate pool), retains no training
    buffer, and ships a tiny linear model.

Reported per model: end-to-end latency (mean / p99 / max over the future
stream), number of train events, cumulative samples trained on, serialized model
size, labelled windows that must be retained for the next fit, and F1 -- so cost
sits next to quality. Wall-clock is machine-dependent; the structural columns
(train events, cumulative samples, model size, retained buffer) are not.

Run:
    python -m ml.experiments.cost_compare --episodes 320 --configs C4
"""
from __future__ import annotations

import argparse
import json
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

from ..configs import CONFIGS
from ..drift import generate_drifting_run
from ..features.build import build_features, split_xy
from ..models.detectors import BaselineModel
from ..models.online import OnlineModel

TRAIN_REGIME = 0


def _periodic_cost(X, y, n_warm, retrain_every, train_window):
    """Replay the future stream in `retrain_every`-sized segments. Inference is
    batched (amortised per window) and the scheduled re-fit's wall-clock is
    charged to the single window that triggers it -- so the per-window latency
    series carries the refit *spike* rather than smearing it away. (Batched on
    purpose: per-single-row predict with a parallel RandomForest is dominated by
    joblib dispatch overhead, which would measure the harness, not the model.)"""
    model = BaselineModel("rf", "binary").fit(X[:n_warm], y[:n_warm])
    n = len(y)
    preds = np.zeros(n, dtype=int)
    lat_ms = np.zeros(n - n_warm, dtype=float)
    train_events = 0
    cum_samples = 0
    i = n_warm
    while i < n:
        j = min(n, i + retrain_every)
        t0 = time.perf_counter()
        preds[i:j] = model.predict(X[i:j])                       # batch inference
        infer_ms = (time.perf_counter() - t0) * 1000.0
        lat_ms[i - n_warm:j - n_warm] = infer_ms / (j - i)       # per-window share
        if j < n:                                                # scheduled refit
            lo = max(0, j - train_window)
            t1 = time.perf_counter()
            model = BaselineModel("rf", "binary").fit(X[lo:j], y[lo:j])
            lat_ms[j - 1 - n_warm] += (time.perf_counter() - t1) * 1000.0  # spike
            train_events += 1
            cum_samples += (j - lo)
        i = j
    return {
        "preds": preds,
        "lat_ms": lat_ms,
        "train_events": train_events,
        "cum_train_samples": cum_samples,
        "model_bytes": len(pickle.dumps(model)),
        "retained_windows": min(train_window, n),   # buffer kept for next refit
    }


def _online_cost(X, y, n_warm, n_features):
    model = OnlineModel(n_features=n_features)
    n = len(y)
    preds = np.zeros(n, dtype=int)
    lat_ms: list[float] = []
    for i in range(n):
        t0 = time.perf_counter()
        p, _ = model.process_one(X[i], int(y[i]))        # predict + update
        dt = (time.perf_counter() - t0) * 1000.0
        preds[i] = p
        if i >= n_warm:
            lat_ms.append(dt)
    n_cand = len(model.candidates)
    return {
        "preds": preds,
        "lat_ms": np.array(lat_ms),
        # one update per window, each touching every candidate learner
        "train_events": n - n_warm,
        "cum_train_samples": (n - n_warm) * n_cand,
        "model_bytes": len(pickle.dumps(model)),
        "retained_windows": 0,                           # nothing kept to refit
        "n_candidates": n_cand,
    }


def _row(name, res, y_future):
    lat = res["lat_ms"]
    return {
        "model": name,
        "f1": round(float(f1_score(y_future, res["preds"], zero_division=0)), 4),
        "train_events": res["train_events"],
        "cum_train_samples": res["cum_train_samples"],
        "total_time_s": round(float(lat.sum() / 1000.0), 3),
        "mean_ms_per_window": round(float(lat.mean()), 4),
        "p99_ms_per_window": round(float(np.percentile(lat, 99)), 4),
        "max_ms_per_window": round(float(lat.max()), 4),
        "model_kb": round(res["model_bytes"] / 1024.0, 1),
        "retained_windows": res["retained_windows"],
    }


def run_config(cfg_key, windows, regimes, retrain_every, train_window):
    X, y, _, _ = split_xy(build_features(windows, CONFIGS[cfg_key]))
    reg = np.asarray(regimes)
    n_warm = int((reg == TRAIN_REGIME).sum())
    y_future = y[n_warm:]

    per = _periodic_cost(X, y, n_warm, retrain_every, train_window)
    onl = _online_cost(X, y, n_warm, X.shape[1])

    # scored on the future region only (R1..R3), aligned to y_future
    per["preds"] = per["preds"][n_warm:]
    onl["preds"] = onl["preds"][n_warm:]

    rows = [_row("offline_periodic", per, y_future),
            _row("online_adaptive", onl, y_future)]
    for r in rows:
        r["config"] = cfg_key
        r["n_future"] = int(len(y_future))
    return rows, per, onl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=320)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--configs", default="C4",
                    help="comma list of C1..C4 (default C4)")
    ap.add_argument("--retrain-every", type=int, default=500)
    ap.add_argument("--train-window", type=int, default=2880)
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg_keys = [c.strip() for c in args.configs.split(",") if c.strip()]

    print(f"[*] RQ4 cost comparison -- drifting stream, {args.episodes} episodes")
    print(f"    offline_periodic: refit every {args.retrain_every} windows on "
          f"the last {args.train_window}")
    windows, regimes = generate_drifting_run(
        n_episodes=args.episodes, seed=args.seed)

    all_rows = []
    ratios = {}
    for k in cfg_keys:
        rows, per, onl = run_config(
            k, windows, regimes, args.retrain_every, args.train_window)
        all_rows += rows
        df = pd.DataFrame(rows)[
            ["model", "f1", "train_events", "cum_train_samples", "total_time_s",
             "mean_ms_per_window", "p99_ms_per_window", "max_ms_per_window",
             "model_kb", "retained_windows"]]
        print(f"\n[*] config {k} ({CONFIGS[k].name}) -- "
              f"{rows[0]['n_future']} future windows")
        print(df.to_string(index=False))

        p_row = next(r for r in rows if r["model"] == "offline_periodic")
        o_row = next(r for r in rows if r["model"] == "online_adaptive")
        ratios[k] = {
            "f1_gain_online_minus_periodic": round(
                o_row["f1"] - p_row["f1"], 4),
            # online's wins: bounded latency, tiny model, no retained data
            "max_latency_ratio_periodic_over_online": round(
                p_row["max_ms_per_window"] / max(1e-9, o_row["max_ms_per_window"]),
                1),
            "model_kb_ratio_periodic_over_online": round(
                p_row["model_kb"] / max(1e-9, o_row["model_kb"]), 1),
            "retained_windows_periodic": p_row["retained_windows"],
            "retained_windows_online": o_row["retained_windows"],
            # honest cost online pays: more total CPU (it works every window)
            "total_cpu_ratio_online_over_periodic": round(
                o_row["total_time_s"] / max(1e-9, p_row["total_time_s"]), 1),
        }
        r = ratios[k]
        print(f"    -> online: +{r['f1_gain_online_minus_periodic']:.3f} F1, "
              f"{r['max_latency_ratio_periodic_over_online']}x lower worst-case "
              f"per-window latency (no blocking refit), "
              f"{r['model_kb_ratio_periodic_over_online']}x smaller model, "
              f"retains 0 vs {p_row['retained_windows']} training windows; "
              f"cost: {r['total_cpu_ratio_online_over_periodic']}x more total CPU "
              f"(constant per-window work vs bursty refits)")

    res = pd.DataFrame(all_rows)
    res.to_csv(out / "rq4_cost.csv", index=False)
    (out / "rq4_cost_summary.json").write_text(json.dumps({
        "episodes": args.episodes,
        "periodic": {"retrain_every": args.retrain_every,
                     "train_window": args.train_window},
        "configs": cfg_keys,
        "ratios_periodic_vs_online": ratios,
    }, indent=2))
    print(f"\n[*] Results -> {out}/  (rq4_cost.csv, rq4_cost_summary.json)")


if __name__ == "__main__":
    main()
