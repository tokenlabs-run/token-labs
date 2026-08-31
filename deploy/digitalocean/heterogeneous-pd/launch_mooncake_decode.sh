#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_IP:?set PUBLIC_IP to the decode node public address}"

MODEL="Qwen/Qwen3-30B-A3B-Instruct-2507-FP8"
IMAGE="token-labs/vllm-openai-rocm-mooncake:v0.26.0"
KV_CONFIG='{"kv_connector":"MooncakeConnector","kv_role":"kv_consumer","kv_connector_extra_config":{"mooncake_protocol":"tcp","num_workers":4}}'

docker rm -f vllm-decode >/dev/null 2>&1 || true
docker run -d \
  --name vllm-decode \
  --group-add=video \
  --cap-add=SYS_PTRACE \
  --security-opt seccomp=unconfined \
  --device /dev/kfd \
  --device /dev/dri \
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
  --no-enable-prefix-caching \
  --kv-transfer-config "${KV_CONFIG}"
