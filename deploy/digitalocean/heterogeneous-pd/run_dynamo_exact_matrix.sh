#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
METRICS_URL="${METRICS_URL:-http://127.0.0.1:8000/metrics}"
DATASET_DIR="${DATASET_DIR:-/root/dynamo-exact-datasets}"
RESULT_DIR="${RESULT_DIR:-/root/dynamo-exact-matrix}"
BENCH_IMAGE="${BENCH_IMAGE:-vllm/vllm-openai:v0.26.0}"

mkdir -p "${RESULT_DIR}"

run_point() {
  local isl="$1" osl="$2" concurrency="$3"
  local point="isl${isl}-osl${osl}-c${concurrency}"

  curl -fsS "${METRICS_URL}" >"${RESULT_DIR}/${point}.before.prom"
  docker run --rm --network host \
    -v /root/.cache/huggingface:/root/.cache/huggingface \
    -v "${DATASET_DIR}:/datasets:ro" \
    -v "${RESULT_DIR}:/results" \
    --entrypoint vllm "${BENCH_IMAGE}" \
    bench serve \
    --backend openai \
    --base-url "${BASE_URL}" \
    --endpoint /v1/completions \
    --model "${MODEL}" \
    --dataset-name custom \
    --dataset-path "/datasets/isl${isl}.jsonl" \
    --custom-output-len "${osl}" \
    --skip-chat-template \
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
  curl -fsS "${METRICS_URL}" >"${RESULT_DIR}/${point}.after.prom"
}

for isl_osl in "1024 8192" "8192 8192" "8192 1024"; do
  read -r isl osl <<<"${isl_osl}"
  for concurrency in 1 2 4 8 16 32 64; do
    run_point "${isl}" "${osl}" "${concurrency}"
  done
done
