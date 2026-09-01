# Live Detection Test Scenarios — the deployed cluster

Repeatable scenarios for the **🛰 Live Cluster** page (`/live/cluster`), the only
surface in the dashboard where both halves of a scored window come from the real
system: the telemetry is whatever PromQL returns for the running services, and the
`truth` column is read from the Chaos Mesh custom resources actually injected into
the cluster (`collectors/chaos.py`).

Each scenario states what to run, what should happen, and what a failure of that
expectation actually means. Numbers marked *(measured)* were observed on this
deployment on 2026-09-01; treat them as the shape to expect, not as targets.

## What this page is not

Three surfaces look similar and answer different questions. Picking the wrong one
is the single most common source of "I injected a fault and nothing happened".

| Surface | Telemetry | Ground truth | Answers |
|---|---|---|---|
| **Live ML** / **Live LLM** | generated (`_synth`) | invented by the engine | how the detector families compare on a controlled stream |
| **Online Mode** | generated, drifting (`ml/drift.py`) | invented | how an online learner survives regime drift |
| **🛰 Live Cluster** | **real** (PromQL, live) | **real** (Chaos Mesh CRs) | does this detect a fault in the deployed system |
| `make live-replay` | **real**, historical | real (labels CSV) | the same, scored after the fact over a recorded campaign |

A Chaos Mesh injection will **never** appear on Live ML, Live LLM or Online Mode.
Those pages generate their own faults — if the `truth` column names a service or a
fault type you did not inject, that is what you are looking at.

## Preconditions

```powershell
# 1. Backends reachable from wherever the dashboard runs
kubectl -n on-demand-observability port-forward svc/prometheus 9090:9090
kubectl -n on-demand-observability port-forward svc/loki       3100:3100
kubectl -n on-demand-observability port-forward svc/tempo      3200:3200
kubectl -n devops-agent           port-forward svc/victoriametrics 8428:8428

# 2. Backend with TF_LIVE=1 (in-cluster this is already set, see k8s/aiops.yaml)
$env:TF_LIVE='1'; python -m uvicorn webui.backend.app:app --port 8000
```

The page's header carries three chips, and **all three must be green before any
number on the page means anything**:

- `TF_LIVE=1 — reading the real stack`. Without it the collectors return
  generated telemetry.
- `Chaos Mesh readable — ground truth is real`. Without it every window is
  labelled `normal` and precision/recall/F1 are meaningless — the page says so in
  a callout rather than reporting a clean-looking score.
- `fitted on N live windows`. The models are fitted on windows collected from
  this cluster, never on the generator. The engine **refuses to start** below 200
  windows / 20 anomalous, because a model fitted on generated data does not fail
  visibly against the cluster — it reports everything as normal, which looks like
  a healthy system.

Verify without opening a browser:

```powershell
curl -s http://localhost:8000/api/live/cluster/info | python -m json.tool
```

## Scenario 1 — CPU saturation (the reference case)

The one to run first: it is the fault the training set covers best.

```powershell
kubectl -n on-demand-observability patch deployment catalog-service --type=strategic `
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"catalog-service","resources":{"requests":{"cpu":"100m"},"limits":{"cpu":"500m"}}}]}}}}'
kubectl -n on-demand-observability rollout status deploy/catalog-service --timeout=180s

make inject SVC=catalog-service FAULT=cpu_saturation DUR=300
```

**Expected**

1. Within one collection cadence (default 10 s) the `truth` column for
   `catalog-service` flips to `cpu_saturation`, and the service appears under
   **Injected faults, right now**. This tracks the CR, not the telemetry, so it
   is immediate.
2. One to three minutes later the metrics move and the detectors follow. *(measured:
   detectors fired at t+35 s on a warm engine, and at window 17 — about 170 s — on
   one started cold.)*
3. Most of the batch detectors flip to ANOMALY on that service while the other
   eight services stay `normal`.

*(measured, 240 s episode, whole session including normal windows)*

```
detector            tp   fp   fn   tn    f1
Online SGD          12   1    2    174   0.889
GradientBoosting    11   0    3    175   0.880
XGBoost             11   0    3    175   0.880
Multimodal fusion   11   0    3    175   0.880
LSTM (temporal)      7   72   7    103   0.151
RandomForest         1    0   13   175   0.133
```

**Underlying telemetry** *(measured)* — useful when the page shows nothing and you
need to know whether the fault or the detector is at fault:

| | baseline | under fault |
|---|---|---|
| `avg(jvm_cpu_recent_utilization_ratio)` | 0.0012 | **0.372** |
| `sum(rate(http_server_request_duration_seconds_count[2m]))` | 11.0/s | **0.0/s** |

**If the truth column flips but no detector ever fires**, the fault is not
reaching the telemetry. Check the CPU limit (see the troubleshooting table) before
suspecting the models.

## Scenario 2 — Latency spike (the honest stress test)

`latency_spike` is absent from the recorded training set, so this is the scenario
that shows what the page does with a fault type it has never been fitted on.

```powershell
make inject SVC=user-service FAULT=latency_spike DUR=300
```

**Expected**: the `truth` column flips (it reads the CR, which does not care what
the models were trained on). Detection is genuinely uncertain — a miss here is a
real, reportable result about training coverage, not a bug. Needs no resource
limit: `latency_spike` is netem, not contention.

## Scenario 3 — Pod kill

```powershell
make inject SVC=recommendation-service FAULT=pod_kill DUR=180
```

**Expected**: the sharpest signal of the five — the pod disappears and its series
stop, so `req_rate` and every JVM metric collapse rather than shift. Note that
`inject.py` builds `PodChaos` with no `duration`: the pod is killed once and the
caller holds the window open, so `truth` is `pod_kill` for the whole `DUR` while
the service is in fact recovering for most of it. The label is deliberately
coarser than the telemetry here.

Needs no resource limit.

## Scenario 4 — Memory leak

Requires the memory half of `k8s/resource-limits-patch.yaml`, which is what makes
the 300 MB stressor drive a real `OOMKilled`:

```powershell
kubectl -n on-demand-observability patch deployment catalog-service --type=strategic `
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"catalog-service","resources":{"limits":{"memory":"384Mi"}}}]}}}}'
make inject SVC=catalog-service FAULT=memory_leak DUR=300
```

**Expected**: `mem` climbs, then the pod is OOM-killed and restarts. Watch for a
CrashLoop — 384 Mi is tight for a service that has never been memory-bounded, and
if it will not stay up, remove the memory limit rather than fighting it.

## Scenario 5 — Negative control

Run the page for ten minutes with **nothing injected**.

**Expected**: `Injected faults, right now` stays empty, every `truth` cell reads
`normal`, and the only interesting number is the false-alarm count. Precision,
recall and F1 are all 0 by construction — there are no positives to score — so
read the **FP** column, not F1.

This is the scenario that exposes a detector fitted on the wrong distribution, and
the one that catches the LSTM's false-alarm rate *(measured: 72 FP over one
session)*.

## Scenario 6 — Ground truth unavailable

Deliberately break the label source and confirm the page says so instead of
quietly reporting good numbers:

Point *the backend process only* at a kubeconfig that does not exist, so the rest
of your session — port-forwards included — keeps working:

```powershell
$env:KUBECONFIG='C:\nonexistent\config'; $env:TF_LIVE='1'
python -m uvicorn webui.backend.app:app --port 8000
```

**Expected**: the second header chip turns red, a callout states that every window
will be labelled `normal` and that the scores are meaningless until it is fixed,
and the detectors keep scoring. A page that shows a healthy F1 in this state is
the bug this scenario exists to catch.

Restore by restarting the backend without the `KUBECONFIG` override.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Fault injected, `truth` column never changes | Watching Live ML / Live LLM / Online Mode | Those generate their own faults. Use 🛰 Live Cluster. |
| `truth` flips, telemetry stays flat | Target has no CPU limit, so the stressor has nothing to contend for on a 12-core node | Patch requests/limits (Scenario 1). Affects every `tier=mesh` service. |
| Fault visible for only a window or two | `DUR=120` — most of it is spent in the export + `[2m]` rate-window lead-in | Use `DUR=300`. |
| Engine status `error`, "not enough live training data" | Fewer than 200 windows / 20 anomalous recorded | Record more: inject, then `make live-replay LIVE_LABELS=<csv> LIVE_OUT=<own dir>`. The page also records every window it collects to `data/live_stream_cache.jsonl`, so simply leaving it running helps. |
| `make live-replay` refuses to start | `data/results_live/` is reserved for the campaign the write-up reports | Pass `LIVE_OUT=data/results_live_<name>`. Never share an out directory between campaigns: the replay resumes from `live_windows_cache.jsonl` and returns *every* window it holds. |
| `Input X contains NaN` during the fit | Old cache from before `_prom_instant` mapped a NaN quantile to 0.0 | Fixed at collection; old caches are repaired on load by `cluster_detect._scrub`. |
| Everything scores as `normal`, no errors | Models fitted on generated data (live baseline `cpu` ≈ 0.003 sits below the generator's *normal* ≈ 0.25) | Cannot happen through this page — it refuses to fit on generated windows — but it is what `make live` used to do. |

## Reading the results honestly

- **C1 only.** The models are fitted on the replay caches, whose log, trace and
  event pillars carry values from replay time rather than from the episode they
  are labelled with. Live collection *could* serve C1–C4 — a window collected now
  has genuine current logs and traces — so the restriction lifts once enough
  windows have been recorded live. The API rejects a config switch on this engine
  with that reason.
- **The training set is thin.** *(measured: 873 windows, 72 anomalous, no
  `latency_spike` at all.)* RandomForest's low F1 and the LSTM's false alarms are
  symptoms of that, not of the live path.
- **It improves itself.** Every window the page collects is appended to
  `data/live_stream_cache.jsonl` in the replay's format. *(measured: 549 → 873
  windows across two test injections.)*
- A single episode is far too small to quote. The replay of one 300 s episode
  scored F1 0.80 against an always-alarm floor of 0.20 over 81 windows with three
  anomalous windows in the test split — enough to show the detector sees
  something, not enough to be a result.

## Related

- [`DATA_LABELLING.md`](DATA_LABELLING.md) — the label schema both paths emit.
- [`INTEGRATION.md`](INTEGRATION.md) — metric-name mapping and the collector flow.
- `streaming/cluster_detect.py` — the engine, and why it refuses rather than
  falls back.
- `collectors/chaos.py` — how a CR becomes a label, and why `AllInjected` matters.
