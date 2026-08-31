#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_IP:?set PUBLIC_IP to the prefill node public address}"

MODEL="Qwen/Qwen3-30B-A3B-Instruct-2507-FP8"
IMAGE="vllm/vllm-openai:v0.26.0"
KV_CONFIG='{"kv_connector":"MooncakeConnector","kv_role":"kv_producer","kv_connector_extra_config":{"mooncake_protocol":"tcp","num_workers":4}}'

docker rm -f vllm-prefill >/dev/null 2>&1 || true
docker run -d \
  --name vllm-prefill \
  --gpus all \
  --ipc=host \
  --network=host \
  -e "VLLM_HOST_IP=${PUBLIC_IP}" \
  -e VLLM_MOONCAKE_BOOTSTRAP_PORT=8998 \
  -e MC_FORCE_TCP=1 \
  -e MC_TRANSFER_TIMEOUT=300 \
  -e MC_TCP_LANES_PER_PEER=8 \
  -e MC_TCP_MAX_QUEUED_TRANSFERS_PER_PEER=65535 \
  -e MC_TCP_MAX_PENDING_ADMISSIONS_PER_PEER=65535 \
  -e MC_TCP_ADMISSION_TIMEOUT_MS=120000 \
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
  --no-enable-prefix-caching \
  --kv-transfer-config "${KV_CONFIG}"
