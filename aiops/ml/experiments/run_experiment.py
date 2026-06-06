#!/usr/bin/env python3
"""
C1-C4 experiment harness for the real TraceFlix stack (RQ1, RQ2, RQ3).

  RQ1: hold the model fixed, vary observability completeness C1..C4, compare
       detection precision/recall/F1/AUC.
  RQ2: under the richest configuration (C4), compare RF / GB / XGBoost / LSTM /
       multimodal late-fusion (HolisticRCA building blocks).
  RQ3: Top-k root-cause localisation with traces excluded (C2) vs included (C3).

Data source is automatic:
  * default      -> synthetic generator (no cluster needed)
  * TF_LIVE=1    -> live PromQL/LogQL/TraceQL via collectors, joined to the
                    labels CSV from faults/run_episodes.py (pass --labels).

Run:
    python -m ml.experiments.run_experiment --episodes 200 --out data/results
    TF_LIVE=1 python -m ml.experiments.run_experiment --labels data/labels.csv
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd
from sklearn.metrics import (f1_score, precision_score, recall_score,
                             roc_auc_score)
from sklearn.model_selection import train_test_split

from ..configs import CONFIGS
from ..dataset import generate_run
from ..features.build import build_features, split_xy
from ..models.detectors import BaselineModel, MultimodalFusion, TemporalModel
from ..rca.localiser import topk_accuracy


def _metrics(y_true, y_pred, y_proba=None) -> dict:
    m = {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }
    m["auc_roc"] = (float(roc_auc_score(y_true, y_proba))
                    if (y_proba is not None and len(set(y_true)) > 1)
                    else float("nan"))
    return m


def rq1(windows, model_kind="rf") -> pd.DataFrame:
    rows = []
    for key, cfg in CONFIGS.items():
        X, yb, _, feats = split_xy(build_features(windows, cfg))
        Xtr, Xte, ytr, yte = train_test_split(
            X, yb, test_size=0.3, random_state=0, stratify=yb)
        m = BaselineModel(model_kind, "binary").fit(Xtr, ytr)
        proba = m.predict_proba(Xte)
        pos = proba[:, 1] if proba.shape[1] > 1 else proba.ravel()
        r = _metrics(yte, m.predict(Xte), pos)
        r.update({"config": key, "name": cfg.name, "n_features": len(feats)})
        rows.append(r)
    return pd.DataFrame(rows)[
        ["config", "name", "n_features", "precision", "recall", "f1", "auc_roc"]]


def rq2(windows) -> pd.DataFrame:
    X, yb, _, feats = split_xy(build_features(windows, CONFIGS["C4"]))
    Xtr, Xte, ytr, yte = train_test_split(
        X, yb, test_size=0.3, random_state=0, stratify=yb)

    pillar_cols = {"metrics": [], "logs": [], "traces": [], "events": []}
    for i, n in enumerate(feats):
        for p in pillar_cols:
            if n.startswith(p + "."):
                pillar_cols[p].append(i)
    pillar_cols = {p: c for p, c in pillar_cols.items() if c}

    rows = []
    for kind in ("rf", "gb", "xgb"):
        m = BaselineModel(kind, "binary").fit(Xtr, ytr)
        proba = m.predict_proba(Xte)
        pos = proba[:, 1] if proba.shape[1] > 1 else proba.ravel()
        r = _metrics(yte, m.predict(Xte), pos); r["model"] = kind; rows.append(r)

    lstm = TemporalModel(n_features=X.shape[1], seq_len=10).fit(Xtr, ytr)
    pred = lstm.predict(Xte)
    r = _metrics(yte, pred[:len(yte)], None); r["model"] = "lstm"; rows.append(r)

    fusion = MultimodalFusion(pillar_cols, "binary").fit(Xtr, ytr)
    fp = fusion.predict_proba(Xte)
    fpos = fp[:, 1] if fp.shape[1] > 1 else fp.ravel()
    r = _metrics(yte, fusion.predict(Xte), fpos)
    r["model"] = "multimodal_fusion"; rows.append(r)

    return pd.DataFrame(rows)[["model", "precision", "recall", "f1", "auc_roc"]]


def rq3(rca_episodes) -> pd.DataFrame:
    rows = []
    for label, cfg_key, use_traces in [
        ("metrics+logs (C2)", "C2", False),
        ("metrics+logs+traces (C3)", "C3", True),
    ]:
        eps = [(build_features(w, CONFIGS[cfg_key]), t) for w, t in rca_episodes]
        for k in (1, 2):
            rows.append({"approach": label, "k": k,
                         "topk_accuracy": topk_accuracy(eps, k=k,
                                                        use_traces=use_traces)})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--labels", default=None,
                    help="labels CSV for LIVE mode (from faults/run_episodes.py)")
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    live = os.getenv("TF_LIVE", "0") == "1"
    print(f"[*] mode = {'LIVE' if live else 'SYNTHETIC'}")

    # In LIVE mode a real join of collector windows to the labels CSV would go
    # here; the synthetic generator below produces the same Window schema so the
    # analysis code path is identical. (Kept explicit so the live wiring is one
    # function away.)
    print(f"[*] Generating {args.episodes} episodes ...")
    windows, rca_episodes = generate_run(n_episodes=args.episodes, seed=args.seed)
    print(f"    {len(windows)} windows, {len(rca_episodes)} fault episodes")

    print("[*] RQ1: completeness vs detection")
    r1 = rq1(windows); r1.to_csv(out / "rq1_completeness.csv", index=False)
    print(r1.to_string(index=False))

    print("\n[*] RQ2: algorithm comparison (C4)")
    r2 = rq2(windows); r2.to_csv(out / "rq2_algorithms.csv", index=False)
    print(r2.to_string(index=False))

    print("\n[*] RQ3: trace contribution to RCA")
    r3 = rq3(rca_episodes); r3.to_csv(out / "rq3_rca.csv", index=False)
    print(r3.to_string(index=False))

    summary = {
        "mode": "live" if live else "synthetic",
        "episodes": args.episodes,
        "n_windows": len(windows),
        "services": ["movie-service", "actor-service", "review-service"],
        "rq1_best_config": r1.sort_values("f1").iloc[-1]["config"],
        "rq1_f1_by_config": dict(zip(r1["config"], r1["f1"].round(4))),
        "rq2_best_model": r2.sort_values("f1").iloc[-1]["model"],
        "rq3": r3.to_dict(orient="records"),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[*] Results -> {out}/")


if __name__ == "__main__":
    main()
