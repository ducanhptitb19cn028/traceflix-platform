"""Resumable LLM scoring for the RQ4 model-family comparison.

``run_experiment.model_family`` scores all six families in one process and writes
once at the end, so an interruption loses everything -- including the ~7.5 h of
CPU inference the local-LLM row costs. Two attempts at the full run were killed
partway through and discarded ~1300 already-scored windows between them.

This script scores ONLY the LLM family, checkpointing after every batch, and
skips windows already present in the checkpoint when restarted. Interruptions
therefore cost at most one batch, and the job can be completed across several
sessions.

The data, the C4 feature build and the train/test split are reproduced EXACTLY as
``model_family`` does them (same generator seed, same ``test_size=0.3``,
``random_state=0``, ``stratify=yb``), so the resulting row is directly comparable
to the other five families in ``data/results/rq4_model_family.csv``.

    python -u -m ml.experiments.score_llm --episodes 200 --seed 42

Preconditions and failure modes are the same as ``make llm`` -- see the target in
the Makefile and ``data/results/README.md``. The run aborts immediately unless
the detector reports LLM mode, and records per-window failures so a degraded run
cannot be mistaken for a clean one.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (f1_score, precision_score, recall_score,
                             roc_auc_score)
from sklearn.model_selection import train_test_split

from ..configs import CONFIGS
from ..dataset import generate_run
from ..features.build import build_features, split_xy
from ..models.llm_detector import LLMDetector


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch", type=int, default=25,
                    help="windows scored between checkpoint writes")
    ap.add_argument("--limit", type=int, default=None,
                    help="score only the first N windows of the test split and "
                         "stop. train_test_split shuffles (stratified), so the "
                         "prefix is a RANDOM subsample of the split, not a "
                         "biased slice -- but a limited run must be reported as "
                         "a subsample of size N, never as the full test set.")
    ap.add_argument("--out", default="data/results_llm")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    ckpt = out / "llm_window_verdicts.csv"

    # -- identical pipeline to run_experiment.model_family ------------------
    print(f"[*] Generating {args.episodes} episodes (seed {args.seed}) ...")
    windows, _ = generate_run(n_episodes=args.episodes, seed=args.seed)
    X, yb, _, feats = split_xy(build_features(windows, CONFIGS["C4"]))
    Xtr, Xte, ytr, yte = train_test_split(
        X, yb, test_size=0.3, random_state=0, stratify=yb)
    print(f"    {len(windows)} windows -> test split {len(Xte)}")

    det = LLMDetector()
    if det.mode != "llm":
        raise SystemExit(
            f"ABORT: detector is in {det.mode!r} mode ({det.mode_reason}). "
            "Start Ollama ('make ollama-forward') -- a heuristic run is not an "
            "LLM result.")
    print(f"[*] detector ready: {det.mode_reason}")
    det.fit(Xtr, ytr, feats)

    done: dict[int, tuple[int, float]] = {}
    if ckpt.exists():
        prev = pd.read_csv(ckpt)
        done = {int(r.i): (int(r.y_pred), float(r.proba))
                for r in prev.itertuples()}
        print(f"[*] resuming: {len(done)}/{len(Xte)} windows already scored")

    n_target = min(args.limit, len(Xte)) if args.limit else len(Xte)
    if n_target < len(Xte):
        print(f"[*] SUBSAMPLE run: scoring {n_target} of {len(Xte)} test windows")
    # NB: never drop entries from `done` -- it is rewritten to the checkpoint in
    # full each batch, so filtering it here would delete windows already scored
    # beyond the limit. Restrict only what we SCORE and what we REPORT.
    todo = [i for i in range(n_target) if i not in done]
    if todo:
        t0 = time.time()
        for start in range(0, len(todo), args.batch):
            idx = todo[start:start + args.batch]
            proba = det.predict_proba(Xte[idx])[:, 1]
            pred = (proba >= 0.5).astype(int)
            for j, i in enumerate(idx):
                done[i] = (int(pred[j]), float(proba[j]))
            pd.DataFrame(
                [{"i": i, "y_true": int(yte[i]), "y_pred": p, "proba": q}
                 for i, (p, q) in sorted(done.items())]
            ).to_csv(ckpt, index=False)
            n = sum(1 for i in done if i < n_target)
            rate = (time.time() - t0) / max(1, n - (n_target - len(todo)))
            eta = rate * (n_target - n) / 60.0
            print(f"    {n}/{n_target} scored | {rate:.1f}s/window | "
                  f"eta {eta:.0f} min | errors {det.n_errors}/{det.n_calls}",
                  flush=True)

    # -- final metrics, in the same shape as run_experiment ------------------
    order = sorted(i for i in done if i < n_target)
    y_pred = np.array([done[i][0] for i in order])
    y_prob = np.array([done[i][1] for i in order])
    y_true = np.array([yte[i] for i in order])

    tag = f"{det.mode},err={det.n_errors}/{det.n_calls}"
    if len(order) < len(Xte):
        tag += f",n={len(order)}/{len(Xte)}"   # subsample -- disclose it
    row = {
        "model": f"llm_{det.model}({tag})",
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
        "auc_roc": roc_auc_score(y_true, y_prob) if len(set(y_true)) > 1 else None,
    }
    pd.DataFrame([row]).to_csv(out / "rq4_llm_row.csv", index=False)
    print("\n[*] LLM row ->", out / "rq4_llm_row.csv")
    print(pd.DataFrame([row]).to_string(index=False))
    if det.n_errors:
        print(f"\n[!] {det.n_errors}/{det.n_calls} calls FAILED -- this row is "
              "DEGRADED and must not be reported as an LLM result.")


if __name__ == "__main__":
    main()
