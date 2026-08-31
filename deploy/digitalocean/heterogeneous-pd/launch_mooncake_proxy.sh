#!/usr/bin/env bash
set -euo pipefail

: "${PREFILL_IP:?set PREFILL_IP to the H200 public address}"
: "${DECODE_IP:?set DECODE_IP to the MI300X public address}"

IMAGE="${IMAGE:-vllm/vllm-openai:v0.26.0}"

docker rm -f mooncake-proxy >/dev/null 2>&1 || true
docker run -d \
  --name mooncake-proxy \
  --network=host \
  --entrypoint python3 \
  "${IMAGE}" \
  /vllm-workspace/examples/disaggregated/mooncake_connector/mooncake_connector_proxy.py \
  --host 0.0.0.0 \
  --port 8000 \
  --prefill "http://${PREFILL_IP}:8010" 8998 \
  --decode "http://${DECODE_IP}:8020"
