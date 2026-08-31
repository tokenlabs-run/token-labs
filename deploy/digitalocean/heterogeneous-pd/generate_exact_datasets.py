#!/usr/bin/env python3
"""Generate tokenizer-stable exact-length prompts for the Dynamo benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from transformers import AutoTokenizer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--model", default="Qwen/Qwen3-30B-A3B-Instruct-2507-FP8"
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model)

    for token_count in (1024, 8192):
        prompt = " hello" * token_count
        actual = len(tokenizer.encode(prompt))
        if actual != token_count:
            raise RuntimeError(
                f"stable prompt check failed: wanted {token_count}, got {actual}"
            )
        path = args.output_dir / f"isl{token_count}.jsonl"
        path.write_text(json.dumps({"prompt": prompt}) + "\n")
        print(f"{path}: {actual} tokens")


if __name__ == "__main__":
    main()
