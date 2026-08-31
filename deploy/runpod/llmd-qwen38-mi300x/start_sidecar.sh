#!/usr/bin/env bash
set -euo pipefail

exec /workspace/llmd/bin/pd-sidecar \
  --port 8200 \
  --model-server-port 8100 \
  --kv-connector nixlv2 \
  --secure-proxy=false \
  --zap-log-level debug
