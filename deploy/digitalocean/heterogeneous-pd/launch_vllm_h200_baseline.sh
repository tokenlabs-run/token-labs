#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
IMAGE="${IMAGE:-vllm/vllm-openai:v0.26.0}"

docker rm -f vllm-h200-baseline >/dev/null 2>&1 || true
docker run -d \
  --name vllm-h200-baseline \
  --gpus all \
  --ipc=host \
  --network=host \
  -v /root/.cache/huggingface:/root/.cache/huggingface \
  --entrypoint vllm \
  "${IMAGE}" \
  serve "${MODEL}" \
  --host 0.0.0.0 \
  --port 8010 \
  --served-model-name "${MODEL}" \
  --max-model-len 17408 \
  --gpu-memory-utilization 0.85 \
  --block-size 16 \
  --kv-cache-dtype auto \
  --no-enable-prefix-caching
