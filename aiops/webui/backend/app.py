"""FastAPI backend for the TraceFlix-AIOps React dashboard.

Endpoints
---------
GET  /api/health                      liveness
GET  /api/configs                     observability configs C1..C4
GET  /api/online/stream               SSE: realtime online-vs-offline simulation
GET  /api/experiments                 list runnable offline experiments
GET  /api/offline/run                 SSE: run an experiment, stream stdout lines
GET  /api/results/comparison          offline-vs-online result tables (JSON)
GET  /api/results/figures/{name}      a generated PNG figure

Run:
    cd aiops
    python -m uvicorn webui.backend.app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
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

from ml.configs import CONFIGS                       # noqa: E402
from ml.online_sim import run_simulation             # noqa: E402

RESULTS = AIOPS / "data" / "results"
FIGURES = RESULTS / "figures"
FRONTEND_DIST = AIOPS / "webui" / "frontend" / "dist"

app = FastAPI(title="TraceFlix-AIOps API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# experiment registry: key -> (python -m module, arg builder, output files)
EXPERIMENTS = {
    "rq123": {
        "label": "RQ1–RQ3 — completeness, algorithms, RCA",
        "module": "ml.experiments.run_experiment",
        "args": lambda ep, cfgs: ["--episodes", str(ep), "--out", "data/results"],
        "outputs": ["rq1_completeness.csv", "rq2_algorithms.csv", "rq3_rca.csv"],
    },
    "rq4": {
        "label": "RQ4 — offline vs online detection (drift)",
        "module": "ml.experiments.online_vs_offline",
        "args": lambda ep, cfgs: ["--episodes", str(ep), "--configs", cfgs, "--out", "data/results"],
        "outputs": ["rq4_online_vs_offline.csv", "rq4_timeline.csv"],
    },
    "cost": {
        "label": "RQ4 — cost comparison",
        "module": "ml.experiments.cost_compare",
        "args": lambda ep, cfgs: ["--episodes", str(ep), "--configs", cfgs, "--out", "data/results"],
        "outputs": ["rq4_cost.csv"],
    },
    "excel": {
        "label": "Export → comparison workbook (Excel)",
        "module": "ml.eval.to_excel",
        "args": lambda ep, cfgs: ["data/results"],
        "outputs": ["rq4_offline_vs_online_comparison.xlsx"],
    },
    "observability": {
        "label": "Export → observability MELT data (Excel/CSV)",
        "module": "ml.eval.export_observability",
        "args": lambda ep, cfgs: ["--episodes", str(ep), "--out", "data/results"],
        "outputs": ["observability_data.xlsx", "observability_melt.csv"],
    },
    "plots": {
        "label": "Plots → regenerate figures",
        "module": "ml.eval.plots",
        "args": lambda ep, cfgs: ["data/results"],
        "outputs": [],
    },
}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/configs")
def configs():
    return [{"key": k, "name": c.name, "represents": c.represents}
            for k, c in CONFIGS.items()]


@app.get("/api/experiments")
def experiments():
    return [{"key": k, "label": v["label"], "module": v["module"]}
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


@app.get("/api/offline/run")
async def offline_run(request: Request, key: str, episodes: int = 200,
                      configs: str = "C1,C2,C3,C4"):
    if key not in EXPERIMENTS:
        raise HTTPException(400, f"unknown experiment {key}")
    spec = EXPERIMENTS[key]
    argv = [sys.executable, "-u", "-m", spec["module"], *spec["args"](episodes, configs)]

    async def gen():
        yield _sse({"type": "start", "cmd": "python -m " + spec["module"] + " "
                    + " ".join(spec["args"](episodes, configs))})
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(AIOPS), stdout=asyncio.subprocess.PIPE,
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
        outputs = [o for o in spec["outputs"] if (RESULTS / o).exists()]
        yield _sse({"type": "done", "code": code, "outputs": outputs})

    return StreamingResponse(gen(), media_type="text/event-stream")


def _df(name: str):
    p = RESULTS / name
    return pd.read_csv(p) if p.exists() else None


@app.get("/api/results/comparison")
def comparison():
    det = _df("rq4_online_vs_offline.csv")
    if det is None:
        raise HTTPException(404, "no results yet — run RQ4 in Offline Mode")
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

    tl = _df("rq4_timeline.csv")
    cost = _df("rq4_cost.csv")
    figs = sorted(p.name for p in FIGURES.glob("*.png")) if FIGURES.exists() else []

    def recs(d):
        return [] if d is None else json.loads(d.round(4).to_json(orient="records"))

    return {
        "f1_by_config": recs(f1_by_config),
        "per_regime": recs(per_regime),
        "timeline": recs(tl),
        "cost": recs(cost),
        "figures": figs,
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
