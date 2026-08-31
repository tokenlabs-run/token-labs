#!/usr/bin/env bash
set -euo pipefail

/workspace/llm-d-router/bin/epp \
  --config-file /workspace/llmd-config/epp-config-disagg.yaml \
  --endpoint-selector role \
  --endpoint-target-ports 8100,8200 \
  --secure-serving=false \
  --tracing=false \
  --metrics-endpoint-auth=false \
  --zap-log-level debug \
  >/workspace/logs/llmd-epp.log 2>&1 &
epp_pid=$!

trap 'kill "$epp_pid" 2>/dev/null || true' EXIT
exec /workspace/llm-d-router/bin/envoy -c /workspace/llmd-config/envoy.yaml \
  --log-level info \
  --log-path /workspace/logs/llmd-envoy.log
