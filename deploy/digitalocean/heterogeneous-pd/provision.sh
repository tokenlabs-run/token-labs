#!/usr/bin/env bash
set -euo pipefail

: "${DIGITALOCEAN_ACCESS_TOKEN:?export DIGITALOCEAN_ACCESS_TOKEN before running}"

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STATE=${STATE:-"$ROOT/state.json"}
REGION=${REGION:-atl1}
SSH_PUBLIC_KEY=${SSH_PUBLIC_KEY:-/home/nvidia/.ssh/id_ed25519.pub}
API=https://api.digitalocean.com/v2
TAG=${TAG:-token-labs-heterogeneous-pd}

command -v curl >/dev/null
command -v jq >/dev/null
test -s "$SSH_PUBLIC_KEY"

api() {
  local method=$1 path=$2 data=${3:-}
  if [[ -n "$data" ]]; then
    curl --fail-with-body --silent --show-error \
      -X "$method" \
      -H "Authorization: Bearer $DIGITALOCEAN_ACCESS_TOKEN" \
      -H 'Content-Type: application/json' \
      -d "$data" "$API$path"
  else
    curl --fail-with-body --silent --show-error \
      -X "$method" \
      -H "Authorization: Bearer $DIGITALOCEAN_ACCESS_TOKEN" \
      "$API$path"
  fi
}

if [[ -e "$STATE" ]]; then
  echo "Refusing to provision while state exists: $STATE" >&2
  exit 1
fi

pubkey=$(<"$SSH_PUBLIC_KEY")
key_id=$(api GET '/account/keys?per_page=200' | jq -r --arg key "$pubkey" \
  '.ssh_keys[] | select(.public_key == $key) | .id' | head -n1)
if [[ -z "$key_id" ]]; then
  payload=$(jq -n --arg name token-labs-benchmark --arg public_key "$pubkey" \
    '{name:$name,public_key:$public_key}')
  key_id=$(api POST /account/keys "$payload" | jq -r '.ssh_key.id')
fi

create_droplet() {
  local name=$1 size=$2 image=$3
  local payload
  payload=$(jq -n \
    --arg name "$name" --arg region "$REGION" --arg size "$size" \
    --arg image "$image" --arg tag "$TAG" --argjson key_id "$key_id" \
    '{name:$name,region:$region,size:$size,image:$image,ssh_keys:[$key_id],
      backups:false,ipv6:true,monitoring:true,tags:[$tag]}')
  api POST /droplets "$payload" | jq -r '.droplet.id'
}

decode_id=$(create_droplet token-labs-mi300x-decode gpu-mi300x1-192gb gpu-amd-base)
prefill_id=$(create_droplet token-labs-h200-prefill gpu-h200x1-141gb gpu-h100x1-base)

jq -n \
  --arg region "$REGION" --arg tag "$TAG" \
  --argjson decode_id "$decode_id" --argjson prefill_id "$prefill_id" \
  '{region:$region,tag:$tag,decode:{id:$decode_id,name:"token-labs-mi300x-decode"},
    prefill:{id:$prefill_id,name:"token-labs-h200-prefill"}}' >"$STATE"

echo "Provisioning started; state saved to $STATE"
echo "decode_id=$decode_id prefill_id=$prefill_id"

