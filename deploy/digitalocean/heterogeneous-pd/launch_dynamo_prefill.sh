#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_IP:?set PUBLIC_IP to the H200 public address}"

MODEL="${MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
IMAGE="${IMAGE:-token-labs/dynamo-vllm-cuda:1.4.2-vllm0.26-mc0.3.13-bootstrap}"
ETCD_ENDPOINTS="${ETCD_ENDPOINTS:-http://127.0.0.1:2379}"
KV_CONFIG='{"kv_connector":"MooncakeConnector","kv_role":"kv_producer","kv_connector_extra_config":{"mooncake_protocol":"tcp","num_workers":4}}'

docker rm -f dynamo-prefill >/dev/null 2>&1 || true
docker run -d \
  --name dynamo-prefill \
  --gpus all \
  --ipc host \
  --network host \
  -e "ETCD_ENDPOINTS=${ETCD_ENDPOINTS}" \
  -e DYN_DISCOVERY_BACKEND=etcd \
  -e DYN_REQUEST_PLANE=tcp \
  -e DYN_EVENT_PLANE=zmq \
  -e "DYN_SYSTEM_HOST=${PUBLIC_IP}" \
  -e "DYN_MOONCAKE_BOOTSTRAP_HOST=${PUBLIC_IP}" \
  -e "VLLM_HOST_IP=${PUBLIC_IP}" \
  -e VLLM_MOONCAKE_BOOTSTRAP_PORT=8998 \
  -e MC_FORCE_TCP=1 \
  -e MC_TRANSFER_TIMEOUT=300 \
  -e MC_TCP_LANES_PER_PEER=8 \
  -e MC_TCP_MAX_QUEUED_TRANSFERS_PER_PEER=65535 \
  -e MC_TCP_MAX_PENDING_ADMISSIONS_PER_PEER=65535 \
  -e MC_TCP_ADMISSION_TIMEOUT_MS=120000 \
  -e LD_LIBRARY_PATH=/usr/local/lib/python3.12/dist-packages/mooncake:/usr/local/lib/python3.12/dist-packages/mooncake_transfer_engine_cuda13.libs:/usr/local/cuda/lib64 \
  -v /root/.cache/huggingface:/root/.cache/huggingface \
  "${IMAGE}" \
  python3 -m dynamo.vllm \
  --disaggregation-mode prefill \
  --model "${MODEL}" \
  --served-model-name "${MODEL}" \
  --max-model-len 17408 \
  --gpu-memory-utilization 0.85 \
  --block-size 16 \
  --kv-cache-dtype auto \
  --no-enable-prefix-caching \
  --kv-transfer-config "${KV_CONFIG}"
