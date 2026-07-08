# TraceFlix — Local Kubernetes Deployment (Windows)

One-command bring-up of the full TraceFlix platform on the local Docker Desktop
Kubernetes cluster, in the **`on-demand-observability`** namespace, plus the
offline experiments.

Everything runs through **`run.ps1`** (native PowerShell) and is exposed as
`make` targets. This path deliberately avoids `make bootstrap` / Git-Bash / WSL,
which are fragile on Windows (see [Why not `make bootstrap`](#why-not-make-bootstrap)).

---

## TL;DR

```powershell
make run-platform      # build 9 services -> images -> load into cluster -> deploy -> wait
make run-experiments   # RQ1-RQ4 + drift + cost + plots  -> aiops/data/results/
make run               # both of the above, end to end
make run-down          # tear the namespaces back down

make aiops-up          # (re)apply just the in-cluster AIOps engine + dashboard
make aiops-down        # remove the AIOps engine
make webui             # run the AIOps dashboard locally on :8000
make webui-build       # rebuild the dashboard SPA (aiops/webui/frontend/dist)
```

Then reach Grafana (admin / admin):

```powershell
kubectl port-forward -n on-demand-observability svc/grafana 3000:3000
# http://localhost:3000
```

---

## What gets deployed

Namespace **`on-demand-observability`** (single manifest:
`observability/on-demand-observability.yaml`):

| Component | Image | Notes |
|-----------|-------|-------|
| **9 Java services** | `traceflix/<name>-service:1.0.0` | `imagePullPolicy: Never` — built locally |
| OpenTelemetry Collector | `otel/opentelemetry-collector-contrib:0.110.0` | traces→Tempo, metrics→Prometheus, logs→Loki |
| Tempo | `grafana/tempo:2.5.0` | traces |
| Loki | `grafana/loki:2.9.8` | logs |
| Prometheus | `prom/prometheus:v2.54.1` | scrapes collector; remote-writes to VictoriaMetrics |
| Grafana | `grafana/grafana:11.1.4` | admin / admin, datasources pre-provisioned |
| load-generator + mesh-load-generator | `curlimages/curl:8.7.1` | drive traffic so telemetry is non-empty |
| **AIOps engine + API** (`:8000`) | `ghcr.io/ducanhptitb19cn028/traceflix-aiops:gpu` | reads the 9 services' live telemetry (`TF_LIVE=1`); pulled from GHCR (no local build), GPU request dropped for Docker Desktop. See [AIOps](#aiops-engine) |
| AIOps dashboard SPA (initContainer) | `traceflix/aiops-dist:1.0.0` | tiny busybox+`dist` image, built & node-loaded locally; injects the React UI into the aiops pod so it serves the dashboard at `/` |

The **9 services** are:
`movie` · `actor` · `review` · `catalog` · `auth` · `user` · `search` ·
`recommendation` · `gateway`.

Also applied: `aiops/k8s/load-generator-fixed.yaml`,
`aiops/k8s/victoriametrics.yaml` (VictoriaMetrics lives in the `devops-agent`
namespace and is the long-term metrics store Prometheus remote-writes to), and
`aiops/k8s/aiops.yaml` (the AIOps engine + dashboard — see [AIOps engine](#aiops-engine)).

---

## Prerequisites

| Tool | Checked by `run.ps1` | Notes |
|------|----------------------|-------|
| Docker Desktop + **Kubernetes enabled** | cluster reachability | Settings → Kubernetes → Enable, wait for green |
| `kubectl` | yes | context `docker-desktop` expected (warns otherwise) |
| `mvn` (Maven) | yes (unless `-SkipBuild`) | uses `JAVA_HOME` |
| JDK 21 via `JAVA_HOME` | yes | must point at a real JDK (`$env:JAVA_HOME\bin\java.exe`) |
| `python` | yes | only strictly needed for experiments |
| `helm` | only with `-Chaos` | for Chaos Mesh |

Run from **PowerShell** (not Git Bash / WSL).

---

## The `run.ps1` pipeline

`make run-platform` calls `run.ps1 -SkipExperiments`. Phases:

1. **Preflight** — verify `docker`/`kubectl`/`mvn`/`python`, validate `JAVA_HOME`,
   and confirm the cluster is reachable (retries 6× to ride out Docker Desktop
   API blips).
2. **Build** — `mvn -q clean package -DskipTests` over the `services/` reactor → 9 jars.
3. **Images** — `docker build` → `traceflix/<name>-service:1.0.0` for all 9 **plus**
   `traceflix/aiops-dist:1.0.0` (the dashboard SPA sidecar), **then load each image
   into every kind node's containerd store** (see below).
4. **Deploy** — `kubectl apply` the observability manifest + load-gen + VictoriaMetrics
   + the AIOps engine (`aiops/k8s/aiops.yaml`).
5. **Wait** — `kubectl wait --for=condition=Available` on all deployments.
6. **Experiments** (skipped by `run-platform`) — pip install + RQ runs + plots.

### Flags (`RUN_ARGS`)

```powershell
make run RUN_ARGS="-SkipBuild"                 # redeploy without rebuilding
make run RUN_ARGS="-SkipPip"                   # skip pip install in experiments
make run RUN_ARGS="-Chaos"                     # also install Chaos Mesh (needs helm)
make run RUN_ARGS="-Episodes 60 -DriftEpisodes 120"   # faster experiment run
```

Or call the script directly: `.\run.ps1 -SkipExperiments`, `.\run.ps1 -Teardown`, etc.

---

## The one non-obvious gotcha: multi-node kind cluster

Docker Desktop's Kubernetes here is a **multi-node kind cluster**
(`desktop-control-plane` + `desktop-worker` + `desktop-worker2`), **not** a single
`docker-desktop` node. Each node is a `kindest/node` **container with its own
containerd image store**, isolated from the host Docker daemon.

Consequence: an image built with `docker build` is **invisible to the kubelet**, so
every `imagePullPolicy: Never` pod fails with **`ErrImageNeverPull`**.

`run.ps1` handles this automatically after building — it loads each image into every
node's store:

```powershell
# piped through cmd, NOT PowerShell (PowerShell's pipeline corrupts binary data)
cmd /c "docker save traceflix/<svc>:1.0.0 | docker exec -i <node> ctr -n k8s.io images import -"
```

If the cluster is ever **recreated** (nodes get a fresh AGE), the stores are wiped —
just re-run `make run-platform` and the load step repopulates them.

---

## AIOps engine

`aiops/k8s/aiops.yaml` deploys the AIOps engine (`aiops` Deployment + Service +
ServiceAccount/RBAC) into `on-demand-observability`. It reads the running stack's
live telemetry (`PROM_URL`, `VM_URL` cross-namespace, `LOKI_URL`, `TEMPO_URL`) with
`TF_LIVE=1` and lists k8s events for root-cause context. The image is **pulled from
GHCR** (public), so it needs no local build; the `nvidia.com/gpu` request is dropped
(Docker Desktop has no GPU — torch runs on CPU).

Verify:
```powershell
kubectl get pods -n on-demand-observability -l app=aiops
kubectl port-forward -n on-demand-observability svc/aiops 8000:8000
# http://localhost:8000/api/health   -> {"status":"ok"}
```

### Dashboard UI — two ways to get it

The published `:gpu` image was built **without** the React SPA (`webui/frontend/dist`),
so out of the box `GET /` on the in-cluster pod would 404. Both of these are wired up:

**A. Local dashboard (`make webui`).** Runs the FastAPI backend on your machine; it
serves the locally-committed `dist` and works immediately:

```powershell
cd aiops
python -m uvicorn webui.backend.app:app --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000   (dashboard + /api/*)
```
Synthetic by default. To drive it from the live cluster, port-forward the backends
and set `TF_LIVE=1 PROM_URL/LOKI_URL/TEMPO_URL/VM_URL` to the forwarded ports.

**B. In-cluster dashboard (default).** `aiops/k8s/aiops.yaml` injects the SPA into the
pod via an **initContainer** using a tiny sidecar image
(`traceflix/aiops-dist:1.0.0`, built from `aiops/k8s/aiops-dist.Dockerfile`) — so the
pod serves the dashboard at `/` **without** rebuilding the multi-GB CUDA image.
`run.ps1` builds and node-loads that sidecar image automatically. Refresh the SPA with
`make webui-build` (rebuilds `dist`), then re-run `make run-platform`.

> For a *real* (non-local) registry deploy, bake the SPA into the image directly —
> `make webui-build` then
> `docker build -f rancher/aiops.Dockerfile -t <registry>/traceflix-aiops:gpu .` — and
> drop the initContainer.

## Access

```powershell
kubectl get pods -n on-demand-observability -w                              # watch
kubectl port-forward -n on-demand-observability svc/grafana 3000:3000       # admin/admin
kubectl port-forward -n on-demand-observability svc/prometheus 9090:9090
kubectl port-forward -n on-demand-observability svc/tempo 3200:3200
kubectl port-forward -n on-demand-observability svc/gateway-service 8080:8080
kubectl port-forward -n on-demand-observability svc/aiops 8000:8000         # AIOps API
```

Experiment results land in `aiops/data/results/` (figures in `.../figures/`).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ErrImageNeverPull` on `traceflix/*` pods | Node containerd store doesn't have the image (cluster recreated, or images built without loading) | `make run-platform` (auto-loads), or manually `docker save … \| docker exec -i <node> ctr -n k8s.io images import -` via **cmd** |
| `kubectl cannot reach a cluster` | Docker Desktop K8s down or mid-restart | Enable/await Kubernetes (green). `run.ps1` retries 6×; if it flaps hard, `wsl --shutdown` then reopen Docker Desktop |
| `JAVA_HOME ... not defined correctly` (via `make bootstrap`) | `make` ran the script under **WSL bash** (`C:\Windows\System32\bash.exe`), which can't see the Windows JDK | Use `make run-platform` (PowerShell path) instead |
| `grpc: the client connection is closing` during `docker build` | Docker Desktop engine restarted mid-build (flapping) | Settle Docker Desktop, re-run |
| Services pods still on old code after rebuild | Same `:1.0.0` tag → `kubectl apply` sees no change, no restart | `kubectl rollout restart -n on-demand-observability deploy/<svc>` |
| Experiments fail on missing `torch`/`xgboost` | Python 3.14 lacks wheels for some ML deps | Use a Python 3.11/3.12 venv |
| `aiops` pod `Init:ErrImageNeverPull` on `traceflix/aiops-dist` | SPA sidecar image not built/loaded into the nodes | `make run-platform` (builds + node-loads it), then `make aiops-up` |
| AIOps dashboard `GET /` → 404, but `/api/health` is 200 | SPA not injected (initContainer didn't run, or wrong dist path) | confirm the `spa` initContainer ran and `traceflix/aiops-dist:1.0.0` is loaded; the readiness probe uses `/api/health`, not `/` |
| `aiops` pod stuck `0/1 Running` | readiness probe path wrong, or backends unreachable | probe must be `/api/health`; check `PROM_URL`/`VM_URL`/`LOKI_URL`/`TEMPO_URL` resolve from the pod |
| AIOps pod `Pending` (unschedulable) | a `nvidia.com/gpu` request on a GPU-less cluster | the local manifest drops the GPU request — don't re-add it for Docker Desktop |

---

## Why not `make bootstrap`

`make bootstrap` runs `scripts/bootstrap.sh` through whatever `bash` `make` finds on
the Windows PATH — which is `C:\Windows\System32\bash.exe`, the **WSL launcher**. WSL
can't see the Windows JDK/Maven/`JAVA_HOME`, so the Maven build dies immediately. The
`run.ps1` path sidesteps this entirely by staying in native PowerShell and calling the
Windows tools directly. (The `Makefile` also pins Git Bash by full path for the few
`.sh` targets, but `run-platform` is the supported Windows entry point.)

---

## Teardown

```powershell
make run-down          # deletes on-demand-observability + devops-agent (+ chaos-mesh if helm)
```
