#!/usr/bin/env bash
set -euo pipefail

: "${PREFILL_IP:?set PREFILL_IP}"
: "${DECODE_IP:?set DECODE_IP}"
export DYN_DISCOVERY_BACKEND=etcd
export DYN_EVENT_PLANE=zmq
export DYN_REQUEST_PLANE=tcp
export ETCD_ENDPOINTS="http://${PREFILL_IP}:2379"
export VLLM_SSM_CONV_STATE_LAYOUT=DS
export VLLM_NIXL_SIDE_CHANNEL_HOST="$PREFILL_IP"

kv_config='{"kv_connector":"NixlConnector","kv_role":"kv_both"}'

exec /opt/dynamo/bin/python -m dynamo.vllm \
  --model /workspace/models/Qwen3.8-27B \
  --served-model-name Qwen/Qwen3.8-27B \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --no-enable-prefix-caching \
  --disaggregation-mode prefill \
  --kv-transfer-config "$kv_config" \
  --dyn-reasoning-parser qwen3
