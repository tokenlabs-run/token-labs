#!/usr/bin/env python3
"""Run a resumable, configuration-driven NVIDIA AIPerf serving matrix."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import shlex
import subprocess
import time
import urllib.request


def load_config(path: pathlib.Path) -> dict:
    cfg = json.loads(path.read_text())
    required = ("tokenizer", "workloads", "concurrencies", "backends")
    missing = [key for key in required if not cfg.get(key)]
    if missing:
        raise ValueError(f"missing config fields: {', '.join(missing)}")
    names = [item["name"] for item in cfg["backends"]]
    if len(names) != len(set(names)):
        raise ValueError("backend names must be unique")
    return cfg


def validate_export(path: pathlib.Path, expected_requests: int, isl: int, osl: int) -> dict:
    data = json.loads(path.read_text())
    if data.get("error_summary"):
        raise ValueError(f"{path}: request errors: {data['error_summary']}")
    completed = (data.get("request_count") or {}).get("avg")
    if completed != expected_requests:
        raise ValueError(f"{path}: completed {completed}, expected {expected_requests}")
    for key, expected in (("input_sequence_length", isl), ("output_sequence_length", osl)):
        block = data.get(key) or {}
        for stat in ("avg", "min", "max"):
            actual = block.get(stat)
            if actual is None or abs(float(actual) - expected) > 0.01:
                raise ValueError(f"{path}: {key}.{stat}={actual}, expected {expected}")
    return data


def wait_ready(url: str, model: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/v1/models", timeout=10) as response:
                if any(item.get("id") == model for item in json.load(response).get("data", [])):
                    return
        except Exception:
            pass
        time.sleep(15)
    raise TimeoutError(f"model {model!r} did not become ready at {url}")


def request_count(cfg: dict, concurrency: int) -> int:
    policy = cfg.get("sampling", {})
    return max(int(policy.get("minimum_requests", 4)), int(policy.get("waves", 2)) * concurrency)


def command_for(cfg: dict, backend: dict, workload: dict, concurrency: int,
                count: int, run_dir: pathlib.Path, aiperf: str) -> list[str]:
    endpoint_type = cfg.get("endpoint_type", "completions")
    cmd = [aiperf, "profile", "-m", backend["model"], "--url", backend["url"],
           "--endpoint-type", endpoint_type, "--streaming", "--concurrency", str(concurrency),
           "--request-count", str(count), "--num-warmup-requests",
           str(cfg.get("sampling", {}).get("warmup_requests", 1)),
           "--synthetic-input-tokens-mean", str(workload["isl"]),
           "--synthetic-input-tokens-stddev", "0", "--output-tokens-mean", str(workload["osl"]),
           "--output-tokens-stddev", "0", "--num-dataset-entries", str(count + 1),
           "--tokenizer", cfg["tokenizer"], "--use-server-token-count", "--random-seed",
           str(cfg.get("seed", 42)), "--request-timeout-seconds",
           str(cfg.get("request_timeout_seconds", 7200)), "--artifact-dir", str(run_dir)]
    if cfg.get("tokenizer_trust_remote_code", True):
        cmd.append("--tokenizer-trust-remote-code")
    if cfg.get("use_legacy_max_tokens", True):
        cmd.append("--use-legacy-max-tokens")
    extra = cfg.get("extra_inputs")
    if extra is not None:
        cmd.extend(("--extra-inputs", json.dumps(extra, separators=(",", ":"))))
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--backend", action="append", help="backend name; repeat to select several")
    parser.add_argument("--aiperf", default=str(pathlib.Path.home() / "aiperf-venv/bin/aiperf"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    selected = set(args.backend or [item["name"] for item in cfg["backends"]])
    backends = [item for item in cfg["backends"] if item["name"] in selected]
    unknown = selected - {item["name"] for item in backends}
    if unknown:
        raise SystemExit(f"unknown backend(s): {', '.join(sorted(unknown))}")
    args.out.mkdir(parents=True, exist_ok=True)
    snapshot = args.out / "benchmark-config.json"
    if snapshot.exists() and json.loads(snapshot.read_text()) != cfg:
        raise SystemExit(f"{snapshot} differs from {args.config}; use a new output directory")
    snapshot.write_text(json.dumps(cfg, indent=2) + "\n")

    for backend in backends:
        if not args.dry_run:
            wait_ready(backend["url"], backend["model"], int(cfg.get("ready_timeout_seconds", 7200)))
        for workload in cfg["workloads"]:
            isl, osl = int(workload["isl"]), int(workload["osl"])
            for concurrency in map(int, cfg["concurrencies"]):
                count = request_count(cfg, concurrency)
                name = f"isl{isl}-osl{osl}__{backend['name']}-c{concurrency}"
                run_dir = args.out / name
                export = run_dir / "profile_export_aiperf.json"
                if export.exists():
                    validate_export(export, count, isl, osl)
                    print(f"RESUME {name}: valid export")
                    continue
                cmd = command_for(cfg, backend, workload, concurrency, count, run_dir, args.aiperf)
                record = {"backend": backend, "hardware": cfg.get("hardware"), "workload": workload,
                          "concurrency": concurrency, "requests": count, "command": cmd,
                          "started_at": dt.datetime.now(dt.timezone.utc).isoformat()}
                (args.out / f"{name}.command.json").write_text(json.dumps(record, indent=2) + "\n")
                print(f"{'DRY-RUN' if args.dry_run else 'START'} {name}: {shlex.join(cmd)}", flush=True)
                if args.dry_run:
                    continue
                run_dir.mkdir(parents=True, exist_ok=True)
                with (args.out / f"{name}.log").open("w") as log:
                    result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                            timeout=int(cfg.get("point_timeout_seconds", 43200)))
                if result.returncode:
                    raise RuntimeError(f"{name} exited {result.returncode}; see {name}.log")
                validate_export(export, count, isl, osl)
                print(f"OK {name}", flush=True)


if __name__ == "__main__":
    main()
