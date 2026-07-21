# TraceFlix — full demo with **only `kubectl`** (Rancher tenant shell, no GPU)

Everything below runs in the Rancher in-browser **kubectl** shell. No `helm`, no
repo files on the cluster, CPU-only. Namespace is `traceflix` — change it if you
were given a different one.

Prereqs: the GHCR packages are **public** (so the cluster can pull), and the
rendered manifest is committed at
`rancher/rendered/traceflix-virtfusion.yaml` on `main`.

---

## 1. Deploy

```bash
# default StorageClass present? (the 5 PVCs need one)
kubectl get storageclass

kubectl create namespace traceflix          # skip if you can't / already have one
kubectl apply -n traceflix \
  -f https://raw.githubusercontent.com/ducanhptitb19cn028/traceflix-platform/main/rancher/rendered/traceflix-virtfusion.yaml
```

## 2. Wait for the rollout

```bash
kubectl -n traceflix get pods -w        # Ctrl-C when all are Running
kubectl -n traceflix wait --for=condition=available --timeout=300s deploy --all
```

All 18 deployments should become Available. The load generator immediately starts
driving `gateway/api/browse`, so telemetry begins flowing within a minute.

## 3. Prove the WHOLE mesh works (one call fans out to all 9 services)

```bash
# the aiops image has curl; call the gateway in-cluster:
kubectl -n traceflix exec deploy/aiops -- \
  curl -s "http://gateway-service:8080/api/browse?userId=2"
```
You get one aggregated JSON `{ user, trending, featured }` — that single request
fanned out `gateway → user →{auth, recommendation→catalog}`,
`gateway → search → catalog`, `gateway → movie →{actor, review}`. All nine.

## 4. Prove all nine services are TRACED (the "only movie" check)

```bash
# Tempo lists every service.name it has received spans for:
kubectl -n traceflix exec deploy/aiops -- \
  curl -s http://tempo:3200/api/search/tag/service.name/values
```
Expect all nine in `tagValues`: gateway/movie/actor/review/user/search/
recommendation/auth/catalog — not just movie-service.

```bash
# metrics backend up?
kubectl -n traceflix exec deploy/aiops -- \
  curl -s "http://prometheus:9090/api/v1/query?query=up" | head -c 300
```

## 5. Prove the AIOps dashboard backend

```bash
kubectl -n traceflix exec deploy/aiops -- curl -s http://localhost:8000/api/health
kubectl -n traceflix exec deploy/aiops -- curl -s http://localhost:8000/api/experiments | head -c 400
```
`/api/health` → `{"status":"ok"}`.

## 6. Run the experiments (the science — RQ1–RQ4)

```bash
# quick smoke first (CPU-friendly):
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && python3 -m ml.experiments.run_experiment --episodes 60 --out data/results'

# full RQ1 (completeness) + RQ4 (model family)  [also prints RQ2's first attempt]:
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && python3 -m ml.experiments.run_experiment --episodes 200 --out data/results'

# RQ2 (localisation) — the reported, propagating-generator experiment:
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && python3 -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46 --out data/results'

# RQ3 — the headline: online vs offline under drift:
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && python3 -m ml.experiments.online_vs_offline --episodes 320 --configs C1,C2,C3,C4 --out data/results'

# streaming backbone over the REAL in-cluster Kafka broker:
kubectl -n traceflix exec deploy/aiops -- sh -c \
  'cd /opt/traceflix/aiops && TF_KAFKA_BOOTSTRAP=kafka:9092 python3 -m streaming.run_pipeline --episodes 40'
```
Expect RQ1 F1 ≈ 0.896→0.986, RQ2 top-1 ≈ 0.36 (C2) → 0.56 (C3) at `bg = 0.1`, RQ3
static ≈ 0.36 vs online ≈ 0.98. (The `top-1 0.77 → 1.00` line printed by
`run_experiment` is RQ2's circular first attempt — see [`DemoRQ2.md`](../DemoRQ2.md).)

## 7. See the UIs in a browser (VirtFusion VM has a public IP)

The in-browser shell's `port-forward` only binds inside the shell pod, so expose
the two UIs as NodePort and hit the VM's public IP:

```bash
kubectl -n traceflix patch svc aiops   -p '{"spec":{"type":"NodePort"}}'
kubectl -n traceflix patch svc grafana -p '{"spec":{"type":"NodePort"}}'
kubectl -n traceflix get svc aiops grafana      # read the 3xxxx nodePort column
```
Open `http://<vm-public-ip>:<nodePort-of-aiops>` (dashboard: Online / Offline /
**Streaming** / Comparison) and `http://<vm-public-ip>:<nodePort-of-grafana>`
(Grafana → Explore → **Tempo** → Search to see the nine-service traces).
Grafana login: `admin` / the password in the manifest (`change-me-please`).

> Prefer not to open a NodePort? Use the Rancher UI's **Port Forwarding** action on
> the `aiops` / `grafana` Service to tunnel it to your browser instead.

## 8. Teardown

```bash
kubectl delete -n traceflix \
  -f https://raw.githubusercontent.com/ducanhptitb19cn028/traceflix-platform/main/rancher/rendered/traceflix-virtfusion.yaml
# or remove everything incl. PVCs:
kubectl delete namespace traceflix
```

---

### Notes
- **CPU-only:** GPU LLM is off, so the dashboard's LLM badge reads `heuristic` and the
  synthetic experiments (RQ1–RQ4) carry the demo. To add the local LLM later you need
  a GPU node + the GPU values.
- **Live fault injection** (Chaos Mesh) needs cluster-admin to install, so it's out of
  scope for a tenant login; the synthetic + Kafka-streaming runs above exercise the
  full pipeline without it.
- **ImagePullBackOff** → the GHCR packages aren't public yet (Step prereq).
- **PVC Pending** → no default StorageClass; tell me the class name from
  `kubectl get storageclass` and I'll re-render pinned to it (or with `emptyDir`).
