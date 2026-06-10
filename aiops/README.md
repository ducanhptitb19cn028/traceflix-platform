# TraceFlix-AIOps — observability experiment layer

An add-on that turns your existing **TraceFlix** (Spring Boot 3.5.4 / Java 21,
three services, OpenTelemetry Java-agent auto-instrumentation) and your
`on-demand-observability` stack into the controlled C1–C4 experiment from the
dissertation *"Does Observability Matter?"*.

This layer **does not modify your services**. It sits beside them and:

1. injects faults into the three real pods (Chaos Mesh),
2. records ground-truth labels with exact timestamps,
3. pulls MELT telemetry from *your* Prometheus / Loki / Tempo (and
   VictoriaMetrics for historical context),
4. trains/evaluates the anomaly-detection + RCA pipeline across C1–C4,
5. and fixes two deployment gaps found in the manifest.

## How it binds to your real system

| Your component | Used by this layer |
|----------------|--------------------|
| `movie-service` → `actor-service` (N sequential calls) + `review-service` | Topology in `ml/configs.py`; drives RCA propagation |
| OTel Java agent metrics via collector Prometheus exporter | `collectors/telemetry.py` PromQL (`http_server_request_duration_*`, `jvm_memory_used_bytes`, `jvm_cpu_recent_utilization_ratio`, …) |
| Loki (`service.name`/`service.namespace` labels) | LogQL collector |
| Tempo (`otlp/tempo`) | TraceQL collector — originating `error_spans` |
| Prometheus `remote_write` → VictoriaMetrics | C4 historical baseline (`mem_baseline_1h`) |
| `load-generator` | Continuous traffic so episodes have signal |

## The research questions, as runnable code

- **RQ1** `ml/experiments/run_experiment.py::rq1` — same model, configs C1→C4.
- **RQ2** `…::rq2` — RF / GB / XGBoost / LSTM / multimodal fusion under C4.
- **RQ3** `…::rq3` — Top-k root-cause localisation, traces excluded vs included.
- **RQ4** `ml/experiments/online_vs_offline.py` — **does detection need to be
  *online*?** A frozen batch model (traditional "train a snapshot, ship it")
  versus an online self-adapting model on a **non-stationary** stream where the
  operating baseline drifts (deploys, autoscaling, data growth — `ml/drift.py`).

## Quick start — offline (no cluster)

The synthetic generator mirrors the live collector schema, so all three RQs
reproduce without Kubernetes:

```bash
pip install -r requirements.txt
bash ./scripts/run_offline.sh 200      # data/results/*.csv + figures
pytest tests/ -q
```

Representative output (synthetic, seed 42, **3-service topology**):

```
RQ1  C1 F1=0.906  C2 0.933  C3 0.988  C4 0.994     (completeness helps; traces drive the jump)
RQ2  RF 0.994 / GB 0.991 / XGB 0.991 F1; fusion high-precision; LSTM needs torch
RQ3  Top-1 RCA: metrics+logs 0.91  ->  +traces 1.00
```

> **Note on RQ3 scale.** With only three services, Top-2 covers two-thirds of
> the mesh and saturates at 1.0; **Top-1 is the discriminating metric** and is
> what the figures emphasise.

## RQ4 — why traditional (offline) anomaly detection is not enough

> **Deep dive:** [`docs/ONLINE_PIPELINE.md`](docs/ONLINE_PIPELINE.md) walks through
> the online pipeline end-to-end — the drift generator, the `OnlineModel` and its
> four adaptation mechanisms, the experiment harness, and the cost comparison.

RQ1–RQ3 hold on a **stationary** stream, where a model trained once stays
calibrated and the batch detectors look excellent (F1 ≈ 0.99). Production
telemetry is **not** stationary: a release regresses latency, autoscaling
changes throughput, data growth raises the JVM memory footprint. None of these
are faults — they are the *new normal* — but a detector whose decision boundary
was frozen on last month's normal starts flagging today's normal as anomalous.
`ml/drift.py` injects exactly this as operational regimes R0→R3 (label-preserving
baseline shifts), and `ml/models/online.py` answers it with an online detector
that **adapts from the incoming data pattern** — no offline re-fit:

1. **adaptive normalisation** — an EW running mean/var tracks the *evolving
   normal* operating point, so a fault stays a large deviation in any regime;
2. **incremental learning** — SGD logistic regression via `partial_fit`
   (prequential test-then-train);
3. **dynamic parameter optimisation** — a pool of learners with different
   learning-rate/regularisation runs in parallel; the champion is re-elected by
   recent F1, so the effective hyper-parameters re-tune themselves;
4. **drift-triggered acceleration** — a two-window error monitor speeds
   re-centring after an abrupt shift.

```bash
./scripts/run_online_offline.sh 320            # -> rq4_*.csv + rq4 figures
```

Representative output (synthetic drift, seed 42) — F1 on the *operational
future* (regimes R1–R3), all models on identical features. `offline_periodic`
refits every 500 windows on the last ~2880 (17 scheduled retrains):

```
config            offline_static   offline_periodic   online_adaptive   offline_full (oracle)
C1 Metrics-Only       0.489             0.757              0.817               0.812
C2 + Logs             0.492             0.778              0.835               0.834
C3 + Traces           0.510             0.890              0.982               0.940
C4 Full MELT          0.511             0.891              0.983               0.939
```

Read-out for the dissertation:

- The **static batch model collapses to F1 ≈ 0.5 under drift even with full
  MELT** (precision ≈ 0.34 — it raises false alarms on the new normal). Richer
  observability does **not** rescue it: the failure is the *learning paradigm*,
  not signal availability.
- **Scheduled retraining is not enough either.** `offline_periodic` recovers a
  lot of the loss (0.49 → 0.76, 0.51 → 0.89) but still trails online by 6–9 F1
  points and never reaches the oracle, because every regime shift opens a
  **drift-response gap** until the next refresh — visible as the sawtooth in
  `rq4_timeline.png` — and each refresh is a full batch re-fit. Faster cadence
  shrinks the gap only by paying more compute; the online model removes it
  structurally.
- The **online adaptive model recovers to oracle level** (0.82 → 0.98) updating
  *per sample*, with no batch re-fit and without seeing the future in batch — and
  *exceeds* the all-regime oracle under C3/C4 because tracking the evolving
  normal beats a single static split. The C2→C3 jump shows traces still help the
  *adaptive* model just as they do in RQ1.
- `offline_full` is an **unrealistic oracle** (trained on a random split across
  all regimes — you cannot train on the operational future); it is included only
  to prove the static model's decay is caused by **non-stationarity**, not by
  model capacity.

### Cost: online vs periodic retraining

A reviewer's fair objection: periodic retraining could close the F1 gap by
refitting *more often*. `ml/experiments/cost_compare.py` measures the price of
that. It replays the post-R0 stream and records, per paradigm, the **per-window
processing latency** (inference + any training that fires on that window), the
number of train events, model size, and the labelled buffer each must retain:

```
C4, 8640 future windows           offline_periodic     online_adaptive
F1                                      0.890               0.983
train events                            17 full refits      8640 updates
worst-case latency / window          ~450 ms (refit stall)  ~12 ms
p99 latency / window                    0.34 ms             6.6 ms
model size                              3.3 MB              16 KB
labelled windows retained to train      2880                0
total CPU over the stream               1.0x (baseline)     ~4.5x
```

The honest trade-off:

- Online is **not cheaper in total CPU** — it does a little work *every* window
  (a pool of linear `partial_fit` updates), ~4.5x the aggregate compute of 17
  RandomForest refits. That cost is real and worth stating.
- But online wins on every dimension that matters operationally: **~38x lower
  worst-case latency** (a full refit blocks the detector for ~450 ms; the online
  update never exceeds ~12 ms, so detection stays real-time), a **~214x smaller
  model**, **zero retained training data** (periodic must keep a 2880-window
  labelled buffer to refit — memory and data-governance cost), *and* higher F1.
- Periodic's mean latency is lower because its work is bursty and rare — but
  bursty is exactly the problem: the stalls land precisely when a regime shifts
  and detection matters most. Buying down the F1 gap with a faster cadence only
  multiplies those stalls and the compute.

So the cost comparison reframes the result: it is not "online is free", it is
**online converts a bursty, stateful, blocking retrain pipeline into a smooth,
bounded-latency, stateless stream — at higher steady CPU but lower operational
risk, smaller footprint, and better accuracy.**

This is the evidence that *operations matter*: in a modern distributed system
the detector must learn continuously, because the ground truth of "normal" moves.

Reproduce everything (RQ4 detection + cost + figures) with one command:

```bash
./scripts/run_online_offline.sh 320            # -> rq4_*.csv, rq4_cost.csv, figures
```

## Quick start — live (against your cluster)

```bash
# 1. your stack
kubectl apply -f ../observability/on-demand-observability.yaml
kubectl apply -f k8s/load-generator-fixed.yaml      # gap fix: correct review path
kubectl apply -f k8s/victoriametrics.yaml           # gap fix: VM in devops-agent ns

# 2. enable OOMKilled escalation (optional, for the E-signal in C4)
for s in movie-service actor-service review-service; do
  kubectl patch deployment $s -n on-demand-observability \
    --patch-file k8s/resource-limits-patch.yaml      # edit container name per service
done

# 3. fault injection engine
./scripts/install_chaos_mesh.sh

# 4. drive episodes + analyse live telemetry
./scripts/run_live_experiment.sh 30
```

## The two gaps this layer fixes

1. **Review path mismatch.** The original `load-generator` calls
   `review-service:8080/api/reviews/$id`, but the controller is
   `GET /api/reviews?movieId={id}` — those calls 404 and never exercise the real
   query path. `k8s/load-generator-fixed.yaml` uses the correct query-param
   contract.
2. **Missing VictoriaMetrics.** Prometheus `remote_write`s to
   `victoriametrics.devops-agent.svc.cluster.local:8428`, but nothing deploys
   it, so C4's historical baseline has no backing store.
   `k8s/victoriametrics.yaml` creates VM in the `devops-agent` namespace with
   the exact service name the manifest expects.

See `docs/INTEGRATION.md` for the full data flow, metric-name mapping, and the
fault-to-service injection plan, and
[`docs/ONLINE_PIPELINE.md`](docs/ONLINE_PIPELINE.md) for the RQ4 online pipeline.
