#!/usr/bin/env python3
"""
RQ4: does anomaly detection need to be *online* in a non-stationary system?

Motivation. RQ1-RQ3 hold on a stationary stream, where a model trained once
stays calibrated. Production telemetry is not stationary -- deploys, autoscaling
and data growth shift the operating baseline (``ml/drift.py``). This experiment
quantifies what that does to the traditional batch detector and whether an
online, self-adapting detector closes the gap.

Four references, all on identical features (so the *learning paradigm* is the
only variable, not signal availability):

  * offline_static    -- RandomForest fit once on regime R0, then frozen. The
                         traditional "train on a snapshot, ship it" deployment.
  * offline_periodic  -- RandomForest on a *scheduled retrain* pipeline: refit
                         every ``--retrain-every`` windows on the most recent
                         ``--train-window`` labelled windows, predicting with the
                         currently deployed model in between. The common
                         production compromise -- and the baseline a reviewer
                         always asks for. It tracks drift, but only at its
                         cadence: each regime shift opens a degraded window until
                         the next refresh absorbs enough new-normal, and every
                         refresh is a full batch re-fit.
  * online_adaptive   -- OnlineModel: prequential test-then-train with adaptive
                         normalisation, incremental learning, dynamic
                         hyper-parameter selection and drift-triggered
                         acceleration (``ml/models/online.py``). Updates per
                         sample, no batch re-fit.
  * offline_full      -- RandomForest fit on a random split spanning *all*
                         regimes. An unrealistic oracle (you cannot train on the
                         operational future) included only as the stationary
                         ceiling -- it isolates drift, not model capacity, as the
                         cause of the static model's decay.

Evaluation is fair: the offline models start fit on R0; the online model is
warmed up (test-then-train, unscored) over the same R0 prefix; all are then
scored on the identical post-R0 stream (R1..R3), the operational future.

Outputs (to --out):
  rq4_online_vs_offline.csv  precision/recall/f1/auc per (config, segment, model)
  rq4_timeline.csv           block-wise rolling F1 over the stream, both models
  rq4_summary.json           headline numbers + drift/adaptation events

Run:
    python -m ml.experiments.online_vs_offline --episodes 320 --out data/results
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (f1_score, precision_score, recall_score,
                             roc_auc_score)
from sklearn.model_selection import train_test_split

from ..configs import CONFIGS
from ..drift import REGIME_NAMES, generate_drifting_run
from ..features.build import build_features, split_xy
from ..models.detectors import BaselineModel
from ..models.online import OnlineModel

BLOCK = 250          # window size for the rolling-F1 timeline
TRAIN_REGIME = 0     # regime the static/online models are fit/warmed on


def _metrics(y_true, y_pred, y_proba=None) -> dict:
    out = {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }
    out["auc_roc"] = (
        float(roc_auc_score(y_true, y_proba))
        if (y_proba is not None and len(set(y_true)) > 1) else float("nan")
    )
    return out


def _run_online(X, y, n_warm, n_features):
    """Prequential pass; predictions/probas collected only for the scored tail."""
    model = OnlineModel(n_features=n_features)
    preds = np.zeros(len(y), dtype=int)
    probas = np.zeros(len(y), dtype=float)
    for i in range(len(y)):
        p, pr = model.process_one(X[i], int(y[i]))
        preds[i] = p
        probas[i] = pr
    return preds, probas, model


def _run_periodic(X, y, n_warm, retrain_every, train_window):
    """Scheduled batch retrain. The deployed RF predicts a whole
    ``retrain_every`` segment (test), then is re-fit on the most recent
    ``train_window`` labelled windows (train) -- prequential at segment
    granularity. The lag between a regime shift and the next refresh is exactly
    the operational gap this baseline exposes."""
    n = len(y)
    preds = np.zeros(n, dtype=int)
    probas = np.zeros(n, dtype=float)
    model = BaselineModel("rf", "binary").fit(X[:n_warm], y[:n_warm])
    retrains = [n_warm]
    i = n_warm
    while i < n:
        j = min(n, i + retrain_every)
        preds[i:j] = model.predict(X[i:j])
        pr = model.predict_proba(X[i:j])
        probas[i:j] = pr[:, 1] if pr.shape[1] > 1 else pr.ravel()
        if j < n:                                    # scheduled refresh at j
            lo = max(0, j - train_window)
            model = BaselineModel("rf", "binary").fit(X[lo:j], y[lo:j])
            retrains.append(j)
        i = j
    return preds, probas, retrains


def _rolling_timeline(y, off_pred, per_pred, on_pred, regimes, start):
    """Block-wise F1 for all three streaming models, tagged by regime."""
    rows = []
    n = len(y)
    for b0 in range(0, n, BLOCK):
        b1 = min(n, b0 + BLOCK)
        ys = y[b0:b1]
        if len(ys) < 30:
            continue
        seg_reg = int(np.bincount(regimes[b0:b1]).argmax())
        rows.append({
            "t_center": int(start + (b0 + b1) // 2),
            "regime": seg_reg,
            "regime_name": REGIME_NAMES[seg_reg],
            "offline_static_f1": float(
                f1_score(ys, off_pred[b0:b1], zero_division=0)),
            "offline_periodic_f1": float(
                f1_score(ys, per_pred[b0:b1], zero_division=0)),
            "online_adaptive_f1": float(
                f1_score(ys, on_pred[b0:b1], zero_division=0)),
        })
    return rows


def run_config(cfg_key, windows, regimes, retrain_every, train_window):
    cfg = CONFIGS[cfg_key]
    df = build_features(windows, cfg)
    X, y, _, feats = split_xy(df)
    reg = np.asarray(regimes)

    train_mask = reg == TRAIN_REGIME
    n_warm = int(train_mask.sum())             # R0 prefix length (contiguous)

    Xtr, ytr = X[:n_warm], y[:n_warm]
    Xte, yte = X[n_warm:], y[n_warm:]
    reg_te = reg[n_warm:]

    # --- offline_static: fit on R0, freeze, predict the future ---
    static = BaselineModel("rf", "binary").fit(Xtr, ytr)
    s_pred = static.predict(Xte)
    s_pro = static.predict_proba(Xte)
    s_pos = s_pro[:, 1] if s_pro.shape[1] > 1 else s_pro.ravel()

    # --- offline_periodic: scheduled retrain every `retrain_every` windows ---
    pe_pred_all, pe_pro_all, retrains = _run_periodic(
        X, y, n_warm, retrain_every, train_window)
    p_pred, p_pos = pe_pred_all[n_warm:], pe_pro_all[n_warm:]

    # --- online_adaptive: warm up on R0, score on R1..R3 ---
    on_pred_all, on_pro_all, model = _run_online(X, y, n_warm, X.shape[1])
    o_pred, o_pro = on_pred_all[n_warm:], on_pro_all[n_warm:]

    # --- offline_full (oracle ceiling): random split across all regimes ---
    Xo_tr, Xo_te, yo_tr, yo_te = train_test_split(
        X, y, test_size=0.3, random_state=0, stratify=y)
    oracle = BaselineModel("rf", "binary").fit(Xo_tr, yo_tr)
    oc_pred = oracle.predict(Xo_te)
    oc_pro = oracle.predict_proba(Xo_te)
    oc_pos = oc_pro[:, 1] if oc_pro.shape[1] > 1 else oc_pro.ravel()

    rows = []

    def emit(model_name, segment, regime, yt, yp, ypos):
        m = _metrics(yt, yp, ypos)
        m.update({"config": cfg_key, "name": cfg.name, "segment": segment,
                  "regime": regime, "model": model_name, "n": int(len(yt))})
        rows.append(m)

    # overall (scored future region) for the three realistic models
    emit("offline_static", "overall_future", -1, yte, s_pred, s_pos)
    emit("offline_periodic", "overall_future", -1, yte, p_pred, p_pos)
    emit("online_adaptive", "overall_future", -1, yte, o_pred, o_pro)
    # oracle ceiling (its own random test split)
    emit("offline_full", "overall_allregimes", -1, yo_te, oc_pred, oc_pos)

    # per future regime
    for rg in sorted(set(reg_te.tolist())):
        mask = reg_te == rg
        if mask.sum() < 30:
            continue
        emit("offline_static", REGIME_NAMES[rg], rg,
             yte[mask], s_pred[mask], s_pos[mask])
        emit("offline_periodic", REGIME_NAMES[rg], rg,
             yte[mask], p_pred[mask], p_pos[mask])
        emit("online_adaptive", REGIME_NAMES[rg], rg,
             yte[mask], o_pred[mask], o_pro[mask])

    timeline = _rolling_timeline(yte, s_pred, p_pred, o_pred, reg_te, start=n_warm)
    for t in timeline:
        t["config"] = cfg_key

    info = {
        "config": cfg_key,
        "n_features": len(feats),
        "n_warm_R0": n_warm,
        "n_future": int(len(yte)),
        "periodic_retrains": len(retrains) - 1,    # excludes the initial R0 fit
        "adapt_events": len(model.adapt_events),
        "champion_params_final": model.champion_params,
    }
    return rows, timeline, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=320)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--configs", default="C1,C4",
                    help="comma list of C1..C4 (default C1,C4)")
    ap.add_argument("--retrain-every", type=int, default=500,
                    help="offline_periodic: scheduled refresh cadence (windows)")
    ap.add_argument("--train-window", type=int, default=2880,
                    help="offline_periodic: sliding window of recent windows to "
                         "refit on (default ~one regime)")
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg_keys = [c.strip() for c in args.configs.split(",") if c.strip()]

    print(f"[*] RQ4 online vs offline -- drifting stream, {args.episodes} episodes")
    windows, regimes = generate_drifting_run(
        n_episodes=args.episodes, seed=args.seed)
    n_reg = len(set(regimes))
    print(f"    {len(windows)} windows across {n_reg} operational regimes "
          f"({', '.join(REGIME_NAMES[:n_reg])})")

    print(f"    offline_periodic: refit every {args.retrain_every} windows on "
          f"the last {args.train_window}")

    all_rows, all_tl, infos = [], [], []
    for k in cfg_keys:
        print(f"\n[*] config {k} ({CONFIGS[k].name})")
        rows, tl, info = run_config(
            k, windows, regimes, args.retrain_every, args.train_window)
        all_rows += rows
        all_tl += tl
        infos.append(info)
        df = pd.DataFrame(rows)
        show = df[df.segment.str.startswith("overall")][
            ["model", "precision", "recall", "f1", "auc_roc"]]
        print(show.to_string(index=False))
        print(f"    periodic retrains: {info['periodic_retrains']}   "
              f"online adaptation events: {info['adapt_events']}   "
              f"final champion {info['champion_params_final']}")

    res = pd.DataFrame(all_rows)[
        ["config", "name", "model", "segment", "regime",
         "precision", "recall", "f1", "auc_roc", "n"]]
    res.to_csv(out / "rq4_online_vs_offline.csv", index=False)
    pd.DataFrame(all_tl).to_csv(out / "rq4_timeline.csv", index=False)

    # headline: F1 on the operational future for the three realistic models
    def _f1(sub, name):
        return round(float(sub[sub.model == name]["f1"].iloc[0]), 4)

    headline = {}
    for k in cfg_keys:
        sub = res[(res.config == k) & (res.segment == "overall_future")]
        s, p, o = (_f1(sub, "offline_static"), _f1(sub, "offline_periodic"),
                   _f1(sub, "online_adaptive"))
        headline[k] = {
            "offline_static_f1": s,
            "offline_periodic_f1": p,
            "online_adaptive_f1": o,
            "online_gain_over_static": round(o - s, 4),
            "online_gain_over_periodic": round(o - p, 4),
        }

    summary = {
        "experiment": "RQ4_online_vs_offline",
        "episodes": args.episodes,
        "n_windows": len(windows),
        "n_regimes": n_reg,
        "regimes": REGIME_NAMES[:n_reg],
        "configs": cfg_keys,
        "periodic": {"retrain_every": args.retrain_every,
                     "train_window": args.train_window},
        "headline_f1_future": headline,
        "per_config": infos,
    }
    (out / "rq4_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[*] Results -> {out}/  (rq4_online_vs_offline.csv, "
          f"rq4_timeline.csv, rq4_summary.json)")


if __name__ == "__main__":
    main()
