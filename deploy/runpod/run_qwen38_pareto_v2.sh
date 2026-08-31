#!/usr/bin/env bash
set -euo pipefail

if (( $# != 3 )); then
  echo "usage: $0 BASE_URL LABEL OUTPUT_DIR" >&2
  exit 2
fi

base_url=$1
label=$2
output_dir=$3
model=Qwen/Qwen3.8-27B
mkdir -p "$output_dir"

for scenario in 1024:8192 8192:8192 8192:1024; do
  isl=${scenario%%:*}
  osl=${scenario##*:}
  for concurrency in 1 2 4 8 16 32; do
    if (( concurrency == 1 )); then prompts=2; else prompts=$concurrency; fi
    filename="${label}-isl${isl}-osl${osl}-c${concurrency}.json"
    if [[ -s "$output_dir/$filename" ]]; then
      echo "[$(date -u +%FT%TZ)] skip completed $filename"
      continue
    fi
    echo "[$(date -u +%FT%TZ)] ${label} ISL=${isl} OSL=${osl} c=${concurrency} n=${prompts}"
    timeout 7200 vllm bench serve \
      --backend openai-chat \
      --base-url "$base_url" \
      --endpoint /v1/chat/completions \
      --model /workspace/models/Qwen3.8-27B \
      --served-model-name "$model" \
      --tokenizer /workspace/models/Qwen3.8-27B \
      --dataset-name random \
      --random-input-len "$isl" \
      --random-output-len "$osl" \
      --random-range-ratio 0.0 \
      --ignore-eos \
      --request-rate inf \
      --temperature 0 \
      --max-concurrency "$concurrency" \
      --num-prompts "$prompts" \
      --seed 42 \
      --save-result \
      --result-dir "$output_dir" \
      --result-filename "$filename" \
      2>&1 | tee "$output_dir/${filename%.json}.log"
  done
done
