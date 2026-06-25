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
cd aiops
ENABLE_LLM=1 OLLAMA_URL=http://localhost:11434 OLLAMA_MODEL=qwen2.5:3b \
  python -m ml.experiments.run_experiment --episodes 200

# 3. or as the LLM stage of the streaming backbone
OLLAMA_URL=http://localhost:11434 python -m streaming.run_pipeline --episodes 40
```

Without Ollama the detector reports a **clearly-marked heuristic** (z-score / rule
of thumb) so a fallback run is never mistaken for a real LLM run.

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
