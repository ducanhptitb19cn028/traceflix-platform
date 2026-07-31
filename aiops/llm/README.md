# LLM detector — local Qwen2.5-3B (Ollama) + LoRA

The detector itself lives in [`../ml/models/llm_detector.py`](../ml/models/llm_detector.py);
this folder is the **fine-tuning + serving** side of it. See the full design in
[`../docs/KAFKA_LLM_ARCHITECTURE.md`](../docs/KAFKA_LLM_ARCHITECTURE.md).

## What it is

An **LLM-based binary anomaly detector**: it reads the *raw* MELT signals of one
telemetry window and answers only *anomalous or not* (no fault typing), competing
with RF/GB/XGB/LSTM/fusion as a new RQ4 model family and running in parallel with
the online ML detector on the Kafka backbone. The base model already knows the
fault signatures from a rule sheet in the prompt; **LoRA** specialises it to this
mesh and is the measured "tuning lift".

## Inference (no training needed)

```bash
# 1. serve the base model
ollama serve &            # or the docker-compose service (deploy overlay)
ollama pull qwen2.5:3b

# 2. run it as an RQ4 model family (offline F1 vs the other detectors)
#    --out is NOT optional: run_experiment rewrites rq1/rq2/rq4/summary.json
#    wholesale, and data/results holds the committed artefacts behind the tables.
cd aiops
ENABLE_LLM=1 OLLAMA_URL=http://localhost:11434 OLLAMA_MODEL=qwen2.5:3b \
  python -m ml.experiments.run_experiment --episodes 200 --out data/results_llm

# 3. or as the LLM stage of the streaming backbone
OLLAMA_URL=http://localhost:11434 python -m streaming.run_pipeline --episodes 40
```

Without Ollama the detector reports a **clearly-marked heuristic** (z-score / rule
of thumb) so a fallback run is never mistaken for a real LLM run.

## What it scored

**F1 0.440** (precision 0.372, recall 0.540) on C4, from a served-model run with
**no failed call** — `data/results_llm/rq4_llm_row.csv`. Above the always-alarm floor
of 0.292; far below the ensemble trees at ~0.98. The honest reading is **a working
detector reading raw signals, not a competitive one**, and no tuning lift has been
measured — the LoRA arm below is implemented but was never run.

Three things must hold before that number is quoted:

1. **The row must say `(llm)`, never `(heuristic)`.** `LLMDetector.mode` is fixed at
   `__init__` and never re-checked, so an Ollama that was unreachable at start yields a
   full run of z-score verdicts under an LLM-looking name.
2. **`err=0`.** A per-window request failure returns `{"anomaly": false}` rather than
   raising, so losing the port-forward mid-run leaves the row labelled `(llm)` while
   recall silently collapses. Treat a near-zero recall as a transport fault, not a
   finding. The row name encodes both checks:
   `llm_qwen2.5:3b(llm,err=0/300,n=3000/6480)`.
3. **Compare it only against the matching subsample.** At ~9 s/window the LLM is scored
   on 3,000 windows; the paper's six-family table therefore uses
   `data/results_uniform/` for the other five so all six share one sample. Do not quote
   it against `data/results/rq4_model_family.csv`, which is the full split.

Because it consumes *raw*, attacker-influenceable log and trace text, it also carries a
**prompt-injection exposure** the feature-based classifiers do not — an open issue, not
a solved one.

## Fine-tune (GPU)

```bash
cd aiops
pip install -r llm/requirements-llm.txt

python -m llm.build_dataset --episodes 400 --out llm/data       # SFT JSONL
python -m llm.train_lora    --data llm/data \
       --out llm/adapters/qwen2.5-3b-traceflix                   # LoRA adapter
bash  llm/export_ollama.sh                                       # -> GGUF -> Ollama

# then evaluate the tuned model
OLLAMA_MODEL=qwen2.5-3b-traceflix ENABLE_LLM=1 \
  python -m ml.experiments.run_experiment --episodes 200
```

## Files

| File | Purpose |
|------|---------|
| `build_dataset.py` | `generate_run()` windows → chat-format SFT JSONL (train/val). |
| `train_lora.py` | transformers + peft (LoRA r=16) + trl SFTTrainer, 4-bit. Saves an adapter. |
| `export_ollama.sh` | merge adapter → GGUF (llama.cpp) → `ollama create`. |
| `Modelfile` | Ollama recipe for the merged GGUF. |
| `requirements-llm.txt` | GPU-only deps, kept out of core `aiops/requirements.txt`. |
