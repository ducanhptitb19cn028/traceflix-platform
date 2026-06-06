"""Invariant tests binding the pipeline to the real TraceFlix topology."""
import numpy as np

from ml.configs import CONFIGS, SERVICES, DEPENDENCIES
from ml.dataset import generate_run
from ml.drift import generate_drifting_run
from ml.features.build import build_features, split_xy
from ml.models.detectors import BaselineModel
from ml.models.online import OnlineModel
from ml.rca.localiser import topk_accuracy
from sklearn.metrics import f1_score


def _data():
    return generate_run(n_episodes=80, seed=1)


def test_topology_matches_real_services():
    assert SERVICES == ["movie-service", "actor-service", "review-service"]
    # movie-service is the only caller; actor/review are leaves
    assert DEPENDENCIES["actor-service"] == []
    assert DEPENDENCIES["review-service"] == []
    assert set(DEPENDENCIES["movie-service"]) == {"actor-service", "review-service"}


def test_feature_count_grows_with_config():
    windows, _ = _data()
    counts = {k: len(split_xy(build_features(windows, c))[3])
              for k, c in CONFIGS.items()}
    assert counts["C1"] < counts["C2"] < counts["C3"] < counts["C4"]


def test_detection_learnable_not_trivial():
    windows, _ = _data()
    X, yb, _, _ = split_xy(build_features(windows, CONFIGS["C3"]))
    acc = (BaselineModel("rf").fit(X, yb).predict(X) == yb).mean()
    assert 0.8 < acc <= 1.0
    assert 0 < yb.mean() < 1


def test_traces_help_rca_top1():
    _, eps = _data()
    e2 = [(build_features(w, CONFIGS["C2"]), t) for w, t in eps]
    e3 = [(build_features(w, CONFIGS["C3"]), t) for w, t in eps]
    # Top-1 is the discriminating metric on a 3-service mesh
    assert topk_accuracy(e3, 1, True) >= topk_accuracy(e2, 1, False)


# --- RQ4: online vs offline under operational drift ------------------------

def test_drift_shifts_baseline_not_labels():
    """Later regimes raise the *normal* operating point (concept drift) while
    keeping the fault labels well defined."""
    windows, regimes = generate_drifting_run(n_episodes=160, seed=3)
    assert len(set(regimes)) == 4
    df = build_features(windows, CONFIGS["C4"])
    df["regime"] = regimes
    normal = df[df["label_fault"] == "normal"]
    r0 = normal[normal["regime"] == 0]["metrics.p99_latency"].mean()
    r3 = normal[normal["regime"] == 3]["metrics.p99_latency"].mean()
    assert r3 > 1.5 * r0          # normal latency baseline has drifted up
    assert 0 < (df["label_fault"] != "normal").mean() < 1   # labels still mixed


def test_online_beats_frozen_offline_under_drift():
    """The core RQ4 claim: a frozen batch model decays on the operational
    future, while the online adaptive model stays close to an all-regime
    oracle -- on identical features."""
    windows, regimes = generate_drifting_run(n_episodes=240, seed=5)
    reg = np.asarray(regimes)
    X, y, _, _ = split_xy(build_features(windows, CONFIGS["C4"]))
    n_warm = int((reg == 0).sum())

    static = BaselineModel("rf").fit(X[:n_warm], y[:n_warm])
    f1_static = f1_score(y[n_warm:], static.predict(X[n_warm:]), zero_division=0)

    online = OnlineModel(n_features=X.shape[1])
    preds = np.array([online.process_one(X[i], int(y[i]))[0]
                      for i in range(len(y))])
    f1_online = f1_score(y[n_warm:], preds[n_warm:], zero_division=0)

    assert f1_static < 0.7            # frozen model decays under drift
    assert f1_online > 0.85           # adaptive model holds up
    assert f1_online > f1_static + 0.2


def test_periodic_retrain_helps_but_trails_online():
    """Scheduled retraining recovers much of the drift loss, but the per-sample
    online model still leads it (retrain cadence leaves a drift-response gap)."""
    from ml.experiments.online_vs_offline import _run_periodic

    windows, regimes = generate_drifting_run(n_episodes=240, seed=5)
    reg = np.asarray(regimes)
    X, y, _, _ = split_xy(build_features(windows, CONFIGS["C4"]))
    n_warm = int((reg == 0).sum())

    static = BaselineModel("rf").fit(X[:n_warm], y[:n_warm])
    f1_static = f1_score(y[n_warm:], static.predict(X[n_warm:]), zero_division=0)

    p_pred, _, retrains = _run_periodic(
        X, y, n_warm, retrain_every=500, train_window=2880)
    f1_periodic = f1_score(y[n_warm:], p_pred[n_warm:], zero_division=0)

    online = OnlineModel(n_features=X.shape[1])
    o_pred = np.array([online.process_one(X[i], int(y[i]))[0]
                       for i in range(len(y))])
    f1_online = f1_score(y[n_warm:], o_pred[n_warm:], zero_division=0)

    assert len(retrains) > 1                       # it actually retrained
    assert f1_periodic > f1_static + 0.1           # scheduling helps
    assert f1_online >= f1_periodic                # online still leads
