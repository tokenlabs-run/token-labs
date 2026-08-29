#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
  echo "usage: $0 FRONTEND_URL PREFILL_LOG DECODE_LOG CONTROL_LOG" >&2
  exit 2
fi

frontend_url=$1
prefill_log=$2
decode_log=$3
control_log=$4

for log_file in "$prefill_log" "$decode_log" "$control_log"; do
  test -s "$log_file" || { echo "missing log: $log_file" >&2; exit 1; }
done


grep -Eq 'kv_producer|disaggregation-mode[ =]prefill|role[=: ]+prefill' "$prefill_log"
grep -Eq 'kv_consumer|disaggregation-mode[ =]decode|role[=: ]+decode' "$decode_log"
grep -Eq 'prefill.*decode|decode.*prefill|always-disagg|typed.*worker' "$control_log"
request_id="pd-gate-$(date -u +%s)"
response_file=$(mktemp)
trap 'rm -f "$response_file"' EXIT
curl -fsS --max-time 300 \
  -H 'content-type: application/json' \
  -H "x-request-id: $request_id" \
  -d '{"model":"Qwen/Qwen3.8-27B","messages":[{"role":"user","content":"Reply with exactly: PD_OK"}],"max_tokens":8,"temperature":0}' \
  "$frontend_url/v1/chat/completions" >"$response_file"
grep -q 'PD_OK' "$response_file"

transfer_id=$(grep -Eho 'tx[0-9a-f-]{16,}' "$prefill_log" "$decode_log" "$control_log" | tail -n 1)
test -n "$transfer_id"
grep -q "$transfer_id" "$prefill_log"
grep -q "$transfer_id" "$decode_log"
grep -Eq 'handshake|Handshake' "$prefill_log" "$decode_log"
grep -Eq 'finished_sending|completed.*transfer|transfer.*complete|KV.*transfer' "$prefill_log" "$decode_log"

printf 'P/D validation PASS request_id=%s transfer_id=%s\n' "$request_id" "$transfer_id"
