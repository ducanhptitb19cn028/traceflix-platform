"""
Online, self-adapting anomaly detector (RQ4).

The detectors in ``models/detectors.py`` are *batch* learners: ``fit`` once on a
static split, then frozen. That is the traditional AIOps deployment -- train on
a historical snapshot, ship the model. It is also exactly what breaks when the
telemetry distribution drifts (see ``ml/drift.py``): the boundary calibrated on
last month's "normal" misfires on this month's normal, and detection decays.

``OnlineModel`` is the streaming alternative. It never re-fits offline; instead
it adapts continuously from the incoming data pattern via four mechanisms:

  1. Adaptive normalisation -- an exponentially-weighted running mean/variance
     (``_EWStandardizer``) tracks the *current normal operating point*. It is
     updated only from windows revealed to be normal, so each feature is a
     z-score against today's normal rather than a stale baseline; a fault is a
     large deviation regardless of which regime it occurs in. This is the
     mechanism that makes the detector drift-robust.

  2. Incremental learning -- logistic regression trained per sample with
     ``SGDClassifier.partial_fit`` under the prequential (test-then-train)
     protocol: predict the window, then learn from its revealed label.

  3. Dynamic parameter optimisation -- a small pool of candidate learners with
     different learning-rate / regularisation settings runs in parallel. The
     "champion" serving predictions is whichever candidate has the best recent
     windowed *F1* (not accuracy -- under class imbalance accuracy would reward a
     trivial always-normal predictor), so the effective hyper-parameters re-tune
     themselves as the data pattern changes (online model selection, a bandit).

  4. Drift-triggered acceleration -- a two-window error monitor (``_DriftDetector``)
     watches the prequential error. When it jumps, the model enters a short
     "boost": the normaliser's decay is raised so it re-centres quickly on the
     new regime. Adaptation events are recorded for reporting.

Label availability: the protocol assumes ground-truth arrives with delay. That
is realistic in this repo's chaos-engineering setting (fault injection yields
labels) and in production via operator-confirmed/dismissed alerts. Reference:
Gama et al. (2014), "A survey on concept drift adaptation".
"""
from __future__ import annotations

from collections import deque

import numpy as np
from sklearn.linear_model import SGDClassifier


class _EWStandardizer:
    """Exponentially-weighted running mean/variance -> tracks a drifting scale."""

    def __init__(self, n_features: int, decay: float = 0.01):
        self.decay = decay
        self.mean = np.zeros(n_features, dtype=float)
        self.var = np.ones(n_features, dtype=float)
        self._init = False

    def warm(self, batch: np.ndarray) -> None:
        """Initialise mean/variance from a burn-in batch so the very first
        z-scores are O(1) -- without this, features like jvm memory (~1e8) make
        the first standardised vectors enormous and the constant-rate SGD
        diverges before it ever sees a stable input."""
        self.mean = batch.mean(axis=0)
        self.var = batch.var(axis=0) + 1e-9
        self._init = True

    def partial_fit(self, x: np.ndarray) -> None:
        if not self._init:
            self.mean = x.astype(float).copy()
            self.var = np.ones_like(self.mean)
            self._init = True
            return
        d = self.decay
        delta = x - self.mean
        self.mean = self.mean + d * delta
        # EW variance (West, 1979): keeps var positive, tracks recent spread
        self.var = (1 - d) * (self.var + d * delta * delta)

    def transform(self, x: np.ndarray) -> np.ndarray:
        z = (x - self.mean) / (np.sqrt(self.var) + 1e-6)
        return np.clip(z, -12.0, 12.0)   # guard against residual blow-ups


class _Candidate:
    """One incremental learner + a rolling record of recent (label, prediction)
    pairs, scored by F1 so champion selection is robust to class imbalance."""

    def __init__(self, eta0: float, alpha: float, seed: int = 42, recent: int = 300):
        self.eta0 = eta0
        self.alpha = alpha
        self.clf = SGDClassifier(
            loss="log_loss", learning_rate="constant", eta0=eta0,
            alpha=alpha, random_state=seed,
        )
        self.recent: deque[tuple[int, int]] = deque(maxlen=recent)
        self.started = False

    def predict(self, xs: np.ndarray) -> int:
        if not self.started:
            return 0
        return int(self.clf.predict(xs.reshape(1, -1))[0])

    def proba(self, xs: np.ndarray) -> float:
        if not self.started:
            return 0.5
        return float(self.clf.predict_proba(xs.reshape(1, -1))[0, 1])

    def learn(self, xs: np.ndarray, y: int) -> None:
        self.clf.partial_fit(xs.reshape(1, -1), [y], classes=[0, 1])
        self.started = True

    def score(self) -> float:
        """Recent windowed F1 (zero when nothing positive is seen/called)."""
        if not self.recent:
            return 0.0
        tp = fp = fn = 0
        for y, p in self.recent:
            tp += (p == 1 and y == 1)
            fp += (p == 1 and y == 0)
            fn += (p == 0 and y == 1)
        denom = 2 * tp + fp + fn
        return (2 * tp / denom) if denom else 0.0


class _DriftDetector:
    """Flags when the recent prequential error exceeds the reference error by
    more than ``delta`` -- a deliberately simple, transparent two-window test."""

    def __init__(self, window: int = 150, delta: float = 0.12):
        self.window = window
        self.delta = delta
        self.errors: deque[int] = deque(maxlen=2 * window)

    def update(self, err: int) -> bool:
        self.errors.append(err)
        if len(self.errors) < 2 * self.window:
            return False
        arr = np.fromiter(self.errors, dtype=float)
        ref = arr[: self.window].mean()
        recent = arr[self.window:].mean()
        return (recent - ref) > self.delta

    def reset(self) -> None:
        self.errors.clear()


class OnlineModel:
    """Prequential, self-adapting binary anomaly detector."""

    def __init__(self, n_features: int, decay: float = 0.02,
                 drift_window: int = 150, drift_delta: float = 0.12,
                 seed: int = 42):
        self.scaler = _EWStandardizer(n_features, decay)
        self.base_decay = decay
        self.candidates = [
            _Candidate(eta0=e, alpha=a, seed=seed)
            for e in (0.01, 0.05, 0.1)
            for a in (1e-4, 1e-3)
        ]
        self.champion = 0
        self.drift = _DriftDetector(drift_window, drift_delta)
        self.adapt_events: list[int] = []   # stream indices where drift fired
        self._t = 0
        self._boost = 0                      # steps of accelerated adaptation left
        self.n_burn = 150                    # burn-in windows to set feature scale
        self._burn: list[np.ndarray] = []

    def process_one(self, x: np.ndarray, y: int) -> tuple[int, float]:
        """Test-then-train on one window. Returns the *pre-update* (honest)
        champion prediction and its anomaly probability."""
        self._t += 1
        x = np.asarray(x, dtype=float)

        # burn-in: accumulate scale before any SGD step, then no-op predict.
        # (always inside the unscored R0 warm-up, so this never affects scoring)
        if not self.scaler._init:
            self._burn.append(x)
            if len(self._burn) >= self.n_burn:
                self.scaler.warm(np.vstack(self._burn))
                self._burn = []
            return 0, 0.5

        xs = self.scaler.transform(x)

        # --- test: champion serves the prediction ---
        champ = self.candidates[self.champion]
        pred = champ.predict(xs)
        proba = champ.proba(xs)

        # --- train: every candidate records (label, its prediction) then learns ---
        for c in self.candidates:
            c.recent.append((int(y), c.predict(xs)))
            c.learn(xs, y)

        # adaptive normaliser tracks the *normal* operating point only, so the
        # fault signal is never standardised away; faster while post-drift boosting
        if y == 0:
            self.scaler.decay = self.base_decay * (8 if self._boost > 0 else 1)
            self.scaler.partial_fit(x)
        if self._boost > 0:
            self._boost -= 1

        # --- dynamic parameter optimisation: re-elect the champion ---
        self.champion = int(np.argmax([c.score() for c in self.candidates]))

        # --- drift response ---
        if self.drift.update(int(pred != y)):
            self.adapt_events.append(self._t)
            self.drift.reset()
            self._boost = 60

        return pred, proba

    @property
    def champion_params(self) -> dict:
        c = self.candidates[self.champion]
        return {"eta0": c.eta0, "alpha": c.alpha}
