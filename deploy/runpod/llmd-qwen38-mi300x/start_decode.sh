#!/usr/bin/env bash
set -euo pipefail

decode_ip="${DECODE_IP:-172.18.0.4}"
kv_config=$(printf '{"kv_connector":"MoRIIOConnector","kv_role":"kv_consumer","kv_connector_extra_config":{"local_ip":"%s","http_port":8100,"handshake_port":5601,"notify_port":5602,"backend":"rdma"}}' "$decode_ip")

exec vllm serve /workspace/models/Qwen3.8-27B \
  --served-model-name Qwen/Qwen3.8-27B \
  --host 0.0.0.0 \
  --port 8100 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 32768 \
  --kv-transfer-config "$kv_config" \
  --reasoning-parser qwen3
