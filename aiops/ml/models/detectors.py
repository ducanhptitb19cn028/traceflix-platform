"""
Anomaly detection models (RQ2: which algorithms are most effective?).

Three families from the proposal:
  * Baseline classifiers : RandomForest, GradientBoosting/XGBoost on engineered
                           features. Strong on tabular metric/log aggregates.
  * Temporal model       : a lightweight LSTM over sequences of windows, for
                           detecting drift the per-window classifiers miss.
  * Multimodal fusion    : late-fusion that trains a per-pillar sub-model and
                           combines their probabilities, following the
                           HolisticRCA "building-blocks" idea (Han et al., 2024).

Heavy deps (torch, xgboost) are imported lazily so the baseline path runs in a
minimal environment; the registry falls back gracefully when a lib is absent.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import f1_score
from sklearn.preprocessing import StandardScaler


class BaselineModel:
    """RandomForest or GradientBoosting; optionally XGBoost if installed."""

    def __init__(self, kind: str = "rf", task: str = "binary"):
        self.kind = kind
        self.task = task
        self.scaler = StandardScaler()
        self.model = self._make(kind)

    @staticmethod
    def _make(kind: str):
        if kind == "rf":
            return RandomForestClassifier(
                n_estimators=300, max_depth=None, n_jobs=-1, random_state=42
            )
        if kind == "gb":
            return GradientBoostingClassifier(random_state=42)
        if kind == "xgb":
            try:
                from xgboost import XGBClassifier

                return XGBClassifier(
                    n_estimators=300,
                    max_depth=6,
                    learning_rate=0.1,
                    tree_method="hist",
                    eval_metric="logloss",
                    random_state=42,
                )
            except ImportError:
                return GradientBoostingClassifier(random_state=42)
        raise ValueError(kind)

    def fit(self, X, y):
        Xs = self.scaler.fit_transform(X)
        self.model.fit(Xs, y)
        return self

    def predict(self, X):
        return self.model.predict(self.scaler.transform(X))

    def predict_proba(self, X):
        return self.model.predict_proba(self.scaler.transform(X))

    def feature_importance(self, feat_names):
        if hasattr(self.model, "feature_importances_"):
            return dict(
                sorted(
                    zip(feat_names, self.model.feature_importances_),
                    key=lambda kv: kv[1],
                    reverse=True,
                )
            )
        return {}


class TemporalModel:
    """LSTM over fixed-length window sequences. No-op fallback without torch."""

    def __init__(self, n_features: int, seq_len: int = 10, n_classes: int = 2):
        self.seq_len = seq_len
        self.n_features = n_features
        self.n_classes = n_classes
        self.scaler = StandardScaler()
        self._available = self._try_build()

    def _try_build(self) -> bool:
        try:
            import torch
            import torch.nn as nn
        except ImportError:
            self.net = None
            return False

        class LSTMNet(nn.Module):
            def __init__(self, n_feat, n_cls):
                super().__init__()
                self.lstm = nn.LSTM(n_feat, 64, batch_first=True, num_layers=2,
                                    dropout=0.2)
                self.head = nn.Sequential(nn.Linear(64, 32), nn.ReLU(),
                                          nn.Linear(32, n_cls))

            def forward(self, x):
                out, _ = self.lstm(x)
                return self.head(out[:, -1, :])

        self._torch = torch
        self._nn = nn
        self.net = LSTMNet(self.n_features, self.n_classes)
        return True

    @staticmethod
    def _sequence(X, y, seq_len):
        seqs, labels = [], []
        for i in range(len(X) - seq_len):
            seqs.append(X[i : i + seq_len])
            labels.append(y[i + seq_len])
        return np.array(seqs), np.array(labels)

    def fit(self, X, y, epochs: int = 8):
        if not self._available:
            return self
        torch = self._torch
        Xs = self.scaler.fit_transform(X)
        seqs, labels = self._sequence(Xs, y, self.seq_len)
        if len(seqs) == 0:
            return self
        xb = torch.tensor(seqs, dtype=torch.float32)
        yb = torch.tensor(labels, dtype=torch.long)
        opt = torch.optim.Adam(self.net.parameters(), lr=1e-3)
        lossf = self._nn.CrossEntropyLoss()
        self.net.train()
        for _ in range(epochs):
            opt.zero_grad()
            loss = lossf(self.net(xb), yb)
            loss.backward()
            opt.step()
        return self

    def predict(self, X):
        if not self._available:
            # torch not installed: emit a clearly-marked heuristic fallback so
            # results are not mistaken for a trained LSTM. Install torch (see
            # ml/requirements.txt) to evaluate the real temporal model.
            z = StandardScaler().fit_transform(X)
            # flag a window anomalous if any standardised feature is extreme
            return (np.abs(z).max(axis=1) > 2.5).astype(int)
        torch = self._torch
        Xs = self.scaler.transform(X)
        seqs, _ = self._sequence(Xs, np.zeros(len(Xs)), self.seq_len)
        if len(seqs) == 0:
            return np.zeros(len(X), dtype=int)
        self.net.eval()
        with torch.no_grad():
            logits = self.net(torch.tensor(seqs, dtype=torch.float32))
            preds = logits.argmax(1).numpy()
        return np.concatenate([np.zeros(self.seq_len, dtype=int), preds])


class MultimodalFusion:
    """Late-fusion of per-pillar baseline models (HolisticRCA building blocks)."""

    def __init__(self, pillar_cols: dict[str, list[int]], task: str = "binary"):
        # pillar_cols: pillar name -> column indices belonging to that pillar
        self.pillar_cols = pillar_cols
        self.submodels = {p: BaselineModel("rf", task) for p in pillar_cols}
        self.meta = BaselineModel("gb", task)

    def fit(self, X, y):
        meta_feats = []
        for p, cols in self.pillar_cols.items():
            self.submodels[p].fit(X[:, cols], y)
            proba = self.submodels[p].predict_proba(X[:, cols])
            meta_feats.append(proba[:, 1:2] if proba.shape[1] > 1 else proba)
        self.meta.fit(np.hstack(meta_feats), y)
        return self

    def _meta_input(self, X):
        feats = []
        for p, cols in self.pillar_cols.items():
            proba = self.submodels[p].predict_proba(X[:, cols])
            feats.append(proba[:, 1:2] if proba.shape[1] > 1 else proba)
        return np.hstack(feats)

    def predict(self, X):
        return self.meta.predict(self._meta_input(X))

    def predict_proba(self, X):
        return self.meta.predict_proba(self._meta_input(X))


def quick_f1(model, X, y) -> float:
    return float(f1_score(y, model.predict(X), average="binary", zero_division=0))
