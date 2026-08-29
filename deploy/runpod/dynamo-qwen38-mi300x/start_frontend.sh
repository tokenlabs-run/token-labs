#!/usr/bin/env bash
set -euo pipefail

: "${PREFILL_IP:?set PREFILL_IP}"
export DYN_DISCOVERY_BACKEND=etcd
export DYN_EVENT_PLANE=zmq
export DYN_REQUEST_PLANE=tcp
export ETCD_ENDPOINTS="http://${PREFILL_IP}:2379"

exec /opt/dynamo/bin/python -m dynamo.frontend \
  --http-host 0.0.0.0 \
  --http-port 8000 \
  --router-mode round-robin \
  --model-name Qwen/Qwen3.8-27B
