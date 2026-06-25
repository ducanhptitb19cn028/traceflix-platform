"""
LoRA fine-tune Qwen2.5-3B on the TraceFlix fault-detection SFT set.

Uses transformers + peft (LoRA) + trl SFTTrainer with optional 4-bit quantisation
(bitsandbytes) so a 3B model trains comfortably on the VM1 GPU (see deploy README).
Saves a LoRA adapter only -- merge to GGUF for Ollama with export_ollama.sh.

    python -m llm.train_lora --data llm/data --out llm/adapters/qwen2.5-3b-traceflix

Requires aiops/llm/requirements-llm.txt. This script intentionally fails fast with
a clear message if those libs are absent (it is GPU-side tooling, not part of the
core offline pipeline).
"""
from __future__ import annotations

import argparse


def _require(mod: str):
    try:
        return __import__(mod)
    except ImportError as e:  # pragma: no cover - environment dependent
        raise SystemExit(
            f"[train_lora] missing '{mod}'. Install GPU deps:\n"
            f"    pip install -r aiops/llm/requirements-llm.txt"
        ) from e


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-3B-Instruct")
    ap.add_argument("--data", default="llm/data")
    ap.add_argument("--out", default="llm/adapters/qwen2.5-3b-traceflix")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--no-4bit", action="store_true")
    args = ap.parse_args()

    _require("torch")
    _require("transformers")
    _require("peft")
    _require("trl")
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)
    from trl import SFTConfig, SFTTrainer
    import torch

    quant = None
    if not args.no_4bit:
        quant = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )

    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, quantization_config=quant, device_map="auto",
        torch_dtype=torch.bfloat16,
    )

    ds = load_dataset("json", data_files={
        "train": f"{args.data}/train.jsonl",
        "validation": f"{args.data}/val.jsonl",
    })

    lora = LoraConfig(
        r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )

    cfg = SFTConfig(
        output_dir=args.out, num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=2, learning_rate=args.lr,
        logging_steps=10, save_strategy="epoch", eval_strategy="epoch",
        bf16=True, packing=False, max_length=1024,
    )

    trainer = SFTTrainer(
        model=model, args=cfg, peft_config=lora,
        train_dataset=ds["train"], eval_dataset=ds["validation"],
        processing_class=tok,
    )
    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    print(f"[train_lora] adapter saved -> {args.out}")
    print("[train_lora] next: bash aiops/llm/export_ollama.sh")


if __name__ == "__main__":
    main()
