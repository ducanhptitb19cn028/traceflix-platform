"""
LoRA fine-tuning harness for the local Qwen2.5-3B fault detector.

  build_dataset.py  -- generate_run() windows -> chat-format SFT JSONL
  train_lora.py     -- transformers + peft (LoRA) + trl SFTTrainer, 4-bit on GPU
  Modelfile         -- Ollama recipe for the merged GGUF
  export_ollama.sh  -- merge adapter -> GGUF -> `ollama create`

Heavy deps live in requirements-llm.txt, kept out of the core aiops requirements.
See ../docs/KAFKA_LLM_ARCHITECTURE.md §5.
"""
