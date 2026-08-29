#!/usr/bin/env bash
set -euo pipefail

: "${PREFILL_IP:?set PREFILL_IP}"
: "${DECODE_IP:?set DECODE_IP}"
export DYN_DISCOVERY_BACKEND=etcd
export DYN_EVENT_PLANE=zmq
export DYN_REQUEST_PLANE=tcp
export ETCD_ENDPOINTS="http://${PREFILL_IP}:2379"

kv_config=$(printf '{"kv_connector":"MoRIIOConnector","kv_role":"kv_producer","kv_connector_extra_config":{"local_ip":"%s","http_port":8100,"handshake_port":5601,"notify_port":5602,"backend":"rdma","decode_host":"%s","decode_handshake_port":5601,"decode_notify_port":5602,"tp_size":1,"remote_dp_size":1}}' "$PREFILL_IP" "$DECODE_IP")

exec /opt/dynamo/bin/python -m dynamo.vllm \
  --model /workspace/models/Qwen3.8-27B \
  --served-model-name Qwen/Qwen3.8-27B \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --disaggregation-mode prefill \
  --kv-transfer-config "$kv_config" \
  --dyn-reasoning-parser qwen3
