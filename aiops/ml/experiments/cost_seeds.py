#!/usr/bin/env python3
"""Five-seed cost profile -- the ranges the write-up actually quotes.

``cost_compare`` profiles **one** seed. But every cost *range* in the paper and
the docs is a min-max over **seeds**, not over configurations: periodic spikes of
580-880 ms, an online tail that never exceeded 78 ms, a 10-48x tail ratio,
~120-390x footprint, 4.1-4.8x total CPU. A single-seed run cannot produce any of
them. Until this module existed the table was assembled by hand from a manual
loop -- which made the one artefact the cost argument leans on the one artefact
nobody could regenerate.

It reuses ``cost_compare.run_config`` rather than re-implementing the
measurement, so a per-seed row here **is** the row ``make cost`` reports for that
seed; there is no second definition of "cost" to drift out of sync.

Two modes:

  * **default** -- generate each seed's drifting stream and profile it. This is
    ``cost_compare`` once per seed, so budget accordingly (hours, not minutes).
  * ``--from-dir`` -- aggregate per-seed CSVs that already exist. No streams are
    generated and no models are fitted; it only re-reads and summarises. Use it
    when the per-seed runs were done separately, or to re-derive the summary
    after inspecting the rows.

**What reproduces and what does not.** The structural columns (train events,
retained windows, model size) are properties of the policy and reproduce exactly.
The wall-clock columns -- and therefore ``tail_ratio`` and ``cpu_ratio`` -- are
properties of the machine and the run, so re-running will *not* reproduce the
committed numbers to the decimal. That is expected, and it is why the write-up
quotes an order-of-magnitude tail gap rather than a millisecond.

    python -u -m ml.experiments.cost_seeds --seeds 42,43,44,45,46 --configs C1,C2,C3,C4
    python -m ml.experiments.cost_seeds --from-dir data/results_cost_seeds
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ..drift import generate_drifting_run
from .cost_compare import run_config

# Ratio columns, and the direction each is defined in. Kept here rather than
# inline so the CSV, the summary and the printed table cannot disagree.
RATIO_COLS = ["tail_ratio", "cpu_ratio", "size_ratio"]
SUMMARY_COLS = ["online_max_ms", "periodic_max_ms"] + RATIO_COLS


def _cells(per_seed: pd.DataFrame, seed: int) -> list[dict]:
    """Collapse one seed's two-rows-per-config cost table into one row per config.

    ``rq3_cost.csv`` carries a row per (config, model); the seed table carries a
    row per config with the periodic/online pair already contrasted, because the
    ranges are ratios and a ratio needs both arms in the same row.
    """
    rows = []
    for cfg, grp in per_seed.groupby("config", sort=True):
        try:
            p = grp[grp["model"] == "offline_periodic"].iloc[0]
            o = grp[grp["model"] == "online_adaptive"].iloc[0]
        except IndexError:
            raise SystemExit(
                f"[!] seed {seed}, config {cfg}: expected both offline_periodic "
                f"and online_adaptive rows, found {sorted(grp['model'])}. "
                f"Re-run cost_compare for this seed.")
        rows.append({
            "seed": seed,
            "config": cfg,
            "periodic_max_ms": float(p["max_ms_per_window"]),
            "online_max_ms": float(o["max_ms_per_window"]),
            # periodic's blocking refit spike against online's bounded update
            "tail_ratio": float(p["max_ms_per_window"]) / float(o["max_ms_per_window"]),
            # the cost online actually pays: it works every window
            "cpu_ratio": float(o["total_time_s"]) / float(p["total_time_s"]),
            "size_ratio": float(p["model_kb"]) / float(o["model_kb"]),
        })
    return rows


def _profile_seed(seed: int, cfg_keys, episodes, retrain_every, train_window):
    """Run cost_compare's measurement for one seed, returning its raw rows."""
    print(f"[*] seed {seed}: generating stream ({episodes} episodes)", flush=True)
    windows, regimes = generate_drifting_run(n_episodes=episodes, seed=seed)
    rows = []
    for k in cfg_keys:
        cfg_rows, _, _ = run_config(k, windows, regimes, retrain_every, train_window)
        rows += cfg_rows
        p = next(r for r in cfg_rows if r["model"] == "offline_periodic")
        o = next(r for r in cfg_rows if r["model"] == "online_adaptive")
        print(f"    {k}: periodic max {p['max_ms_per_window']:.1f} ms, "
              f"online max {o['max_ms_per_window']:.1f} ms "
              f"({p['max_ms_per_window'] / o['max_ms_per_window']:.1f}x)", flush=True)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="42,43,44,45,46")
    ap.add_argument("--configs", default="C1,C2,C3,C4")
    ap.add_argument("--episodes", type=int, default=320)
    ap.add_argument("--retrain-every", type=int, default=500)
    ap.add_argument("--train-window", type=int, default=2880)
    ap.add_argument("--out", default="data/results",
                    help="where rq3_cost_seeds.csv + summary land")
    ap.add_argument("--per-seed-out", default="data/results_cost_seeds",
                    help="where each seed's full rq3_cost table is kept")
    ap.add_argument("--from-dir", default=None,
                    help="aggregate existing rq3_cost_seed<N>.csv from this "
                         "directory instead of re-running the profile")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    cfg_keys = [c.strip() for c in args.configs.split(",") if c.strip()]

    cells: list[dict] = []
    if args.from_dir:
        src = Path(args.from_dir)
        print(f"[*] aggregating existing per-seed tables from {src}/")
        for sd in seeds:
            f = src / f"rq3_cost_seed{sd}.csv"
            if not f.exists():
                raise SystemExit(
                    f"[!] {f} not found. Either run without --from-dir to "
                    f"profile seed {sd}, or drop it from --seeds.")
            cells += _cells(pd.read_csv(f), sd)
    else:
        per_seed_out = Path(args.per_seed_out)
        per_seed_out.mkdir(parents=True, exist_ok=True)
        print(f"[*] RQ3 cost over {len(seeds)} seeds x {len(cfg_keys)} configs "
              f"-- this is cost_compare once per seed")
        for sd in seeds:
            df = _profile_seed(sd, cfg_keys, args.episodes,
                               args.retrain_every, args.train_window)
            # keep the full per-seed table: the aggregate discards the F1 and
            # structural columns, and those are what make a surprising ratio
            # diagnosable after the fact.
            df.to_csv(per_seed_out / f"rq3_cost_seed{sd}.csv", index=False)
            cells += _cells(df, sd)

    res = pd.DataFrame(cells).sort_values(["seed", "config"]).reset_index(drop=True)
    res.to_csv(out / "rq3_cost_seeds.csv", index=False)

    summary = {"seeds": seeds, "n_cells": int(len(res))}
    for col in SUMMARY_COLS:
        summary[col] = [round(float(res[col].min()), 1),
                        round(float(res[col].max()), 1)]
    (out / "rq3_cost_seeds_summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n[*] {len(res)} cells over seeds {seeds}")
    print(res.to_string(index=False))
    print("\n    ranges (min-max over all cells -- these are the numbers the "
          "write-up quotes):")
    for col in SUMMARY_COLS:
        lo, hi = summary[col]
        print(f"      {col:16} {lo} - {hi}")
    print(f"\n[*] Results -> {out}/  "
          f"(rq3_cost_seeds.csv, rq3_cost_seeds_summary.json)")


if __name__ == "__main__":
    main()
