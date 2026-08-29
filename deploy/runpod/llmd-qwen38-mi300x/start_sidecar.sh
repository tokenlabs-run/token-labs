#!/usr/bin/env bash
set -euo pipefail

exec /workspace/llmd/bin/pd-sidecar \
  --port 8200 \
  --model-server-port 8100 \
  --kv-connector nixlv2 \
  --moriio-write-mode \
  --moriio-local-pod-ip "${DECODE_IP:-172.18.0.4}" \
  --moriio-remote-hosts "${PREFILL_IP:-172.18.0.3}" \
  --moriio-decode-hosts "${DECODE_IP:-172.18.0.4}" \
  --moriio-decode-handshake-port 5601 \
  --moriio-decode-notify-port 5602 \
  --moriio-prefill-handshake-port 5601 \
  --moriio-prefill-notify-port 5602 \
  --moriio-tp-size 1 \
  --moriio-dp-size 1 \
  --secure-proxy=false \
  --zap-log-level debug
