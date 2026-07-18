#!/usr/bin/env python3
"""
RQ2 (corrected): what does distributed tracing contribute to root-cause
localisation, when the origin is *not* handed to the localiser?

The original RQ2 was circular. It ran on the base generator, where error spans
are switched on by ``is_origin`` -- the ground-truth label the localiser must
recover -- so the origin was the unique emitter and a ranker weighting error
spans scored a perfect 1.0 at every k. That measured the generator.

This experiment re-runs it on the propagating generator
(``ml.dataset.generate_rca_run``): the fault's errors travel up the call path
and attenuate per hop, so every service on the path emits error spans and the
origin sits at the *root of the error tree*. Nothing tells the localiser where
that root is; it has to be inferred from the call graph.

Two factors are crossed so the trace contribution is not confounded:

  * signal    -- C2 (metrics+logs) vs C3 (+traces), the same ranking algorithm
                 for both, only the feature set differing;
  * algorithm -- flat ranking vs the graph-aware root-of-the-error-tree rule,
                 to separate "traces help" from "using the call graph helps".

Reported: top-1/2/3 accuracy, mean +/- sd over five seeds, against the 1/9
random-guess floor.

Run:
    python -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..configs import CONFIGS, SERVICES
from ..dataset import generate_rca_run
from ..features.build import build_features
from ..rca.localiser import topk_accuracy

ARMS = [
    ("Metrics+Logs (C2)", "C2", False, False),
    ("Metrics+Logs+Traces (C3)", "C3", True, False),
    ("Metrics+Logs (C2), graph-aware", "C2", False, True),
    ("Metrics+Logs+Traces (C3), graph-aware", "C3", True, True),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--seeds", default="42,43,44,45,46")
    ap.add_argument("--attenuation", type=float, default=0.6)
    ap.add_argument("--backgrounds", default="0.0,0.1,0.25,0.5",
                    help="per-episode probability of an off-path background "
                         "incident; 0.0 is the unrealistically quiet mesh")
    ap.add_argument("--out", default="data/results")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]
    backgrounds = [float(b) for b in args.backgrounds.split(",")]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for bg in backgrounds:
        for seed in seeds:
            eps = generate_rca_run(n_episodes=args.episodes, seed=seed,
                                   attenuation=args.attenuation,
                                   background_errors=bg)
            print(f"[*] background={bg}  seed={seed}: {len(eps)} fault episodes")
            for label, cfg_key, use_traces, graph in ARMS:
                built = [(build_features(w, CONFIGS[cfg_key]), t) for w, t in eps]
                for k in (1, 2, 3):
                    rows.append({
                        "background": bg, "seed": seed, "approach": label,
                        "config": cfg_key, "graph_aware": graph, "k": k,
                        "n_episodes": len(eps),
                        "topk_accuracy": topk_accuracy(built, k=k,
                                                       use_traces=use_traces,
                                                       graph_aware=graph),
                    })

    df = pd.DataFrame(rows)
    df.to_csv(out / "rq2_localisation_propagating.csv", index=False)

    agg = (df.groupby(["background", "approach", "config", "graph_aware", "k"])
             ["topk_accuracy"].agg(["mean", "std"]).reset_index())
    print("\n=== RQ2 corrected: top-1 localisation vs background-error rate "
          f"(mean +/- sd over {len(seeds)} seeds) ===")
    print(f"random-guess floor = {1/len(SERVICES):.4f}\n")
    top1 = agg[agg["k"] == 1]
    print(f"{'approach':42s}" + "".join(f"bg={b:<6}" for b in backgrounds))
    for label, _, _, _ in ARMS:
        cells = "".join(
            f"{top1[(top1['background'] == b) & (top1['approach'] == label)]['mean'].iloc[0]:.3f}  "
            for b in backgrounds)
        print(f"{label:42s}{cells}")

    summary = {
        "generator": "propagating (errors travel up the call path)",
        "attenuation_per_hop": args.attenuation,
        "episodes_per_seed": args.episodes,
        "seeds": seeds,
        "backgrounds": backgrounds,
        "random_floor": round(1 / len(SERVICES), 4),
        "topk": {
            f"bg{r['background']}|{r['approach']}|top{int(r['k'])}":
                {"mean": round(float(r["mean"]), 4),
                 "sd": round(float(r["std"]), 4)}
            for _, r in agg.iterrows()
        },
    }
    (out / "rq2_propagating_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[*] Results -> {out}/rq2_localisation_propagating.csv")


if __name__ == "__main__":
    main()
