# Kafka Event Backbone + Local-LLM Detector — Architecture & Plan

> **Status:** design + scaffold (this pass). Runs today with graceful fallbacks
> (in-memory bus when no broker; heuristic LLM when Ollama/peft absent), the same
> way the project already degrades synthetic→live and LSTM→heuristic.
>
> **Additive intent.** New code lives in `aiops/streaming/` and `aiops/llm/`, one new
> model in `aiops/ml/models/llm_detector.py`, and a deploy overlay in
> `deploy/virtfusion/vm1-gpu/`. The existing C1–C4 / RQ1–RQ4 pipeline is unchanged;
> the LLM detector slots into the *existing* `model_family()` harness as one more row.

## 1. Why these two pieces, in this project

This repo studies real-time anomaly detection + RCA on a 3-service mesh under
observability levels C1–C4. Two gaps motivate the additions:

| Piece | Role here | Research hook |
|-------|-----------|---------------|
| **Kafka** | A durable **event backbone** that carries telemetry windows, anomaly verdicts, and incidents between stages, decoupling collection / detection / reasoning. Turns the "online streaming pipeline" (already a per-window `partial_fit` loop in `ml/models/online.py`) into a *real* event stream rather than an in-process loop. | Makes RQ3's "online/streaming" claim architecturally honest; lets detection and LLM reasoning scale and fail independently. |
| **Local LLM** (Qwen2.5-3B via **Ollama**, optionally **LoRA**-tuned) | A second **binary anomaly detector** that reasons over the *raw* MELT signals of a window and answers only *anomalous or not* — **no fault typing**. Runs in parallel with the ML detector and is evaluated head-to-head against RF/GB/XGB/LSTM/fusion. | A new **model family** in RQ4 — "can a small local LLM reason over raw telemetry as well as engineered-feature classifiers?" LoRA measures how much task-specific tuning closes the gap. |

> **Scope note.** This project is *anomaly detection* (binary anomaly + RCA
> localisation), not incident management. There is no "incident" object or
> lifecycle: every detector — ML or LLM — emits the same binary `AnomalyEvent`.

## 2. Topics & message schemas

Two topics (prefix configurable via `TF_KAFKA_PREFIX`, default `tf`):

| Topic | Key | Producer | Consumers | Payload |
|-------|-----|----------|-----------|---------|
| `tf.telemetry.windows` | `service` | `streaming/producer_collector.py` | ML detector, LLM detector | a serialised `Window` (ts, service, label*, metrics/logs/traces/events) |
| `tf.anomalies` | `service` | **both** detectors: `consumer_detector.py` (OnlineModel, `detector="online_sgd"`) and `consumer_llm.py` (`detector="llm"`) | dashboards, comparison | `{ts, service, detector, y_pred, proba, model_version, signals, label}` |

Both detectors write the **same** binary `AnomalyEvent` to `tf.anomalies`, tagged
by `detector`, so their verdicts on each window are directly comparable. There is
no incident topic — the LLM is just another detector, not an incident producer.

`*label`: the ground-truth fault rides along on `telemetry.windows` only so the
**prequential** ML detector can `partial_fit` after predicting (test-then-train,
exactly as `OnlineModel.process_one`). In a true production deployment the label
arrives later on a separate `tf.labels` topic; the scaffold keeps it inline for
reproducibility, mirroring how `dataset.py` joins labels offline.

Schemas are defined once in `streaming/schemas.py` (dataclasses + `to_json`/`from_json`)
so producers and consumers cannot drift. `Window` (de)serialisation reuses the
existing `collectors.telemetry.Window` shape verbatim. The `signals` field is a
compact digest of the window's raw values, carried on each verdict for dashboards.

## 3. Dataflow (the full backbone)

```
                aiops/streaming/
producer_collector ──▶ tf.telemetry.windows
  (synthetic generate_run() OR live collect_window(TF_LIVE=1))
                              │
              ┌───────────────┴───────────────┐
              ▼                                ▼
consumer_detector                        consumer_llm
  OnlineModel.process_one(x,y)             LLMDetector.classify_named(signals)
              │                                │
              ▼                                ▼
   tf.anomalies (detector=online_sgd)   tf.anomalies (detector=llm)
              └───────────── binary verdicts ──┘
```

- **Bus abstraction** (`streaming/bus.py`): a thin `Producer`/`Consumer` over
  `kafka-python`. If the library or a broker is absent, it transparently falls
  back to an **in-process queue** (`InMemoryBus`) so the whole chain runs in one
  `pytest` with no Docker — the same "works offline by default" contract as the
  synthetic collectors. Each `(topic, group)` has its own cursor, so the two
  detectors consume the windows topic independently.
- **ML detector consumer** preserves the prequential protocol: predict the window
  with the pre-update champion, emit the verdict, *then* learn from the revealed
  label. State (`OnlineModel`) is per-service.
- **LLM detector consumer** scores each window independently (it does not gate on
  the ML detector) and emits its own binary verdict.

## 4. The LLM detector (`ml/models/llm_detector.py`)

Same call surface as the other detectors so it drops into `run_experiment.model_family()`:

Same call surface as the other detectors, and **binary only** (0/1) — no fault typing:

```python
m = LLMDetector()                     # binary anomaly detector
m.fit(Xtr, ytr, feat_names)           # caches scale + a few in-context exemplars
y = m.predict(Xte)                    # -> np.ndarray[int]  (0/1)
```

- **Inference path:** formats one window's raw signals into a compact prompt,
  calls Ollama `POST /api/chat` (`OLLAMA_URL`, default `http://localhost:11434`)
  with model `OLLAMA_MODEL` (default `qwen2.5:3b`), and parses a strict JSON reply
  `{"anomaly": bool, "confidence": 0-1}`.
- **Prompt:** a system rule sheet listing the *signs of abnormality* (derived from
  `collectors.telemetry._FAULT_SHIFT`) followed by a single binary question, plus a
  few in-context exemplars sampled at `fit()` from the training split. The fault
  signatures only guide the model's reasoning; the output is anomalous-or-not.
- **Fallback:** if Ollama is unreachable, `predict` returns a clearly-marked
  **z-score / rule-of-thumb** verdict — identical pattern to `TemporalModel`
  without torch, so results are never silently mistaken for a real LLM run. A
  `requires_llm` flag and a log line make the mode explicit.
- **Batching/caching:** per-window calls are cached on a quantised signal key to
  keep eval cheap; concurrency via a bounded thread pool (`LLM_CONCURRENCY`).

## 5. LoRA fine-tuning (`aiops/llm/`)

Goal: specialise Qwen2.5-3B on this mesh's fault signatures and measure the lift
over the base model in RQ4.

| Step | File | What |
|------|------|------|
| 1. Build SFT data | `llm/build_dataset.py` | `generate_run()` → JSONL of `{messages:[system,user(signals),assistant({"anomaly":bool,"confidence":..})]}`; stratified train/val split. |
| 2. Train adapter | `llm/train_lora.py` | `transformers` + `peft` (LoRA, r=16) + `trl.SFTTrainer`, 4-bit (`bitsandbytes`) on the VM1 GPU. Saves an adapter to `llm/adapters/qwen2.5-3b-traceflix/`. |
| 3. Serve via Ollama | `llm/Modelfile` + `llm/export_ollama.sh` | merge adapter → GGUF (llama.cpp) → `ollama create qwen2.5-3b-traceflix -f Modelfile`. The detector then points `OLLAMA_MODEL` at it. |

All heavy deps are isolated in `aiops/llm/requirements-llm.txt` (transformers,
peft, trl, bitsandbytes, datasets, accelerate) — **not** added to the core
`aiops/requirements.txt`, so the base pipeline stays lean.

## 6. Deployment (VM1 GPU overlay)

`deploy/virtfusion/vm1-gpu/docker-compose.kafka-llm.yml` adds, alongside the
existing `aiops` service and on the same Compose network:

- **kafka** — `bitnami/kafka` single-node **KRaft** (no ZooKeeper), bound to the
  VM's WireGuard IP only (same security posture as the rest of the overlay).
- **ollama** — `ollama/ollama` with `gpus: all`, model volume persisted; an init
  step pulls `qwen2.5:3b`.

The `aiops` service gains `TF_KAFKA_BOOTSTRAP`, `OLLAMA_URL`, `OLLAMA_MODEL` env.
Kafka co-locates on VM1 for a single-broker dev setup; for a data-tier split it
can move to VM3 by repointing `TF_KAFKA_BOOTSTRAP` — no code change.

## 7. How it maps to the paper / RQs

- **RQ3 (online vs offline under drift):** unchanged numbers, but the streaming
  story is now backed by a real broker — a deployment-architecture paragraph, not
  a new result.
- **RQ4 (model family):** **new rows** — `llm_qwen2.5_3b` (base) and
  `llm_qwen2.5_3b_lora` (tuned) beside RF/GB/XGB/LSTM/fusion, same C4 split, same
  `_metrics()`. This is the headline new result.
- No change to RQ1/RQ2 inputs or claims.

## 8. Run order (scaffold, no Docker needed)

```bash
cd aiops
# 1. end-to-end backbone on the in-memory bus (no Kafka, no Ollama required)
python -m streaming.run_pipeline --episodes 40

# 2. with a real broker + Ollama:
docker compose -f ../deploy/virtfusion/vm1-gpu/docker-compose.kafka-llm.yml up -d
TF_KAFKA_BOOTSTRAP=localhost:9092 OLLAMA_URL=http://localhost:11434 \
  python -m streaming.run_pipeline --episodes 40

# 3. LLM as an RQ4 model family (offline eval)
python -m ml.experiments.run_experiment --episodes 200   # now includes llm rows when ENABLE_LLM=1

# 4. LoRA fine-tune (GPU)
python -m llm.build_dataset --episodes 400 --out llm/data
python -m llm.train_lora    --data llm/data --out llm/adapters/qwen2.5-3b-traceflix
bash llm/export_ollama.sh
```

## 9. Open decisions (defaults chosen, easy to flip)

1. **LLM detector scope** — **binary anomaly only** (no fault typing), to stay
   within the project's anomaly-detection scope and keep F1 directly comparable to
   the other detectors.
2. **Parallel, not gated** — the LLM scores every window independently rather than
   only those the ML detector flags, so the two detectors are a fair head-to-head.
   (Real-Ollama cost is bounded by the quantised-signal cache + `LLM_CONCURRENCY`.)
3. **Kafka placement** — VM1 (default) vs VM3 data tier (env repoint).
```
