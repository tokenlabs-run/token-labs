#!/usr/bin/env bash
set -euo pipefail
export VLLM_SSM_CONV_STATE_LAYOUT=DS
export VLLM_NIXL_SIDE_CHANNEL_HOST=172.18.0.2

decode_ip="${DECODE_IP:-172.18.0.2}"
kv_config='{"kv_connector":"NixlConnector","kv_role":"kv_consumer"}'

exec vllm serve /workspace/models/Qwen3.8-27B \
  --served-model-name Qwen/Qwen3.8-27B \
  --host 0.0.0.0 \
  --port 8100 \
  --gpu-memory-utilization 0.90 \
  --no-enable-prefix-caching \
  --max-model-len 32768 \
  --kv-transfer-config "$kv_config" \
  --reasoning-parser qwen3
