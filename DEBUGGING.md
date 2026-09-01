# TraceFlix — Debugging Guide

How to find a fault in the platform, by layer. Complements
[`DEPLOYMENT.md`](DEPLOYMENT.md) (which covers bring-up and has a
symptom→cause→fix table for the recurring deployment failures) and
[`DEMO.md`](DEMO.md) (the guided tour).

> **`make` is blocked on the Windows dev machine.** Smart App Control refuses
> Chocolatey's unsigned `make.exe`, so every `make <target>` below is written as
> `.\mk.ps1 <target>` — the native PowerShell stand-in that runs the identical
> command. On Linux/WSL the `make` form works.

---

## 0. Start here: which layer is broken?

```powershell
.\mk.ps1 status                                    # pods + nodes
kubectl get events -n on-demand-observability --sort-by=.lastTimestamp | Select-Object -Last 25
```

The stack has five failure surfaces and they fail differently. Identify which
one before digging:

| Layer | Symptom shape | First command |
|---|---|---|
| Kubernetes / images | `ErrImageNeverPull`, `Pending`, `Init:*`, restarts | `kubectl describe pod <p> -n on-demand-observability` |
| The 9 Java services | 5xx from gateway, empty telemetry | `kubectl logs deploy/<svc>-service -n on-demand-observability --tail=100` |
| Telemetry pipeline | Grafana panels empty, AIOps sees nothing | otel-collector → Prometheus/Loki/Tempo, see §3 |
| AIOps engine (Python) | `/api/*` 500s, blank dashboard, stalled SSE | `kubectl logs deploy/aiops -n on-demand-observability -f` |
| Experiments (offline) | tracebacks, missing CSVs | run the module directly, see §5 |

A healthy namespace is 18 pods `Running` (9 services + otel-collector + Tempo +
Loki + Prometheus + Grafana + 2 load generators + aiops + ollama), plus the
completed `ollama-pull` job. The frontend is **not** part of that set — it is
brought up separately (§7).

---

## 1. Kubernetes layer

```powershell
kubectl describe pod <pod> -n on-demand-observability     # Events at the bottom = the real cause
kubectl logs <pod> -n on-demand-observability --previous  # after a restart / CrashLoop
```

[`DEPLOYMENT.md`](DEPLOYMENT.md#troubleshooting) already tabulates the recurring
ones — `ErrImageNeverPull`, the WSL `JAVA_HOME` trap, a GPU request on a
GPU-less cluster. Read that before improvising.

**The stale-image trap** is the one that bites most. Every local image is
`:1.0.0` with `imagePullPolicy: Never`, so `kubectl apply` after a rebuild is a
**no-op** — the spec is unchanged, nothing restarts, and you debug old code
while believing you shipped new code. Always follow a rebuild with:

```powershell
kubectl rollout restart deploy/<name> -n on-demand-observability
kubectl rollout status  deploy/<name> -n on-demand-observability --timeout=180s
```

---

## 2. Java services

```powershell
kubectl port-forward -n on-demand-observability svc/gateway-service 8080:8080
curl http://localhost:8080/actuator/health
kubectl logs deploy/catalog-service -n on-demand-observability --tail=100 -f
```

To test service→service reachability **the way the app sees it**, curl from
inside a pod using the ClusterIP DNS name, not from your host:

```powershell
kubectl exec -it deploy/catalog-service -n on-demand-observability -- sh
# inside: wget -qO- http://movie-service:8080/actuator/health
```

A host-side `port-forward` proves only that the Service routes; it says nothing
about whether the mesh's own DNS and network policy let one service reach
another.

---

## 3. Telemetry pipeline — debug in the direction the data flows

```
9 services --OTLP--> otel-collector --> Tempo (traces)
                                    --> Prometheus (metrics) --remote_write--> VictoriaMetrics
                                    --> Loki (logs)
                                            \--> Grafana + AIOps engine
```

Bisect at each hop rather than staring at an empty Grafana panel:

```powershell
kubectl logs deploy/otel-collector -n on-demand-observability --tail=50   # export errors surface here
kubectl port-forward -n on-demand-observability svc/prometheus 9090:9090  # run the PromQL by hand
kubectl port-forward -n on-demand-observability svc/grafana    3000:3000  # admin / admin
kubectl port-forward -n on-demand-observability svc/tempo      3200:3200
kubectl port-forward -n on-demand-observability svc/loki        3100:3100
```

- Prometheus **has** the series but AIOps reports nothing → the fault is in the
  collector query (§4), not the pipeline.
- Prometheus is empty too → check the load generators are actually driving
  traffic. No traffic means no telemetry, and every downstream component then
  looks broken while being perfectly healthy.

---

## 4. AIOps engine

### Edit-and-see loop

The pod overlays the working-tree `aiops/` via the `traceflix/aiops-src:1.0.0`
initContainer (`aiops/k8s/aiops.yaml`), so local Python edits reach the cluster
in one step:

```powershell
.\mk.ps1 aiops-refresh          # rebuild the src image + rollout restart + wait
kubectl logs deploy/aiops -n on-demand-observability -f
```

Do **not** debug by editing files inside the pod — the overlay is an `emptyDir`
and the next restart wipes it.

### API surface

Defined in `aiops/webui/backend/app.py`:

```powershell
kubectl port-forward -n on-demand-observability svc/aiops 8000:8000
curl http://localhost:8000/api/health          # the readiness probe uses this, NOT /
curl http://localhost:8000/api/live/ml/info
curl http://localhost:8000/api/results/comparison
```

**Key distinction when the dashboard misbehaves:** `/api/health` returning 200
while `/` returns 404 means the SPA sidecar did not inject — a *packaging*
problem (`traceflix/aiops-dist:1.0.0` missing or built without
`aiops/webui/frontend/dist`), not an engine problem. Rebuild with
`.\mk.ps1 webui-build`.

### Live-mode collectors

Live mode depends on five env vars resolving in-cluster (`aiops/k8s/aiops.yaml`):
`TF_LIVE=1`, `PROM_URL`, `VM_URL`, `LOKI_URL`, `TEMPO_URL`. When live windows
come back empty, verify reachability **from inside the pod**:

```powershell
kubectl exec -it deploy/aiops -n on-demand-observability -- sh -c "wget -qO- http://prometheus:9090/-/healthy"
kubectl exec -it deploy/aiops -n on-demand-observability -- env | Select-String "TF_|_URL"
```

---

## 5. Experiments / ML — debug on the host, not in the cluster

The experiment harness is pure Python and defaults to the `_synth` telemetry
backend, so it needs no cluster at all. Run the module directly for a real
traceback, and shrink the episode count so the loop takes seconds:

```powershell
cd aiops
python -m ml.experiments.run_experiment --episodes 5 --seed 42 --out data/scratch
python -m pytest tests/ -q
```

or from the repo root: `.\mk.ps1 test-aiops`.

`.\mk.ps1 quick` runs the whole campaign at 60/120 episodes — use it to
reproduce a failure fast before committing to the full 200/320.

**Live-vs-synthetic discrepancies** live in `aiops/collectors/telemetry.py`. The
two backends share one `Window` schema, so diff the windows the two paths
produce before suspecting the detector.

Missing wheels (`torch`, `xgboost`) mean the interpreter is too new — use a
Python 3.11/3.12 venv.

---

## 6. LLM path (Ollama, in-cluster)

Ollama runs as an in-cluster Deployment (`aiops/k8s/ollama.yaml`); there is no
host install to check.

```powershell
.\mk.ps1 ollama-forward         # then: curl http://localhost:11434/api/tags
.\mk.ps1 ollama-logs            # follows job/ollama-pull (the ~2 GB qwen2.5:3b pull)
kubectl describe pod -l app=ollama -n on-demand-observability
```

If LLM calls hang or the pod shows restarts, suspect node memory first — the
model needs ~3Gi free. A restarted Ollama pod has an empty model cache until the
pull job replays.

---

## 7. Frontend

The frontend is not deployed by `run-platform`; bring it up explicitly:

```powershell
.\mk.ps1 frontend-image         # docker build + load into the node stores
.\mk.ps1 frontend-up            # kubectl apply services/frontend/k8s/frontend.yaml
.\mk.ps1 frontend-forward       # local :5173
```

"The frontend is broken" is, more often than not, "the frontend was never
brought up" — check `kubectl get deploy -n on-demand-observability` for a
`frontend` entry before debugging its code.

---

## Quick reference

```powershell
.\mk.ps1 status                 # pod overview
.\mk.ps1 aiops-refresh          # ship local aiops/ edits into the cluster
.\mk.ps1 test-aiops             # Python test suite
.\mk.ps1 quick                  # fast experiment campaign (60/120 episodes)
.\mk.ps1 inject -Svc catalog-service -Fault cpu_saturation -Dur 120
.\mk.ps1 k8s-clean              # ordered teardown (chaos CRs first — finalizers)
```

`NS = on-demand-observability` throughout.
