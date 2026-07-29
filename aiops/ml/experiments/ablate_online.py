"""Component ablation of the online detector (RQ3).

``baseline_streaming`` showed that a plain incremental learner with a running
standardiser recovers most of the online detector's accuracy, which raises the
obvious follow-up: of the detector's own components, which one earns its place?

This decomposes the detector along its two switchable mechanisms, on the same
drifted stream, seed and R0 warm-up as ``online_vs_offline``:

  * full            -- EW normaliser + champion pool + drift monitor (as reported)
  * no_drift        -- champion pool, no drift-triggered normaliser boost
  * no_drift_no_champ -- EW normaliser only; champion pinned to the first candidate

Read with ``rq3_streaming_baselines.csv`` this gives the whole ladder, from a raw
SGD classifier through a standardised one to the full detector, so the accuracy
attributable to each mechanism is explicit rather than assumed.

    python -u -m ml.experiments.ablate_online --episodes 320 --seed 42
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (f1_score, precision_score, recall_score,
                             roc_auc_score)

from ..configs import CONFIGS
from ..drift import generate_drifting_run
from ..features.build import build_features, split_xy
from ..models.online import OnlineModel

ARMS = {
    "full": dict(use_champion=True, use_drift=True),
    "no_drift": dict(use_champion=True, use_drift=False),
    "no_drift_no_champion": dict(use_champion=False, use_drift=False),
}


def run_arm(X, y, n_warm, **flags):
    model = OnlineModel(n_features=X.shape[1], **flags)
    preds = np.zeros(len(y), dtype=int)
    probas = np.zeros(len(y), dtype=float)
    for i in range(len(y)):
        preds[i], probas[i] = model.process_one(X[i], int(y[i]))
    return preds[n_warm:], probas[n_warm:], len(model.adapt_events)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=320)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--configs", default="C1,C2,C3,C4")
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    print(f"[*] drifting stream: {args.episodes} episodes, seed {args.seed}")
    windows, regimes = generate_drifting_run(n_episodes=args.episodes,
                                             seed=args.seed)
    rows = []
    for cfg in args.configs.split(","):
        X, y, _, _ = split_xy(build_features(windows, CONFIGS[cfg]))
        reg = np.asarray(regimes)[:len(y)]
        n_warm = int((reg == 0).sum())
        print(f"[*] {cfg}: {len(y)} windows, R0 warm-up {n_warm}")
        for arm, flags in ARMS.items():
            p, pr, n_adapt = run_arm(X, y, n_warm, **flags)
            yte = y[n_warm:]
            rows.append({
                "config": cfg, "arm": arm,
                "precision": precision_score(yte, p, zero_division=0),
                "recall": recall_score(yte, p, zero_division=0),
                "f1": f1_score(yte, p, zero_division=0),
                "auc_roc": roc_auc_score(yte, pr) if len(set(yte)) > 1 else None,
                "adapt_events": n_adapt, "n_future": int(len(yte)),
            })
            print(f"    {arm:22} f1={rows[-1]['f1']:.4f}  adapt={n_adapt}")

    res = pd.DataFrame(rows)
    res.to_csv(out / "rq3_online_ablation.csv", index=False)
    piv = res.pivot(index="config", columns="arm", values="f1")
    summary = {
        "episodes": args.episodes, "seed": args.seed,
        "delta_full_minus_no_drift": (piv["full"] - piv["no_drift"]).round(4).to_dict(),
        "delta_full_minus_no_drift_no_champion":
            (piv["full"] - piv["no_drift_no_champion"]).round(4).to_dict(),
    }
    (out / "rq3_online_ablation_summary.json").write_text(json.dumps(summary, indent=2))
    print("\n[*] ->", out / "rq3_online_ablation.csv")
    print(res.to_string(index=False))
    print("\ndeltas:", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
