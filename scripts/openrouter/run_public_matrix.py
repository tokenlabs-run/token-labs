#!/usr/bin/env python3
"""Run and strictly validate Tokenlabs' public-path OpenRouter capacity matrix.

The API key is read from an environment variable and is never written to the
command/provenance record. Each point is resumable only after its AIPerf export
passes request-count, error, and exact synthetic token-length validation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import subprocess
import sys
from typing import Any


DEFAULT_MODEL = "qwen/qwen3-30b-a3b-instruct-2507"
DEFAULT_TOKENIZER = "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8"
PROFILES = {
    "interactive": (512, 128),
    "tool-use": (1024, 256),
    "balanced": (2048, 1024),
    "long-prefill": (8192, 512),
    "long-decode": (1024, 8192),
    "long-mixed": (8192, 8192),
}
DEFAULT_PROFILES = ("interactive", "tool-use", "balanced", "long-prefill")
DEFAULT_CONCURRENCIES = (1, 2, 4, 8, 16, 32, 64)


def metric_value(data: dict[str, Any], name: str, statistic: str = "avg") -> float:
    value = (data.get(name) or {}).get(statistic)
    if value is None:
        raise ValueError(f"missing metric {name}.{statistic}")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"invalid metric {name}.{statistic}: {value!r}")
    return number


def validate_export(
    path: pathlib.Path,
    *,
    minimum_requests: int,
    isl: int,
    osl: int,
) -> dict[str, Any]:
    data = json.loads(path.read_text())
    errors = data.get("error_summary")
    if errors:
        raise ValueError(f"{path}: benchmark errors: {errors}")
    completed = metric_value(data, "request_count")
    if completed < minimum_requests:
        raise ValueError(
            f"{path}: completed {completed:g}, require at least {minimum_requests}"
        )
    for metric, expected in (
        ("input_sequence_length", isl),
        ("output_sequence_length", osl),
    ):
        observed = {
            statistic: metric_value(data, metric, statistic)
            for statistic in ("avg", "min", "max")
        }
        if any(abs(value - expected) > 0.01 for value in observed.values()):
            raise ValueError(
                f"{path}: {metric} mismatch: {observed}, expected {expected}"
            )
    for metric, statistic in (
        ("output_token_throughput", "avg"),
        ("output_token_throughput_per_user", "avg"),
        ("time_to_first_token", "p50"),
        ("time_to_first_token", "p95"),
        ("inter_token_latency", "p50"),
        ("request_latency", "p50"),
    ):
        metric_value(data, metric, statistic)
    return data


def parse_int_list(value: str) -> tuple[int, ...]:
    values = tuple(int(item) for item in value.split(","))
    if not values or any(item < 1 for item in values):
        raise argparse.ArgumentTypeError("expected comma-separated positive integers")
    return values


def redacted_command(command: list[str]) -> list[str]:
    result = list(command)
    if "--api-key" in result:
        result[result.index("--api-key") + 1] = "<redacted>"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="public API base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--tokenizer", default=DEFAULT_TOKENIZER)
    parser.add_argument("--label", default="qwen3-fp8-vllm")
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument(
        "--aiperf", default="/home/nvidia/aiperf-venv/bin/aiperf"
    )
    parser.add_argument(
        "--api-key-env",
        default="TOKENLABS_BENCH_API_KEY",
        help="environment variable containing the bearer token",
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=tuple(PROFILES),
        help="repeat to select profiles; defaults to four production profiles",
    )
    parser.add_argument(
        "--concurrencies",
        type=parse_int_list,
        default=DEFAULT_CONCURRENCIES,
    )
    parser.add_argument("--minimum-requests", type=int, default=100)
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="steady-state seconds; 0 runs solely to the request-count target",
    )
    parser.add_argument("--request-timeout", type=int, default=7200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.minimum_requests < 1:
        parser.error("--minimum-requests must be positive")
    if args.duration < 0:
        parser.error("--duration cannot be negative")

    api_key = os.environ.get(args.api_key_env)
    if not api_key and not args.dry_run:
        parser.error(f"environment variable {args.api_key_env!r} is not set")

    selected_profiles = tuple(args.profile or DEFAULT_PROFILES)
    args.out.mkdir(parents=True, exist_ok=True)
    suite_record = {
        "schema_version": 1,
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": args.url,
        "model": args.model,
        "tokenizer": args.tokenizer,
        "label": args.label,
        "profiles": {name: PROFILES[name] for name in selected_profiles},
        "concurrencies": args.concurrencies,
        "minimum_requests": args.minimum_requests,
        "duration_seconds": args.duration,
        "api_key_env": args.api_key_env,
        "authentication": "bearer token present" if api_key else "dry-run only",
    }
    (args.out / "suite.json").write_text(json.dumps(suite_record, indent=2) + "\n")

    for profile in selected_profiles:
        isl, osl = PROFILES[profile]
        for concurrency in args.concurrencies:
            point = f"{profile}__{args.label}-c{concurrency}"
            point_dir = args.out / point
            export = point_dir / "profile_export_aiperf.json"
            if export.exists():
                validate_export(
                    export,
                    minimum_requests=args.minimum_requests,
                    isl=isl,
                    osl=osl,
                )
                print(f"RESUME {point}: valid export", flush=True)
                continue

            command = [
                args.aiperf,
                "profile",
                "--model",
                args.model,
                "--url",
                args.url,
                "--endpoint-type",
                "chat",
                "--streaming",
                "--api-key",
                api_key or "<dry-run>",
                "--concurrency",
                str(concurrency),
                "--num-warmup-requests",
                str(max(1, min(concurrency, 8))),
                "--synthetic-input-tokens-mean",
                str(isl),
                "--synthetic-input-tokens-stddev",
                "0",
                "--output-tokens-mean",
                str(osl),
                "--output-tokens-stddev",
                "0",
                "--num-dataset-entries",
                str(args.minimum_requests + max(1, min(concurrency, 8))),
                "--tokenizer",
                args.tokenizer,
                "--use-server-token-count",
                "--use-legacy-max-tokens",
                "--random-seed",
                "42",
                "--extra-inputs",
                json.dumps({"ignore_eos": True, "temperature": 0}),
                "--request-timeout-seconds",
                str(args.request_timeout),
                "--artifact-dir",
                str(point_dir),
            ]
            if args.duration:
                command.extend(("--benchmark-duration", str(args.duration)))
            else:
                command.extend(("--request-count", str(args.minimum_requests)))

            command_record = {
                "profile": profile,
                "input_tokens": isl,
                "output_tokens": osl,
                "concurrency": concurrency,
                "minimum_requests": args.minimum_requests,
                "duration_seconds": args.duration,
                "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "command": redacted_command(command),
            }
            (args.out / f"{point}.command.json").write_text(
                json.dumps(command_record, indent=2) + "\n"
            )
            print(f"START {point}", flush=True)
            if args.dry_run:
                print(" ".join(redacted_command(command)), flush=True)
                continue

            with (args.out / f"{point}.log").open("w") as log:
                result = subprocess.run(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=max(args.request_timeout * 2, args.duration + 3600),
                    check=False,
                )
            if result.returncode:
                raise RuntimeError(
                    f"{point} failed with exit {result.returncode}; see its log"
                )
            validate_export(
                export,
                minimum_requests=args.minimum_requests,
                isl=isl,
                osl=osl,
            )
            print(f"OK {point}", flush=True)

    print("COMPLETE public-path matrix", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
