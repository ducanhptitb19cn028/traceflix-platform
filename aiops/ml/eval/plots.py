"""Publication-ready figures from experiment CSVs (for the dissertation write-up)."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot_online_vs_offline(d: Path, out: Path):
    """RQ4 figures: (a) rolling-F1 timeline of the static batch model vs the
    online adaptive model across drifting regimes; (b) per-config F1 bars for
    static / online / oracle. Skipped quietly if RQ4 CSVs are absent."""
    tl_path, tab_path = d / "rq4_timeline.csv", d / "rq4_online_vs_offline.csv"
    if not (tl_path.exists() and tab_path.exists()):
        return

    tl = pd.read_csv(tl_path)
    # (a) timeline -- one panel per config, regime bands shaded
    cfgs = list(dict.fromkeys(tl["config"]))
    fig, axes = plt.subplots(len(cfgs), 1, figsize=(9, 3.2 * len(cfgs)),
                             squeeze=False)
    cmap = plt.get_cmap("tab10")
    for ax, cfg in zip(axes[:, 0], cfgs):
        sub = tl[tl["config"] == cfg].sort_values("t_center")
        for rg in sorted(sub["regime"].unique()):
            seg = sub[sub["regime"] == rg]
            ax.axvspan(seg["t_center"].min(), seg["t_center"].max(),
                       color=cmap(rg % 10), alpha=0.07)
        ax.plot(sub["t_center"], sub["offline_static_f1"], "o-",
                color="#c0392b", label="offline_static (frozen)")
        if "offline_periodic_f1" in sub:
            ax.plot(sub["t_center"], sub["offline_periodic_f1"], "^--",
                    color="#e67e22", label="offline_periodic (scheduled retrain)")
        ax.plot(sub["t_center"], sub["online_adaptive_f1"], "s-",
                color="#27ae60", label="online_adaptive")
        ax.set_title(f"RQ4: detection over a drifting stream -- {cfg}")
        ax.set_ylabel("rolling F1"); ax.set_ylim(0, 1.03)
        ax.set_xlabel("stream position (window index)"); ax.legend(loc="lower left")
    plt.tight_layout(); plt.savefig(out / "rq4_timeline.png", dpi=150); plt.close()

    # (b) per-config overall F1 bars (static vs online vs oracle ceiling)
    tab = pd.read_csv(tab_path)
    over = tab[tab["segment"].str.startswith("overall")]
    piv = over.pivot_table(index="config", columns="model", values="f1")
    cols = [c for c in ["offline_static", "offline_periodic",
                        "online_adaptive", "offline_full"] if c in piv.columns]
    ax = piv[cols].plot(kind="bar", figsize=(8, 4), ylim=(0, 1.05),
                        color={"offline_static": "#c0392b",
                               "offline_periodic": "#e67e22",
                               "online_adaptive": "#27ae60",
                               "offline_full": "#7f8c8d"})
    ax.set_title("RQ4: F1 on the operational future (post-drift)\n"
                 "frozen vs scheduled-retrain vs online adaptive vs all-regime oracle")
    ax.set_ylabel("F1"); plt.xticks(rotation=0); plt.tight_layout()
    plt.savefig(out / "rq4_online_vs_offline.png", dpi=150); plt.close()
    print(f"RQ4 figures -> {out}/")


def main(results_dir: str = "data/results"):
    d = Path(results_dir); out = d / "figures"; out.mkdir(exist_ok=True)

    plot_online_vs_offline(d, out)

    if not (d / "rq1_completeness.csv").exists():
        return   # RQ4-only run

    rq1 = pd.read_csv(d / "rq1_completeness.csv")
    ax = rq1.plot(x="config", y=["precision", "recall", "f1", "auc_roc"],
                  kind="bar", figsize=(8, 4), ylim=(0.8, 1.005))
    ax.set_title("RQ1: Detection vs observability completeness (TraceFlix)")
    ax.set_ylabel("score"); plt.tight_layout()
    plt.savefig(out / "rq1_completeness.png", dpi=150); plt.close()

    rq2 = pd.read_csv(d / "rq2_algorithms.csv")
    ax = rq2.plot(x="model", y=["precision", "recall", "f1"], kind="bar",
                  figsize=(8, 4))
    ax.set_title("RQ2: Algorithm comparison on full MELT (C4)")
    plt.xticks(rotation=20); plt.tight_layout()
    plt.savefig(out / "rq2_algorithms.png", dpi=150); plt.close()

    rq3 = pd.read_csv(d / "rq3_rca.csv")
    pivot = rq3.pivot(index="k", columns="approach", values="topk_accuracy")
    ax = pivot.plot(kind="bar", figsize=(7, 4), ylim=(0, 1.05))
    ax.set_title("RQ3: Top-k RCA, traces excluded vs included\n"
                 "(note: 3-service mesh -> Top-1 is the discriminating metric)")
    ax.set_ylabel("Top-k accuracy"); plt.tight_layout()
    plt.savefig(out / "rq3_rca.png", dpi=150); plt.close()
    print(f"Figures -> {out}/")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/results")
