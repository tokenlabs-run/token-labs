#!/usr/bin/env python3
"""Prove that Token Labs rejects OpenRouter overload early instead of queueing.

The API key is read from an environment variable. Reports contain only timing,
status, and header-presence evidence; credentials and generated content are not
stored. Run only against an authorized benchmark deployment.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import os
import pathlib
import statistics
import sys
import threading
import time
from typing import Any

import requests


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * fraction + 0.999) - 1))
    return ordered[index]


def evaluate(results: list[dict[str, Any]], max_429_ms: float,
             expected_max_admitted: int) -> tuple[bool, list[str], dict[str, Any]]:
    statuses = [item["status_code"] for item in results]
    accepted = [item for item in results if item["status_code"] == 200]
    rejected = [item for item in results if item["status_code"] == 429]
    unexpected = [status for status in statuses if status not in (200, 429)]
    failures = []
    if not accepted:
        failures.append("no request was accepted")
    if not rejected:
        failures.append("no overload request received HTTP 429")
    if unexpected:
        failures.append(f"unexpected status codes: {sorted(set(unexpected))}")
    if len(accepted) > expected_max_admitted:
        failures.append(
            f"accepted {len(accepted)} requests; limit is {expected_max_admitted}"
        )
    missing_retry = sum(not item["retry_after_present"] for item in rejected)
    if missing_retry:
        failures.append(f"{missing_retry} HTTP 429 responses omitted Retry-After")
    rejected_ms = [item["headers_ms"] for item in rejected]
    p95_429_ms = percentile(rejected_ms, 0.95) if rejected_ms else None
    if p95_429_ms is not None and p95_429_ms > max_429_ms:
        failures.append(
            f"HTTP 429 p95 {p95_429_ms:.1f} ms exceeds {max_429_ms:.1f} ms"
        )
    summary = {
        "request_count": len(results),
        "accepted_200": len(accepted),
        "rejected_429": len(rejected),
        "unexpected_status_count": len(unexpected),
        "retry_after_missing": missing_retry,
        "p50_429_headers_ms": statistics.median(rejected_ms) if rejected_ms else None,
        "p95_429_headers_ms": p95_429_ms,
        "max_429_headers_ms": max(rejected_ms) if rejected_ms else None,
    }
    return not failures, failures, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True,
                        help="provider chat-completions URL")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="TOKENLABS_BENCH_API_KEY")
    parser.add_argument("--requests", type=int, default=24)
    parser.add_argument("--expected-max-admitted", type=int, default=16)
    parser.add_argument("--hold-seconds", type=float, default=5.0)
    parser.add_argument("--max-429-ms", type=float, default=1000.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    if args.requests <= args.expected_max_admitted:
        parser.error("requests must exceed expected-max-admitted")
    if min(args.expected_max_admitted, args.hold_seconds, args.max_429_ms,
           args.timeout) <= 0:
        parser.error("limits, hold time, and timeout must be positive")
    key = os.environ.get(args.api_key_env)
    if not key:
        parser.error(f"environment variable {args.api_key_env!r} is not set")

    barrier = threading.Barrier(args.requests)
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": "Count upward indefinitely."}],
        "max_tokens": 8192,
        "temperature": 0,
        "stream": True,
    }

    def one_request(index: int) -> dict[str, Any]:
        barrier.wait()
        started = time.perf_counter()
        try:
            response = requests.post(
                args.url,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
                stream=True,
                timeout=args.timeout,
            )
            headers_ms = (time.perf_counter() - started) * 1000
            result = {
                "index": index,
                "status_code": response.status_code,
                "headers_ms": headers_ms,
                "retry_after_present": "retry-after" in response.headers,
            }
            if response.status_code == 200:
                time.sleep(args.hold_seconds)
            response.close()
            return result
        except requests.RequestException as exc:
            return {
                "index": index,
                "status_code": 0,
                "headers_ms": (time.perf_counter() - started) * 1000,
                "retry_after_present": False,
                "error_type": type(exc).__name__,
            }

    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    with ThreadPoolExecutor(max_workers=args.requests) as executor:
        results = list(executor.map(one_request, range(args.requests)))
    passed, failures, summary = evaluate(
        results, args.max_429_ms, args.expected_max_admitted
    )
    report = {
        "schema_version": 1,
        "started_at_utc": started_at,
        "finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": args.url,
        "model": args.model,
        "expected_max_admitted": args.expected_max_admitted,
        "hold_seconds": args.hold_seconds,
        "max_429_ms": args.max_429_ms,
        "passed": passed,
        "failures": failures,
        "summary": summary,
        "requests": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": passed, **summary}, sort_keys=True))
    print(f"wrote {args.output}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
