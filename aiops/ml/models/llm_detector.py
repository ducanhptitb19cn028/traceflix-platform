"""
LLM-based anomaly detector (RQ4: a new model family).

Where RF/GB/XGB/LSTM/fusion classify *engineered features*, this detector hands a
small local LLM (Qwen2.5-3B, served by Ollama) the *raw* MELT signals of a window
and asks a single binary question: is this window anomalous or not. It exposes the
same ``fit``/``predict``/``predict_proba`` surface as ``models/detectors.py`` so it
drops straight into ``run_experiment.model_family()``, and it runs as the LLM stage
of the streaming backbone in parallel with the online ML detector.

It does *not* classify the fault type -- this project is anomaly detection; the
verdict is binary (0 normal / 1 anomalous), directly comparable to every other
detector's F1.

Two operating modes, chosen automatically:

  * LLM    -- Ollama reachable at ``OLLAMA_URL`` (default http://localhost:11434).
              Each window is formatted into a compact prompt; the model returns
              strict JSON ``{"anomaly": bool, "confidence": 0-1}``. Point
              ``OLLAMA_MODEL`` at ``qwen2.5-3b-traceflix`` for the LoRA-tuned variant.
  * HEURISTIC -- Ollama unreachable. Falls back to a z-score / rule-of-thumb test,
              *clearly marked* via ``self.mode``, so a fallback run is never mistaken
              for a real LLM run (same honesty pattern as TemporalModel without torch).
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sklearn.preprocessing import StandardScaler

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "4"))

# Signs of abnormality (distilled from collectors.telemetry._FAULT_SHIFT) given to
# the model as context, then a single binary question. The model reasons over the
# signatures but only outputs anomalous-or-not -- no fault typing.
_DETECT_RULES = """\
You are an SRE assistant deciding if ONE telemetry window of a 3-service mesh is anomalous.
A window is ANOMALOUS if it shows any of these deviations from normal:
- cpu up ~2x+ (cpu saturation)
- mem up ~2x and gc_pause elevated (memory leak)
- p50/p99 latency up ~2x (latency spike)
- err_rate up ~2x+ with req_rate roughly halved (pod kill / crash)
- err_rate up with request_logs down (network partition)
- crashloop / oomkilled / restart events present
Otherwise it is NORMAL (values near baseline).
Reply with ONLY a JSON object, no prose:
{"anomaly": <true|false>, "confidence": <0..1>}"""


def _ollama_available() -> bool:
    try:
        import httpx

        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


class LLMDetector:
    """Local-LLM binary anomaly detector with the standard detector interface."""

    def __init__(self, model: str | None = None, n_shots: int = 6, seed: int = 42):
        self.model = model or OLLAMA_MODEL
        self.n_shots = n_shots
        self.rng = np.random.default_rng(seed)
        self.feat_names: list[str] = []
        self.scaler = StandardScaler()
        self._shots: list[tuple[str, str]] = []     # (signal text, json answer)
        self._cache: dict[tuple, dict] = {}
        self.mode = "llm" if _ollama_available() else "heuristic"
        self.requires_llm = True

    # -- training: cache scale + a few in-context exemplars ------------------
    def fit(self, X, y, feat_names: list[str] | None = None):
        X = np.asarray(X, dtype=float)
        self.scaler.fit(X)
        self.feat_names = feat_names or [f"f{i}" for i in range(X.shape[1])]
        y = np.asarray(y)
        idx_pos = np.where(y == 1)[0]
        idx_neg = np.where(y == 0)[0]
        half = max(1, self.n_shots // 2)
        chosen = np.concatenate([
            self.rng.choice(idx_pos, min(half, len(idx_pos)), replace=False)
            if len(idx_pos) else np.array([], dtype=int),
            self.rng.choice(idx_neg, min(half, len(idx_neg)), replace=False)
            if len(idx_neg) else np.array([], dtype=int),
        ]).astype(int)
        for i in chosen:
            answer = json.dumps({"anomaly": bool(y[i]), "confidence": 0.9})
            self._shots.append((self._format_signals(X[i]), answer))
        return self

    # -- inference ----------------------------------------------------------
    def predict(self, X) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    def predict_proba(self, X) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if self.mode == "heuristic":
            return self._heuristic_proba(X)
        with ThreadPoolExecutor(max_workers=LLM_CONCURRENCY) as pool:
            results = list(pool.map(self._classify_row, X))
        p1 = np.array([r["confidence"] if r["anomaly"] else 1 - r["confidence"]
                       for r in results], dtype=float)
        return np.column_stack([1 - p1, p1])

    def classify(self, x) -> dict:
        """Single-window binary verdict from a feature vector."""
        return self._classify_row(np.asarray(x, dtype=float))

    def classify_named(self, signals: dict) -> dict:
        """Binary verdict from a name->value digest (the streaming path). No fitted
        scaler needed -- this is the entry point the Kafka LLM consumer uses."""
        if self.mode == "heuristic":
            return self._heuristic_named(signals)
        text = ", ".join(f"{k}={float(v):.4g}" for k, v in signals.items())
        return self._ollama_classify(text)

    # -- internals ----------------------------------------------------------
    def _heuristic_proba(self, X) -> np.ndarray:
        z = np.abs(self.scaler.transform(X))
        score = np.clip(z.max(axis=1) / 5.0, 0.0, 1.0)   # >2.5 sigma -> >0.5
        return np.column_stack([1 - score, score])

    @staticmethod
    def _heuristic_named(signals: dict) -> dict:
        """Rule-of-thumb anomaly test from raw signals when no LLM is available.
        Mirrors the dominant terms of collectors.telemetry._FAULT_SHIFT."""
        g = lambda k: float(signals.get(k, 0.0))
        anomalous = (
            bool(signals.get("events.crashloop")) or bool(signals.get("events.oomkilled"))
            or g("metrics.cpu") > 0.5
            or g("metrics.gc_pause") > 0.09
            or g("metrics.p99_latency") > 0.28
            or g("metrics.err_rate") > 0.5
            or (g("logs.request_logs") and g("logs.request_logs") < 12
                and g("metrics.err_rate") > 0.4)
        )
        return {"anomaly": anomalous,
                "confidence": 0.6 if anomalous else 0.55,
                "explanation": "heuristic (no LLM)"}

    def _format_signals(self, x) -> str:
        return ", ".join(f"{n}={float(v):.4g}"
                         for n, v in zip(self.feat_names, x))

    def _classify_row(self, x) -> dict:
        key = tuple(np.round(x, 3))
        if key in self._cache:
            return self._cache[key]
        out = self._ollama_classify(self._format_signals(x))
        self._cache[key] = out
        return out

    def _ollama_classify(self, signal_text: str) -> dict:
        import httpx

        messages = [{"role": "system", "content": _DETECT_RULES}]
        for sig, ans in self._shots:
            messages.append({"role": "user", "content": f"Window: {sig}"})
            messages.append({"role": "assistant", "content": ans})
        messages.append({"role": "user", "content": f"Window: {signal_text}"})
        try:
            r = httpx.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": self.model, "messages": messages,
                      "stream": False, "format": "json",
                      "options": {"temperature": 0.0}},
                timeout=60.0,
            )
            return self._parse(r.json()["message"]["content"])
        except Exception as e:
            return {"anomaly": False, "confidence": 0.5,
                    "explanation": f"llm error: {e!r}"}

    @staticmethod
    def _parse(content: str) -> dict:
        try:
            d = json.loads(content)
        except Exception:
            m = re.search(r"\{.*\}", content, re.DOTALL)
            d = json.loads(m.group(0)) if m else {}
        anomaly = bool(d.get("anomaly", False))
        return {
            "anomaly": anomaly,
            "confidence": float(d.get("confidence", 0.5)),
            "explanation": str(d.get("explanation", ""))
            or ("anomalous" if anomaly else "normal"),
        }
