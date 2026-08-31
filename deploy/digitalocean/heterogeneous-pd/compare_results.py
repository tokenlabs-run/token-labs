#!/usr/bin/env python3
"""Compare heterogeneous P/D results with H200 and MI300X monolithic runs."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

POINTS = [
    (isl, osl, concurrency)
    for isl, osl in ((1024, 8192), (8192, 8192), (8192, 1024))
    for concurrency in (1, 2, 4, 8, 16, 32, 64)
]


def load(root: Path, point: tuple[int, int, int]) -> dict[str, object]:
    isl, osl, concurrency = point
    path = root / f"isl{isl}-osl{osl}-c{concurrency}.json"
    data = json.loads(path.read_text())
    if data["completed"] != concurrency or data["failed"] != 0:
        raise ValueError(
            f"{path}: completed={data['completed']} failed={data['failed']}"
        )
    return data


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: compare_results.py HETERO_DIR H200_BASELINE_DIR MI300X_BASELINE_DIR"
        )
    roots = [Path(arg) for arg in sys.argv[1:]]
    rows: list[dict[str, object]] = []

    for point in POINTS:
        isl, osl, concurrency = point
        hetero, h200, mi300x = (load(root, point) for root in roots)
        hetero_text = hetero["generated_texts"]
        h200_text = h200["generated_texts"]
        mi300x_text = mi300x["generated_texts"]
        rows.append(
            {
                "isl": isl,
                "osl": osl,
                "concurrency": concurrency,
                "hetero_output_tps": round(hetero["output_throughput"], 3),
                "h200_output_tps": round(h200["output_throughput"], 3),
                "mi300x_output_tps": round(mi300x["output_throughput"], 3),
                "hetero_vs_h200_tps": round(
                    hetero["output_throughput"] / h200["output_throughput"], 4
                ),
                "hetero_vs_mi300x_tps": round(
                    hetero["output_throughput"] / mi300x["output_throughput"], 4
                ),
                "hetero_median_ttft_ms": round(hetero["median_ttft_ms"], 3),
                "h200_median_ttft_ms": round(h200["median_ttft_ms"], 3),
                "mi300x_median_ttft_ms": round(mi300x["median_ttft_ms"], 3),
                "hetero_median_tpot_ms": round(hetero["median_tpot_ms"], 3),
                "h200_median_tpot_ms": round(h200["median_tpot_ms"], 3),
                "mi300x_median_tpot_ms": round(mi300x["median_tpot_ms"], 3),
                "exact_text_matches_h200": sum(
                    left == right for left, right in zip(hetero_text, h200_text)
                ),
                "exact_text_matches_mi300x": sum(
                    left == right for left, right in zip(hetero_text, mi300x_text)
                ),
                "requests": concurrency,
            }
        )

    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
