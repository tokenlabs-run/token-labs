#!/usr/bin/env python3
"""Aggregate public-path suites and select only an admissible throughput winner.

This tool evaluates performance and latency gates. It deliberately does not
claim launch readiness: license, API/tool conformance, quality, reliability
soak, and unit economics are independent gates in the provider plan.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from typing import Any

from run_public_matrix import metric_value, validate_export


PRIMARY_PROFILES = ("interactive", "tool-use", "balanced", "long-prefill")
TTFT_P95_LIMIT_MS = {
    "interactive": 2_000.0,
    "tool-use": 2_000.0,
    "balanced": 5_000.0,
    "long-prefill": 15_000.0,
}


def geometric_mean(values: list[float]) -> float:
    if not values or any(value <= 0 or not math.isfinite(value) for value in values):
        raise ValueError("geometric mean requires finite positive values")
    return math.exp(sum(math.log(value) for value in values) / len(values))


def point_from_export(
    path: pathlib.Path,
    *,
    profile: str,
    concurrency: int,
    minimum_requests: int,
    isl: int,
    osl: int,
) -> dict[str, Any]:
    data = validate_export(
        path,
        minimum_requests=minimum_requests,
        isl=isl,
        osl=osl,
    )
    ttft_p95 = metric_value(data, "time_to_first_token", "p95")
    limit = TTFT_P95_LIMIT_MS.get(profile)
    gate_reasons = []
    if limit is not None and ttft_p95 > limit:
        gate_reasons.append(f"ttft_p95_ms {ttft_p95:.3f} exceeds {limit:.3f}")
    return {
        "profile": profile,
        "concurrency": concurrency,
        "input_tokens": isl,
        "output_tokens": osl,
        "completed_requests": int(metric_value(data, "request_count")),
        "output_tokens_per_second": metric_value(data, "output_token_throughput"),
        "per_user_output_tokens_per_second": metric_value(
            data, "output_token_throughput_per_user"
        ),
        "ttft_p50_ms": metric_value(data, "time_to_first_token", "p50"),
        "ttft_p95_ms": ttft_p95,
        "itl_p50_ms": metric_value(data, "inter_token_latency", "p50"),
        "request_latency_p50_ms": metric_value(data, "request_latency", "p50"),
        "performance_gate_passed": not gate_reasons,
        "performance_gate_reasons": gate_reasons,
        "source": str(path),
    }


def select_candidate(
    points: list[dict[str, Any]],
    *,
    profiles: tuple[str, ...] = PRIMARY_PROFILES,
) -> dict[str, Any]:
    by_key = {(point["profile"], point["concurrency"]): point for point in points}
    concurrency_values = sorted({point["concurrency"] for point in points})
    evaluated = []
    for concurrency in concurrency_values:
        selected = [by_key.get((profile, concurrency)) for profile in profiles]
        missing = [profile for profile, point in zip(profiles, selected) if point is None]
        failures = [
            point["profile"]
            for point in selected
            if point is not None and not point["performance_gate_passed"]
        ]
        eligible = not missing and not failures
        score = None
        if eligible:
            score = geometric_mean(
                [point["output_tokens_per_second"] for point in selected if point]
            )
        evaluated.append(
            {
                "concurrency": concurrency,
                "eligible": eligible,
                "missing_profiles": missing,
                "failed_profiles": failures,
                "primary_throughput_geomean": score,
            }
        )
    eligible = [item for item in evaluated if item["eligible"]]
    chosen = max(eligible, key=lambda item: item["concurrency"]) if eligible else None
    return {
        "performance_gate_passed": chosen is not None,
        "admissible_concurrency": chosen["concurrency"] if chosen else None,
        "primary_throughput_geomean": (
            chosen["primary_throughput_geomean"] if chosen else None
        ),
        "evaluated_concurrencies": evaluated,
    }


def load_suite(root: pathlib.Path) -> dict[str, Any]:
    suite_path = root / "suite.json"
    if not suite_path.is_file():
        raise ValueError(f"missing suite manifest: {suite_path}")
    suite = json.loads(suite_path.read_text())
    profiles = suite.get("profiles") or {}
    concurrencies = suite.get("concurrencies") or []
    minimum_requests = int(suite.get("minimum_requests", 0))
    if minimum_requests < 1:
        raise ValueError(f"{suite_path}: invalid minimum_requests")
    points = []
    missing = []
    for profile, lengths in profiles.items():
        isl, osl = map(int, lengths)
        for concurrency in map(int, concurrencies):
            name = f"{profile}__{suite['label']}-c{concurrency}"
            export = root / name / "profile_export_aiperf.json"
            if not export.is_file():
                missing.append(name)
                continue
            points.append(
                point_from_export(
                    export,
                    profile=profile,
                    concurrency=concurrency,
                    minimum_requests=minimum_requests,
                    isl=isl,
                    osl=osl,
                )
            )
    selection = select_candidate(points)
    return {
        "label": suite["label"],
        "model": suite["model"],
        "url": suite["url"],
        "root": str(root),
        "complete": not missing,
        "missing": missing,
        "points": points,
        "selection": selection,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    candidates = [load_suite(root) for root in args.roots]
    incomplete = [candidate["label"] for candidate in candidates if not candidate["complete"]]
    if incomplete and not args.allow_partial:
        raise SystemExit(f"incomplete suites: {', '.join(incomplete)}")
    eligible = [
        candidate
        for candidate in candidates
        if candidate["complete"] and candidate["selection"]["performance_gate_passed"]
    ]
    winner = None
    if eligible:
        winner = max(
            eligible,
            key=lambda candidate: candidate["selection"]["primary_throughput_geomean"],
        )["label"]
    payload = {
        "schema_version": 1,
        "scope": "performance and latency gates only; not launch readiness",
        "primary_profiles": list(PRIMARY_PROFILES),
        "ttft_p95_limits_ms": TTFT_P95_LIMIT_MS,
        "complete": not incomplete,
        "throughput_winner": winner,
        "candidates": candidates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"wrote {args.output}; complete={payload['complete']}; "
        f"throughput_winner={winner}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
