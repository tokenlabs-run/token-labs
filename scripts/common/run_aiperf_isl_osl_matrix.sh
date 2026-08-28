#!/usr/bin/env bash
# llm-d vs Dynamo across task-shaped ISL/OSL combos on DGX Spark GB10.
#
# The 1024/256 sweep found throughput parity with a TTFT gap at mid concurrency
# (llm-d 25-38% faster at c=4-8). TTFT is a prefill/admission signal, and at
# ISL 1024 prefill is nearly free -- so that combo cannot tell a real per-request
# routing cost from noise.
#
# The design is therefore a PREFILL LADDER at fixed OSL=1024, so exactly one
# variable moves and the TTFT gap can be checked for linear scaling with prefill
# tokens (the signature of a fixed per-request cost):
#
#   8192/1024  prefill 8x   RAG / summarization / code review
#   4096/1024  prefill 4x   mid-context retrieval
#   1024/1024  prefill 1x   balanced chat, ties back to the 1024/256 sweep
#
# Plus one decode-heavy cell to cover the opposite regime:
#
#   1024/4096  agentic loops, reasoning chains
#
# Deliberately NOT run: 8192/8192 (most expensive cell, and it moves both axes
# at once so its result blends the two effects the ladder isolates cleanly) and
# 1024/8192 (2x the cost of 1024/4096 to answer the same question).
#
# Cost is wildly asymmetric: OSL 8192 is 32x the decode of OSL 256. Request
# counts are therefore sized in ROUNDS, not with a flat per-stream multiplier --
# at c=32 a single round already yields 32 samples, which is plenty for a median,
# while at c=1 a round is one sample so we need several.
set -uo pipefail

AIPERF=${AIPERF:-$HOME/aiperf-venv/bin/aiperf}
OUT=${1:-$HOME/aiperf-runs/$(date -u +%Y-%m-%d)-llmd-vs-dynamo-islosl}
TOKENIZER="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
CONCURRENCIES=${CONCURRENCIES:-"1 8 32"}

# isl:osl -- prefill ladder first (that is the open question), decode cell last
COMBOS=${COMBOS:-"8192:1024 4096:1024 1024:1024 1024:4096"}

BACKENDS=(
  "llm-d|http://10.100.193.86:8000|nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-llm-d"
  "dynamo|http://10.110.31.76:8000|nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-dynamo"
)

mkdir -p "$OUT"
echo "output -> $OUT"

for combo in $COMBOS; do
  ISL=${combo%%:*}; OSL=${combo##*:}
  TAG="isl${ISL}-osl${OSL}"

  # Long generations get 1 round (plus a floor for low concurrency); short ones get 5.
  if [ "$OSL" -ge 4096 ]; then MULT=1; FLOOR=4; else MULT=5; FLOOR=20; fi

  for entry in "${BACKENDS[@]}"; do
    IFS='|' read -r NAME URL MODEL <<<"$entry"

    if ! curl -sf -m 15 "$URL/v1/models" >/dev/null; then
      echo "!! $NAME unreachable at $URL, skipping"
      continue
    fi

    for C in $CONCURRENCIES; do
      REQ=$(( C * MULT )); [ "$REQ" -lt "$FLOOR" ] && REQ=$FLOOR
      WARM=$(( C < 4 ? 2 : 4 ))
      RUN_DIR="$OUT/${TAG}__${NAME}-c${C}"
      echo "=== $TAG $NAME concurrency=$C requests=$REQ ==="

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
        >"$OUT/${TAG}__${NAME}-c${C}.log" 2>&1

      if [ -f "$RUN_DIR/profile_export_aiperf.json" ]; then
        echo "OK $TAG $NAME c=$C"
      else
        echo "FAILED $TAG $NAME c=$C -- see $OUT/${TAG}__${NAME}-c${C}.log"
        tail -5 "$OUT/${TAG}__${NAME}-c${C}.log" | sed 's/^/    /'
      fi
    done
  done
  echo "COMBO_DONE $TAG"
done

echo "MATRIX_COMPLETE $OUT"
