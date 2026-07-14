#!/usr/bin/env python3
"""
RQ3 supplementary: trivial baselines, threshold recalibration, and seed variance.

Three controls the headline RQ3 comparison needs but did not report.

  1. always_alarm      -- the degenerate detector that flags every window. Fixes
                          the interpretation of the static model's F1: without a
                          trivial floor, "F1 collapses to 0.36" has no yardstick.

  2. static_recalib    -- the frozen R0 model, but with its decision threshold
                          re-tuned *on the drifted stream itself* (an oracle
                          upper bound no deployment could achieve: it sees the
                          test labels). This isolates *boundary location* from
                          *boundary shape*. If a stale model can be rescued by
                          moving its cut-point alone, continual learning is not
                          needed and RQ3's conclusion does not hold. It is the
                          single strongest objection to the thesis, so it is
                          measured rather than argued.

  3. seed variance     -- the whole comparison, repeated over several seeds, so
                          the paradigm gaps carry a spread rather than resting on
                          one deterministic run.

Writes (additive; does not touch the frozen RQ3 datasets):
  rq3_baselines.csv   per (seed, config): prevalence, always-alarm, static
                      frozen vs. oracle-recalibrated
  rq3_seeds.csv       per (seed, config, policy): precision/recall/f1/auc
  rq3_seeds_summary.json  mean +/- sd of the headline F1 per (config, policy)

Run:
    python -m ml.experiments.baselines_and_seeds --seeds 42,43,44,45,46
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
from ..models.detectors import BaselineModel
from ..models.online import OnlineModel
from .online_vs_offline import _run_periodic, _run_online, TRAIN_REGIME


def _best_threshold_f1(y, scores):
    """Oracle re-threshold: the best F1 attainable from these scores by moving
    the cut-point alone, chosen with knowledge of the test labels."""
    best_f1, best_t = 0.0, 0.5
    for t in np.quantile(scores, np.linspace(0.01, 0.99, 99)):
        f = f1_score(y, (scores >= t).astype(int), zero_division=0)
        if f > best_f1:
            best_f1, best_t = float(f), float(t)
    return best_f1, best_t


def _pr(y, pred, pos=None):
    return {
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "auc_roc": float(roc_auc_score(y, pos)) if pos is not None else float("nan"),
    }


def run_seed(seed, cfg_keys, retrain_every, train_window):
    windows, regimes = generate_drifting_run(n_episodes=320, seed=seed)
    reg = np.asarray(regimes)
    base_rows, pol_rows = [], []

    for key in cfg_keys:
        df = build_features(windows, CONFIGS[key])
        X, y, _, feats = split_xy(df)
        n_warm = int((reg == TRAIN_REGIME).sum())
        Xtr, ytr = X[:n_warm], y[:n_warm]
        Xte, yte = X[n_warm:], y[n_warm:]

        static = BaselineModel("rf", "binary").fit(Xtr, ytr)
        s_pro = static.predict_proba(Xte)
        s_pos = s_pro[:, 1] if s_pro.shape[1] > 1 else s_pro.ravel()
        s_pred = static.predict(Xte)

        recal_f1, recal_t = _best_threshold_f1(yte, s_pos)
        always = np.ones_like(yte)

        base_rows.append({
            "seed": seed, "config": key, "n_future": int(len(yte)),
            "prevalence": float(yte.mean()),
            "always_alarm_f1": float(f1_score(yte, always, zero_division=0)),
            "static_frozen_f1": float(f1_score(yte, s_pred, zero_division=0)),
            "static_frozen_precision": float(precision_score(yte, s_pred, zero_division=0)),
            "static_auc": float(roc_auc_score(yte, s_pos)),
            "static_recalibrated_f1": recal_f1,
            "recalibrated_threshold": recal_t,
        })

        pe_pred, pe_pos, _ = _run_periodic(X, y, n_warm, retrain_every, train_window)
        on_pred, on_pro, _ = _run_online(X, y, n_warm, X.shape[1])

        for name, pred, pos in [
            ("offline_static", s_pred, s_pos),
            ("offline_periodic", pe_pred[n_warm:], pe_pos[n_warm:]),
            ("online_adaptive", on_pred[n_warm:], on_pro[n_warm:]),
        ]:
            r = _pr(yte, pred, pos)
            r.update({"seed": seed, "config": key, "policy": name})
            pol_rows.append(r)

        print(f"    seed {seed} {key}: prev={yte.mean():.3f} "
              f"always={base_rows[-1]['always_alarm_f1']:.3f} "
              f"static={base_rows[-1]['static_frozen_f1']:.3f} "
              f"recal={recal_f1:.3f} "
              f"online={pol_rows[-1]['f1']:.3f}", flush=True)

    return base_rows, pol_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="42,43,44,45,46")
    ap.add_argument("--configs", default="C1,C2,C3,C4")
    ap.add_argument("--retrain-every", type=int, default=500)
    ap.add_argument("--train-window", type=int, default=2880)
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    cfg_keys = [c.strip() for c in args.configs.split(",") if c.strip()]

    print(f"[*] RQ3 baselines + seed variance: seeds={seeds} configs={cfg_keys}")
    all_base, all_pol = [], []
    for sd in seeds:
        print(f"[*] seed {sd}", flush=True)
        b, p = run_seed(sd, cfg_keys, args.retrain_every, args.train_window)
        all_base += b
        all_pol += p

    bdf = pd.DataFrame(all_base)
    pdf = pd.DataFrame(all_pol)
    bdf.to_csv(out / "rq3_baselines.csv", index=False)
    pdf.to_csv(out / "rq3_seeds.csv", index=False)

    summary = {"seeds": seeds, "configs": cfg_keys, "headline_f1_mean_sd": {}}
    for key in cfg_keys:
        summary["headline_f1_mean_sd"][key] = {}
        for pol in ["offline_static", "offline_periodic", "online_adaptive"]:
            v = pdf[(pdf.config == key) & (pdf.policy == pol)]["f1"]
            summary["headline_f1_mean_sd"][key][pol] = {
                "mean": round(float(v.mean()), 4),
                "sd": round(float(v.std(ddof=1)), 4) if len(v) > 1 else 0.0,
                "min": round(float(v.min()), 4),
                "max": round(float(v.max()), 4),
            }
        sub = bdf[bdf.config == key]
        summary["headline_f1_mean_sd"][key]["always_alarm"] = {
            "mean": round(float(sub.always_alarm_f1.mean()), 4)}
        summary["headline_f1_mean_sd"][key]["static_recalibrated"] = {
            "mean": round(float(sub.static_recalibrated_f1.mean()), 4),
            "sd": round(float(sub.static_recalibrated_f1.std(ddof=1)), 4)
            if len(sub) > 1 else 0.0}
        summary["headline_f1_mean_sd"][key]["prevalence"] = round(
            float(sub.prevalence.mean()), 4)

    (out / "rq3_seeds_summary.json").write_text(json.dumps(summary, indent=2))

    print("\n=== headline F1, mean +/- sd over seeds ===")
    for key in cfg_keys:
        d = summary["headline_f1_mean_sd"][key]
        print(f"{key}  prev={d['prevalence']:.3f}  "
              f"always={d['always_alarm']['mean']:.3f}  "
              f"static={d['offline_static']['mean']:.3f}+/-{d['offline_static']['sd']:.3f}  "
              f"recal={d['static_recalibrated']['mean']:.3f}  "
              f"periodic={d['offline_periodic']['mean']:.3f}+/-{d['offline_periodic']['sd']:.3f}  "
              f"online={d['online_adaptive']['mean']:.3f}+/-{d['online_adaptive']['sd']:.3f}")
    print(f"\n[*] -> {out}/rq3_baselines.csv, rq3_seeds.csv, rq3_seeds_summary.json")


if __name__ == "__main__":
    main()
