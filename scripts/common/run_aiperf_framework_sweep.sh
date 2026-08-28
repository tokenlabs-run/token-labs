#!/usr/bin/env bash
# llm-d vs Dynamo aggregated A/B on DGX Spark GB10, driven by NVIDIA AIPerf.
#
# Both backends serve the SAME model (nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4,
# modelopt_fp4 weights, fp8 KV, dspark speculative decoding, TP=1) so the only
# variable is the serving framework.
#
# Load is generated from the controller node, not from the GPU nodes, so client-side
# CPU never competes with the engines under test.
#
# Backends are hit DIRECTLY on their ClusterIPs rather than through the Envoy AI
# Gateway: the gateway is common to both and would only add variance to both arms.
#
# usage: run_aiperf_framework_sweep.sh [out_dir]
set -uo pipefail

AIPERF=${AIPERF:-$HOME/aiperf-venv/bin/aiperf}
OUT=${1:-$HOME/aiperf-runs/$(date -u +%Y-%m-%d)-llmd-vs-dynamo}
TOKENIZER="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"

# Workload: 1024-token prompt / 256-token completion. Representative of chat
# turns and deep enough that decode dominates, so the frameworks are compared on
# steady-state token generation rather than on prefill.
ISL=${ISL:-1024}
OSL=${OSL:-256}

# Concurrency ladder. This is the x-axis of the Pareto frontier: each point trades
# per-user speed for aggregate throughput. Powers of two from single-stream to
# saturation give even spacing on the log-scaled latency axis.
CONCURRENCIES=${CONCURRENCIES:-"1 2 4 8 16 32"}

# name|url|served-model-name
BACKENDS=(
  "llm-d|http://10.100.193.86:8000|nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-llm-d"
  "dynamo|http://10.110.31.76:8000|nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-dynamo"
)

mkdir -p "$OUT"
echo "output -> $OUT"

for entry in "${BACKENDS[@]}"; do
  IFS='|' read -r NAME URL MODEL <<<"$entry"

  if ! curl -sf -m 15 "$URL/v1/models" >/dev/null; then
    echo "!! $NAME unreachable at $URL, skipping"
    continue
  fi

  for C in $CONCURRENCIES; do
    # Enough requests for a stable median at every concurrency, without letting
    # high-concurrency points balloon: 10 requests per stream, floor of 20.
    REQ=$(( C * 10 )); [ "$REQ" -lt 20 ] && REQ=20
    WARM=$(( C * 2 )); [ "$WARM" -lt 4 ] && WARM=4

    RUN_DIR="$OUT/${NAME}-c${C}"
    echo "=== $NAME concurrency=$C requests=$REQ ==="

    "$AIPERF" profile \
      -m "$MODEL" \
      --url "$URL" \
      --endpoint-type chat \
      --streaming \
      --concurrency "$C" \
      --request-count "$REQ" \
      --num-warmup-requests "$WARM" \
      --synthetic-input-tokens-mean "$ISL" \
      --output-tokens-mean "$OSL" \
      --tokenizer "$TOKENIZER" \
      --tokenizer-trust-remote-code \
      --artifact-dir "$RUN_DIR" \
      >"$OUT/${NAME}-c${C}.log" 2>&1

    if [ -f "$RUN_DIR/profile_export_aiperf.json" ]; then
      echo "OK $NAME c=$C"
    else
      echo "FAILED $NAME c=$C -- see $OUT/${NAME}-c${C}.log"
      tail -5 "$OUT/${NAME}-c${C}.log" | sed 's/^/    /'
    fi
  done
done

echo "SWEEP_COMPLETE $OUT"
