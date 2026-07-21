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
import math
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
You are an SRE assistant deciding if ONE telemetry window of a microservice mesh is anomalous.
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

# The normal operating point the heuristic fallback measures deviations against,
# mirroring the base values in collectors.telemetry._synth. Each synthetic signal
# is base * (1 + N(0, 0.35)), so a value/base ratio of r sits (r - 1) / 0.35 noise
# sigmas from normal -- which is what makes a sigma threshold meaningful here.
# NB: if _synth's baselines change, these must follow.
_NORMAL_POINT = {
    "metrics.req_rate": 20.0, "metrics.err_rate": 0.3,
    "metrics.p50_latency": 0.03, "metrics.p99_latency": 0.15,
    "metrics.cpu": 0.25, "metrics.mem": 180e6,
    "metrics.gc_pause": 0.05, "metrics.threads": 30.0,
    "logs.request_logs": 20.0, "logs.error_logs": 1.0,
}
_NORMAL_NOISE = 0.35
# Sigmas of deviation at which the fallback calls a window anomalous. Swept over
# 2.0-4.0 on 3x3000 windows from three seeds: F1 sits on a plateau between 2.75
# and 3.0 (mean 0.863 vs 0.857) and falls away either side -- below it the ~87% of
# windows that are normal dominate the false positives, above it recall collapses.
_HEURISTIC_THRESHOLD = 2.75


def _ollama_ready(model: str) -> tuple[bool, str]:
    """Is Ollama serving *this* model? Returns (ready, human-readable reason).

    Checking only that the server answers is not enough, and the failure it misses
    is worse than being down: with the daemon up but the model not pulled, every
    request errors, ``_ollama_classify`` turns each error into a bland
    ``{"anomaly": false}``, and the detector reports "normal" for every window --
    F1 0.0 dressed up as a real model run. So the model has to be in /api/tags
    before we claim LLM mode."""
    try:
        import httpx

        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        if r.status_code != 200:
            return False, f"Ollama at {OLLAMA_URL} returned HTTP {r.status_code}"
        names = {m.get("name", "") for m in r.json().get("models", [])}
        # Ollama reports fully-qualified tags ("qwen2.5:3b"); a bare name means :latest
        want = model if ":" in model else f"{model}:latest"
        if want in names or model in names:
            return True, f"{model} served by Ollama"
        if not names:
            return False, (f"Ollama is running but has no models - "
                           f"run: ollama pull {model}")
        return False, (f"Ollama is running but {model} is not pulled "
                       f"(available: {', '.join(sorted(names))}) - "
                       f"run: ollama pull {model}")
    except Exception as e:
        return False, f"no Ollama reachable at {OLLAMA_URL} ({type(e).__name__})"


def _ollama_available() -> bool:
    """Back-compat shim: server reachable *and* serving the configured model."""
    return _ollama_ready(OLLAMA_MODEL)[0]


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
        ready, reason = _ollama_ready(self.model)
        self.mode = "llm" if ready else "heuristic"
        self.mode_reason = reason      # why, in words, for the dashboard + logs
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

        Scores *exactly the deviations listed in ``_DETECT_RULES``* -- the same
        evidence the model is handed -- so switching between modes changes the
        reasoner, not the question. Deliberately excludes ``traces.error_spans``
        for the same reason: it is not in the rules the model is given, and in the
        base generator it is origin-conditional, so leaning on it would answer from
        the label rather than from the signals.

        Graded, not boolean. Each signal is scored as its deviation from the normal
        operating point in units of the collector's own noise, the rules are
        combined by taking the strongest, and the margin over the decision
        threshold becomes a real confidence -- the earlier version returned one of
        two constants, which left the confidence bar and the latency/confidence
        chart displaying nothing.
        """
        g = lambda k: float(signals.get(k, 0.0))

        # An event is categorical, not a deviation: a container that OOM-killed or
        # is crash-looping is anomalous whatever the rest of the window looks like.
        for ev, why in (("events.crashloop", "crashloop"),
                        ("events.oomkilled", "OOMKilled")):
            if signals.get(ev):
                return {"anomaly": True, "confidence": 0.97,
                        "explanation": f"heuristic: {why} event present"}

        def dev(key: str) -> float:
            """Deviation above normal, in noise sigmas (negative = below normal)."""
            base = _NORMAL_POINT.get(key)
            if not base:
                return 0.0
            return (g(key) / base - 1.0) / _NORMAL_NOISE

        cpu, gc = dev("metrics.cpu"), dev("metrics.gc_pause")
        mem, err = dev("metrics.mem"), dev("metrics.err_rate")
        p50, p99 = dev("metrics.p50_latency"), dev("metrics.p99_latency")
        req, reqlogs = dev("metrics.req_rate"), dev("logs.request_logs")

        # one entry per bullet in _DETECT_RULES; paired signatures score as their
        # weaker half, so both halves must be present
        rules = [
            ("cpu saturation", cpu, "metrics.cpu"),
            ("memory leak", min(mem, gc), "metrics.mem"),
            ("gc pressure", gc, "metrics.gc_pause"),
            ("latency spike", max(p50, p99), "metrics.p99_latency"),
            ("elevated errors", err, "metrics.err_rate"),
            ("pod kill / crash", min(err, -req), "metrics.err_rate"),
            ("network partition", min(err, -reqlogs), "metrics.err_rate"),
        ]
        why, score, field = max(rules, key=lambda r: r[1])

        # margin over the threshold -> confidence in whichever verdict is returned
        p = 1.0 / (1.0 + math.exp(-(score - _HEURISTIC_THRESHOLD)))
        anomalous = p >= 0.5
        ratio = g(field) / _NORMAL_POINT[field] if _NORMAL_POINT.get(field) else 0.0
        return {
            "anomaly": anomalous,
            "confidence": round(p if anomalous else 1.0 - p, 3),
            "explanation": (f"heuristic: {why} - {field.split('.')[-1]} "
                            f"{ratio:.1f}x baseline ({score:+.1f} sd)" if anomalous
                            else f"heuristic: nothing above threshold "
                                 f"(strongest: {why} {score:+.1f} sd)"),
        }

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
            payload = r.json()
            # Ollama reports problems as {"error": "..."} with no "message" key --
            # report what it said, rather than a KeyError('message') that hides it
            if "message" not in payload:
                raise RuntimeError(payload.get("error") or f"HTTP {r.status_code}")
            return self._parse(payload["message"]["content"])
        except Exception as e:
            return {"anomaly": False, "confidence": 0.5,
                    "explanation": f"llm error: {e}"}

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
