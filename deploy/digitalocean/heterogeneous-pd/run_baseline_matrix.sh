#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
RESULT_DIR="${RESULT_DIR:-/root/vllm-baseline-matrix}"
BENCH_IMAGE="${BENCH_IMAGE:-vllm/vllm-openai:v0.26.0}"

mkdir -p "${RESULT_DIR}"

run_point() {
  local isl="$1" osl="$2" concurrency="$3"
  local point="isl${isl}-osl${osl}-c${concurrency}"

  docker run --rm --network=host \
    -v /root/.cache/huggingface:/root/.cache/huggingface \
    -v "${RESULT_DIR}:/results" \
    --entrypoint vllm "${BENCH_IMAGE}" \
    bench serve \
    --backend openai \
    --base-url "${BASE_URL}" \
    --endpoint /v1/completions \
    --model "${MODEL}" \
    --dataset-name random \
    --random-input-len "${isl}" \
    --random-output-len "${osl}" \
    --random-range-ratio 0 \
    --num-prompts "${concurrency}" \
    --max-concurrency "${concurrency}" \
    --ignore-eos \
    --temperature 0 \
    --seed 0 \
    --save-result \
    --save-detailed \
    --result-dir /results \
    --result-filename "${point}.json" \
    2>&1 | tee "${RESULT_DIR}/${point}.log"
}

for isl_osl in "1024 8192" "8192 8192" "8192 1024"; do
  read -r isl osl <<<"${isl_osl}"
  for concurrency in 1 2 4 8 16 32 64; do
    run_point "${isl}" "${osl}" "${concurrency}"
  done
done
