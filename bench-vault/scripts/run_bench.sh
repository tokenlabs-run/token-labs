#!/usr/bin/env bash
# Run one benchmark and archive + log it in a single step.
# Usage example:
#   ./scripts/run_bench.sh --endpoint http://localhost:8000 \
#     --model Qwen/Qwen3-32B --gpu GB10 --quant fp8 --tp 2 \
#     --concurrency 32 --isl 1024 --osl 256 --num-prompts 500
set -euo pipefail

ENDPOINT="http://localhost:8000"; MODEL=""; GPU=""; QUANT="bf16"; TP=1
CONC=16; ISL=1024; OSL=256; NUM=500; ENGINE_VERSION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --endpoint) ENDPOINT="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --gpu) GPU="$2"; shift 2;;
    --quant) QUANT="$2"; shift 2;;
    --tp) TP="$2"; shift 2;;
    --concurrency) CONC="$2"; shift 2;;
    --isl) ISL="$2"; shift 2;;
    --osl) OSL="$2"; shift 2;;
    --num-prompts) NUM="$2"; shift 2;;
    --engine-version) ENGINE_VERSION="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done
[[ -n "$MODEL" && -n "$GPU" ]] || { echo "--model and --gpu are required" >&2; exit 1; }

OUT="$(mktemp -d)/bench-result.json"
echo "== benchmarking $MODEL on $GPU (c=$CONC isl=$ISL osl=$OSL) =="
vllm bench serve \
  --base-url "$ENDPOINT" --model "$MODEL" \
  --dataset-name random --random-input-len "$ISL" --random-output-len "$OSL" \
  --num-prompts "$NUM" --max-concurrency "$CONC" \
  --save-result --result-filename "$OUT"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/log_run.py" \
  --result "$OUT" --harness vllm-bench --harness-version "$ENGINE_VERSION" \
  --model "$MODEL" --gpu "$GPU" --engine-version "$ENGINE_VERSION" \
  --quant "$QUANT" --tp "$TP" --concurrency "$CONC" \
  --isl "$ISL" --osl "$OSL" ${MLFLOW_TRACKING_URI:+--mlflow}
echo "== archived =="
