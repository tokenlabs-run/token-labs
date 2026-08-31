#!/usr/bin/env python3
"""Compare deterministic semantic probes and their KV-transfer counters."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def counter(path: Path, name: str, required_label: str | None = None) -> float:
    total = 0.0
    found = False
    for line in path.read_text().splitlines():
        if not line.startswith(name):
            continue
        if required_label is not None and required_label not in line:
            continue
        match = re.search(r"\s([^\s]+)$", line)
        if match:
            total += float(match.group(1))
            found = True
    if not found:
        raise ValueError(f"{name!r} not found in {path}")
    return total


def matching_prefix(left: list[str], right: list[str]) -> int:
    count = 0
    for left_token, right_token in zip(left, right):
        if left_token != right_token:
            break
        count += 1
    return count


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: analyze_semantic.py RAW_H200_ARTIFACT_DIR")
    root = Path(sys.argv[1])
    output: dict[str, object] = {}

    for probe in ("short", "long"):
        responses = {
            "heterogeneous": json.loads(
                (root / "hetero-semantic" / f"{probe}.response.json").read_text()
            ),
            "h200": json.loads(
                (root / "semantic-h200" / f"{probe}.response.json").read_text()
            ),
            "mi300x": json.loads(
                (root / "semantic-mi300x" / f"{probe}.response.json").read_text()
            ),
        }
        choices = {name: doc["choices"][0] for name, doc in responses.items()}
        tokens = {name: choice["logprobs"]["tokens"] for name, choice in choices.items()}
        before = root / "hetero-semantic" / f"{probe}.before.prom"
        after = root / "hetero-semantic" / f"{probe}.after.prom"

        external = counter(
            after,
            "vllm:prompt_tokens_by_source_total",
            'source="external_kv_transfer"',
        ) - counter(
            before,
            "vllm:prompt_tokens_by_source_total",
            'source="external_kv_transfer"',
        )
        prefix = counter(after, "vllm:prefix_cache_hits_total") - counter(
            before, "vllm:prefix_cache_hits_total"
        )
        hetero_choice = choices["heterogeneous"]
        comparisons = {}
        for baseline in ("h200", "mi300x"):
            comparisons[baseline] = {
                "exact_text": hetero_choice["text"] == choices[baseline]["text"],
                "matching_prefix_tokens": matching_prefix(
                    tokens["heterogeneous"], tokens[baseline]
                ),
                "output_tokens": len(tokens["heterogeneous"]),
            }

        output[probe] = {
            "prompt_tokens": responses["heterogeneous"]["usage"]["prompt_tokens"],
            "completion_tokens": responses["heterogeneous"]["usage"][
                "completion_tokens"
            ],
            "external_kv_tokens": int(external),
            "verified_transfer_bytes": ((int(external) + 15) // 16) * 16 * 98_304,
            "local_prefix_hit_tokens": int(prefix),
            "comparisons": comparisons,
        }

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
