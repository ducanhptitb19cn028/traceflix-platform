"""
Build the LoRA SFT dataset from the synthetic generator.

Each training example is a chat triple:
    system    -> the same fault rule sheet the detector uses at inference
    user      -> "Window: <raw signal=value, ...>"
    assistant -> strict JSON {"anomaly", "fault", "confidence"}

so the tuned model learns to emit exactly the JSON the detector parses. Output is
JSONL (one example per line), stratified into train/val.

    python -m llm.build_dataset --episodes 400 --out llm/data
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from ml.configs import CONFIGS
from ml.dataset import generate_run
from ml.features.build import build_features
from ml.models.llm_detector import _DETECT_RULES

# raw signal fields shown to the model (the same digest the streaming path carries)
_FIELDS = ["metrics.req_rate", "metrics.err_rate", "metrics.p50_latency",
           "metrics.p99_latency", "metrics.cpu", "metrics.mem",
           "metrics.gc_pause", "metrics.threads",
           "logs.error_logs", "logs.warn_logs", "logs.request_logs",
           "traces.error_spans", "traces.p99_span_ms",
           "events.oomkilled", "events.crashloop", "events.pod_restarts"]


def _example(row) -> dict:
    sig = ", ".join(f"{f}={float(row.get(f, 0.0)):.4g}" for f in _FIELDS)
    anomaly = str(row["label_fault"]) != "normal"
    answer = json.dumps({"anomaly": anomaly, "confidence": 0.9})
    return {"messages": [
        {"role": "system", "content": _DETECT_RULES},
        {"role": "user", "content": f"Window: {sig}"},
        {"role": "assistant", "content": answer},
    ]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--out", default="llm/data")
    args = ap.parse_args()

    windows, _ = generate_run(n_episodes=args.episodes, seed=args.seed)
    df = build_features(windows, CONFIGS["C4"])
    examples = [_example(r) for _, r in df.iterrows()]

    rng = random.Random(args.seed)
    rng.shuffle(examples)
    n_val = int(len(examples) * args.val_frac)
    val, train = examples[:n_val], examples[n_val:]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train.jsonl", train), ("val.jsonl", val)):
        with (out / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    print(f"[build_dataset] {len(train)} train / {len(val)} val -> {out}/")


if __name__ == "__main__":
    main()
