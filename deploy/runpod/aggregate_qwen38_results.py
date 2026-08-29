#!/usr/bin/env python3
"""Normalize vLLM benchmark JSON files for the tokenlabs.run Pareto chart."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

NAME = re.compile(
    r"(?P<label>.+)-isl(?P<isl>\d+)-osl(?P<osl>\d+)-c(?P<concurrency>\d+)\.json$"
)


def normalize(path: Path) -> tuple[str, str, dict]:
    match = NAME.fullmatch(path.name)
    if not match:
        raise ValueError(f"unexpected result filename: {path.name}")
    raw = json.loads(path.read_text())
    if raw.get("failed") or raw.get("completed") != raw.get("num_prompts"):
        raise ValueError(f"incomplete benchmark result: {path}")
    label = match["label"]
    scenario = f"ISL{match['isl']}/OSL{match['osl']}"
    tpot = float(raw["median_tpot_ms"])
    row = {
        "concurrency": int(match["concurrency"]),
        "requests": int(raw["completed"]),
        "duration_s": round(float(raw["duration"]), 3),
        "tput_total": round(float(raw["output_throughput"]), 3),
        "tput_per_user": round(1000.0 / tpot, 3),
        "ttft_p50": round(float(raw["median_ttft_ms"]), 3),
        "ttft_p99": round(float(raw["p99_ttft_ms"]), 3),
        "tpot_p50": round(tpot, 3),
        "tpot_p99": round(float(raw["p99_tpot_ms"]), 3),
        "itl_p50": round(float(raw["median_itl_ms"]), 3),
        "itl_p99": round(float(raw["p99_itl_ms"]), 3),
        "errors": int(raw["failed"]),
    }
    return scenario, label, row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result: dict[str, dict[str, list[dict]]] = {}
    for root in args.inputs:
        for path in sorted(root.glob("*.json")):
            scenario, label, row = normalize(path)
            result.setdefault(scenario, {}).setdefault(label, []).append(row)
    for by_label in result.values():
        for rows in by_label.values():
            rows.sort(key=lambda row: row["concurrency"])
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
