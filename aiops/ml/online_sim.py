"""Realtime simulation engine for the online-vs-offline pipeline.

Drives the *same* drifting MELT stream and the *same* models used by
ml.experiments.online_vs_offline, but as a step-by-step generator so a UI can
visualise the online pipeline adapting (and the offline models decaying / doing
their bursty retrains) window by window.

Pure Python (numpy + sklearn) — no UI dependency. Consumed by the web API
(webui/backend) and previously by the Streamlit dashboard.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field

import numpy as np

from .configs import CONFIGS
from .drift import REGIME_NAMES, generate_drifting_run
from .features.build import build_features, split_xy
from .models.detectors import BaselineModel
from .models.online import OnlineModel

WINDOW_F1 = 250          # sliding window for the live rolling-F1 metric


def _f1(buf: deque) -> float:
    tp = fp = fn = 0
    for yt, yp in buf:
        tp += (yp == 1 and yt == 1)
        fp += (yp == 1 and yt == 0)
        fn += (yp == 0 and yt == 1)
    d = 2 * tp + fp + fn
    return (2 * tp / d) if d else 0.0


@dataclass
class Snapshot:
    i: int
    processed: int
    total: int
    regime: int
    regime_name: str
    f1_online: float
    f1_static: float
    f1_periodic: float
    champion: dict
    online_updates: int
    periodic_retrains: int
    next_retrain_in: int
    adapt_events: int
    just_retrained: bool
    just_adapted: bool
    # --- online pipeline internals (for the process visualisation) ---
    pred: int = 0                 # champion prediction this window (pre-update)
    proba: float = 0.5            # champion anomaly probability
    true_label: int = 0           # revealed ground-truth label
    correct: bool = True          # pred == true_label
    boost: int = 0                # accelerated-adaptation steps left (>0 = boosting)
    champion_idx: int = 0         # which candidate is serving
    candidates: list = field(default_factory=list)   # the learner pool + scores
    events: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def run_simulation(config_key: str, episodes: int = 320, seed: int = 42,
                   include_periodic: bool = True, retrain_every: int = 500,
                   train_window: int = 2880, max_windows: int | None = None,
                   chunk: int = 40):
    """Yield a Snapshot every `chunk` scored windows (and on every event)."""
    windows, regimes = generate_drifting_run(n_episodes=episodes, seed=seed)
    df = build_features(windows, CONFIGS[config_key])
    X, y, _, _ = split_xy(df)
    reg = np.asarray(regimes)
    n_warm = int((reg == 0).sum())

    static = BaselineModel("rf", "binary").fit(X[:n_warm], y[:n_warm])
    periodic = (BaselineModel("rf", "binary").fit(X[:n_warm], y[:n_warm])
                if include_periodic else None)
    next_retrain = n_warm + retrain_every

    online = OnlineModel(n_features=X.shape[1])
    for i in range(n_warm):
        online.process_one(X[i], int(y[i]))
    prev_adapt = len(online.adapt_events)

    on_buf: deque = deque(maxlen=WINDOW_F1)
    st_buf: deque = deque(maxlen=WINDOW_F1)
    pe_buf: deque = deque(maxlen=WINDOW_F1)
    events: list = []
    retrains = 0

    n = len(y)
    end = n if max_windows is None else min(n, n_warm + max_windows)
    total = end - n_warm

    for i in range(n_warm, end):
        yi = int(y[i])
        xi = X[i]
        rg = int(reg[i])

        on_pred, on_proba = online.process_one(xi, yi)
        st_pred = int(static.predict(xi.reshape(1, -1))[0])
        just_adapted = len(online.adapt_events) > prev_adapt
        if just_adapted:
            prev_adapt = len(online.adapt_events)
            events.append({"window": i, "event": "online adapted (drift)",
                           "regime": REGIME_NAMES[rg]})

        just_retrained = False
        pe_pred = 0
        if periodic is not None:
            pe_pred = int(periodic.predict(xi.reshape(1, -1))[0])
            if i >= next_retrain:
                lo = max(0, i - train_window)
                periodic = BaselineModel("rf", "binary").fit(X[lo:i], y[lo:i])
                retrains += 1
                next_retrain = i + retrain_every
                just_retrained = True
                events.append({"window": i, "event": "periodic RETRAIN (batch refit)",
                               "regime": REGIME_NAMES[rg]})

        on_buf.append((yi, on_pred))
        st_buf.append((yi, st_pred))
        pe_buf.append((yi, pe_pred))

        processed = i - n_warm + 1
        emit = (processed % chunk == 0) or just_retrained or just_adapted \
            or (i == end - 1)
        if emit:
            pool = [{"eta0": c.eta0, "alpha": c.alpha,
                     "score": round(c.score(), 3),
                     "champion": idx == online.champion}
                    for idx, c in enumerate(online.candidates)]
            yield Snapshot(
                i=i, processed=processed, total=total,
                regime=rg, regime_name=REGIME_NAMES[rg],
                f1_online=round(_f1(on_buf), 4), f1_static=round(_f1(st_buf), 4),
                f1_periodic=round(_f1(pe_buf), 4) if periodic is not None else None,
                champion=online.champion_params,
                online_updates=processed,
                periodic_retrains=retrains,
                next_retrain_in=(next_retrain - i) if periodic is not None else -1,
                adapt_events=len(online.adapt_events),
                just_retrained=just_retrained, just_adapted=just_adapted,
                pred=on_pred, proba=round(float(on_proba), 4), true_label=yi,
                correct=(on_pred == yi), boost=online._boost,
                champion_idx=online.champion, candidates=pool,
                events=events[-12:],
            )
