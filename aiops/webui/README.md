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
cd aiops/webui/frontend 
npm install 
npm run build
cd ../.. 
python -m uvicorn webui.backend.app:app --port 8000
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

## Streaming page — live Kafka broker + real Ollama LLM

The 🌊 **Live Kafka + LLM** page (nav bar) drives the *in-process* bus and the
*heuristic* LLM fallback by default, so it runs with no infrastructure. To make it
**live** — verdicts produced to a real Kafka broker and scored by the real
Qwen2.5-3B model — start the two containers and configure the backend via **`.env`**
(no command-line env needed):

```powershell
# 1. containers (scale the k8s mesh down first if it's running — RAM)
docker start tf-kafka tf-ollama          # or the `docker run` lines in dissertation/FIGURES.md §6
docker exec tf-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --topic tf.telemetry.windows --if-not-exists
docker exec tf-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --topic tf.anomalies --if-not-exists

# 2. one-time deps + config
cd aiops
python -m pip install kafka-python python-dotenv
copy .env.example .env                   # already points at localhost:9092 / :11434

# 3. launch (the backend loads aiops/.env at startup)
python -m uvicorn webui.backend.app:app --port 8000     # or ./scripts/run_webui.ps1
```

**`aiops/.env`** (created from `.env.example`) holds the live config:

```dotenv
TF_KAFKA_BOOTSTRAP=localhost:9092    # unset/empty -> in-memory bus
OLLAMA_URL=http://localhost:11434    # unreachable -> heuristic fallback
OLLAMA_MODEL=qwen2.5:3b
```

`webui/backend/app.py` calls `load_dotenv(aiops/.env)` **before** importing the
modules that read these at import time. The page's header chips then read
**⚡ Kafka: localhost:9092** and **LLM: qwen2.5:3b (llm)** instead of *in-memory* /
*heuristic*, the topic counters count real messages on `tf.telemetry.windows` /
`tf.anomalies`, and the **live verdict feed** shows each `online_sgd` + `llm` verdict
as it lands on the broker. Everything falls back to the in-process bus / heuristic
automatically if the broker or Ollama is unreachable, so nothing breaks when the
containers are down. `.env` is git-ignored; `.env.example` is the tracked template.
