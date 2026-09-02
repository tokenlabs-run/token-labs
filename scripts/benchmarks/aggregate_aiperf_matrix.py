#!/usr/bin/env python3
"""Strictly validate an AIPerf matrix and emit JSON/CSV with Pareto membership."""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from run_aiperf_matrix import load_config, request_count, validate_export


def metric(data: dict, name: str, stat: str = "avg") -> float:
    value = (data.get(name) or {}).get(stat)
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"invalid {name}.{stat}: {value}")
    return number


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    cfg = load_config(args.config)
    rows, missing, combos = [], [], {}
    for workload in cfg["workloads"]:
        isl, osl = int(workload["isl"]), int(workload["osl"])
        label = f"ISL{isl}/OSL{osl}"
        combos[label] = {}
        for backend in cfg["backends"]:
            name = backend["name"]
            combos[label][name] = []
            for concurrency in map(int, cfg["concurrencies"]):
                run_name = f"isl{isl}-osl{osl}__{name}-c{concurrency}"
                source = args.root / run_name / "profile_export_aiperf.json"
                if not source.is_file():
                    missing.append(run_name)
                    continue
                count = request_count(cfg, concurrency)
                data = validate_export(source, count, isl, osl)
                row = {"framework": name, "concurrency": concurrency, "req_isl": isl,
                       "req_osl": osl, "tput_total": metric(data, "output_token_throughput"),
                       "tput_per_user": metric(data, "output_token_throughput_per_user"),
                       "ttft_p50": metric(data, "time_to_first_token", "p50"),
                       "ttft_p95": metric(data, "time_to_first_token", "p95"),
                       "itl_p50": metric(data, "inter_token_latency", "p50"),
                       "req_latency_p50": metric(data, "request_latency", "p50"),
                       "isl": metric(data, "input_sequence_length"),
                       "osl": metric(data, "output_sequence_length"), "requests": count,
                       "errors": 0, "source": str(source)}
                combos[label][name].append(row)
                rows.append(row)
        candidates = [row for values in combos[label].values() for row in values]
        for row in candidates:
            def dominates(other: dict) -> bool:
                return (other["tput_total"] >= row["tput_total"] and
                        other["tput_per_user"] >= row["tput_per_user"] and
                        (other["tput_total"] > row["tput_total"] or
                         other["tput_per_user"] > row["tput_per_user"]))
            row["pareto"] = not any(dominates(other) for other in candidates)
            row["framework_pareto"] = not any(dominates(other) for other in candidates
                                               if other["framework"] == row["framework"])
    expected = len(cfg["workloads"]) * len(cfg["concurrencies"]) * len(cfg["backends"])
    if missing and not args.allow_partial:
        raise SystemExit("incomplete matrix: " + ", ".join(missing))
    payload = {"schema_version": 1, "experiment": cfg.get("experiment"),
               "hardware": cfg.get("hardware"), "model": cfg.get("model"),
               "complete": not missing, "expected_points": expected,
               "measured_points": len(rows), "missing": missing,
               "measured_requests": sum(row["requests"] for row in rows), "combos": combos}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    if rows:
        with args.output.with_suffix(".csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    print(f"{len(rows)}/{expected} valid points; complete={not missing}")


if __name__ == "__main__":
    main()
