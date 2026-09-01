#!/usr/bin/env python3
"""
C1-C4 detection harness for the real TraceFlix stack.

This script produces the *held-out reference* results for the paper, aligned to
its (reordered) research questions:

  * completeness()  -> paper RQ1 (completeness). Hold the model fixed, vary
      observability completeness C1..C4, and report detection precision / recall
      / F1 / AUC on a controlled, single-distribution HELD-OUT slice.
      NB: the paper poses RQ1 *under non-stationarity*. This function supplies
      only the stationary HELD-OUT REFERENCE column; the operative drifted-stream
      column of RQ1 (and the whole paradigm comparison, paper RQ3) is produced by
      ``online_vs_offline.py`` on the drifted future stream. The two are reported
      side by side in the manuscript's RQ1 table.
  * localisation()  -> paper RQ2 (localisation). Top-k root-cause accuracy with
      traces excluded (C2) vs included (C3).
  * model_family()  -> paper RQ4 (model family, answered last). Under the richest
      configuration (C4), compare RF / GB / XGBoost / LSTM / multimodal
      late-fusion (HolisticRCA building blocks).

  (Paper RQ3 -- static vs periodic vs online learning under drift -- is *not*
   computed here; see ``online_vs_offline.py``.)

Outputs (one CSV per question, named by the paper's RQ number):
  rq1_completeness.csv, rq2_localisation.csv, rq4_model_family.csv

Data source is the synthetic generator, always. TF_LIVE and --labels are accepted
but the join of collected windows to a labels CSV was never implemented (see the
note in main()), so this module has no live mode however it is invoked. To score
the deployed stack against a campaign faults/inject.py or faults/run_episodes.py
recorded, use ml.experiments.live_replay, which does implement that join.

Run:
    python -m ml.experiments.run_experiment --episodes 200 --out data/results
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

from ..configs import CONFIGS, SERVICES
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


def completeness(windows, model_kind="rf") -> pd.DataFrame:
    """Paper RQ1 (held-out reference column): detection vs completeness C1..C4.

    The model is held fixed; only the signal set varies. Evaluated on a
    single-distribution held-out split -- the stationary reference against which
    the drifted-stream RQ1 result (from online_vs_offline.py) is compared.
    """
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


def model_family(windows, limit: int | None = None) -> pd.DataFrame:
    """Paper RQ4 (answered last): model-family comparison on full MELT (C4).

    ``limit`` evaluates on the first ``limit`` windows of the test split while
    still training on the full training set. ``train_test_split`` shuffles and
    stratifies, so that prefix is a random subsample rather than a biased slice.

    Its purpose is uniformity: the local-LLM family costs ~5 s/window, so scoring
    it on the whole split is a multi-hour job (``score_llm.py``). Passing the same
    ``limit`` here evaluates every family on the SAME subset, which keeps the six
    rows directly comparable -- preferable to reporting one row on a different
    sample size from the other five.
    """
    X, yb, _, feats = split_xy(build_features(windows, CONFIGS["C4"]))
    Xtr, Xte, ytr, yte = train_test_split(
        X, yb, test_size=0.3, random_state=0, stratify=yb)
    if limit:
        Xte, yte = Xte[:limit], yte[:limit]

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

    # New model family: local-LLM detector (Qwen2.5-3B via Ollama, optionally
    # LoRA-tuned). Opt-in via ENABLE_LLM=1 since it needs Ollama up to be a real
    # LLM run; without it the detector reports a clearly-marked heuristic.
    if os.getenv("ENABLE_LLM", "0") == "1":
        from ..models.llm_detector import LLMDetector

        llm = LLMDetector().fit(Xtr, ytr, feats)
        proba = llm.predict_proba(Xte)
        r = _metrics(yte, llm.predict(Xte), proba[:, 1])
        # Report the failure count in the row name, not just the mode: mode is
        # fixed at construction, so a mid-run loss of Ollama leaves it reading
        # "llm" while the verdicts degrade to a constant "normal". Anything but
        # err=0 means the row is NOT a clean LLM result.
        tag = f"{llm.mode},err={llm.n_errors}/{llm.n_calls}"
        r["model"] = f"llm_{llm.model}({tag})"; rows.append(r)
        if llm.n_errors:
            print(f"    [!] {llm.n_errors}/{llm.n_calls} LLM calls failed "
                  f"-- DEGRADED, do not report as an LLM result. "
                  f"last error: {llm.last_error}")

    return pd.DataFrame(rows)[["model", "precision", "recall", "f1", "auc_roc"]]


def localisation(rca_episodes) -> pd.DataFrame:
    """Paper RQ2: top-k root-cause localisation, traces excluded (C2) vs (C3)."""
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
    ap.add_argument("--limit", type=int, default=None,
                    help="RQ4 only: evaluate every model family on the first N "
                         "windows of the test split, matching score_llm.py's "
                         "--limit so all six families share one evaluation set")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    # The join of collected windows to the labels CSV was never written, so this
    # run is synthetic whatever TF_LIVE says. Say so rather than printing
    # "mode = LIVE" over a generated stream -- generate_run invents the fault it
    # labels each window with, and no live telemetry corresponds to that label.
    print("[*] mode = SYNTHETIC (generated stream)")
    if os.getenv("TF_LIVE", "0") == "1" or args.labels:
        print("    NOTE: TF_LIVE/--labels do not apply here -- the live join is "
              "unimplemented. Scoring the deployed stack against a recorded "
              "campaign is ml.experiments.live_replay.")

    # If that join is ever written it goes here; the synthetic generator below
    # produces the same Window schema, so the analysis code path is identical.
    print(f"[*] Generating {args.episodes} episodes ...")
    windows, rca_episodes = generate_run(n_episodes=args.episodes, seed=args.seed)
    print(f"    {len(windows)} windows, {len(rca_episodes)} fault episodes")

    print("[*] RQ1: completeness vs detection (held-out reference)")
    r1 = completeness(windows)
    r1.to_csv(out / "rq1_completeness.csv", index=False)
    print(r1.to_string(index=False))

    print("\n[*] RQ2: trace contribution to root-cause localisation")
    r2 = localisation(rca_episodes)
    r2.to_csv(out / "rq2_localisation.csv", index=False)
    print(r2.to_string(index=False))

    print("\n[*] RQ4: model-family comparison (C4)"
          + (f" -- test subsample n={args.limit}" if args.limit else ""))
    r4 = model_family(windows, limit=args.limit)
    r4.to_csv(out / "rq4_model_family.csv", index=False)
    print(r4.to_string(index=False))

    print("\n[i] RQ3 (static vs periodic vs online under drift) is produced by "
          "online_vs_offline.py, not this script.")

    summary = {
        "mode": "synthetic",       # unconditional: see the note in main() above
        "episodes": args.episodes,
        "n_windows": len(windows),
        "services": list(SERVICES),
        "test_subsample": args.limit,
        "note": "RQ1 and RQ4 follow the paper. RQ3 (drift) is in "
                "online_vs_offline.py. The rq2 block below is NOT the paper's "
                "RQ2 -- see its key.",
        "rq1_completeness_reference_f1": dict(zip(r1["config"], r1["f1"].round(4))),
        # The base generator raises error spans only at the fault's origin, so a
        # localiser reading that signal recovers the label it is meant to infer
        # and scores ~1.0. The paper therefore reports RQ2 on the *propagating*
        # generator (ml/experiments/rq2_localisation.py) instead. This block is
        # retained for completeness and must not be quoted as the RQ2 result.
        "rq2_localisation_base_generator_not_reported": r2.to_dict(orient="records"),
        "rq4_best_model": r4.sort_values("f1").iloc[-1]["model"],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[*] Results -> {out}/")


if __name__ == "__main__":
    main()
