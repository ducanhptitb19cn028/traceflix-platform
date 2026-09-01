"""
Always-on anomaly detection on the DEPLOYED mesh -- the live counterpart of the
generated stream in streaming.live_detect.

The difference is where both halves of a scored window come from. On the ML and
LLM pages the engine invents the fault, so the signals must be invented too, and
the reported F1 is a statement about the generator. Here neither half is
invented: the telemetry is whatever PromQL/LogQL/TraceQL return for the running
services, and the label is read from the Chaos Mesh resources actually injected
into the cluster (collectors.chaos). What the page reports is therefore a
statement about the deployed system, which is the only place a claim about
observability in production can honestly come from.

Three consequences shape the design, and each is surfaced rather than hidden:

  * **Cadence is real.** A window costs a PromQL round trip per metric per
    service; the nine services are fetched concurrently, and instants are spaced
    by ``cadence`` seconds. This engine runs at a fraction of a window per
    second, not the four per second the generated pages sustain, and the rate
    control is therefore a cadence control.

  * **C1 only, deliberately.** Live collection *could* serve C1-C4 -- unlike the
    historical replay, a window collected at the present instant carries genuine
    present-moment logs, traces and events. But the models here are fitted on the
    replay caches, whose C2-C4 pillars hold values from replay time rather than
    from the episode, so anything above C1 would train on telemetry that does not
    belong to its label. When enough windows have been recorded live -- which
    this engine does, see ``_RECORD`` -- that restriction can be lifted.

  * **Scale, not shape, is what breaks a transferred model.** A detector fitted
    on the generator sees a normal `cpu` around 0.25; the deployed mesh idles two
    orders of magnitude below that, so a generated-data model scores live windows
    as uniformly normal. That is why the models here are refitted on live windows
    and why the page states how many it had.

The engine records every window it collects to ``data/live_stream_cache.jsonl``
in the replay's own format, so the training set grows each time the page runs and
a later fit can be made on genuinely live data rather than on replayed episodes.
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from collectors.chaos import active_faults_checked, chaos_reachable
from collectors.telemetry import LIVE, Window, collect_window
from ml.configs import NAMESPACE, PROM_URL, SERVICES
from .live_detect import MLEngine

_CADENCE = 10.0            # seconds between collected instants
_MIN_TRAIN = 200           # windows below which a fit is not worth attempting
_MIN_ANOM = 20             # anomalous windows below which the same is true
_TRAIN_GLOB = "data/results_live*/live_windows_cache.jsonl"
_RECORD = "data/live_stream_cache.jsonl"
_CONFIG = "C1"             # see the module docstring
_TRUTH_TTL = 5.0           # seconds a ground-truth read is reused for

_AIOPS = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# training sample                                                              #
# --------------------------------------------------------------------------- #
def load_live_windows(patterns: tuple[str, ...] = (_TRAIN_GLOB, _RECORD)) -> list[Window]:
    """Every live window on disk, de-duplicated by (service, instant).

    The replay checkpoints its collection and this engine appends its own, so the
    same instant can appear in more than one file; a duplicate would be counted
    twice by the fit and inflate whatever it agrees with.
    """
    seen: dict[tuple[str, str], Window] = {}
    for pattern in patterns:
        for path in sorted(glob.glob(str(_AIOPS / pattern))):
            try:
                with open(path, encoding="utf8") as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        d = json.loads(line)
                        seen[(d["service"], f'{d["ts"]:.3f}')] = Window(**_scrub(d))
            except Exception:
                continue                      # a truncated checkpoint is not fatal
    return list(seen.values())


def _scrub(d: dict) -> dict:
    """Map any NaN in a cached window to 0.0.

    _prom_instant does this at collection now, but caches written before it did
    still carry NaNs from `histogram_quantile` over an empty bucket rate, and
    GradientBoosting refuses to fit on them. Re-collecting those episodes is not
    possible -- their retention window has passed -- so they are repaired on load.
    """
    for pillar in ("metrics", "logs", "traces", "events"):
        vals = d.get(pillar)
        if isinstance(vals, dict):
            for k, v in vals.items():
                if isinstance(v, float) and v != v:
                    vals[k] = 0.0
    return d


# --------------------------------------------------------------------------- #
# live window source                                                           #
# --------------------------------------------------------------------------- #
class _Truth:
    """Cached view of which service is under which fault.

    One API call per instant rather than one per service, and reused for
    ``_TRUTH_TTL`` so a fast cadence cannot turn the label lookup into the
    dominant cost of a window.
    """

    def __init__(self, namespace: str):
        self.namespace = namespace
        self._at = 0.0
        self._map: dict[str, str] = {}
        self.ok = False
        self._lock = threading.Lock()

    def get(self) -> dict[str, str]:
        with self._lock:
            now = time.time()
            if now - self._at > _TRUTH_TTL:
                # `ok` is refreshed on every read, never captured once at start-up:
                # RBAC can be granted (or revoked) while the engine runs, and a
                # flag fixed at fit time would keep reporting the state the engine
                # was born into long after it stopped being true.
                self.ok, self._map = active_faults_checked(self.namespace)
                self._at = now
            return dict(self._map)


def cluster_windows(cadence: float, truth: _Truth, record: Path | None = None):
    """Yield real windows for the nine services, one instant at a time.

    Every window carries the fault Chaos Mesh has injected into its service at
    the moment of collection, or "normal". Collection is concurrent because it is
    entirely round-trip bound -- serially the nine services take most of a
    cadence between them, which would make the instant a range.
    """
    if not LIVE:
        raise RuntimeError(
            "TF_LIVE=1 is required: refusing to present generated telemetry as "
            "the deployed cluster's")
    fh = open(record, "a", encoding="utf8") if record else None
    try:
        while True:
            t0 = time.time()
            faults = truth.get()
            with ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
                futs = {pool.submit(collect_window, svc,
                                    faults.get(svc, "normal"), t0, None): svc
                        for svc in SERVICES}
                out = []
                for fut in as_completed(futs):
                    try:
                        out.append(fut.result())
                    except Exception:
                        continue
            out.sort(key=lambda w: SERVICES.index(w.service))
            for w in out:
                if fh:
                    fh.write(json.dumps(w.__dict__) + "\n")
                yield w
            if fh:
                fh.flush()
            time.sleep(max(0.0, cadence - (time.time() - t0)))
    finally:
        if fh:
            fh.close()


# --------------------------------------------------------------------------- #
# engine                                                                       #
# --------------------------------------------------------------------------- #
class ClusterEngine(MLEngine):
    """The ML page's detector line-up, fitted on live windows, scoring the mesh.

    Subclasses MLEngine on purpose: same six families, same feature builder, same
    scoring loop. Holding everything else fixed is what makes the two pages a
    controlled comparison -- generated stream versus deployed cluster -- rather
    than two unrelated dashboards.
    """

    name_ = "cluster"

    def __init__(self, cadence: float = _CADENCE):
        # rate=0: the loop runs flat out and cluster_windows does the pacing, so
        # the engine blocks on collection rather than on a sleep it chose.
        super().__init__(rate=0.0)
        self.cadence = cadence
        self.config = _CONFIG
        self.truth = _Truth(NAMESPACE)
        self.train_n = 0
        self.train_anom = 0
        self.train_faults: dict[str, int] = {}
        self.chaos_ok, self.chaos_why = False, "not checked"

    def set_rate(self, rate: float) -> None:
        """The control is a cadence here, in seconds between instants."""
        self.cadence = max(1.0, min(float(rate), 300.0))

    def _stream(self):
        rec = _AIOPS / _RECORD
        rec.parent.mkdir(parents=True, exist_ok=True)
        return cluster_windows(self.cadence, self.truth, rec)

    def _fit(self, config: str) -> None:
        """Fit on windows collected from the deployed mesh, never on the generator.

        Refuses rather than falls back. A model fitted on generated telemetry and
        pointed at the cluster does not degrade visibly -- it reports everything
        as normal, which looks like a healthy system rather than a detector fitted
        on the wrong distribution.
        """
        self.chaos_ok, self.chaos_why = chaos_reachable(NAMESPACE)
        windows = load_live_windows()
        self.train_n = len(windows)
        self.train_anom = sum(1 for w in windows if w.fault != "normal")
        self.train_faults = {}
        for w in windows:
            self.train_faults[w.fault] = self.train_faults.get(w.fault, 0) + 1

        if self.train_n < _MIN_TRAIN or self.train_anom < _MIN_ANOM:
            raise RuntimeError(
                f"not enough live training data: {self.train_n} windows, "
                f"{self.train_anom} anomalous (need {_MIN_TRAIN}/{_MIN_ANOM}). "
                f"Record more with 'make inject SVC=<svc> FAULT=<fault> DUR=300' "
                f"then 'make live-replay LIVE_LABELS=<labels> LIVE_OUT=<dir>'.")

        windows.sort(key=lambda w: w.ts)
        self._fit_on(windows, config)

    def _fit_on(self, windows: list[Window], config: str) -> None:
        """MLEngine._fit's body, with the sample supplied rather than generated.

        Kept as an override point instead of a parameter on the parent so the two
        engines cannot accidentally share a training set: the whole distinction
        between the pages is which windows the models saw.
        """
        import numpy as np                                    # noqa: F401 (parity)
        from ml.configs import CONFIGS
        from ml.features.build import build_features, split_xy
        from ml.models.detectors import BaselineModel, MultimodalFusion, TemporalModel
        from ml.models.online import OnlineModel
        from .live_detect import _PILLARS, _SEQ_LEN

        with self._lock:
            self._state = {**self._state, "status": "training"}
        X, y, _, feats = split_xy(build_features(windows, CONFIGS[config]))
        y = y.astype(int)

        t0 = time.perf_counter()
        self.fitted = {}
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
            for i in range(len(X)):
                self.online.process_one(X[i], int(y[i]))

        for m in (self.fitted.get("rf"),
                  *(getattr(self.fitted.get("fusion"), "submodels", {}) or {}).values()):
            if m is not None and hasattr(m.model, "n_jobs"):
                m.model.n_jobs = 1

        self.train_ms = round((time.perf_counter() - t0) * 1000, 1)
        self.n_features = int(X.shape[1])
        self.bootstrap_windows = len(windows)
        from collections import deque
        self.seq_buf = deque(X[-_SEQ_LEN:], maxlen=_SEQ_LEN + 1)

    def _score(self, w):
        body, point = super()._score(w)
        faults = self.truth.get()
        body.update({
            "source": "cluster",
            "namespace": NAMESPACE,
            "prom_url": PROM_URL,
            "cadence_s": self.cadence,
            # from the live read, not the fit-time probe
            "chaos_ok": self.truth.ok,
            "chaos_reason": "" if self.truth.ok else self.chaos_why,
            "active_faults": [{"service": s, "fault": f} for s, f in sorted(faults.items())],
            "training": {
                "windows": self.train_n,
                "anomalous": self.train_anom,
                "prevalence": round(self.train_anom / self.train_n, 4) if self.train_n else 0.0,
                "by_fault": self.train_faults,
                "source": "live windows recorded from this cluster",
            },
        })
        return body, point


def cluster_info() -> dict:
    """Status without starting a scoring loop, for the page's header."""
    from .live_detect import get_engine, ml_catalogue

    eng = get_engine("cluster")
    # One read answers both questions, so the reported reachability and the
    # reported fault list cannot disagree with each other; chaos_reachable is
    # consulted only to explain a failure, never to decide one.
    ok, faults = active_faults_checked(NAMESPACE)
    why = "" if ok else chaos_reachable(NAMESPACE)[1]
    windows = load_live_windows()
    anom = sum(1 for w in windows if w.fault != "normal")
    snap = eng.snapshot()
    return {
        "source": "cluster",
        "live": LIVE,
        "namespace": NAMESPACE,
        "prom_url": PROM_URL,
        "config": _CONFIG,
        "cadence_s": getattr(eng, "cadence", _CADENCE),
        "chaos_ok": ok,
        "chaos_reason": why,
        "active_faults": [{"service": s, "fault": f}
                          for s, f in sorted(faults.items())] if ok else [],
        "detectors": ml_catalogue(),
        "training": {"windows": len(windows), "anomalous": anom,
                     "needed": {"windows": _MIN_TRAIN, "anomalous": _MIN_ANOM}},
        "engine": snap.get("status"),
        "error": snap.get("error"),
        "record_path": _RECORD,
    }
