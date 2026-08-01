"""FastAPI backend for the TraceFlix-AIOps React dashboard.

Endpoints
---------
GET  /api/health                      liveness
GET  /api/configs                     observability configs C1..C4
GET  /api/online/stream               SSE: realtime online-vs-offline simulation
GET  /api/experiments                 list runnable offline experiments
GET  /api/offline/run                 SSE: run an experiment, stream stdout lines
GET  /api/results/comparison          offline-vs-online result tables (JSON)
GET  /api/results/rq2                 RQ2 localisation on the propagating generator
GET  /api/results/controls            the RQ3 controls that bound the headline claim
GET  /api/results/figures/{name}      a generated PNG figure
GET  /api/streaming/info              Kafka topics + MELT pillars + LLM detector status
GET  /api/streaming/stream            SSE: live event backbone (topics, MELT, LLM verdicts)
GET  /api/live/ml/info                ML detector catalogue (availability, families)
GET  /api/live/ml/stream              SSE: live ML anomaly detection, all families side by side
GET  /api/live/llm/info               LLM detector status (model, mode, endpoint)
GET  /api/live/llm/stream             SSE: live LLM anomaly detection, window by window

Run:
    cd aiops
    python -m uvicorn webui.backend.app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

# aiops package root on sys.path (this file is aiops/webui/backend/app.py)
AIOPS = Path(__file__).resolve().parents[2]
if str(AIOPS) not in sys.path:
    sys.path.insert(0, str(AIOPS))

# Load aiops/.env BEFORE importing modules that read env at import time:
# streaming.bus reads TF_KAFKA_BOOTSTRAP, ml.models.llm_detector reads OLLAMA_URL/
# OLLAMA_MODEL. This is what makes the Streaming page live without exporting env on
# the command line. Silently skipped if python-dotenv or the file is absent.
try:
    from dotenv import load_dotenv
    load_dotenv(AIOPS / ".env")
except ImportError:
    pass

from ml.configs import CONFIGS                       # noqa: E402
from ml.online_sim import run_simulation             # noqa: E402
from streaming.live_detect import (                  # noqa: E402
    get_engine, llm_info, ml_info)
from streaming.webui_stream import (                 # noqa: E402
    backbone_info, stream_backbone)

DATA = AIOPS / "data"
RESULTS = DATA / "results"
FIGURES = RESULTS / "figures"
FRONTEND_DIST = AIOPS / "webui" / "frontend" / "dist"

# The RQ3 controls each write to their OWN directory, never data/results — see
# data/results/README.md. results/ holds the committed artefacts behind the
# paper's tables, and no control run should be able to overwrite them by
# accident. results_baselines/ (unscaled-only) is superseded by
# results_baselines_scaled/ and is deliberately not read here.
SWEEP_DIR = DATA / "results_drift_sweep"
BASELINES_DIR = DATA / "results_baselines_scaled"
ABLATION_DIR = DATA / "results_ablation"
LIVE_DIR = DATA / "results_live"

app = FastAPI(title="TraceFlix-AIOps API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Experiment registry. One entry per runnable module, mirroring the Makefile
# targets so a run started here is the same run `make <target>` performs.
#
#   group    which section of the Offline Mode picker it belongs to
#   args     argv builder; takes the parameter dict, returns a list of strings
#   params   which controls the page should render ("episodes"/"configs"/"seeds")
#   out      directory the module writes to, relative to aiops/
#   outputs  filenames inside `out`, checked for existence when the run finishes
#   cost     rough wall-clock, so nobody starts an hours-long job by accident
#   env      extra environment the module needs (live replay only)
EXPERIMENTS = {
    # ---- reported campaign ------------------------------------------------
    "rq14": {
        "group": "Reported campaign",
        "label": "RQ1/RQ4 — completeness and model family",
        "module": "ml.experiments.run_experiment",
        "args": lambda p: ["--episodes", str(p["episodes"]), "--out", "data/results"],
        "params": ["episodes"],
        "out": "data/results",
        "outputs": ["rq1_completeness.csv", "rq4_model_family.csv", "summary.json"],
        "cost": "minutes",
        "note": "Also rewrites rq2_localisation.csv — RQ2's withdrawn first attempt. "
                "The reported RQ2 result comes from the separate rq2 run below.",
    },
    "rq2": {
        "group": "Reported campaign",
        "label": "RQ2 — localisation on the propagating generator",
        "module": "ml.experiments.rq2_localisation",
        "args": lambda p: ["--episodes", str(p["episodes"]), "--seeds", p["seeds"],
                           "--out", "data/results"],
        "params": ["episodes", "seeds"],
        "out": "data/results",
        "outputs": ["rq2_localisation_propagating.csv", "rq2_propagating_summary.json"],
        "cost": "minutes",
        "note": "The RQ2 rebuild: errors propagate up the call path, so the origin must "
                "be inferred rather than read off the ranking feature.",
    },
    "rq3": {
        "group": "Reported campaign",
        "label": "RQ3 — static vs periodic vs online detection under drift",
        "module": "ml.experiments.online_vs_offline",
        "args": lambda p: ["--episodes", str(p["episodes"]), "--configs", p["configs"],
                           "--out", "data/results"],
        "params": ["episodes", "configs"],
        "out": "data/results",
        "outputs": ["rq3_online_vs_offline.csv", "rq3_timeline.csv", "rq3_summary.json"],
        "cost": "minutes",
    },
    "cost": {
        "group": "Reported campaign",
        "label": "RQ3 — cost comparison, single seed",
        "module": "ml.experiments.cost_compare",
        "args": lambda p: ["--episodes", str(p["episodes"]), "--configs", p["configs"],
                           "--out", "data/results"],
        "params": ["episodes", "configs"],
        "out": "data/results",
        "outputs": ["rq3_cost.csv", "rq3_cost_summary.json"],
        "cost": "minutes",
        "note": "Seed 42 only. The cost RANGES in the write-up come from cost-seeds-agg.",
    },
    # ---- RQ3 controls ------------------------------------------------------
    "seeds": {
        "group": "RQ3 controls",
        "label": "Controls — always-alarm floor, oracle re-threshold, seed variance",
        "module": "ml.experiments.baselines_and_seeds",
        "args": lambda p: ["--seeds", p["seeds"], "--configs", p["configs"],
                           "--out", "data/results"],
        "params": ["seeds", "configs"],
        "out": "data/results",
        "outputs": ["rq3_baselines.csv", "rq3_seeds.csv", "rq3_seeds_summary.json"],
        "cost": "tens of minutes",
        "note": "Episodes are hardcoded at 320 in this module — the slider does not apply.",
    },
    "baselines": {
        "group": "RQ3 controls",
        "label": "Controls — off-the-shelf streaming learners (raw vs scaled)",
        "module": "ml.experiments.baseline_streaming",
        "args": lambda p: ["--episodes", str(p["episodes"]), "--seed", "42",
                           "--configs", p["configs"], "--out", "data/results_baselines_scaled"],
        "params": ["episodes", "configs"],
        "out": "data/results_baselines_scaled",
        "outputs": ["rq3_streaming_baselines.csv", "rq3_streaming_baselines_summary.json"],
        "cost": "tens of minutes",
        "note": "The scaled arm is the fair contrast — our detector carries its own "
                "normaliser. The raw arm shows what normalisation alone is worth.",
    },
    "ablation": {
        "group": "RQ3 controls",
        "label": "Controls — online detector ablation (champion pool, drift monitor)",
        "module": "ml.experiments.ablate_online",
        "args": lambda p: ["--episodes", str(p["episodes"]), "--seed", "42",
                           "--configs", p["configs"], "--out", "data/results_ablation"],
        "params": ["episodes", "configs"],
        "out": "data/results_ablation",
        "outputs": ["rq3_online_ablation.csv", "rq3_online_ablation_summary.json"],
        "cost": "tens of minutes",
    },
    "sweep": {
        "group": "RQ3 controls",
        "label": "Controls — drift-magnitude sweep (alpha)",
        "module": "ml.experiments.drift_sweep",
        "args": lambda p: ["--episodes", str(p["episodes"]), "--seed", "42",
                           "--configs", p["configs"], "--out", "data/results_drift_sweep"],
        "params": ["episodes", "configs"],
        "out": "data/results_drift_sweep",
        "outputs": ["rq3_drift_sweep.csv", "rq3_drift_sweep_summary.json"],
        "cost": "hours",
        "note": "Regenerates the whole stream once per alpha per config (8 alphas by "
                "default). Checkpoints the CSV as it goes. Two configs is already slow.",
    },
    "cost-seeds-agg": {
        "group": "RQ3 controls",
        "label": "Controls — re-aggregate the five-seed cost ranges",
        "module": "ml.experiments.cost_seeds",
        "args": lambda p: ["--seeds", p["seeds"], "--from-dir", "data/results_cost_seeds",
                           "--out", "data/results"],
        "params": ["seeds"],
        "out": "data/results",
        "outputs": ["rq3_cost_seeds.csv", "rq3_cost_seeds_summary.json"],
        "cost": "seconds",
        "note": "Re-reads the per-seed tables in data/results_cost_seeds/ and fits "
                "nothing. Profiling the seeds from scratch (make cost-seeds) takes "
                "hours and its wall-clock columns will not reproduce anyway.",
    },
    "live-replay": {
        "group": "RQ3 controls",
        "label": "Live — replay a recorded campaign against historical PromQL",
        "module": "ml.experiments.live_replay",
        "args": lambda p: ["--labels", "data/labels_live.csv", "--out", "data/results_live"],
        "params": [],
        "out": "data/results_live",
        "outputs": ["rq1_live_c1.csv", "rq1_live_c1_summary.json"],
        "cost": "minutes",
        "env": {"TF_LIVE": "1", "PROM_URL": os.environ.get("PROM_URL", "http://localhost:9090")},
        "note": "Needs a reachable Prometheus still holding the campaign's retention "
                "window. Without one every window collects zeros and the run is a "
                "silent no-op rather than an error. C1 only — the log, trace and event "
                "collectors take no timestamp.",
    },
    # ---- exports -----------------------------------------------------------
    "excel": {
        "group": "Exports",
        "label": "Export → comparison workbook (Excel)",
        "module": "ml.eval.to_excel",
        "args": lambda p: ["data/results"],
        "params": [],
        "out": "data/results",
        "outputs": ["rq3_offline_vs_online_comparison.xlsx"],
        "cost": "seconds",
    },
    "observability": {
        "group": "Exports",
        "label": "Export → observability MELT data (Excel/CSV)",
        "module": "ml.eval.export_observability",
        "args": lambda p: ["--episodes", str(p["episodes"]), "--out", "data/results"],
        "params": ["episodes"],
        "out": "data/results",
        "outputs": ["observability_data.xlsx", "observability_melt.csv"],
        "cost": "minutes",
    },
    "plots": {
        "group": "Exports",
        "label": "Plots → regenerate figures",
        "module": "ml.eval.plots",
        "args": lambda p: ["data/results"],
        "params": [],
        "out": "data/results",
        "outputs": [],
        "cost": "seconds",
    },
}

# Placeholders the frontend substitutes into the command preview, so the preview
# is generated by the same arg builder that runs the job rather than by a second
# copy of the argument list that can drift out of step with it.
_PREVIEW_PARAMS = {"episodes": "{episodes}", "configs": "{configs}", "seeds": "{seeds}"}


def _preview(spec: dict) -> str:
    return "python -m " + spec["module"] + " " + " ".join(spec["args"](_PREVIEW_PARAMS))


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.on_event("startup")
def _start_live_engines():
    """Bring the always-on detectors up with the server.

    The ML engine fits its frozen models once before it can score anything; doing
    that at start-up means the live pages are ready when someone opens them
    instead of making them watch a progress chip for half a minute."""
    get_engine("ml")
    get_engine("llm")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/configs")
def configs():
    return [{"key": k, "name": c.name, "represents": c.represents}
            for k, c in CONFIGS.items()]


@app.get("/api/experiments")
def experiments():
    """The runnable catalogue, with enough metadata for the page to render the
    right controls and the right warnings without hardcoding a second copy of
    which experiment takes which flag."""
    return [{"key": k, "label": v["label"], "module": v["module"],
             "group": v["group"], "params": v["params"], "out": v["out"],
             "outputs": v["outputs"], "cost": v["cost"],
             "note": v.get("note"), "env": v.get("env"),
             "preview": _preview(v)}
            for k, v in EXPERIMENTS.items()]


@app.get("/api/online/stream")
async def online_stream(request: Request, config: str = "C4", episodes: int = 320,
                        include_periodic: bool = True, max_windows: int = 3000,
                        delay_ms: int = 40):
    if config not in CONFIGS:
        raise HTTPException(400, f"unknown config {config}")

    async def gen():
        loop = asyncio.get_event_loop()
        it = run_simulation(config, episodes=episodes,
                            include_periodic=include_periodic,
                            max_windows=max_windows)
        yield _sse({"type": "start", "config": config})
        while True:
            if await request.is_disconnected():
                break
            snap = await loop.run_in_executor(None, lambda: next(it, None))
            if snap is None:
                yield _sse({"type": "done"})
                break
            yield _sse({"type": "snapshot", **snap.to_dict()})
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/streaming/info")
def streaming_info():
    """Topic catalogue, MELT pillars, and live LLM-detector status (llm/heuristic)."""
    return backbone_info()


@app.get("/api/streaming/stream")
async def streaming_stream(request: Request, episodes: int = 40,
                           max_windows: int = 2000, delay_ms: int = 60):
    async def gen():
        loop = asyncio.get_event_loop()
        it = stream_backbone(episodes=episodes, max_windows=max_windows)
        yield _sse({"type": "start"})
        while True:
            if await request.is_disconnected():
                break
            snap = await loop.run_in_executor(None, lambda: next(it, None))
            if snap is None:
                yield _sse({"type": "done"})
                break
            yield _sse({"type": "snapshot", **snap})
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _engine_sse(request: Request, kind: str) -> StreamingResponse:
    """Attach a viewer to an always-on detection engine.

    The engine scores windows on its own thread whether or not anyone is watching;
    this only forwards each newly published snapshot. Several viewers can attach to
    the same engine and see the same counters, and a page reload rejoins the stream
    already in progress rather than restarting it."""
    eng = get_engine(kind)

    async def gen():
        snap = eng.snapshot()
        yield _sse({"type": "start", "history": eng.history(), **snap})
        last = snap["seq"]
        while True:
            if await request.is_disconnected():
                break
            snap = eng.snapshot()
            if snap["seq"] != last:
                last = snap["seq"]
                yield _sse({"type": "snapshot", **snap})
            else:
                yield ": keepalive\n\n"          # engine paused / still training
            await asyncio.sleep(0.05)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/live/ml/info")
def live_ml_info():
    """Which ML detectors this backend can actually run (torch/xgboost present?)."""
    return ml_info()


@app.get("/api/live/ml/stream")
def live_ml_stream(request: Request):
    return _engine_sse(request, "ml")


@app.get("/api/live/llm/info")
def live_llm_info():
    """LLM detector status — real Ollama model or the marked heuristic fallback."""
    return llm_info()


@app.get("/api/live/llm/stream")
def live_llm_stream(request: Request):
    return _engine_sse(request, "llm")


@app.get("/api/live/{kind}/control")
def live_control(kind: str, rate: float | None = None, paused: bool | None = None,
                 reset: bool = False, config: str | None = None):
    """Adjust a running engine: stream rate (windows/sec), pause, clear stats, or
    (ML only) switch observability configuration.

    Engine state is shared, so these affect every attached viewer -- deliberately:
    there is one live detector, not one per browser tab."""
    if kind not in ("ml", "llm"):
        raise HTTPException(404, f"unknown engine {kind}")
    eng = get_engine(kind)
    if rate is not None:
        eng.set_rate(rate)
    if paused is not None:
        eng.set_paused(paused)
    if config is not None:
        if not hasattr(eng, "set_config"):
            raise HTTPException(400, f"{kind} engine has no configuration to switch")
        if config not in CONFIGS:
            raise HTTPException(400, f"unknown config {config}")
        eng.set_config(config)      # applied on the engine's next loop (refit)
    if reset:
        eng.reset()
    return eng.snapshot()


@app.get("/api/offline/run")
async def offline_run(request: Request, key: str, episodes: int = 200,
                      configs: str = "C1,C2,C3,C4", seeds: str = "42,43,44,45,46"):
    if key not in EXPERIMENTS:
        raise HTTPException(400, f"unknown experiment {key}")
    spec = EXPERIMENTS[key]
    args = spec["args"]({"episodes": episodes, "configs": configs, "seeds": seeds})
    argv = [sys.executable, "-u", "-m", spec["module"], *args]
    out_dir = AIOPS / spec["out"]

    # live_replay needs TF_LIVE=1 and a PROM_URL; without them it silently
    # collects zeros rather than failing, so the environment is part of the
    # experiment definition and not left to whatever the server inherited.
    env = {**os.environ, **spec.get("env", {})}

    async def gen():
        yield _sse({"type": "start",
                    "cmd": "python -m " + spec["module"] + " " + " ".join(args)})
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(AIOPS), env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        while True:
            if await request.is_disconnected():
                proc.terminate()
                break
            line = await proc.stdout.readline()
            if not line:
                break
            yield _sse({"type": "log", "line": line.decode(errors="replace").rstrip()})
        code = await proc.wait()
        outputs = [o for o in spec["outputs"] if (out_dir / o).exists()]
        yield _sse({"type": "done", "code": code, "outputs": outputs,
                    "out": spec["out"]})

    return StreamingResponse(gen(), media_type="text/event-stream")


def _df(name: str, base: Path = RESULTS):
    p = base / name
    return pd.read_csv(p) if p.exists() else None


def _json_file(name: str, base: Path = RESULTS):
    p = base / name
    return json.loads(p.read_text()) if p.exists() else None


def _recs(d):
    """DataFrame -> JSON records, NaN-safe.

    to_json emits `null` for NaN where a plain to_dict would emit a float the
    JSON encoder then rejects. The Gaussian-NB baseline rows carry NaNs, so this
    is load-bearing rather than defensive."""
    return [] if d is None else json.loads(d.round(4).to_json(orient="records"))


@app.get("/api/results/comparison")
def comparison():
    det = _df("rq3_online_vs_offline.csv")
    if det is None:
        raise HTTPException(404, "no results yet — run RQ3 in Offline Mode")
    models = ["offline_static", "offline_periodic", "online_adaptive", "offline_full"]

    fut = det[det.segment.isin(["overall_future", "overall_allregimes"])]
    f1_by_config = (fut.pivot_table(index=["config", "name"], columns="model",
                                    values="f1").reindex(columns=models)
                       .reset_index().round(4))

    reg = det[det.regime >= 0]
    per_regime = (reg.pivot_table(index=["config", "segment"], columns="model",
                                  values="f1")
                     .reindex(columns=[m for m in models if m != "offline_full"])
                     .reset_index().round(4))

    tl = _df("rq3_timeline.csv")
    cost = _df("rq3_cost.csv")
    figs = sorted(p.name for p in FIGURES.glob("*.png")) if FIGURES.exists() else []

    # The always-alarm floor belongs beside the headline bars, not two tabs away:
    # "static collapses to 0.36" only means something against the score of a
    # detector that flags every window and reads nothing.
    base = _df("rq3_baselines.csv")
    floor = round(float(base.always_alarm_f1.mean()), 4) if base is not None else None

    return {
        "f1_by_config": _recs(f1_by_config),
        "per_regime": _recs(per_regime),
        "timeline": _recs(tl),
        "cost": _recs(cost),
        "cost_seeds": _recs(_df("rq3_cost_seeds.csv")),
        "cost_seeds_summary": _json_file("rq3_cost_seeds_summary.json"),
        "summary": _json_file("rq3_summary.json"),
        "floor": floor,
        "figures": figs,
    }


@app.get("/api/results/rq2")
def rq2():
    """RQ2 localisation on the propagating generator — the reported result.

    Seeds are averaged here rather than in the browser: the raw file is
    (backgrounds x seeds x arms x k) and only its mean per arm is ever read.
    `withdrawn_present` reports whether the superseded circular run is still on
    disk, so the page can label the figure that plots it."""
    df = _df("rq2_localisation_propagating.csv")
    if df is None:
        return {"available": False,
                "withdrawn_present": (RESULTS / "rq2_localisation.csv").exists()}

    df = df.copy()
    df["arm"] = df.config + df.graph_aware.map({True: " + graph-aware", False: ""})
    topk = (df.groupby(["background", "arm", "k"], as_index=False)
              .agg(topk_accuracy=("topk_accuracy", "mean"),
                   sd=("topk_accuracy", "std"))
              .round(4))
    return {
        "available": True,
        "topk": _recs(topk),
        "arms": sorted(df.arm.unique().tolist()),
        "backgrounds": sorted(df.background.unique().tolist()),
        "summary": _json_file("rq2_propagating_summary.json"),
        "withdrawn_present": (RESULTS / "rq2_localisation.csv").exists(),
    }


@app.get("/api/results/controls")
def controls():
    """The controls that bound how much of the RQ3 headline may be claimed.

    Each block reports its own availability instead of the endpoint 404-ing, so
    a page can show which controls have been run and which have not — several
    of these cost hours and will legitimately be missing on a fresh checkout."""
    base = _df("rq3_baselines.csv")
    seeds = _df("rq3_seeds.csv")
    ablation = _df("rq3_online_ablation.csv", ABLATION_DIR)
    streaming = _df("rq3_streaming_baselines.csv", BASELINES_DIR)
    sweep = _df("rq3_drift_sweep.csv", SWEEP_DIR)
    live = _df("rq1_live_c1.csv", LIVE_DIR)

    floor_by_config = None if base is None else (
        base.groupby("config", as_index=False)
            .agg(prevalence=("prevalence", "mean"),
                 always_alarm_f1=("always_alarm_f1", "mean"),
                 static_frozen_f1=("static_frozen_f1", "mean"),
                 static_auc=("static_auc", "mean"),
                 static_recalibrated_f1=("static_recalibrated_f1", "mean")))

    return {
        "floor_recalibration": {
            "available": base is not None,
            "rows": _recs(floor_by_config),
            "per_seed": _recs(base),
        },
        "seed_variance": {
            "available": seeds is not None,
            "summary": _json_file("rq3_seeds_summary.json"),
        },
        "ablation": {
            "available": ablation is not None,
            "rows": _recs(ablation),
            "summary": _json_file("rq3_online_ablation_summary.json", ABLATION_DIR),
        },
        "streaming_baselines": {
            "available": streaming is not None,
            "rows": _recs(streaming),
            "summary": _json_file("rq3_streaming_baselines_summary.json", BASELINES_DIR),
        },
        "drift_sweep": {
            "available": sweep is not None,
            "rows": _recs(sweep),
            "summary": _json_file("rq3_drift_sweep_summary.json", SWEEP_DIR),
        },
        "live_pilot": {
            "available": live is not None,
            "summary": _json_file("rq1_live_c1_summary.json", LIVE_DIR),
        },
    }


@app.get("/api/results/figures/{name}")
def figure(name: str):
    p = FIGURES / name
    if not p.exists() or p.suffix != ".png":
        raise HTTPException(404, "figure not found")
    return FileResponse(p)


# serve the built React app if present (production single-origin)
if FRONTEND_DIST.exists():
    from fastapi.staticfiles import StaticFiles

    # SPA fallback: client-side routes (/online, /offline, …) and page refreshes
    # must return index.html, not 404. Real files are served; unknown non-/api
    # paths fall back to the app shell.
    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "not found")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
