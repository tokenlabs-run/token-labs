#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_IP:?set PUBLIC_IP to the H200 public address}"

MODEL="${MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
IMAGE="${IMAGE:-token-labs/dynamo-vllm-cuda:1.4.2-vllm0.26-mc0.3.13-bootstrap}"
ETCD_ENDPOINTS="${ETCD_ENDPOINTS:-http://127.0.0.1:2379}"

docker rm -f dynamo-frontend >/dev/null 2>&1 || true
docker run -d \
  --name dynamo-frontend \
  --network host \
  -e "ETCD_ENDPOINTS=${ETCD_ENDPOINTS}" \
  -e DYN_DISCOVERY_BACKEND=etcd \
  -e DYN_REQUEST_PLANE=tcp \
  -e DYN_EVENT_PLANE=zmq \
  -e "DYN_SYSTEM_HOST=${PUBLIC_IP}" \
  -v /root/.cache/huggingface:/root/.cache/huggingface \
  "${IMAGE}" \
  python3 -m dynamo.frontend \
  --http-host 127.0.0.1 \
  --http-port 8000 \
  --router-mode round-robin \
  --router-min-initial-workers 1 \
  --model-name "${MODEL}" \
  --trust-remote-code
