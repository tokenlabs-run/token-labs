#!/usr/bin/env bash
set -euo pipefail

prefill_ip="${PREFILL_IP:-172.18.0.3}"
kv_config=$(printf '{"kv_connector":"MoRIIOConnector","kv_role":"kv_producer","kv_connector_extra_config":{"local_ip":"%s","http_port":8100,"handshake_port":5601,"notify_port":5602,"backend":"rdma"}}' "$prefill_ip")

exec vllm serve /workspace/models/Qwen3.8-27B \
  --served-model-name Qwen/Qwen3.8-27B \
  --host 0.0.0.0 \
  --port 8100 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 32768 \
  --kv-transfer-config "$kv_config" \
  --reasoning-parser qwen3
