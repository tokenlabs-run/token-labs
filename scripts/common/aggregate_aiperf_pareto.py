#!/usr/bin/env python3
"""Aggregate an AIPerf framework sweep into Pareto-frontier data.

Reads the per-run profile_export_aiperf.json files produced by
run_aiperf_framework_sweep.sh and emits a single JSON keyed by framework, with
one entry per concurrency level.

The Pareto axes are the two quantities that genuinely trade against each other
in LLM serving:
  x = output_token_throughput_per_user  (how fast one user's tokens arrive)
  y = output_token_throughput           (how many tokens the box emits in total)
Raising concurrency moves you right-to-left along that curve: aggregate
throughput climbs while each individual user waits longer.

usage: aggregate_aiperf_pareto.py <sweep_dir> [-o out.json]
"""

import argparse
import json
import pathlib
import re
import sys


def pick(metric, *names):
    """Pull the first available stat from an AIPerf metric block."""
    if not isinstance(metric, dict):
        return None
    for n in names:
        if metric.get(n) is not None:
            return round(float(metric[n]), 2)
    return None


def requested_lengths(d):
    """The ISL/OSL the run ASKED for, from input_config.

    Must not use the measured averages: a run that lands on OSL 255.4 instead of
    256 would otherwise get its own combo bucket and silently split one curve in
    two. Falls back to rounded measurements only if the config is absent.
    """
    for ds in d.get("input_config", {}).get("datasets", []) or []:
        p = ds.get("prompts") or {}
        isl = (p.get("isl") or {}).get("mean")
        osl = (p.get("osl") or {}).get("mean")
        if isl is not None and osl is not None:
            return int(round(isl)), int(round(osl))
    isl = (d.get("input_sequence_length") or {}).get("avg")
    osl = (d.get("output_sequence_length") or {}).get("avg")
    if isl is None or osl is None:
        return None, None
    return int(round(isl)), int(round(osl))


def combo_label(isl, osl):
    if isl is None or osl is None:
        return "unknown"
    return f"ISL{isl}/OSL{osl}"


def load_run(run_dir):
    f = run_dir / "profile_export_aiperf.json"
    if not f.is_file():
        return None
    d = json.loads(f.read_text())
    req_isl, req_osl = requested_lengths(d)
    return {
        "req_isl": req_isl,
        "req_osl": req_osl,
        "tput_total": pick(d.get("output_token_throughput"), "avg"),
        "tput_per_user": pick(d.get("output_token_throughput_per_user"), "avg"),
        "ttft_p50": pick(d.get("time_to_first_token"), "p50"),
        "ttft_p95": pick(d.get("time_to_first_token"), "p95", "p90", "p75"),
        "itl_p50": pick(d.get("inter_token_latency"), "p50"),
        "itl_p95": pick(d.get("inter_token_latency"), "p95", "p90", "p75"),
        "req_latency_p50": pick(d.get("request_latency"), "p50"),
        "req_latency_p95": pick(d.get("request_latency"), "p95", "p90", "p75"),
        "req_throughput": pick(d.get("request_throughput"), "avg"),
        "isl": pick(d.get("input_sequence_length"), "avg"),
        "osl": pick(d.get("output_sequence_length"), "avg"),
        "requests": pick(d.get("request_count"), "avg"),
        "errors": len(d.get("error_summary") or []),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep_dir")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    root = pathlib.Path(args.sweep_dir).expanduser()
    if not root.is_dir():
        sys.exit(f"no such sweep dir: {root}")

    combos = {}
    for run_dir in sorted(root.iterdir()):
        # flat layout: '<fw>-c<N>'   matrix layout: 'isl<I>-osl<O>__<fw>-c<N>'
        name = run_dir.name.split("__")[-1]
        m = re.fullmatch(r"(.+)-c(\d+)", name)
        if not (run_dir.is_dir() and m):
            continue
        fw, conc = m.group(1), int(m.group(2))
        row = load_run(run_dir)
        if row is None:
            print(f"  skip {run_dir.name}: no export", file=sys.stderr)
            continue
        row["concurrency"] = conc
        combos.setdefault(combo_label(row["req_isl"], row["req_osl"]), {}).setdefault(fw, []).append(row)

    for byfw in combos.values():
        for rows in byfw.values():
            rows.sort(key=lambda r: r["concurrency"])

    # cheapest prefill first so tab order reads as a ladder
    ordered = dict(
        sorted(combos.items(), key=lambda kv: [int(x) for x in re.findall(r"\d+", kv[0])])
    )

    payload = {"source": str(root), "combos": ordered}
    text = json.dumps(payload, indent=2)

    if args.out:
        pathlib.Path(args.out).expanduser().write_text(text + "\n")
        print(f"wrote {args.out}")

    for combo, byfw in ordered.items():
        print(f"\n### {combo}")
        for fw, rows in sorted(byfw.items()):
            print(f"  {fw}")
            print(
                f"    {'conc':>5} {'tok/s':>9} {'tok/s/user':>11} "
                f"{'TTFT p50':>9} {'ITL p50':>8} {'err':>4}"
            )
            for r in rows:
                print(
                    f"    {r['concurrency']:>5} {r['tput_total']:>9} {r['tput_per_user']:>11} "
                    f"{r['ttft_p50']:>9} {r['itl_p50']:>8} {r['errors']:>4}"
                )


if __name__ == "__main__":
    main()
