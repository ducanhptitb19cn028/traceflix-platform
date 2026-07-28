"""Off-the-shelf streaming baselines for RQ3.

``online_vs_offline`` compares the bespoke ``OnlineModel`` (SGD + champion pool +
EW normaliser + drift monitor) against two *offline* policies. That leaves an
obvious reviewer question unanswered: is the bespoke machinery earning its
complexity, or would a standard incremental learner do as well?

This script answers it directly. It scores canonical ``partial_fit`` classifiers
prequentially on the *identical* drifted stream -- same generator, seed, regimes
and R0 warm-up as ``online_vs_offline.run_config`` -- so the rows drop straight
beside ``rq3_online_vs_offline.csv``:

  * passive_aggressive -- Crammer et al.'s online margin classifier
  * perceptron         -- the classical mistake-driven linear learner
  * sgd_logistic       -- plain SGD on the logistic loss, no normalisation,
                          no champion pool, no drift monitor. This is the
                          ablation that isolates what the extra machinery buys.
  * gaussian_nb        -- incremental generative baseline

All four see each window once, predict before updating, and are scored on the
post-R0 tail only, exactly as the online model is.

    python -u -m ml.experiments.baseline_streaming --episodes 320 --seed 42
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import (PassiveAggressiveClassifier, Perceptron,
                                  SGDClassifier)
from sklearn.metrics import (f1_score, precision_score, recall_score,
                             roc_auc_score)
from sklearn.naive_bayes import GaussianNB

from ..configs import CONFIGS
from ..drift import generate_drifting_run
from ..features.build import build_features, split_xy


def _make(name: str):
    if name == "passive_aggressive":
        return PassiveAggressiveClassifier(random_state=0)
    if name == "perceptron":
        return Perceptron(random_state=0)
    if name == "sgd_logistic":
        return SGDClassifier(loss="log_loss", learning_rate="constant",
                             eta0=0.01, random_state=0)
    if name == "gaussian_nb":
        # var_smoothing well above the default 1e-9: incremental fitting meets
        # near-constant features early in the stream, and the resulting
        # degenerate variances produce NaN posteriors (divide-by-zero in log).
        return GaussianNB(var_smoothing=1e-6)
    raise ValueError(name)


def _proba(clf, x):
    """Positive-class score, whatever the estimator exposes."""
    if hasattr(clf, "predict_proba"):
        try:
            return float(clf.predict_proba(x)[0][-1])
        except Exception:
            pass
    if hasattr(clf, "decision_function"):
        try:
            d = float(clf.decision_function(x)[0])
            return 1.0 / (1.0 + np.exp(-d))
        except Exception:
            pass
    return float(clf.predict(x)[0])


def prequential(name, X, y, n_warm):
    """Test-then-train over the whole stream; score the post-warm-up tail."""
    clf = _make(name)
    classes = np.array([0, 1])
    preds = np.zeros(len(y), dtype=int)
    probas = np.zeros(len(y), dtype=float)
    started = False
    for i in range(len(y)):
        xi = X[i:i + 1]
        if started:
            preds[i] = int(clf.predict(xi)[0])
            probas[i] = _proba(clf, xi)
        clf.partial_fit(xi, y[i:i + 1], classes=classes)
        started = True
    # A degenerate estimator can still emit NaN; treat that as "no opinion"
    # (0.5) rather than letting it propagate into the metrics, and report the
    # count so a silently broken baseline is visible rather than inferred.
    n_bad = int(np.isnan(probas[n_warm:]).sum())
    probas = np.nan_to_num(probas, nan=0.5)
    return preds[n_warm:], probas[n_warm:], n_bad


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
        df = build_features(windows, CONFIGS[cfg])
        X, y, _, _ = split_xy(df)
        reg = np.asarray(regimes)[:len(y)] if len(regimes) >= len(y) else None
        n_warm = int((reg == 0).sum()) if reg is not None else len(y) // 4
        print(f"[*] {cfg}: {len(y)} windows, R0 warm-up {n_warm}")
        for name in ("passive_aggressive", "perceptron", "sgd_logistic",
                     "gaussian_nb"):
            p, pr, n_bad = prequential(name, X, y, n_warm)
            yte = y[n_warm:]
            rows.append({
                "config": cfg, "model": name,
                "precision": precision_score(yte, p, zero_division=0),
                "recall": recall_score(yte, p, zero_division=0),
                "f1": f1_score(yte, p, zero_division=0),
                "auc_roc": roc_auc_score(yte, pr) if len(set(yte)) > 1 else None,
                "n_future": int(len(yte)), "nan_scores": n_bad,
            })
            flag = f"  [!] {n_bad} NaN scores" if n_bad else ""
            print(f"    {name:20} f1={rows[-1]['f1']:.4f}{flag}")

    res = pd.DataFrame(rows)
    res.to_csv(out / "rq3_streaming_baselines.csv", index=False)
    best = res.loc[res.groupby("config").f1.idxmax()][["config", "model", "f1"]]
    (out / "rq3_streaming_baselines_summary.json").write_text(json.dumps({
        "episodes": args.episodes, "seed": args.seed,
        "best_off_the_shelf_per_config": best.to_dict(orient="records"),
    }, indent=2))
    print("\n[*] ->", out / "rq3_streaming_baselines.csv")
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
