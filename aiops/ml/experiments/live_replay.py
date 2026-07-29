"""Replay a recorded fault-injection campaign against live telemetry (C1).

This is the join that ``run_experiment``'s ``TF_LIVE`` branch never had: it takes
the ground truth written by ``faults/run_episodes.py`` and reconstructs, for each
labelled interval, the metric windows Prometheus actually recorded at the time.
The result is a detection score computed on **measured** telemetry rather than on
the generator of ``ml/dataset.py``.

Scope, and it is narrow on purpose:

  * **C1 only.** ``collect_metrics_live`` takes an ``at`` timestamp, so metrics
    can be reconstructed historically. The Loki, Tempo and Kubernetes-event
    collectors are not time-parameterised, so C2--C4 would silently mix
    present-moment values into a past window. They are not attempted here.
  * **Origin-only labelling.** A window is anomalous iff its service is the
    injected root cause for that interval. The affected set of Eq. (2) also
    contains the origin's ancestors, so ancestors degraded by the fault are
    labelled normal here. That is deliberately conservative: it can only depress
    apparent precision, never inflate it.
  * **One short campaign.** Twelve episodes is a feasibility measurement, not a
    replacement for the reported 320-episode study.

    TF_LIVE=1 PROM_URL=http://localhost:9090 \\
      python -u -m ml.experiments.live_replay --labels data/labels_live.csv
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (f1_score, precision_score, recall_score,
                             roc_auc_score)
from sklearn.model_selection import train_test_split

from ..configs import CONFIGS
from ..features.build import build_features, split_xy
from ..models.detectors import BaselineModel

MESH = ["gateway-service", "auth-service", "catalog-service", "movie-service",
        "actor-service", "review-service", "search-service",
        "recommendation-service", "user-service"]


def build_live_windows(labels: pd.DataFrame, cadence: float, margin: float,
                       cache: Path):
    """One Window per (service, sampled instant) inside each labelled interval.

    Collection is the slow part -- one PromQL round trip per metric per window --
    so every window is appended to ``cache`` as JSON as soon as it is fetched,
    and a restart skips whatever is already there. An interrupted replay then
    costs only the window in flight rather than the whole campaign.
    """
    from collectors.telemetry import LIVE, Window, collect_window

    if not LIVE:
        raise SystemExit("ABORT: TF_LIVE=1 is required; refusing to replay "
                         "against the synthetic generator.")
    done: dict[tuple[str, str], Window] = {}
    if cache.exists():
        for line in cache.read_text(encoding="utf8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            done[(d["service"], f"{d['ts']:.3f}")] = Window(**d)
        print(f"[*] resuming: {len(done)} windows already collected")

    rng = np.random.default_rng(0)
    fh = cache.open("a", encoding="utf8")
    try:
        for ep in labels.itertuples():
            # `margin` trims each end so a window never straddles inject/clear
            t0, t1 = ep.start_ts + margin, ep.end_ts - margin
            if t1 <= t0:
                continue
            for ts in np.arange(t0, t1, cadence):
                # the nine services are independent queries against the same
                # instant, so fetch them concurrently: collection is entirely
                # round-trip bound and this is the difference between ~7 s and
                # ~1 s per instant.
                todo = []
                for svc in MESH:
                    key = (svc, f"{float(ts):.3f}")
                    if key in done:
                        continue
                    is_origin = (isinstance(ep.root_cause, str)
                                 and ep.root_cause == svc)
                    fault = (ep.fault if (is_origin and ep.fault != "normal")
                             else "normal")
                    todo.append((key, svc, fault))
                if not todo:
                    continue
                with ThreadPoolExecutor(max_workers=len(todo)) as pool:
                    futs = {pool.submit(collect_window, svc, fault,
                                        float(ts), rng): key
                            for key, svc, fault in todo}
                    for fut in as_completed(futs):
                        w = fut.result()
                        done[futs[fut]] = w
                        fh.write(json.dumps(w.__dict__) + "\n")
                fh.flush()
            print(f"    {ep.fault:18} {str(ep.root_cause):22} "
                  f"-> {len(done)} windows", flush=True)
    finally:
        fh.close()
    return list(done.values()), len(done)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="data/labels_live.csv")
    ap.add_argument("--cadence", type=float, default=30.0,
                    help="seconds between sampled windows inside an interval")
    ap.add_argument("--margin", type=float, default=20.0,
                    help="seconds trimmed from each end of an interval")
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    labels = pd.read_csv(args.labels)
    labels = labels[labels.end_ts - labels.start_ts > 1]     # drop dry-run rows
    print(f"[*] {len(labels)} labelled episodes from {args.labels}")
    print(f"[*] PROM_URL={os.getenv('PROM_URL', 'http://localhost:9090')}")

    cache = out / "live_windows_cache.jsonl"
    windows, n_q = build_live_windows(labels, args.cadence, args.margin, cache)
    print(f"[*] {len(windows)} windows reconstructed (cache: {cache})")

    X, y, _, feats = split_xy(build_features(windows, CONFIGS["C1"]))
    X = np.asarray(X, dtype=float)
    prevalence = float(np.mean(y))
    print(f"[*] C1 features={X.shape[1]}  windows={len(y)}  "
          f"anomalous={int(np.sum(y))} ({prevalence:.3f})")
    if len(set(y)) < 2:
        raise SystemExit("ABORT: only one class present; nothing to score.")

    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.3, random_state=0, stratify=y)
    m = BaselineModel("rf", "binary").fit(Xtr, ytr)
    pred = m.predict(Xte)
    pro = m.predict_proba(Xte)
    pos = pro[:, 1] if pro.ndim > 1 and pro.shape[1] > 1 else pro.ravel()

    row = {
        "source": "live", "config": "C1", "model": "rf",
        "precision": precision_score(yte, pred, zero_division=0),
        "recall": recall_score(yte, pred, zero_division=0),
        "f1": f1_score(yte, pred, zero_division=0),
        "auc_roc": roc_auc_score(yte, pos),
        "n_windows": int(len(y)), "n_test": int(len(yte)),
        "prevalence": prevalence, "episodes": int(len(labels)),
        "always_alarm_f1": float(2 * prevalence / (1 + prevalence)),
    }
    pd.DataFrame([row]).to_csv(out / "rq1_live_c1.csv", index=False)
    (out / "rq1_live_c1_summary.json").write_text(json.dumps(row, indent=2))
    print("\n[*] ->", out / "rq1_live_c1.csv")
    for k, v in row.items():
        print(f"    {k:18} {v}")


if __name__ == "__main__":
    main()
