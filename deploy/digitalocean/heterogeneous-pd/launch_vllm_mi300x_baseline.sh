#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
IMAGE="${IMAGE:-token-labs/vllm-openai-rocm-mooncake:v0.26.0}"

docker rm -f vllm-mi300x-baseline >/dev/null 2>&1 || true
docker run -d \
  --name vllm-mi300x-baseline \
  --group-add=video \
  --cap-add=SYS_PTRACE \
  --security-opt seccomp=unconfined \
  --device /dev/kfd \
  --device /dev/dri \
  --ipc=host \
  --network=host \
  -e LD_LIBRARY_PATH=/usr/local/lib/python3.12/dist-packages/mooncake:/opt/rocm/lib \
  -v /root/.cache/huggingface:/root/.cache/huggingface \
  --entrypoint vllm \
  "${IMAGE}" \
  serve "${MODEL}" \
  --host 0.0.0.0 \
  --port 8020 \
  --served-model-name "${MODEL}" \
  --max-model-len 17408 \
  --gpu-memory-utilization 0.85 \
  --block-size 16 \
  --kv-cache-dtype auto \
  --no-enable-prefix-caching
