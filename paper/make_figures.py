"""Generate publication figures for the 'Learning Under Drift' paper.

Figures are written as vector PDFs into the paper/ directory and embedded by
sn-article.tex. Numbers are taken from the result CSVs where stable across
runs (RQ1) and from the consolidated RQ4 results doc otherwise, so that every
figure is consistent with the tables in the manuscript.
"""
import csv
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "..", "aiops", "data", "results")

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "figure.dpi": 200,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linestyle": ":",
})

# colour-blind-friendly palette (Wong)
C_BLUE, C_ORANGE, C_GREEN, C_GREY = "#0072B2", "#E69F00", "#009E73", "#999999"
CONFIGS = ["C1", "C2", "C3", "C4"]


def save(fig, name):
    path = os.path.join(HERE, name)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print("wrote", path)


# ---------------------------------------------------------------- RQ1
def fig_rq1():
    rows = list(csv.DictReader(open(os.path.join(RESULTS, "rq1_completeness.csv"))))
    metrics = [("precision", "Precision"), ("recall", "Recall"),
               ("f1", "F1"), ("auc_roc", "AUC-ROC")]
    x = range(len(CONFIGS))
    w = 0.2
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    colours = [C_GREY, C_ORANGE, C_BLUE, C_GREEN]
    for i, (key, lab) in enumerate(metrics):
        vals = [float(r[key]) for r in rows]
        ax.bar([xi + (i - 1.5) * w for xi in x], vals, w, label=lab,
               color=colours[i], edgecolor="black", linewidth=0.4)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{c}\n({r['n_features']}f)" for c, r in zip(CONFIGS, rows)])
    ax.set_ylim(0.80, 1.005)
    ax.set_ylabel("Score")
    ax.set_xlabel("Telemetry configuration")
    ax.legend(ncol=4, loc="lower right", framealpha=0.9)
    save(fig, "fig_rq1_completeness.pdf")


# ---------------------------------------------------------------- RQ4 headline
def fig_rq4_headline():
    # F1 on the future (drifted) stream -- Run B (320 episodes), consistent
    # with manuscript Table 7 / rq4_summary.json headline_f1_future.
    static  = [0.4894, 0.4921, 0.5097, 0.5112]
    periodic = [0.7574, 0.7776, 0.8904, 0.8905]
    online  = [0.8174, 0.8347, 0.9817, 0.9834]
    oracle_c4 = 0.9387
    x = range(len(CONFIGS))
    w = 0.26
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.bar([xi - w for xi in x], static, w, label="offline static",
           color=C_GREY, edgecolor="black", linewidth=0.4)
    ax.bar(list(x), periodic, w, label="offline periodic",
           color=C_ORANGE, edgecolor="black", linewidth=0.4)
    ax.bar([xi + w for xi in x], online, w, label="online adaptive",
           color=C_GREEN, edgecolor="black", linewidth=0.4)
    ax.axhline(oracle_c4, color=C_BLUE, ls="--", lw=1.2,
               label="all-regimes oracle (C4)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(CONFIGS)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("F1 on drifted future stream")
    ax.set_xlabel("Telemetry configuration")
    ax.legend(ncol=2, loc="upper left", framealpha=0.9)
    save(fig, "fig_rq4_headline.pdf")


# ---------------------------------------------------------------- RQ4 cost
def fig_rq4_cost():
    # Operational measurements (latency, footprint) come from the dedicated
    # cost-profiling run (rq4_cost.csv); F1 is reconciled to the Run B
    # headline so a single F1 value is used throughout the manuscript.
    f1_runB = {
        ("offline_periodic", "C1"): 0.7574, ("online_adaptive", "C1"): 0.8174,
        ("offline_periodic", "C2"): 0.7776, ("online_adaptive", "C2"): 0.8347,
        ("offline_periodic", "C3"): 0.8904, ("online_adaptive", "C3"): 0.9817,
        ("offline_periodic", "C4"): 0.8905, ("online_adaptive", "C4"): 0.9834,
    }
    rows = list(csv.DictReader(open(os.path.join(RESULTS, "rq4_cost.csv"))))
    fig, ax = plt.subplots(figsize=(6.2, 3.8))
    seen = set()
    for r in rows:
        model = r["model"]
        f1 = f1_runB[(model, r["config"])]
        ms = float(r["max_ms_per_window"])
        kb = float(r["model_kb"])
        cfg = r["config"]
        is_online = model == "online_adaptive"
        colour = C_GREEN if is_online else C_ORANGE
        marker = "o" if is_online else "s"
        size = max(40, min(600, kb / 8.0 + 60))  # area ~ footprint (clamped)
        lbl = ("online adaptive" if is_online else "offline periodic")
        ax.scatter(ms, f1, s=size, c=colour, marker=marker, alpha=0.75,
                   edgecolors="black", linewidths=0.5,
                   label=lbl if lbl not in seen else None)
        seen.add(lbl)
        ax.annotate(cfg, (ms, f1), textcoords="offset points",
                    xytext=(6, 4), fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("Max latency per window (ms, log scale)  --  lower is better")
    ax.set_ylabel("F1 on drifted future stream")
    ax.set_ylim(0.6, 1.02)
    ax.legend(loc="lower left", framealpha=0.9,
              title="marker area $\\propto$ model footprint")
    save(fig, "fig_rq4_cost.pdf")


if __name__ == "__main__":
    fig_rq1()
    fig_rq4_headline()
    fig_rq4_cost()
    print("done")
