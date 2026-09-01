"""
Always-on anomaly detection for the two *live detection* dashboard pages.

There is no run to trigger here. Two detection engines start with the backend and
keep going: an endless telemetry stream is generated window by window, every
detector scores each window as it arrives, and the dashboard simply attaches to
whatever the engine is doing right now. Reload the page and the counters keep
their values, because the state lives in the engine, not in the browser.

  * ``ML_ENGINE``  -- the classical model families on one stream (online SGD,
                      RandomForest, GradientBoosting, XGBoost, LSTM, multimodal
                      late fusion). The batch learners are fitted once, at
                      start-up, on a bootstrap sample and then frozen -- how they
                      are actually deployed -- while the online learner keeps
                      learning from every window it scores. That asymmetry is what
                      the page exists to show.
  * ``LLM_ENGINE`` -- the local-LLM detector alone: the raw signals it is handed,
                      the strict JSON it returns, per-call latency, and a
                      per-fault-type detection breakdown. Latency and fault
                      sensitivity are what separate it from the cheap tabular
                      detectors, so they get the space.

Both engines run on a daemon thread, publish an immutable snapshot under a lock,
and bump a sequence number per scored window; the FastAPI layer polls that
sequence and forwards each new snapshot as SSE. Engines start lazily on the first
request and are shared by every connected viewer.
"""
from __future__ import annotations

import importlib.util
import random
import threading
import time
from collections import deque

import numpy as np

from collectors.telemetry import _synth
from ml.configs import CONFIGS, FAULT_TYPES, SERVICES
from ml.dataset import ancestors, generate_run
from ml.features.build import build_features, split_xy
from ml.models.detectors import BaselineModel, MultimodalFusion, TemporalModel
from ml.models.llm_detector import OLLAMA_URL, LLMDetector, _ollama_ready
from ml.models.online import OnlineModel
from .schemas import signal_digest

_PILLARS = ("metrics", "events", "logs", "traces")
_SEQ_LEN = 10                      # LSTM sequence length (matches run_experiment)
_WINDOWS_PER_EPISODE = 12
_NORMAL_RATIO = 0.4
_HISTORY = 400                     # rolling chart points kept for late joiners
_MELT_HISTORY = 1350               # rolling raw MELT windows kept for the MELT page.
                                   # Every source yields one window per service per
                                   # instant, so this is 150 instants across the nine
                                   # services -- 25 min of the cluster engine at its
                                   # 10 s cadence, which is what makes an injected
                                   # fault still visible on the page after it ends.
_BOOTSTRAP_WINDOWS = 1200          # one-off sample the frozen models are fitted on
                                   # (kept small so the page is live within seconds)
_BURN_IN_WINDOWS = 400             # of those, how many the online learner burns in on
                                   # (150 set the feature scale; the rest train it —
                                   # replaying all 1200 costs ~10 s for no gain)
_DEFAULT_CONFIG = "C4"             # the ML page starts on full MELT; switchable live
_LLM_PROBE_SEC = 15.0              # how often to re-check whether Ollama came up


def _installed(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


# --------------------------------------------------------------------------- #
# endless telemetry source                                                     #
# --------------------------------------------------------------------------- #
def live_windows(seed: int | None = None):
    """Yield telemetry windows forever, one service at a time.

    The episode structure of ``ml.dataset.generate_run`` -- alternating normal and
    fault episodes, one injected root cause per fault episode, ancestors inheriting
    a secondary latency symptom -- but unbounded, so a detector can be watched
    indefinitely instead of over a fixed run.

    Calls ``_synth`` rather than ``collect_window`` deliberately. Under ``TF_LIVE=1``
    -- which is how the in-cluster deployment runs -- ``collect_window`` returns the
    *observed* telemetry of the real mesh but keeps the *requested* fault as the
    label. These pages score every verdict against that label, so live signals under
    an injected label would make each reported F1 meaningless, and would fire a
    PromQL/LogQL/TraceQL round trip per service per window at several windows a
    second. The ground truth here is injected, so the signals must be too; reading
    the real stack is the Online/Offline pages' job."""
    rng = random.Random(seed if seed is not None else int(time.time()))
    fault_pool = [f for f in FAULT_TYPES if f != "normal"]
    ts = 0.0
    while True:
        if rng.random() < _NORMAL_RATIO:
            fault, root = "normal", None
        else:
            fault, root = rng.choice(fault_pool), rng.choice(SERVICES)
        secondary = ancestors(root)
        for _ in range(_WINDOWS_PER_EPISODE):
            ts += 10.0
            for svc in SERVICES:
                if fault == "normal":
                    svc_fault, is_origin = "normal", False
                elif svc == root:
                    svc_fault, is_origin = fault, True
                elif svc in secondary:
                    svc_fault, is_origin = "latency_spike", False
                else:
                    svc_fault, is_origin = "normal", False
                yield _synth(svc, svc_fault, ts, rng, is_origin)


class Score:
    """Running confusion counts -> accuracy / precision / recall / F1."""

    __slots__ = ("tp", "fp", "fn", "tn")

    def __init__(self):
        self.tp = self.fp = self.fn = self.tn = 0

    def add(self, y_pred: int, y: int) -> None:
        self.tp += (y_pred == 1 and y == 1)
        self.fp += (y_pred == 1 and y == 0)
        self.fn += (y_pred == 0 and y == 1)
        self.tn += (y_pred == 0 and y == 0)

    def as_dict(self) -> dict:
        n = self.tp + self.fp + self.fn + self.tn
        p_d, r_d, f_d = self.tp + self.fp, self.tp + self.fn, 2 * self.tp + self.fp + self.fn
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
            "acc": round((self.tp + self.tn) / n, 4) if n else 0.0,
            "precision": round(self.tp / p_d, 4) if p_d else 0.0,
            "recall": round(self.tp / r_d, 4) if r_d else 0.0,
            "f1": round(2 * self.tp / f_d, 4) if f_d else 0.0,
        }


def _melt(w) -> dict:
    return {p: {k: round(float(v), 4) for k, v in getattr(w, p).items()}
            for p in _PILLARS}


class _Engine(threading.Thread):
    """Base: a daemon loop that scores an endless stream and publishes snapshots.

    Subclasses implement ``_prepare`` (once, before scoring starts) and ``_score``
    (per window, returning the snapshot body). Everything else -- the thread, the
    sequence number, the lock, the pause/rate controls, the rolling history for
    late-joining viewers -- is shared."""

    name_ = "engine"

    def __init__(self, rate: float = 4.0):
        super().__init__(daemon=True, name=f"live-{self.name_}")
        self.rate = rate                    # target windows per second (0 = flat out)
        self.paused = False
        self._seq = 0
        self._state: dict = {"status": "starting", "processed": 0}
        self._history: deque = deque(maxlen=_HISTORY)
        self._melt: deque = deque(maxlen=_MELT_HISTORY)
        self._lock = threading.RLock()
        self._started_at = time.time()
        self._actual = 0.0                  # measured throughput, windows/sec

    # -- public surface ----------------------------------------------------- #
    def snapshot(self) -> dict:
        with self._lock:
            return {"seq": self._seq, "rate": self.rate, "paused": self.paused,
                    "actual_rate": round(self._actual, 2),
                    "uptime_s": round(time.time() - self._started_at, 1), **self._state}

    def history(self) -> list:
        with self._lock:
            return list(self._history)

    def melt_history(self) -> list:
        """The raw four-pillar signals of the recent windows, oldest first.

        The snapshot carries only the window just scored, so a page attaching to
        the stream would draw nothing until nine more windows had gone by and
        would lose everything on a reload. This is the backfill: the MELT page
        renders the last few minutes of the mesh immediately, then follows the
        stream. Raw collector output, before build_features -- what the pillars
        actually held, not what any configuration selected from them."""
        with self._lock:
            return list(self._melt)

    def set_rate(self, rate: float) -> None:
        self.rate = max(0.0, min(float(rate), 200.0))

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)

    def reset(self) -> None:
        """Clear the running statistics without restarting the models."""
        with self._lock:
            self._reset_stats()
            self._history.clear()
            self._melt.clear()
            self._started_at = time.time()

    # -- subclass hooks ----------------------------------------------------- #
    def _prepare(self) -> None: ...
    def _score(self, w) -> tuple[dict, dict | None]:
        """Return (snapshot body, chart point or None)."""
        raise NotImplementedError
    def _reset_stats(self) -> None: ...
    def _tick(self) -> None:
        """Called once per loop before scoring, for periodic engine housekeeping."""
    def _stream(self):
        """The window source. Generated by default; the cluster engine reads the
        deployed mesh instead (see streaming.cluster_detect)."""
        return live_windows()

    # -- loop --------------------------------------------------------------- #
    def run(self) -> None:
        try:
            self._prepare()
        except Exception as e:                      # surface, never crash silently
            with self._lock:
                self._state = {"status": "error", "error": repr(e), "processed": 0}
            return
        stream = self._stream()
        while True:
            if self.paused:
                time.sleep(0.1)
                continue
            t0 = time.perf_counter()
            try:
                self._tick()
                body, point = self._score(next(stream))
            except StopIteration:
                # Both window sources loop forever, so this only happens after the
                # source has already raised something of its own -- and a generator
                # that raised is exhausted, so retrying pulls StopIteration from it
                # for as long as the loop runs. Left to itself that overwrites the
                # real reason within the second, and every page reporting the
                # engine's error shows `StopIteration()` instead of, say, the
                # cluster engine's refusal to run without TF_LIVE=1. Keep the first
                # error and stop pulling.
                with self._lock:
                    self._state = {**self._state, "status": "error",
                                   "error": self._state.get("error")
                                   or "window source ended"}
                return
            except Exception as e:
                with self._lock:
                    self._state = {**self._state, "status": "error", "error": repr(e)}
                time.sleep(1.0)
                continue
            with self._lock:
                self._seq += 1
                self._state = {"status": "live", **body}
                if point:
                    self._history.append({"seq": self._seq, **point})
                # Every engine's body carries `melt`; the guard is for a future
                # one whose body does not, which should cost the MELT page its
                # backfill rather than crash the scoring loop.
                if "melt" in body:
                    self._melt.append({
                        "seq": self._seq, "ts": body.get("ts"),
                        "service": body.get("service"),
                        "fault": body.get("label_fault"),
                        "label": 0 if body.get("label") == "normal" else 1,
                        **body["melt"],
                    })
            if self.rate:
                time.sleep(max(0.0, 1.0 / self.rate - (time.perf_counter() - t0)))
            # Measured, not requested: a detector that costs 200 ms a window cannot
            # be driven at 25/s however the selector is set, and the page should say
            # so rather than repeat the target back.
            dt = time.perf_counter() - t0
            with self._lock:
                self._actual = (1.0 / dt if not self._actual
                                else 0.9 * self._actual + 0.1 / dt)


# --------------------------------------------------------------------------- #
# ML engine                                                                    #
# --------------------------------------------------------------------------- #
def ml_catalogue() -> list[dict]:
    """The detector line-up, with honest availability flags.

    ``available=False`` means the library is missing and the detector is left out
    rather than silently replaced by a heuristic -- the same honesty rule
    ``TemporalModel`` and ``LLMDetector`` follow."""
    xgb, torch = _installed("xgboost"), _installed("torch")
    return [
        {"key": "online_sgd", "name": "Online SGD", "family": "incremental",
         "color": "#22c55e", "available": True,
         "note": "prequential test-then-train: learns from every window as it "
                 "arrives, never refitted offline"},
        {"key": "rf", "name": "RandomForest", "family": "batch (frozen)",
         "color": "#3b82f6", "available": True,
         "note": "300 trees on engineered features; fitted once at start-up, then frozen"},
        {"key": "gb", "name": "GradientBoosting", "family": "batch (frozen)",
         "color": "#a855f7", "available": True,
         "note": "sklearn gradient boosting; fitted once at start-up"},
        {"key": "xgb", "name": "XGBoost" if xgb else "XGBoost (→ GB fallback)",
         "family": "batch (frozen)", "color": "#ec4899", "available": True,
         "note": "histogram-tree boosting" if xgb else
                 "xgboost not installed — BaselineModel falls back to GradientBoosting"},
        {"key": "lstm", "name": "LSTM (temporal)", "family": "batch (frozen)",
         "color": "#f59e0b", "available": torch,
         "note": f"2-layer LSTM over the last {_SEQ_LEN} windows"
                 if torch else "torch not installed — detector left out"},
        {"key": "fusion", "name": "Multimodal fusion", "family": "batch (frozen)",
         "color": "#14b8a6", "available": True,
         "note": "per-pillar RF sub-models, probabilities combined by a GB meta-model"},
    ]


class MLEngine(_Engine):
    name_ = "ml"

    def __init__(self, rate: float = 4.0):
        super().__init__(rate)
        self.catalogue = {d["key"]: d for d in ml_catalogue()}
        self.keys = [k for k, d in self.catalogue.items() if d["available"]]
        self.config = _DEFAULT_CONFIG
        self._pending_config: str | None = None
        self.scores = {k: Score() for k in self.keys}
        self._lat = {k: 0.0 for k in self.keys}
        self._n = 0
        self.feed: deque = deque(maxlen=12)

    def _reset_stats(self) -> None:
        self.scores = {k: Score() for k in self.keys}
        self._lat = {k: 0.0 for k in self.keys}
        self._n = 0
        self.feed.clear()

    def set_config(self, config: str) -> None:
        """Queue a switch to another observability configuration.

        Changing C1..C4 changes which signals exist, so the feature vector changes
        shape and every model has to be refitted — it cannot be applied mid-window.
        The engine picks this up at the top of its next loop, refits, and clears the
        statistics, because scores either side of the switch are not comparable."""
        if config not in CONFIGS:
            raise ValueError(config)
        if config != self.config:
            self._pending_config = config

    def _tick(self) -> None:
        if self._pending_config:
            self.config, self._pending_config = self._pending_config, None
            self._fit(self.config)
            with self._lock:
                self._reset_stats()
                self._history.clear()

    def _prepare(self) -> None:
        self._fit(self.config)

    def _fit(self, config: str) -> None:
        """Fit the frozen learners, and burn the online learner in, on a bootstrap
        sample. This is the deployment step: after it, the batch models never see a
        label again."""
        with self._lock:
            self._state = {**self._state, "status": "training"}
        cfg = CONFIGS[config]
        windows, _ = generate_run(n_episodes=12, seed=42)
        windows.sort(key=lambda w: w.ts)
        windows = windows[:_BOOTSTRAP_WINDOWS]
        X, y, _, feats = split_xy(build_features(windows, cfg))
        y = y.astype(int)

        # ~14 s, of which the LSTM is ~7 s and the fusion's five sub-models ~4 s.
        # Fitting these on threads was tried and returned about a second (the GIL),
        # and cutting LSTM epochs would buy the rest by shipping a weaker model on a
        # page whose whole point is comparing model families. So it stays serial and
        # runs at backend start-up instead, where nobody is waiting on it.
        t0 = time.perf_counter()
        self.fitted: dict = {}
        for k in self.keys:
            if k in ("rf", "gb", "xgb"):
                self.fitted[k] = BaselineModel(k, "binary").fit(X, y)
            elif k == "fusion":
                cols = {p: [i for i, n in enumerate(feats) if n.startswith(p + ".")]
                        for p in _PILLARS}
                self.fitted[k] = MultimodalFusion(
                    {p: c for p, c in cols.items() if c}, "binary").fit(X, y)
            elif k == "lstm":
                self.fitted[k] = TemporalModel(
                    n_features=X.shape[1], seq_len=_SEQ_LEN).fit(X, y)
        self.online = OnlineModel(n_features=X.shape[1]) if "online_sgd" in self.keys else None
        if self.online is not None:
            # burn-in only: it goes on learning from the live stream, so replaying
            # the whole bootstrap here would just delay start-up
            for i in range(min(_BURN_IN_WINDOWS, len(X))):
                self.online.process_one(X[i], int(y[i]))

        # Serving is one window at a time, where sklearn's tree parallelism is pure
        # thread-pool overhead (~100 ms/window for a 300-tree forest against ~1 ms
        # single-threaded). Fitting keeps n_jobs=-1; only inference is pinned, so
        # the per-window cost the page reports is the model's, not the pool's.
        for m in (self.fitted.get("rf"), *(getattr(self.fitted.get("fusion"), "submodels", {}) or {}).values()):
            if m is not None and hasattr(m.model, "n_jobs"):
                m.model.n_jobs = 1

        self.train_ms = round((time.perf_counter() - t0) * 1000, 1)
        self.n_features = int(X.shape[1])
        self.bootstrap_windows = len(windows)
        self.seq_buf: deque = deque(X[-_SEQ_LEN:], maxlen=_SEQ_LEN + 1)

    def _score(self, w):
        x, y_arr, _, _ = split_xy(build_features([w], CONFIGS[self.config]))
        x, yt = x[0], int(y_arr[0])
        self._n += 1
        verdicts = {}

        for k in self.keys:
            t = time.perf_counter()
            if k == "online_sgd":
                pred, proba = self.online.process_one(x, yt)
                pred = int(pred)
            elif k == "lstm":
                self.seq_buf.append(x)
                if len(self.seq_buf) <= _SEQ_LEN:
                    pred, proba = 0, 0.5
                else:
                    out = self.fitted[k].predict(np.asarray(self.seq_buf, dtype=np.float32))
                    pred = int(out[-1])
                    proba = float(pred)      # the LSTM head yields a class, not a score
            else:
                p = self.fitted[k].predict_proba(x.reshape(1, -1))
                proba = float(p[0, 1]) if p.shape[1] > 1 else float(p[0, 0])
                pred = int(proba >= 0.5)
            self._lat[k] += (time.perf_counter() - t) * 1000
            self.scores[k].add(pred, yt)
            verdicts[k] = {"pred": pred, "proba": round(float(proba), 3)}

        self.feed.appendleft({"window": self._n, "service": w.service, "fault": w.fault,
                              "label": yt, "preds": {k: verdicts[k]["pred"] for k in self.keys}})

        body = {
            "processed": self._n,
            "ts": w.ts,
            "config": self.config,
            "config_name": CONFIGS[self.config].name,
            "service": w.service,
            "label": "anomaly" if yt else "normal",
            "label_fault": w.fault,
            "bootstrap_windows": self.bootstrap_windows,
            "train_ms": self.train_ms,
            "n_features": self.n_features,
            "adapt_events": len(self.online.adapt_events) if self.online else 0,
            "champion": self.online.champion_params if self.online else None,
            "melt": _melt(w),
            "feed": list(self.feed),
            "detectors": [
                {"key": k, "name": self.catalogue[k]["name"],
                 "color": self.catalogue[k]["color"], "family": self.catalogue[k]["family"],
                 **verdicts[k], **self.scores[k].as_dict(),
                 "latency_ms": round(self._lat[k] / self._n, 3)}
                for k in self.keys
            ],
        }
        point = {"window": self._n}
        for k in self.keys:
            point[k] = self.scores[k].as_dict()["f1"]
        return body, point


# --------------------------------------------------------------------------- #
# LLM engine                                                                   #
# --------------------------------------------------------------------------- #
class LLMEngine(_Engine):
    name_ = "llm"

    def __init__(self, rate: float = 2.0):
        super().__init__(rate)
        self.score = Score()
        self.lats: deque = deque(maxlen=500)
        self.by_fault: dict[str, dict] = {}
        self.feed: deque = deque(maxlen=12)
        self._n = 0

    def _reset_stats(self) -> None:
        self.score = Score()
        self.lats.clear()
        self.by_fault = {}
        self.feed.clear()
        self._n = 0

    def _prepare(self) -> None:
        self.llm = LLMDetector()
        self._probe_at = 0.0
        self._probing = False
        self.mode_since = time.time()

    def _tick(self) -> None:
        """Re-check Ollama periodically so the detector picks up a model server
        that was started *after* the backend was.

        ``LLMDetector`` probes once, in its constructor, which would otherwise
        strand the engine in heuristic mode until a restart. The probe itself runs
        on its own thread: it is an HTTP call with a 2 s timeout, and blocking the
        scoring loop on it every 15 s would show up as a stutter in the stream."""
        now = time.time()
        if self._probing or now - self._probe_at < _LLM_PROBE_SEC:
            return
        self._probe_at = now
        self._probing = True

        def probe():
            try:
                ready, reason = _ollama_ready(self.llm.model)
                self.llm.mode_reason = reason
                mode = "llm" if ready else "heuristic"
                if mode != self.llm.mode:
                    self.llm.mode = mode
                    self.mode_since = time.time()
                    # the two modes are different detectors; pooling their verdicts
                    # into one F1 would misreport both
                    self.reset()
            finally:
                self._probing = False

        threading.Thread(target=probe, daemon=True, name="llm-probe").start()

    def _score(self, w):
        digest = signal_digest(w)
        yt = int(w.fault != "normal")
        prompt = ", ".join(f"{k}={float(v):.4g}" for k, v in digest.items())

        t = time.perf_counter()
        verdict = self.llm.classify_named(digest)
        ms = (time.perf_counter() - t) * 1000

        pred = int(bool(verdict["anomaly"]))
        conf = float(verdict.get("confidence", 0.5))
        self._n += 1
        self.score.add(pred, yt)
        self.lats.append(ms)

        b = self.by_fault.setdefault(w.fault, {"fault": w.fault, "n": 0, "hit": 0})
        b["n"] += 1
        b["hit"] += int(pred == yt)

        self.feed.appendleft({"window": self._n, "service": w.service, "fault": w.fault,
                              "label": yt, "pred": pred, "conf": round(conf, 3),
                              "ms": round(ms, 1)})

        arr = np.asarray(self.lats)
        body = {
            "processed": self._n,
            "ts": w.ts,
            "service": w.service,
            "label": "anomaly" if yt else "normal",
            "label_fault": w.fault,
            "model": self.llm.model,
            "mode": self.llm.mode,
            "mode_reason": getattr(self.llm, "mode_reason", ""),
            "mode_age_s": round(time.time() - self.mode_since, 1),
            "url": OLLAMA_URL,
            "correct": int(pred == yt),
            "melt": _melt(w),
            "signals": digest,
            "prompt": prompt,
            "verdict": {
                "pred": pred, "confidence": round(conf, 3),
                "explanation": verdict.get("explanation", ""),
                "json": {"anomaly": bool(pred), "confidence": round(conf, 2)},
            },
            "latency": {
                "last_ms": round(ms, 1),
                "mean_ms": round(float(arr.mean()), 1),
                "p95_ms": round(float(np.percentile(arr, 95)), 1),
            },
            "score": self.score.as_dict(),
            "by_fault": sorted(self.by_fault.values(), key=lambda d: d["fault"]),
            "feed": list(self.feed),
        }
        return body, {"window": self._n, "f1": self.score.as_dict()["f1"],
                      "acc": self.score.as_dict()["acc"], "ms": round(ms, 1)}


# --------------------------------------------------------------------------- #
# lazy singletons                                                              #
# --------------------------------------------------------------------------- #
_ENGINES: dict[str, _Engine] = {}
_ENGINE_LOCK = threading.Lock()


def get_engine(kind: str) -> _Engine:
    """The shared, always-on engine for ``kind`` ("ml" | "llm" | "cluster").

    Idempotent: the first caller starts the thread, everyone after attaches to it.
    The backend calls this at start-up (see ``webui.backend.app``) so the ML
    engine's one-off bootstrap fit happens while the server is booting rather than
    while someone waits on the page."""
    with _ENGINE_LOCK:
        eng = _ENGINES.get(kind)
        if eng is None:
            if kind == "cluster":
                # imported here, not at module scope: cluster_detect subclasses
                # MLEngine, so a top-level import would be circular
                from .cluster_detect import ClusterEngine
                eng = ClusterEngine()
            else:
                eng = MLEngine() if kind == "ml" else LLMEngine()
            _ENGINES[kind] = eng
            eng.start()
        return eng


def ml_info() -> dict:
    eng = get_engine("ml")
    return {
        "detectors": ml_catalogue(),
        "configs": [{"key": k, "name": c.name, "represents": c.represents}
                    for k, c in CONFIGS.items()],
        "config": getattr(eng, "config", _DEFAULT_CONFIG),
        "seq_len": _SEQ_LEN,
        "pillars": list(_PILLARS),
        "engine": eng.snapshot().get("status"),
        "rate": eng.rate,
    }


def llm_info() -> dict:
    eng = get_engine("llm")
    llm = getattr(eng, "llm", None) or LLMDetector()
    return {
        "model": llm.model,
        "mode": llm.mode,                 # "llm" (model served) | "heuristic" (fallback)
        "mode_reason": getattr(llm, "mode_reason", ""),
        "url": OLLAMA_URL,
        "pillars": list(_PILLARS),
        "engine": eng.snapshot().get("status"),
        "rate": eng.rate,
    }


# --------------------------------------------------------------------------- #
# MELT catalogue                                                               #
# --------------------------------------------------------------------------- #
# What each pillar actually holds, and where each field came from. The MELT page
# renders straight from this, so a signal added to a collector is described in one
# place rather than re-typed into the frontend -- and, more importantly, the page
# can name the query behind every number instead of showing a bare float.
#
#   kind   "gauge"   a level; plot it as it stands
#          "rate"    per-second over the collector's 2 m window
#          "count"   an occurrence tally; discrete, plot as bars/markers
#   scale  "s"       seconds        "ms" milliseconds
#          "bytes"   bytes          "ratio" 0..1        "" dimensionless
_MELT_FIELDS = {
    "metrics": {
        "icon": "📈", "title": "Metrics", "colour": "#3b82f6",
        "source": "PromQL — OTel Java agent v2.12.0 via the collector's Prometheus exporter",
        "fields": [
            {"key": "req_rate", "label": "request rate", "kind": "rate", "scale": "",
             "query": "sum(rate(http_server_request_duration_seconds_count[2m]))"},
            {"key": "err_rate", "label": "5xx rate", "kind": "rate", "scale": "",
             "query": 'same count, http_response_status_code=~"5.."', "bad": "high"},
            {"key": "p50_latency", "label": "p50 latency", "kind": "gauge", "scale": "s",
             "query": "histogram_quantile(0.5, …_bucket[2m])", "bad": "high"},
            {"key": "p99_latency", "label": "p99 latency", "kind": "gauge", "scale": "s",
             "query": "histogram_quantile(0.99, …_bucket[2m])", "bad": "high"},
            {"key": "cpu", "label": "JVM CPU", "kind": "gauge", "scale": "ratio",
             "query": "avg(jvm_cpu_recent_utilization_ratio)", "bad": "high"},
            {"key": "mem", "label": "JVM heap", "kind": "gauge", "scale": "bytes",
             "query": "sum(jvm_memory_used_bytes)", "bad": "high"},
            {"key": "gc_pause", "label": "GC pause", "kind": "rate", "scale": "s",
             "query": "sum(rate(jvm_gc_duration_seconds_sum[2m]))", "bad": "high"},
            {"key": "threads", "label": "threads", "kind": "gauge", "scale": "",
             "query": "avg(jvm_thread_count)"},
            # C4 only: the long-range series, which is the whole point of the
            # historical pillar -- a leak is a departure from it, not a level.
            {"key": "mem_baseline_1h", "label": "heap baseline (1 h)", "kind": "gauge",
             "scale": "bytes", "query": "avg_over_time(jvm_memory_used_bytes[1h]) @ VictoriaMetrics",
             "config": "C4"},
        ],
    },
    "events": {
        "icon": "🔔", "title": "Events", "colour": "#f59e0b",
        "source": "Kubernetes API — namespaced events for the service's pods",
        "fields": [
            {"key": "oomkilled", "label": "OOMKilled", "kind": "count", "scale": "", "bad": "high"},
            {"key": "crashloop", "label": "CrashLoopBackOff", "kind": "count", "scale": "", "bad": "high"},
            {"key": "pod_restarts", "label": "BackOff / restarts", "kind": "count", "scale": "", "bad": "high"},
            {"key": "unhealthy", "label": "Unhealthy probe", "kind": "count", "scale": "", "bad": "high"},
        ],
    },
    "logs": {
        "icon": "📜", "title": "Logs", "colour": "#22c55e",
        "source": "LogQL — Loki, count_over_time over a 2 m window",
        "fields": [
            {"key": "log_volume", "label": "lines", "kind": "count", "scale": "",
             "query": '{service_name="…"}'},
            {"key": "error_logs", "label": "error / exception", "kind": "count", "scale": "",
             "query": '|~ "(?i)error|exception"', "bad": "high"},
            {"key": "warn_logs", "label": "warn", "kind": "count", "scale": "",
             "query": '|~ "(?i)warn"', "bad": "high"},
            {"key": "request_logs", "label": "requests served", "kind": "count", "scale": "",
             "query": '|= "received headers"'},
        ],
    },
    "traces": {
        "icon": "🕸", "title": "Traces", "colour": "#6366f1",
        "source": "TraceQL — Tempo search, up to 200 traces per window",
        "fields": [
            {"key": "trace_count", "label": "traces", "kind": "count", "scale": ""},
            {"key": "mean_span_ms", "label": "mean span", "kind": "gauge", "scale": "ms"},
            {"key": "p99_span_ms", "label": "p99 span", "kind": "gauge", "scale": "ms", "bad": "high"},
            # The trace-only signal: a span erroring at THIS service rather than
            # one merely on the latency path of something else's failure.
            {"key": "error_spans", "label": "error spans (origin)", "kind": "count",
             "scale": "", "bad": "high"},
        ],
    },
}


def melt_catalogue() -> list[dict]:
    """The four pillars and the signals each one carries, in MELT order."""
    return [{"key": p, **_MELT_FIELDS[p]} for p in _PILLARS]


def melt_info(kind: str = "cluster") -> dict:
    """Header for the MELT page: the pillar catalogue plus where this engine's
    windows come from -- which is the difference between a page showing the
    deployed mesh and one showing the generator, and must never be implicit."""
    eng = get_engine(kind)
    snap = eng.snapshot()
    live = kind == "cluster"
    return {
        "kind": kind,
        "pillars": melt_catalogue(),
        "services": list(SERVICES),
        "config": getattr(eng, "config", _DEFAULT_CONFIG),
        "engine": snap.get("status"),
        "error": snap.get("error"),
        "processed": snap.get("processed", 0),
        "buffered": len(eng.melt_history()),
        "capacity": _MELT_HISTORY,
        # cadence for the cluster engine is seconds between instants; for the
        # generated engines `rate` is windows per second. Two different knobs.
        "rate": eng.rate,
        "cadence_s": getattr(eng, "cadence", None),
        "real": live,
        "source": ("PromQL / LogQL / TraceQL against the deployed stack, "
                   "labelled by the live Chaos Mesh resources" if live else
                   "ml.dataset generator — plausible signals, injected labels"),
    }
