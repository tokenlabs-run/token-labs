#!/usr/bin/env python3
"""Archive one benchmark run and (optionally) log it to MLflow.

Files are the truth: the raw harness JSON + manifest.yaml are always copied
into results/<date>/<run-name>/, and summary.json holds the flattened
percentiles. MLflow logging is a searchable index on top — skipped with
--dry-run or when MLFLOW_TRACKING_URI is unset and --mlflow is not passed.

Supported inputs:
  - vLLM `bench serve --save-result` JSON  (ttfts / itls / e2els arrays)
  - GuideLLM `benchmarks.json`             (percentiles in summary metrics)
  - anything else: percentiles computed from any per-request arrays found
"""
import argparse, json, math, os, shutil, statistics, sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent

def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (q / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)

def summarize(values):
    if not values:
        return {}
    return {"mean": statistics.fmean(values),
            "p50": pct(values, 50), "p90": pct(values, 90), "p99": pct(values, 99)}

def extract_metrics(data):
    """Return flat {metric_name: value} from a harness result dict."""
    m = {}
    # vLLM bench serve: per-request arrays, seconds
    for key, label in (("ttfts", "ttft"), ("itls", "itl"), ("e2els", "e2e")):
        if isinstance(data.get(key), list) and data[key]:
            for stat, val in summarize([float(x) for x in data[key]]).items():
                m[f"{label}_{stat}_s"] = val
    for key, label in (("total_output_tokens", None), ("total_input_tokens", None),
                       ("request_throughput", "req_per_s"),
                       ("output_throughput", "output_tok_per_s"),
                       ("total_token_throughput", "total_tok_per_s"),
                       ("duration", "duration_s")):
        if isinstance(data.get(key), (int, float)):
            m[label or key] = float(data[key])
    # GuideLLM: benchmarks -> metrics with percentile dicts (values in seconds)
    for bench in data.get("benchmarks", []) if isinstance(data.get("benchmarks"), list) else []:
        metrics = bench.get("metrics", {}) if isinstance(bench, dict) else {}
        for name, node in metrics.items():
            if isinstance(node, dict):
                for stat in ("mean", "median", "p90", "p99"):
                    v = node.get(stat)
                    if isinstance(v, (int, float)):
                        m[f"{name}_{'p50' if stat == 'median' else stat}"] = float(v)
    return m

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--result", required=True, help="harness result JSON")
    ap.add_argument("--harness", default="vllm-bench",
                    choices=["vllm-bench", "guidellm", "aiperf", "genai-perf", "custom"])
    ap.add_argument("--harness-version", default="")
    ap.add_argument("--model", required=True)
    ap.add_argument("--gpu", required=True)
    ap.add_argument("--engine", default="vllm")
    ap.add_argument("--engine-version", default="")
    ap.add_argument("--quant", default="bf16")
    ap.add_argument("--tp", type=int, default=1)
    ap.add_argument("--pp", type=int, default=1)
    ap.add_argument("--dp", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--isl", type=int, default=0)
    ap.add_argument("--osl", type=int, default=0)
    ap.add_argument("--arrival", default="constant")
    ap.add_argument("--notes", default="")
    ap.add_argument("--mlflow", action="store_true", help="log to MLFLOW_TRACKING_URI")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src = Path(a.result)
    data = json.loads(src.read_text())
    metrics = extract_metrics(data)
    if not metrics:
        print("warning: no metrics extracted — raw file will still be archived",
              file=sys.stderr)

    now = datetime.now(timezone.utc)
    model_slug = a.model.split("/")[-1].lower()
    run_name = (f"{model_slug}__{a.gpu.lower()}__{a.engine}-{a.engine_version or 'x'}"
                f"__{a.quant}__tp{a.tp}__c{a.concurrency}__isl{a.isl}-osl{a.osl}")
    run_dir = VAULT / "results" / now.strftime("%Y-%m-%d") / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_name": run_name, "timestamp_utc": now.isoformat(),
        "model": a.model, "engine": a.engine, "engine_version": a.engine_version,
        "gpu": a.gpu, "quantization": a.quant,
        "parallelism": {"tp": a.tp, "pp": a.pp, "dp": a.dp},
        "harness": a.harness, "harness_version": a.harness_version,
        "metric_schema": f"{a.harness}-v1",
        "workload": {"concurrency": a.concurrency, "input_tokens": a.isl,
                     "output_tokens": a.osl, "arrival_pattern": a.arrival},
        "notes": a.notes,
    }
    # manifest as YAML (tiny emitter; keys are simple scalars/dicts)
    def emit(d, ind=0):
        out = []
        for k, v in d.items():
            if isinstance(v, dict):
                out.append(" " * ind + f"{k}:")
                out += emit(v, ind + 2)
            else:
                out.append(" " * ind + f"{k}: {json.dumps(v)}")
        return out
    (run_dir / "manifest.yaml").write_text("\n".join(emit(manifest)) + "\n")
    shutil.copyfile(src, run_dir / "raw.json")
    summary = {"run_name": run_name, "metrics": metrics}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    if a.mlflow and not a.dry_run:
        import mlflow  # pip install mlflow
        mlflow.set_experiment("bench-vault")
        with mlflow.start_run(run_name=run_name):
            params = {"model": a.model, "engine": a.engine,
                      "engine_version": a.engine_version, "gpu": a.gpu,
                      "quant": a.quant, "tp": a.tp, "pp": a.pp, "dp": a.dp,
                      "harness": a.harness, "harness_version": a.harness_version,
                      "metric_schema": manifest["metric_schema"],
                      "concurrency": a.concurrency, "isl": a.isl, "osl": a.osl,
                      "arrival": a.arrival}
            mlflow.log_params(params)
            mlflow.log_metrics({k: v for k, v in metrics.items() if v is not None})
            mlflow.log_artifact(str(run_dir / "raw.json"))
            mlflow.log_artifact(str(run_dir / "manifest.yaml"))
        print(f"logged to MLflow: {run_name}")
    print(json.dumps({"archived": str(run_dir), "metrics": metrics}, indent=2))

if __name__ == "__main__":
    main()
