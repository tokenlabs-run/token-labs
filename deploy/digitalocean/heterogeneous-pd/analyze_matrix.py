#!/usr/bin/env python3
"""Validate a heterogeneous P/D matrix and emit a compact CSV summary."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

KV_BYTES_PER_TOKEN = 98_304
POINT_RE = re.compile(r"isl(?P<isl>\d+)-osl(?P<osl>\d+)-c(?P<c>\d+)\.json$")
EXPECTED_POINTS = [
    (isl, osl, concurrency)
    for isl, osl in ((1024, 8192), (8192, 8192), (8192, 1024))
    for concurrency in (1, 2, 4, 8, 16, 32, 64)
]
SHAPE_ORDER = {(1024, 8192): 0, (8192, 8192): 1, (8192, 1024): 2}


def point_key(path: Path) -> tuple[int, int]:
    match = POINT_RE.match(path.name)
    if match is None:
        return (len(SHAPE_ORDER), 0)
    isl, osl, concurrency = (int(match.group(k)) for k in ("isl", "osl", "c"))
    return (SHAPE_ORDER.get((isl, osl), len(SHAPE_ORDER)), concurrency)


def metric(path: Path, name: str, labels: str = "") -> float:
    pattern = re.compile(
        rf"^{re.escape(name)}(?:\{{(?=[^}}]*{re.escape(labels)})[^}}]*\}})?\s+([^\s]+)$"
    )
    for line in path.read_text().splitlines():
        match = pattern.match(line)
        if match:
            return float(match.group(1))
    raise ValueError(f"metric {name!r} labels {labels!r} missing from {path}")


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    rows: list[dict[str, object]] = []
    failures: list[str] = []
    observed_points: set[tuple[int, int, int]] = set()

    for result_path in sorted(root.glob("isl*-osl*-c*.json"), key=point_key):
        match = POINT_RE.match(result_path.name)
        if not match:
            continue
        isl, osl, concurrency = (int(match.group(k)) for k in ("isl", "osl", "c"))
        observed_points.add((isl, osl, concurrency))
        stem = result_path.stem
        before = root / f"{stem}.before.prom"
        after = root / f"{stem}.after.prom"
        result = json.loads(result_path.read_text())

        external_name = "vllm:prompt_tokens_by_source_total"
        external_labels = 'source="external_kv_transfer"'
        prefix_name = "vllm:prefix_cache_hits_total"
        external_tokens = metric(after, external_name, external_labels) - metric(
            before, external_name, external_labels
        )
        local_prefix_tokens = metric(after, prefix_name) - metric(before, prefix_name)
        expected_input = isl * concurrency
        expected_output = osl * concurrency
        checks = {
            "completed": result["completed"] == concurrency,
            "failed": result["failed"] == 0,
            "input_tokens": result["total_input_tokens"] == expected_input,
            "output_tokens": result["total_output_tokens"] == expected_output,
            "external_tokens": external_tokens == expected_input,
            "prefix_cache_disabled": local_prefix_tokens == 0,
        }
        if not all(checks.values()):
            failures.append(f"{stem}: {checks}")

        rows.append(
            {
                "isl": isl,
                "osl": osl,
                "concurrency": concurrency,
                "requests": result["completed"],
                "failures": result["failed"],
                "duration_s": round(result["duration"], 3),
                "request_throughput_rps": round(result["request_throughput"], 4),
                "output_throughput_tps": round(result["output_throughput"], 3),
                "median_ttft_ms": round(result["median_ttft_ms"], 3),
                "p99_ttft_ms": round(result["p99_ttft_ms"], 3),
                "median_tpot_ms": round(result["median_tpot_ms"], 3),
                "p99_tpot_ms": round(result["p99_tpot_ms"], 3),
                "external_kv_tokens": int(external_tokens),
                "verified_transfer_bytes": int(external_tokens) * KV_BYTES_PER_TOKEN,
                "local_prefix_hit_tokens": int(local_prefix_tokens),
                "validated": all(checks.values()),
            }
        )

    if not rows:
        raise SystemExit(f"no result JSON files found under {root}")
    missing = set(EXPECTED_POINTS) - observed_points
    unexpected = observed_points - set(EXPECTED_POINTS)
    if missing:
        failures.append(f"missing matrix points: {sorted(missing)}")
    if unexpected:
        failures.append(f"unexpected matrix points: {sorted(unexpected)}")
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    if failures:
        print("\nVALIDATION FAILURES", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"validated {len(rows)} matrix points", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
