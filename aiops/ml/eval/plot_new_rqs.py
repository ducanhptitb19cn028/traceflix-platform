#!/usr/bin/env python3
"""Figures for the three new RQs, generated from the AIOps result CSVs.

  rqA_robustness.csv -> fig_rqA_robustness.png  (RQ-A: sampling curve + fragility)
  rqD_leadtime.csv   -> fig_rqD_leadtime.png     (RQ-D: lead-time distributions)
  rqO_obs_cost.csv   -> fig_rqO_pareto.png        (RQ-O: F1-vs-cost Pareto front)

Run:  python -m ml.eval.plot_new_rqs            (from aiops/, reads data/results/)
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams.update({"font.family": "serif", "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.3, "grid.linestyle": ":", "figure.dpi": 200})
BLUE, ORANGE, GREEN, GREY = "#0072B2", "#E69F00", "#009E73", "#999999"


def main(results="data/results"):
    R = Path(results); F = R / "figures"; F.mkdir(parents=True, exist_ok=True)

    # ---------- RQ-A: robustness ----------
    a = pd.read_csv(R / "rqA_robustness.csv")
    clean_f1 = float(a[a.degradation == "clean"]["f1"].iloc[0])
    samp = a[a.degradation == "sampling"].copy()
    samp["s"] = samp["level"].astype(float)
    samp = samp.sort_values("s")
    drop = a[a.degradation == "dropout"].copy()
    drop["dF1"] = clean_f1 - drop["f1"].astype(float)
    drop = drop.sort_values("dF1", ascending=False)

    fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.1))
    ax[0].plot(samp["s"], samp["f1"], "o-", color=BLUE)
    ax[0].axhline(clean_f1, ls="--", color=GREY, lw=1, label=f"clean C4 ({clean_f1:.2f})")
    ax[0].set_xlabel("trace sampling rate"); ax[0].set_ylabel("detection F1")
    ax[0].set_title("Detection vs trace sampling"); ax[0].set_ylim(0.7, 1.01)
    ax[0].invert_xaxis(); ax[0].legend(fontsize=8, loc="lower left")
    ax[1].bar(drop["level"], drop["dF1"],
              color=[ORANGE if p == "traces" else GREY for p in drop["level"]],
              edgecolor="black", linewidth=0.5)
    ax[1].set_ylabel(r"$\Delta$F1 when pillar dropped")
    ax[1].set_title("Signal fragility")
    for x, v in zip(range(len(drop)), drop["dF1"]):
        ax[1].text(x, v + 0.004, f"{v:.3f}", ha="center", fontsize=8)
    fig.tight_layout(); fig.savefig(F / "fig_rqA_robustness.png", bbox_inches="tight")
    plt.close(fig)

    # ---------- RQ-D: lead-time vs observability completeness ----------
    d = pd.read_csv(R / "rqD_leadtime.csv")
    flt = d[d.is_fault == 1]
    order = ["C1", "C2", "C3", "C4"]
    boxlabels = ["C1\nmetrics", "C2\n+logs", "C3\n+traces", "C4\nfull MELT"]
    leads = [flt[flt.config == k]["lead"].dropna() for k in order]
    meds = [float(l.median()) for l in leads]
    ewr = [float((flt[flt.config == k]["lead"] > 0).mean()) * 100 for k in order]
    far = [float((d[(d.config == k) & (d.is_fault == 0)]["alarm_t"] >= 0).mean()) * 100
           for k in order]
    cols = [GREY, GREY, GREEN, GREEN]            # traces (C3,C4) highlighted

    fig, ax = plt.subplots(1, 2, figsize=(7.8, 3.4))
    bp = ax[0].boxplot(leads, labels=boxlabels, patch_artist=True, widths=0.6, showmeans=True)
    for patch, c in zip(bp["boxes"], cols):
        patch.set_facecolor(c); patch.set_alpha(0.55)
    ax[0].axhline(0, ls="--", color="red", lw=1, label="SLO breach (lead = 0)")
    ax[0].set_ylabel("lead time (windows; + = early warning)")
    ax[0].set_title("Earliness of alarm by observability config")
    ax[0].legend(fontsize=8, loc="lower right")

    ax[1].bar(range(4), meds, color=cols, edgecolor="black", linewidth=0.5, alpha=0.85)
    for i, (m, e, fa) in enumerate(zip(meds, ewr, far)):
        ax[1].text(i, m + 0.07, f"{m:.0f} win\n{e:.0f}% early\nFA {fa:.0f}%",
                   ha="center", fontsize=7.5)
    ax[1].set_xticks(range(4)); ax[1].set_xticklabels(order)
    ax[1].set_ylabel("median lead time (windows)")
    ax[1].set_title("Lead time grows with completeness")
    ax[1].set_ylim(0, max(meds) + 1.5)
    ax[1].annotate("traces deliver\nthe earliness", xy=(2, meds[2]), xytext=(0.15, max(meds) + 0.9),
                   fontsize=8, fontweight="bold",
                   arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.2))
    fig.tight_layout(); fig.savefig(F / "fig_rqD_leadtime.png", bbox_inches="tight")
    plt.close(fig)

    # ---------- RQ-O: F1-vs-cost Pareto ----------
    o = pd.read_csv(R / "rqO_obs_cost.csv")
    par = o[o.pareto == True].sort_values("cost")
    dom = o[o.pareto != True]
    fig, ax = plt.subplots(figsize=(6.2, 4.0))
    ax.scatter(dom["cost"], dom["f1"], c=GREY, s=28, alpha=0.6, label="dominated")
    ax.plot(par["cost"], par["f1"], "o-", color=GREEN, ms=6, label="Pareto front")
    # annotate full MELT and the knee (metrics+traces, full sampling)
    full = o[(o.config == "M+L+T+E") & (o["sampling"] == 1.0)]
    knee = o[(o.config == "M+T") & (o["sampling"] == 1.0)]
    for sub, txt, dy in [(full, "full MELT", 0.004), (knee, "knee: M+T", -0.012)]:
        if len(sub):
            r = sub.iloc[0]
            ax.annotate(txt, (r["cost"], r["f1"]),
                        textcoords="offset points", xytext=(-6, 8 if dy > 0 else -14),
                        fontsize=9, fontweight="bold")
    ax.set_xlabel("telemetry cost (traces weighted, scaled by sampling)")
    ax.set_ylabel("detection F1")
    ax.set_title("Observability-cost optimisation: F1 vs cost")
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout(); fig.savefig(F / "fig_rqO_pareto.png", bbox_inches="tight")
    plt.close(fig)

    print("wrote:")
    for n in ("fig_rqA_robustness.png", "fig_rqD_leadtime.png", "fig_rqO_pareto.png"):
        print("  ", F / n)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/results")
