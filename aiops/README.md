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

- **RQ1** `ml/experiments/run_experiment.py::completeness` — same model, configs C1→C4.
- **RQ2** `ml/experiments/rq2_localisation.py` — Top-k root-cause localisation on the
  **propagating** generator (`ml/dataset.py::generate_rca_run`), crossing signal
  (C2 vs C3) with ranking rule (flat vs graph-aware). The older
  `run_experiment.py::localisation` was a circular first attempt — see the note below.
- **RQ3** `ml/experiments/online_vs_offline.py` — **does detection need to be
  *online*?** A frozen batch model (traditional "train a snapshot, ship it")
  versus an online self-adapting model on a **non-stationary** stream where the
  operating baseline drifts (deploys, autoscaling, data growth — `ml/drift.py`).
- **RQ4** `…::model_family` — RF / GB / XGBoost / LSTM / multimodal fusion under C4,
  plus an opt-in sixth family: the local-LLM detector (Qwen2.5-3B over *raw*
  signals, `ENABLE_LLM=1`, needs Ollama). Run it with `make llm`, which writes to
  `data/results_llm/` so it cannot overwrite the committed artefacts; see
  [`data/results/README.md`](data/results/README.md) for the two silent failure
  modes that must be checked before quoting any number from it.

Four **controls** sit underneath RQ3, each answering an objection the headline
cannot answer by itself:

| Control | Question it settles | Code |
|---|---|---|
| Floor, oracle re-threshold, seed variance | Is 0.36 bad? Can a threshold fix it? Is the ordering seed-luck? | `ml/experiments/baselines_and_seeds.py` |
| **Drift-magnitude sweep** | Does drift break frozen detectors, or did we just set drift = fault size? | `ml/experiments/drift_sweep.py` |
| **Streaming baselines + component ablation** | Which mechanism earns the online margin? | `ml/experiments/baseline_streaming.py`, `ablate_online.py` |
| **Live replay** | Does any of this run on *measured* telemetry? | `ml/experiments/live_replay.py` |

## Quick start — offline (no cluster)

The synthetic generator mirrors the live collector schema, so all three RQs
reproduce without Kubernetes:

```bash
pip install -r requirements.txt
bash ./scripts/run_offline.sh 200      # data/results/*.csv + figures
pytest tests/ -q
```

Representative output (synthetic, seed 42, **9-service mesh** — see
`docs/MESH_EXPANSION.md`):

```
RQ1  C1 F1=0.896  C2 0.915  C3 0.985  C4 0.986     (completeness helps; traces drive the jump)
RQ2  Top-1 RCA: metrics+logs 0.77  ->  +traces 1.00   <- first attempt, see below
RQ4  GB 0.988 / RF 0.986 / XGB 0.984 F1; fusion 0.891 (hi-precision); LSTM 0.227 (weak)
```

> **The RQ2 line above is RQ2's circular first attempt.** `run_offline.sh` runs the
> localisation experiment on the *base* generator, where `error_spans` is gated on
> `is_origin` — the ground-truth label the localiser must recover — so the ranking
> feature is the answer key and a perfect 1.00 is arithmetic, not inference. The line
> is still printed, and `rq2_localisation.csv` still written, only so the defect stays
> inspectable. The reported RQ2 result is below.

**RQ2, as reported.** `ml/dataset.py::generate_rca_run` propagates the fault's errors
*up* the call path, attenuating 0.6 per hop, so every service on the path emits error
spans and the origin is identifiable only as the **root of the error tree**;
`--backgrounds` adds unrelated off-path incidents so the mesh is not unrealistically
silent.

```bash
python -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46 --episodes 200
```

```
Top-1 (5 seeds; random floor 0.111)      bg=0.0   bg=0.1   bg=0.25  bg=0.5
Metrics+Logs (C2)                         0.387    0.359    0.337    0.340
Metrics+Logs+Traces (C3)                  0.626    0.563    0.496    0.456
Metrics+Logs (C2), graph-aware            0.446    0.391    0.274    0.207
Metrics+Logs+Traces (C3), graph-aware     1.000    0.736    0.486    0.335
```

**The answer to RQ2:** traces are worth **+0.20 top-1** at bg = 0.1 and stay positive
at every noise level — earned by ablation, not by varying the model. Nothing
saturates (best arm 0.736 top-1, 0.948 top-3). The 1.000 at bg = 0.0 is a boundary
condition — a single error path has a unique root by construction — and the
graph-aware rule *inverts* against flat ranking by bg = 0.5, because it cannot tell a
real root from a spurious one. Answered in direction, bounded in magnitude. Full
analysis: [`../DemoRQ2.md`](../DemoRQ2.md).

## RQ3 — why traditional (offline) anomaly detection is not enough

> **Deep dive:** [`docs/ONLINE_PIPELINE.md`](docs/ONLINE_PIPELINE.md) walks through
> the online pipeline end-to-end — the drift generator, the `OnlineModel` and its
> four adaptation mechanisms, the experiment harness, and the cost comparison.

RQ1, RQ2 and RQ4 hold on a **stationary** stream, where a model trained once stays
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
./scripts/run_online_offline.sh 320            # -> rq3_*.csv + rq3 figures
```

Representative output (synthetic drift, seed 42) — F1 on the *operational
future* (regimes R1–R3), all models on identical features. `offline_periodic`
refits every 500 windows on the last ~2880 (51 scheduled retrains):

```
config            offline_static   offline_periodic   online_adaptive   offline_full (oracle)
C1 Metrics-Only       0.360             0.820              0.813               0.812
C2 + Logs             0.361             0.832              0.827               0.817
C3 + Traces           0.370             0.925              0.974               0.929
C4 Full MELT          0.371             0.926              0.976               0.927
```

Read against the **always-alarm floor of F1 = 0.292** (prevalence 0.171 — flag every
window), measured in `ml/experiments/baselines_and_seeds.py`.

Read-out for the dissertation:

- The **static batch model collapses to F1 ≈ 0.36 under drift even with full
  MELT** (precision ≈ 0.22 — it raises false alarms on the new normal), barely
  above the trivial floor. Richer observability does **not** rescue it: the
  failure is the *learning paradigm*, not signal availability.
- **And you cannot fix it by moving the threshold.** Granting the frozen model the
  best cut-point obtainable *on the drifted stream itself* — an oracle no deployment
  could achieve — recovers it only to 0.44–0.55. The boundary is the wrong **shape**,
  not merely in the wrong **place**.
- **Scheduled retraining recovers most of the gap** (0.36 → 0.82–0.93) but is
  bursty: every regime shift opens a **drift-response gap** until the next
  refresh — visible as the sawtooth in `rq3_timeline.png` — and each refresh is a
  full batch re-fit that blocks the detector. Faster cadence shrinks the gap only
  by paying more compute; the online model removes it structurally.
- The **online adaptive model reaches or exceeds oracle level** updating *per
  sample*, with no batch re-fit. Under **thin** telemetry (C1/C2) it is **tied**
  with periodic (seed-variance runs put the difference inside noise); its advantage
  is real only once traces are present (C3/C4: +0.05, ~9 σ over five seeds).
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
C4, 25,920 future windows         offline_periodic     online_adaptive
F1                                      0.9255              0.9755
train events                            51 full refits      25,920 updates
worst-case latency / window             581.6 ms (stall)    15.5 ms
p99 latency / window                    0.14 ms             8.5 ms
model size                              2287.7 KB           15.7 KB
labelled windows retained to train      2880                0
total CPU over the stream               29.4 s (1.0x)       129.7 s (~4.4x)
```

The honest trade-off:

- Online is **not cheaper in total CPU** — it does a little work *every* window
  (a pool of linear `partial_fit` updates), 4.1–4.8x the aggregate compute of 51
  RandomForest refits. That cost is real and worth stating.
- But online wins on every dimension that matters operationally: **10–48x lower
  worst-case latency** (a full refit blocks the detector for 580–880 ms; the
  online update never exceeded 78 ms across five seeds, so detection stays
  real-time), a **~120–390x smaller model** (≈15 KB against 2–6 MB), **zero
  retained training data** (periodic must keep a 2880-window labelled buffer to
  refit — memory and data-governance cost), *and* higher F1 once traces are present.
- Periodic's mean latency is lower because its work is bursty and rare — but
  bursty is exactly the problem: the stalls land precisely when a regime shifts
  and detection matters most. Buying down the F1 gap with a faster cadence only
  multiplies those stalls and the compute.

> The wall-clock columns are properties of this workstation and a single pass. The
> **structural** columns — refit count, footprint, retained windows — follow from the
> policy and reproduce exactly, and the cost argument rests on those plus the
> order-of-magnitude tail gap, not on any particular millisecond.

The table above is **seed 42** (`make cost`). Every *range* quoted in this section is a
min–max over five seeds, which one seed cannot produce — `make cost-seeds` drives
`cost_compare` across seeds and aggregates them into `data/results/rq3_cost_seeds.csv`
(`make cost-seeds-agg` re-derives the summary from per-seed tables already on disk, in
seconds). Quote ranges from there, not from the seed-42 table.

So the cost comparison reframes the result: it is not "online is free", it is
**online converts a bursty, stateful, blocking retrain pipeline into a smooth,
bounded-latency, stateless stream — at higher steady CPU but lower operational
risk, smaller footprint, and better accuracy.**

This is the evidence that *operations matter*: in a modern distributed system
the detector must learn continuously, because the ground truth of "normal" moves.

Reproduce everything (RQ3 detection + cost + figures) with one command:

```bash
./scripts/run_online_offline.sh 320            # -> rq3_*.csv, rq3_cost.csv, figures
```

### How far must the baseline move? — the drift-magnitude sweep

Everything above is measured at **one** drift amplitude, and that amplitude is
comparable to the fault signatures themselves (`REGIME_FACTORS` moves p99 by 2.2x,
`_FAULT_SHIFT` moves it by 2.3x). A boundary fitted on R0 *must* fail there, so the
collapse is entailed by the parameterisation rather than measured. One operating
point cannot separate "drift defeats frozen detectors" from "we set the drift as
large as the fault".

`scaled_regime_factors(alpha)` (`ml/drift.py`) rescales every multiplier toward 1,
preserving which fields each regime moves and in what proportion, varying only how
far. Labels are assigned before the factors are applied and the generator draws the
same random numbers either way, so **the fault schedule is identical at every
alpha** — the only thing that varies is how far the healthy baseline has moved.

```bash
make sweep                    # from the repo root; knobs: DRIFT_EPISODES= SWEEP_CONFIGS=
# equivalently, from aiops/:
python -u -m ml.experiments.drift_sweep --episodes 320 --seed 42 --configs C1,C4 \
  --out data/results_drift_sweep
```

```
       R3 shift   C1: static periodic online   C4: static periodic online
a=0.00   1.00x       0.890    0.885    0.815      0.989    0.985    0.977
a=0.15   1.15x       0.830    0.880    0.815      0.933    0.982    0.977
a=0.30   1.29x       0.682    0.867    0.815      0.769    0.974    0.977
a=0.50   1.49x       0.511    0.852    0.814      0.546    0.954    0.976
a=1.00   1.97x       0.360    0.820    0.813      0.370    0.925    0.976   <- reported campaign
a=1.30   2.26x       0.333    0.813    0.813      0.341    0.921    0.976
```

- **Adaptation is not free.** On a stationary stream the frozen model is the *best*
  of the three and the online detector the worst (0.815 vs 0.890 at C1). Continual
  updating is worth having because the stream drifts, not because it is continual.
- **The failure is gradual.** Static F1 at C4 falls 0.989 → 0.370; by a 1.29x shift a
  detector has lost a fifth of its F1 while still looking serviceable.
- **The decision threshold is a number, not an assertion.** Refitting starts to pay
  by a **1.15x** shift, and the frozen model drops below twice the always-alarm floor
  between **1.29x and 1.49x**. The reported campaign sits at 1.97x — well beyond it.
- **The two adaptive policies differ in kind.** Online F1 at C4 varies by 0.001 across
  the whole sweep; periodic decays steadily (0.985 → 0.921), exposed to whatever
  accumulates between refits. At C1 periodic leads or ties at *every* amplitude.

`alpha=1` reproduces `rq3_online_vs_offline.csv` to four decimals — treat it as the
sweep's regression check.

### What the adaptive machinery is actually worth — baselines and ablation

Two experiments build a ladder underneath the online detector, so its margin is
attributed rather than assumed.

```bash
make baselines                # 1. off-the-shelf learners, raw and standardised
make ablation                 # 2. the detector's own mechanisms, off in turn
# equivalently, from aiops/:
python -u -m ml.experiments.baseline_streaming --episodes 320 --seed 42 \
  --out data/results_baselines_scaled
python -u -m ml.experiments.ablate_online --episodes 320 --seed 42 \
  --out data/results_ablation
```

**Normalisation carries the policy; the rest is close to free.** Three canonical
linear learners (passive-aggressive, perceptron, plain SGD) scored prequentially on
the identical stream reach **F1 0.302–0.308 unnormalised at every configuration** —
barely above the floor, and flat in richness. Put a running `StandardScaler` in front
of the *same* learner and they reach **0.760–0.796 at C1** and **0.959–0.971 at C3**,
tracking completeness as the full detector does (plain SGD +0.170 from C1→C4 against
the detector's +0.163).

Against the best off-the-shelf scaled arm the full detector retains **+0.017 at C1**
and **+0.003 at C3** — the latter inside the seed spread. The ablation splits that
remainder: champion re-election is worth **+0.013 (C1)**, +0.005 (C2) and **nothing**
at C3/C4; the drift monitor is worth **nothing anywhere** (−0.0014 at C1, 0.0000 at
C3/C4), so its adapt events are diagnostic rather than load-bearing.

The honest read-out: **a standardised incremental learner is a close substitute for
the whole detector.** That does not weaken RQ3 — the clean, unconfounded contrast was
always static-vs-periodic within one family — but it does bound what the detector's
extra machinery may be credited with.

### The live-replay pilot — the one measured result

`ml/experiments/live_replay.py` joins the ground truth from `faults/run_episodes.py`
to *historical* PromQL: `collect_metrics_live(service, at=ts)` evaluates each query at
the instant its window represents, so a recorded campaign is reconstructed rather than
filled with present-moment telemetry.

```bash
make live-replay              # PROM_URL= and LIVE_LABELS= override the defaults
# equivalently, from aiops/:
TF_LIVE=1 PROM_URL=http://localhost:9090 \
  python -u -m ml.experiments.live_replay --labels data/labels_live.csv \
  --out data/results_live
```

```
source config model  P      R      F1     AUC    n_test  prevalence  floor
live   C1     rf     0.700  0.700  0.700  0.967  135     0.078       0.144
```

Narrow on purpose, and the narrowness is the point: **C1 only** (the log, trace and
event collectors are not time-parameterised, so C2–C4 would silently mix present
values into a past window — this pilot therefore says *nothing* about the trace
increment), **origin-only labelling** (ancestors degraded by the fault count as
normal — conservative, it can only depress precision), and **twelve episodes**. It is
evidence the pipeline works end to end on genuine telemetry; it is not evidence about
any number in the paper. The full drifted live campaign remains the outstanding
experiment.

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
[`docs/ONLINE_PIPELINE.md`](docs/ONLINE_PIPELINE.md) for the RQ3 online pipeline.
To exercise detection against the deployed cluster — inject a fault and watch the
🛰 Live Cluster page score it —
[`docs/LIVE_DETECTION_SCENARIOS.md`](docs/LIVE_DETECTION_SCENARIOS.md) has the
scenarios, the preconditions that must be green first, and the symptom→cause table
for the ways it silently reports nothing.
