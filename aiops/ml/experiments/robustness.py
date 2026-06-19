#!/usr/bin/env python3
"""
RQ-A: Robustness of observability-driven anomaly detection to telemetry
degradation.

A detector is trained on *clean* full-MELT (C4) telemetry and then evaluated on
telemetry that has been degraded in one of three realistic ways, swept across
severity levels:

  * sampling  -- distributed-trace sampling: trace-derived counts are scaled by
                 the sampling rate s, and the rare originating error-spans are
                 lost entirely with probability (1-s) (tail sampling misses them).
  * noise     -- multiplicative Gaussian noise N(0, sigma) on every numeric
                 telemetry field (jitter / measurement error).
  * dropout   -- a whole modality goes dark: every field of one pillar is zeroed.

For each (kind, level) we report precision/recall/F1/AUC on the degraded test
set. The clean point (s=1.0 / sigma=0 / dropout=none) is the C4 ceiling, so the
drop from it is the *fragility* of detection to that degradation, and the
per-pillar dropout sweep ranks which signal the detector most depends on.

Run:
    python -m ml.experiments.robustness --episodes 200 --out data/results
"""
from __future__ import annotations

import argparse
import copy
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from ..configs import CONFIGS
from ..dataset import generate_run
from ..features.build import build_features, split_xy
from ..models.detectors import BaselineModel
from .run_experiment import _metrics

PILLARS = ("metrics", "logs", "traces", "events")


def _degrade(windows, kind, level, rng):
    """Return a degraded deep-copy of `windows` (labels untouched)."""
    out = []
    for w in windows:
        d = copy.deepcopy(w)
        if kind == "sampling":
            for k, v in list(d.traces.items()):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    d.traces[k] = v * level
            # rare error spans are dropped wholesale when not sampled
            for ek in ("error_spans", "originating_error_spans"):
                if ek in d.traces and rng.random() > level:
                    d.traces[ek] = 0
        elif kind == "noise":
            for p in PILLARS:
                bag = getattr(d, p)
                for k, v in list(bag.items()):
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        bag[k] = v * (1.0 + rng.gauss(0.0, level))
        elif kind == "dropout":          # `level` is the pillar name to zero
            bag = getattr(d, level)
            for k, v in list(bag.items()):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    bag[k] = 0.0
        out.append(d)
    return out


# (kind, level, human-readable level) sweep
def _sweep():
    sweep = [("clean", 1.0, "clean")]
    for s in (1.0, 0.5, 0.25, 0.1, 0.05):
        sweep.append(("sampling", s, f"{s:g}"))
    for sg in (0.0, 0.05, 0.1, 0.2, 0.4):
        sweep.append(("noise", sg, f"{sg:g}"))
    for pillar in ("logs", "traces", "events"):
        sweep.append(("dropout", pillar, pillar))
    return sweep


def run_robustness(windows, seed=0):
    cfg = CONFIGS["C4"]
    Xc, yb, _, feats = split_xy(build_features(windows, cfg))
    Xc = np.asarray(Xc, dtype=float)
    yb = np.asarray(yb)

    idx = np.arange(len(yb))
    tr, te = train_test_split(idx, test_size=0.3, random_state=seed, stratify=yb)
    model = BaselineModel("rf", "binary").fit(Xc[tr], yb[tr])

    def _eval(Xte_te):
        proba = model.predict_proba(Xte_te)
        pos = proba[:, 1] if proba.shape[1] > 1 else proba.ravel()
        return _metrics(yb[te], model.predict(Xte_te), pos)

    rng = random.Random(seed)
    rows = []
    for kind, level, lname in _sweep():
        if kind == "clean":
            Xd = Xc
        else:
            Xd = np.asarray(
                split_xy(build_features(_degrade(windows, kind, level, rng), cfg))[0],
                dtype=float)
        r = _eval(Xd[te])
        r.update({"degradation": kind, "level": lname})
        rows.append(r)
        print(f"    {kind:9s} {lname:7s}  F1={r['f1']:.4f}  AUC={r['auc_roc']:.4f}")

    df = pd.DataFrame(rows)[
        ["degradation", "level", "precision", "recall", "f1", "auc_roc"]]
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    print(f"[*] RQ-A robustness: generating {args.episodes} episodes ...")
    windows, _ = generate_run(n_episodes=args.episodes, seed=args.seed)
    print(f"    {len(windows)} windows; detector = RandomForest on C4 (clean train)")

    df = run_robustness(windows, seed=0)
    df.to_csv(out / "rqA_robustness.csv", index=False)

    clean_f1 = float(df[df.degradation == "clean"]["f1"].iloc[0])
    frag = []
    for p in ("logs", "traces", "events"):
        sub = df[(df.degradation == "dropout") & (df.level == p)]
        if len(sub):
            frag.append((p, clean_f1 - float(sub["f1"].iloc[0])))
    frag.sort(key=lambda x: -x[1])
    summary = {
        "experiment": "RQ-A robustness",
        "episodes": args.episodes,
        "clean_C4_f1": round(clean_f1, 4),
        "fragility_dF1_by_dropped_pillar": {p: round(v, 4) for p, v in frag},
    }
    (out / "rqA_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[*] clean C4 F1 = {clean_f1:.4f}")
    print(f"[*] pillar fragility (dF1 when dropped): {summary['fragility_dF1_by_dropped_pillar']}")
    print(f"[*] Results -> {out}/rqA_robustness.csv")


if __name__ == "__main__":
    main()
