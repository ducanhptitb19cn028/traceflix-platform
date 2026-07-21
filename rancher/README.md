# TraceFlix on a Rancher GPU Kubernetes cluster — end-to-end demo

A complete walkthrough: **from `git clone` to a fully running, demonstrable
deployment** of the whole platform on a Rancher-managed cluster with GPU node(s) —
the nine-service mesh, MELT observability, the Kafka backbone, the local LLM
(Qwen2.5-3B), and the AIOps engine + dashboard.

> **Additive only.** Everything in `rancher/` is new; no file in `aiops/`,
> `services/`, `observability/`, `deploy/` or `paper/` is modified. This is the
> Kubernetes equivalent of the `deploy/virtfusion/` Compose overlay — one cluster
> with GPU instead of four VMs.

### Two ways to deploy

| Path | How images are built | How the chart is installed | Use when |
|------|----------------------|----------------------------|----------|
| **A — Manual Helm** (Steps 0–6) | `rancher/build-push.*` from your laptop | `helm install` (or Rancher Apps → Charts) | one-off / first try |
| **B — GitOps with Fleet** ([jump](#deploy-with-rancher-fleet-gitops)) | GitHub Actions → GHCR (`.github/workflows/images.yml`) | Rancher Fleet watches `rancher/` + `fleet.yaml` | every `git push` auto-deploys |

Both deploy **pre-built images** — neither Rancher nor Fleet compiles your source.
Path B is the recommended "point Rancher at a git repo" workflow.

**What you'll have at the end:** real distributed traces across nine services in
Grafana, the AIOps dashboard live on an ingress URL (Online / Offline / **Streaming**
/ Comparison), the RQ1–RQ4 experiments reproducible inside the cluster, and
fault-injection driving live anomaly detection.

| Component | Workload | GPU |
|-----------|----------|-----|
| Nine microservices (`gateway`→…→`catalog`) | Deployments + Services, OTel java-agent injected | — |
| OTel Collector → Prometheus · VictoriaMetrics · Loki · Tempo · Grafana | Deployments + PVCs + Services | — |
| Apache Kafka (KRaft, single node) | Deployment + PVC + Service | — |
| Ollama (Qwen2.5-3B) | Deployment + PVC + Service + model-pull Job | **GPU** |
| AIOps engine + dashboard | Deployment + Service + Ingress + RBAC | **GPU** |
| Load generator | Deployment | — |

```
                 Ingress (nginx)
        ┌──────────────┴───────────────┐
   traceflix.<domain>            grafana.<domain>
        │                              │
   ┌────▼─────┐ GPU              ┌─────▼────┐
   │  aiops   │                  │  grafana │
   │dashboard │                  └─────┬────┘
   └────┬─────┘                        │ datasources
        │ PROM/LOKI/TEMPO/VM/Kafka/Ollama
   ┌────▼─────────────────────────────────────────────┐
   │ otel-collector ◄── 9 services ◄── load-generator  │
   │   ├ metrics ─► Prometheus ─► VictoriaMetrics       │
   │   ├ logs ────► Loki                                │
   │   └ traces ──► Tempo                               │
   │ Kafka (backbone)      Ollama (Qwen2.5-3B, GPU)     │
   └───────────────────────────────────────────────────┘
```

---

## Step 0 — Clone the repository

On a workstation that has `docker`, `kubectl` (pointed at your Rancher cluster),
`helm` 3+, plus `mvn` and JDK 21:

```bash
git clone https://github.com/ducanhptitb19cn028/traceflix-platform.git
cd traceflix-platform
```

All commands below are run from this repo root.

---

## Step 1 — Check the cluster prerequisites

- **GPU node(s)** with the **NVIDIA GPU Operator** installed (Rancher → Apps →
  *nvidia gpu-operator*). Confirm GPUs are advertised:
  ```bash
  kubectl get nodes -o json | jq '.items[].status.allocatable["nvidia.com/gpu"]'
  ```
- An **ingress controller** (ingress-nginx assumed; otherwise set `ingress.className`).
- A **default StorageClass** (Longhorn / local-path) — or set `storage.className`.
- A **container registry** the cluster can pull from.

---

## Step 2 — Build and push the images

> **Prefer CI?** `.github/workflows/images.yml` already builds all ten images and
> pushes them to **GHCR** (`ghcr.io/<owner>/...`) on every push to `main`. If you use
> that (and Path B does), skip this step — just make the packages public, or set up a
> pull secret ([below](#private-registry--ghcr-pull-secret)). The manual script below
> is for building from your laptop.

A helper script builds the nine services **and** the AIOps image, then pushes them.
Pass your registry (e.g. `ghcr.io/ducanhptitb19cn028`):

**Windows (PowerShell):**

```powershell
./rancher/build-push.ps1 -Registry registry.example.com/traceflix
# if script execution is blocked:
#   powershell -ExecutionPolicy Bypass -File rancher/build-push.ps1 -Registry registry.example.com/traceflix
```

**Linux / macOS / Git Bash:**

```bash
./rancher/build-push.sh registry.example.com/traceflix
```

Useful flags: `-SkipBuild` / `SKIP_BUILD=1` (reuse jars), `-ServicesOnly` /
`SERVICES_ONLY=1`, `-NoPush` / `NO_PUSH=1`.

<details>
<summary>…or run the commands manually</summary>

**PowerShell** (note `mvn -f services/pom.xml` builds all nine modules — no `cd`):

```powershell
$REG = "registry.example.com/traceflix"
mvn -f services/pom.xml clean package -DskipTests
foreach ($s in "movie","actor","review","gateway","user","search","recommendation","auth","catalog") {
  docker build -t "$REG/$s-service:1.0.0" "services/$s-service"
  docker push  "$REG/$s-service:1.0.0"
}
docker build -f rancher/aiops.Dockerfile -t "$REG/traceflix-aiops:gpu" .
docker push "$REG/traceflix-aiops:gpu"
```

**Bash:**

```bash
REG=registry.example.com/traceflix
( cd services && mvn clean package -DskipTests )
for s in movie actor review gateway user search recommendation auth catalog; do
  docker build -t "$REG/$s-service:1.0.0" "services/$s-service" && docker push "$REG/$s-service:1.0.0"
done
docker build -f rancher/aiops.Dockerfile -t "$REG/traceflix-aiops:gpu" .
docker push "$REG/traceflix-aiops:gpu"
```

</details>

<a id="private-registry--ghcr-pull-secret"></a>
### Private registry / GHCR pull secret

Public images need nothing. For **private GHCR packages**, give the cluster a pull
secret — the token must **never** be committed to git. Two options:

**A) Create it once with `kubectl`** (recommended — token stays out of git), then set
`image.pullSecrets`:

```bash
kubectl create namespace traceflix
kubectl -n traceflix create secret docker-registry ghcr-cred \
  --docker-server=ghcr.io \
  --docker-username=ducanhptitb19cn028 \
  --docker-password=<GitHub PAT (classic) with read:packages>
# then: --set-json 'image.pullSecrets=[{"name":"ghcr-cred"}]'
```

**B) Let the chart create it** — `templates/image-pull-secret.yaml` builds the secret
when `imagePullSecret.create=true`; supply the credentials at install time only
(`--set imagePullSecret.username=… --set imagePullSecret.password=…`), never in a
committed file. See `rancher/extras/ghcr-pull-secret.example.yaml` for the object shape.

> The easiest demo path is to make the packages **public**: GitHub → your profile →
> **Packages** → each package → **Package settings → Change visibility → Public**.
> Then no pull secret is needed.

---

## Step 3 — Find your GPU node selector / toleration

GPU nodes are usually labelled and tainted by the operator:

```bash
kubectl get nodes -L nvidia.com/gpu.present
kubectl describe node <gpu-node> | grep -i taint
```

Typical values (adjust to your cluster): nodeSelector
`nvidia.com/gpu.present: "true"`, toleration
`key=nvidia.com/gpu, operator=Exists, effect=NoSchedule`, and some setups need
`runtimeClassName: nvidia`.

---

## Step 4 — Install with Helm

```bash
helm install traceflix ./rancher -n traceflix --create-namespace \
  --set image.registry=$REG \
  --set storage.className=longhorn \
  --set grafana.adminPassword='choose-a-password' \
  --set ingress.dashboardHost=traceflix.example.com \
  --set ingress.grafanaHost=grafana.example.com \
  --set ollama.model=qwen2.5:3b \
  --set-json 'gpu.nodeSelector={"nvidia.com/gpu.present":"true"}' \
  --set-json 'gpu.tolerations=[{"key":"nvidia.com/gpu","operator":"Exists","effect":"NoSchedule"}]'
```

Prefer a file? `cp rancher/values.yaml my-values.yaml`, edit, then
`helm install traceflix ./rancher -n traceflix -f my-values.yaml`. Rancher's
**Apps → Charts → Create from local chart** works too.

> The dashboard runs **synthetic** experiments out of the box (`aiops.live=false`),
> so it works before any live telemetry flows; the model is pulled by a one-shot
> Job after install.

---

## Deploy with Rancher Fleet (GitOps)

The "point Rancher at a git repo and it deploys" path. Rancher **Fleet**
(Continuous Delivery) watches your repo and applies the Helm chart in `rancher/`;
`rancher/fleet.yaml` holds the value overrides. Fleet deploys images — it does **not**
build them — so GitHub Actions builds and pushes to GHCR first.

```
git push ─► GitHub Actions builds 10 images ─► ghcr.io/ducanhptitb19cn028/…
git push ─► Fleet sees rancher/fleet.yaml ──► helm install/upgrade ─► pods pull from GHCR
```

1. **Build the images via CI.** Push to `main`; `.github/workflows/images.yml` builds
   the nine services + the aiops image and pushes them to GHCR. Confirm under GitHub →
   **Actions**, then GitHub → **Packages**. Make them **public** or set up a pull
   secret ([above](#private-registry--ghcr-pull-secret)).

2. **Set cluster-specific values in `rancher/fleet.yaml`** — `image.registry`
   (`ghcr.io/ducanhptitb19cn028`), `storage.className`, `grafana.adminPassword`, the
   ingress hosts, and the GPU `nodeSelector`/`tolerations` (Step 3). Commit and push.

3. **Register the repo in Rancher** → your cluster → **☰ → Continuous Delivery →
   Git Repos → Create**:
   - **Repository URL:** `https://github.com/ducanhptitb19cn028/traceflix-platform.git`
   - **Branch:** `main`  · **Path:** `rancher`
   - **Target:** the GPU cluster / workspace
   - Private repo? Attach an SSH-key or token **Auth** secret here.

4. Fleet clones, finds the chart + `fleet.yaml`, and installs. The **Continuous
   Delivery → Git Repos** view shows the bundle reach **Active**. From then on every
   `git push` auto-deploys. Continue at **Step 5** to verify.

---

## Step 5 — Verify the rollout

```bash
kubectl -n traceflix get pods
kubectl -n traceflix rollout status deploy/aiops
kubectl -n traceflix logs job/ollama-pull          # → model pulled
```

All pods should reach `Running`/`Completed`. The load generator immediately starts
driving `gateway/api/browse`, so telemetry begins flowing within a minute.

---

## Step 6 — See the full project running (the demo)

Use your ingress hosts, or port-forward if you skipped ingress:

```bash
kubectl -n traceflix port-forward svc/aiops 8000:8000      # http://localhost:8000
kubectl -n traceflix port-forward svc/grafana 3000:3000    # http://localhost:3000
```

1. **Distributed traces** — Grafana → *Explore* → **Tempo** → *Search*. You'll see
   request traces fanning out `gateway → movie/{actor,review}`, `user → {auth,
   recommendation→catalog}`, `search → catalog` — the real nine-service call graph.
2. **The AIOps dashboard** — open `traceflix.<domain>` (or `localhost:8000`):
   - **Streaming** → *Start backbone* → the **Topics**, **MELT**, and **LLM** panels
     update window-by-window; the LLM badge reads `llm` (Ollama up) or `heuristic`.
   - **Online / Offline / Comparison** → the RQ1–RQ4 experiment views.
3. **Metrics & logs** — Grafana → Prometheus (`service_name=…` JVM/HTTP metrics),
   VictoriaMetrics (long-range), Loki (LogQL).

---

## Step 7 — Reproduce the experiments inside the cluster

The dashboard's *Offline Mode* page runs these from the UI; or run them directly:

```bash
# RQ1 (completeness) + RQ4 (model family)   [also prints RQ2's first attempt]
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && python3 -m ml.experiments.run_experiment --episodes 200 --out data/results'

# RQ2 (localisation) — the reported, propagating-generator experiment
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && python3 -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46 --out data/results'

# RQ3 — online vs offline under drift (the headline)
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && python3 -m ml.experiments.online_vs_offline --episodes 320 --configs C1,C2,C3,C4 --out data/results'

# the Kafka backbone over the real broker
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && TF_KAFKA_BOOTSTRAP=kafka:9092 python3 -m streaming.run_pipeline --episodes 40'
```

Expect RQ1 F1 ≈ 0.896→0.986, RQ2 top-1 ≈ 0.36 (C2) → 0.56 (C3) at `bg = 0.1`, RQ3
static ≈ 0.36 vs online ≈ 0.98. (The `top-1 0.77 → 1.00` line printed by
`run_experiment` is RQ2's circular first attempt — see [`DemoRQ2.md`](../DemoRQ2.md).)

---

## Step 8 — Fault injection → live detection

Install Chaos Mesh, inject faults, and run the analysis against **live** telemetry:

```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/k3s/containerd/containerd.sock   # RKE2/k3s; adjust for your runtime

kubectl apply -f rancher/extras/chaos-examples.yaml    # cpu / pod-kill / latency / partition

# record start/stop timestamps as ground truth (schema: fault,root_cause,start_ts,end_ts),
# then run the live C1–C4 analysis from inside the cluster:
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && TF_LIVE=1 python3 -m ml.experiments.run_experiment --labels data/labels.csv'
```

The collectors issue real PromQL/LogQL/TraceQL and emit the **same `Window` schema**
the synthetic generator mirrors, so the whole analysis runs unchanged on live data.

---

## Step 9 — Access URLs

| URL | What |
|-----|------|
| `https://traceflix.<domain>/` | AIOps dashboard (Online / Offline / **Streaming** / Comparison) |
| `https://grafana.<domain>/` | Grafana (Prometheus / VictoriaMetrics / Loki / Tempo) |

---

## Step 10 — Upgrade / uninstall / teardown

```bash
helm upgrade traceflix ./rancher -n traceflix -f my-values.yaml
helm uninstall traceflix -n traceflix
kubectl delete namespace traceflix          # also removes the PVCs
helm uninstall chaos-mesh -n chaos-mesh      # if installed
```

> **Using Fleet?** Don't `helm uninstall` — Fleet owns the release and would
> re-apply it. Instead delete the **Git Repo** in Rancher → Continuous Delivery
> (removes the workloads), then `kubectl delete namespace traceflix` for the PVCs.

---

## Mapping to the VirtFusion overlay

| VirtFusion (Compose, 4 VMs) | Here (Helm, 1 GPU cluster) |
|-----------------------------|----------------------------|
| VM1 GPU: aiops + dashboard, Kafka, Ollama | `aiops`, `kafka`, `ollama` (GPU pods) |
| VM2: 9 services + OTel collector | `services.yaml` + `otel-collector` |
| VM3: Prometheus/VM/Loki/Tempo | `telemetry-backends.yaml` |
| VM4: Grafana + nginx gateway | `grafana` + Ingress |
| WireGuard mesh | in-cluster Service DNS |
| Pumba fault injection | Chaos Mesh (`extras/chaos-examples.yaml`) |
| `.env` `VM*_IP` | Service names (`prometheus`, `tempo`, `kafka`, …) |

---

## Troubleshooting

- **GPU pods Pending** — node not advertising `nvidia.com/gpu` (operator not ready)
  or the toleration/nodeSelector doesn't match. `kubectl describe pod ollama-…`.
- **ImagePullBackOff** — wrong `image.registry` or missing `image.pullSecrets`.
- **Services CrashLoop at start** — the OTel agent download (initContainer) needs
  egress to GitHub; on air-gapped clusters mirror the jar and set `otelAgent.url`.
- **No traces in Grafana** — check `otel-collector` is `Running`; services export to
  `http://otel-collector:4317` (same namespace).
- **`ollama-pull` Job retrying** — Ollama still starting; it retries up to 10×.
- **PVCs Pending** — no default StorageClass; set `storage.className`.
- **LLM badge shows `heuristic`** — `ollama.enabled=false` or model not pulled yet.
