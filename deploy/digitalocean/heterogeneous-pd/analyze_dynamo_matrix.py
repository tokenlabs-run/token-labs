#!/usr/bin/env python3
"""Validate Dynamo P/D results and Mooncake transfer-byte accounting."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

KV_BYTES_PER_TOKEN = 98_304
POINT_RE = re.compile(r"isl(?P<isl>\d+)-osl(?P<osl>\d+)-c(?P<c>\d+)\.json$")
TRANSFER_RE = re.compile(
    r"Num successful transfers=(?P<success>\d+),.*?"
    r"Avg MB per transfer=(?P<mb>[0-9.]+),.*?"
    r"Num failed transfers=(?P<failed>\d+)"
)
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


def main() -> int:
    if len(sys.argv) not in (2, 3, 4):
        raise SystemExit(
            "usage: analyze_dynamo_matrix.py RESULT_DIR "
            "[PREFILL_BENCHMARK_LOG] [WIRE_PROBE_DIR]"
        )
    root = Path(sys.argv[1])
    transfer_log = Path(sys.argv[2]) if len(sys.argv) >= 3 else None
    wire_probe_dir = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    rows: list[dict[str, object]] = []
    failures: list[str] = []
    observed_points: set[tuple[int, int, int]] = set()
    total_input_tokens = 0

    for result_path in sorted(root.glob("isl*-osl*-c*.json"), key=point_key):
        match = POINT_RE.match(result_path.name)
        if match is None:
            continue
        isl, osl, concurrency = (int(match.group(k)) for k in ("isl", "osl", "c"))
        observed_points.add((isl, osl, concurrency))
        result = json.loads(result_path.read_text())
        expected_input = isl * concurrency
        expected_output = osl * concurrency
        checks = {
            "completed": result["completed"] == concurrency,
            "failed": result["failed"] == 0,
            "input_tokens": result["total_input_tokens"] == expected_input,
            "output_tokens": result["total_output_tokens"] == expected_output,
        }
        if not all(checks.values()):
            failures.append(f"{result_path.stem}: {checks}")
        total_input_tokens += int(result["total_input_tokens"])
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
                "expected_transfer_bytes": expected_input * KV_BYTES_PER_TOKEN,
                "validated": all(checks.values()),
            }
        )

    missing = set(EXPECTED_POINTS) - observed_points
    unexpected = observed_points - set(EXPECTED_POINTS)
    if missing:
        failures.append(f"missing matrix points: {sorted(missing)}")
    if unexpected:
        failures.append(f"unexpected matrix points: {sorted(unexpected)}")

    expected_bytes = total_input_tokens * KV_BYTES_PER_TOKEN
    observed_bytes: int | None = None
    transfer_failures: int | None = None
    if transfer_log is not None:
        observed_bytes = 0
        transfer_failures = 0
        for match in TRANSFER_RE.finditer(transfer_log.read_text()):
            observed_bytes += round(
                int(match.group("success"))
                * float(match.group("mb"))
                * 1024
                * 1024
            )
            transfer_failures += int(match.group("failed"))
        if transfer_failures != 0:
            failures.append(f"Mooncake reported {transfer_failures} failed transfers")

    wire_probes: list[dict[str, object]] = []
    if wire_probe_dir is not None:
        probe_log = (wire_probe_dir / "mooncake-prefill.log").read_text()
        probe_records = [
            (
                int(match.group("success")),
                float(match.group("mb")),
                int(match.group("failed")),
            )
            for match in TRANSFER_RE.finditer(probe_log)
        ]
        for isl in (1024, 8192):
            expected_payload = isl * KV_BYTES_PER_TOKEN
            result = json.loads((wire_probe_dir / f"isl{isl}.json").read_text())
            tcp_payload = int(
                (wire_probe_dir / f"isl{isl}.tcp-payload-delta.txt")
                .read_text()
                .strip()
            )
            overhead = tcp_payload - expected_payload
            overhead_ratio = overhead / expected_payload
            expected_mb = expected_payload / 1024**2
            mooncake_recorded = any(
                success == 1 and mb == expected_mb and failed == 0
                for success, mb, failed in probe_records
            )
            probe_valid = all(
                (
                    result["completed"] == 1,
                    result["failed"] == 0,
                    result["total_input_tokens"] == isl,
                    result["total_output_tokens"] == 1,
                    mooncake_recorded,
                    0 <= overhead_ratio <= 0.01,
                )
            )
            if not probe_valid:
                failures.append(f"isl{isl} wire-byte probe failed validation")
            wire_probes.append(
                {
                    "isl": isl,
                    "expected_kv_payload_bytes": expected_payload,
                    "mooncake_reported_mib": expected_mb if mooncake_recorded else None,
                    "tcp_payload_bytes": tcp_payload,
                    "protocol_overhead_bytes": overhead,
                    "protocol_overhead_percent": overhead_ratio * 100,
                    "validated": probe_valid,
                }
            )

    if rows:
        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "matrix_points": len(rows),
        "requests": sum(int(row["requests"]) for row in rows),
        "input_tokens": total_input_tokens,
        "expected_transfer_bytes": expected_bytes,
        "expected_transfer_gib": expected_bytes / 1024**3,
        "mooncake_sampled_transfer_bytes": observed_bytes,
        "mooncake_sampled_coverage_percent": (
            observed_bytes / expected_bytes * 100
            if observed_bytes is not None and expected_bytes
            else None
        ),
        "mooncake_failed_transfers": transfer_failures,
        "wire_byte_probes": wire_probes,
        "validated": not failures,
    }
    print(json.dumps(summary, indent=2), file=sys.stderr)
    if failures:
        print("VALIDATION FAILURES", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
