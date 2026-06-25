#!/usr/bin/env bash
# Merge the LoRA adapter into Qwen2.5-3B, convert to GGUF, and register with Ollama.
#
#   bash aiops/llm/export_ollama.sh
#
# Prereqs: the adapter from train_lora.py, llama.cpp checked out (for the GGUF
# converter + quantiser), and `ollama` on PATH. Run from the repo root or aiops/.
set -euo pipefail

ADAPTER="${ADAPTER:-llm/adapters/qwen2.5-3b-traceflix}"
BASE="${BASE:-Qwen/Qwen2.5-3B-Instruct}"
MERGED="${MERGED:-llm/merged/qwen2.5-3b-traceflix}"
GGUF_DIR="${GGUF_DIR:-llm/gguf}"
LLAMA_CPP="${LLAMA_CPP:-$HOME/llama.cpp}"
OLLAMA_NAME="${OLLAMA_NAME:-qwen2.5-3b-traceflix}"

echo "[1/4] merge LoRA adapter -> full weights ($MERGED)"
python - "$BASE" "$ADAPTER" "$MERGED" <<'PY'
import sys
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
base, adapter, out = sys.argv[1:4]
tok = AutoTokenizer.from_pretrained(base)
model = AutoModelForCausalLM.from_pretrained(base, torch_dtype="auto")
model = PeftModel.from_pretrained(model, adapter)
model = model.merge_and_unload()
model.save_pretrained(out); tok.save_pretrained(out)
print("merged ->", out)
PY

echo "[2/4] convert merged weights -> GGUF (f16)"
mkdir -p "$GGUF_DIR"
python "$LLAMA_CPP/convert_hf_to_gguf.py" "$MERGED" \
  --outfile "$GGUF_DIR/qwen2.5-3b-traceflix-f16.gguf" --outtype f16

echo "[3/4] quantise -> q4_k_m"
"$LLAMA_CPP/build/bin/llama-quantize" \
  "$GGUF_DIR/qwen2.5-3b-traceflix-f16.gguf" \
  "$GGUF_DIR/qwen2.5-3b-traceflix-q4_k_m.gguf" Q4_K_M

echo "[4/4] register with Ollama as '$OLLAMA_NAME'"
cd "$(dirname "$0")"
ollama create "$OLLAMA_NAME" -f Modelfile
echo "done. Use:  OLLAMA_MODEL=$OLLAMA_NAME python -m streaming.run_pipeline"
