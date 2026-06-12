# TraceFlix-AIOps Dashboard (React + FastAPI)

A React single-page app with a FastAPI backend, visualising the online-vs-offline
anomaly-detection story. Replaces the earlier Streamlit prototype.

```
webui/
  backend/app.py        FastAPI: SSE streams (online sim, offline runs) + result JSON
  frontend/             Vite + React + Recharts SPA (nav: Online / Offline / Comparison)
```

## Run (one command)

```bash
cd aiops
bash scripts/run_webui.sh          # builds the SPA, serves everything on http://localhost:8000
bash scripts/run_webui.sh --dev    # hot-reload dev: backend :8000 + Vite :5173
PORT=8080 bash scripts/run_webui.sh # override the backend port
```

The launcher resolves Python, checks node/npm, installs backend + frontend deps
on first run, then builds and serves. The manual steps below are equivalent.

### Windows (PowerShell)

Use the native PowerShell launcher — **no bash needed**:

```powershell
cd aiops
./scripts/run_webui.ps1                  # build SPA, serve on http://localhost:8000
./scripts/run_webui.ps1 -Dev             # hot-reload dev: backend :8000 + Vite :5173
$env:PORT=8080; ./scripts/run_webui.ps1  # override the backend port
```

> **Why not `bash scripts/run_webui.sh`?** In PowerShell, plain `bash` usually
> resolves to **WSL** (`C:\Windows\System32\bash.exe`), a separate Linux
> environment that does *not* see your Windows Node/Python — you'll get
> `ERROR: node not found on PATH`. Use `run_webui.ps1` above, or invoke
> **Git Bash** explicitly:
>
> ```powershell
> & "C:\Program Files\Git\bin\bash.exe" scripts/run_webui.sh
> ```

## Run (development — two processes, hot reload)

```bash
# 1) backend  (from aiops/)
cd aiops
pip install -r requirements.txt
python -m uvicorn webui.backend.app:app --reload --port 8000

# 2) frontend (from aiops/webui/frontend/)
cd webui/frontend
npm install
npm run dev            # http://localhost:5173  (proxies /api -> :8000)
```

Open **http://localhost:5173**.

## Run (production — single process)

Build the SPA once; the backend then serves it at `/` (same origin, no proxy):

```bash
cd aiops/webui/frontend && npm install && npm run build
cd ../.. && python -m uvicorn webui.backend.app:app --port 8000
```

Open **http://localhost:8000**.

## Pages (top nav bar)

| Page | What it does |
|------|--------------|
| 🟢 **Online Mode** | Opens an SSE stream (`/api/online/stream`) that drives `ml/online_sim.py` (the `OnlineModel` over the drifting stream) window-by-window. Live: rolling-F1 chart (online vs static vs periodic), KPI cards, champion η₀/α, and a pipeline panel showing online's continuous `partial_fit` vs periodic's blocking batch-refit flashes. |
| 🔵 **Offline Mode** | Sends a command (`/api/offline/run`) that subprocesses an `ml.experiments`/`ml.eval` module and streams its stdout live into a terminal view; lists produced outputs on completion. |
| 📊 **Result Comparison** | Reads `/api/results/comparison`; tabs for F1-by-config (table + bar chart), rolling-F1 timeline, per-regime, cost, and the generated PNG figures. |

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | liveness |
| GET | `/api/configs` | observability configs C1–C4 |
| GET | `/api/experiments` | runnable offline experiments |
| GET | `/api/online/stream` | **SSE** realtime simulation snapshots |
| GET | `/api/offline/run` | **SSE** experiment run, streamed stdout |
| GET | `/api/results/comparison` | comparison tables (JSON) |
| GET | `/api/results/figures/{name}` | a generated PNG |

The Online Mode runs in-process (no Kubernetes needed); the drift stream mirrors
the live `Window` schema.
