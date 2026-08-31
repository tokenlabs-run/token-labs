#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
DATASET_DIR="${DATASET_DIR:-/root/dynamo-exact-datasets}"
RESULT_DIR="${RESULT_DIR:-/root/dynamo-wire-byte-verification}"
BENCH_IMAGE="${BENCH_IMAGE:-token-labs/vllm-bench:v0.26.0}"
MOONCAKE_TARGET="${MOONCAKE_TARGET:-165.245.141.196}"
MOONCAKE_PORT="${MOONCAKE_PORT:-15608}"

mkdir -p "${RESULT_DIR}"

tcp_payload_bytes_sent() {
  ss -tin dst "${MOONCAKE_TARGET}:${MOONCAKE_PORT}" \
    | grep -o 'bytes_sent:[0-9]*' \
    | cut -d: -f2 \
    | awk '{ total += $1 } END { print total + 0 }'
}

run_probe() {
  local isl="$1"
  local before after

  before="$(tcp_payload_bytes_sent)"
  printf '%s\n' "${before}" >"${RESULT_DIR}/isl${isl}.tcp-payload-before.txt"

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
    --custom-output-len 1 \
    --skip-chat-template \
    --num-prompts 1 \
    --max-concurrency 1 \
    --ignore-eos \
    --temperature 0 \
    --seed 0 \
    --save-result \
    --save-detailed \
    --result-dir /results \
    --result-filename "isl${isl}.json" \
    2>&1 | tee "${RESULT_DIR}/isl${isl}.log"

  after="$(tcp_payload_bytes_sent)"
  printf '%s\n' "${after}" >"${RESULT_DIR}/isl${isl}.tcp-payload-after.txt"
  printf '%s\n' "$((after - before))" >"${RESULT_DIR}/isl${isl}.tcp-payload-delta.txt"
}

run_probe 1024
run_probe 8192
