#!/usr/bin/env bash
set -euo pipefail

: "${DIGITALOCEAN_ACCESS_TOKEN:?export DIGITALOCEAN_ACCESS_TOKEN before running}"

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STATE=${STATE:-"$ROOT/state.json"}
API=https://api.digitalocean.com/v2

test -s "$STATE"

for role in decode prefill; do
  id=$(jq -r ".${role}.id" "$STATE")
  name=$(jq -r ".${role}.name" "$STATE")
  actual=$(curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $DIGITALOCEAN_ACCESS_TOKEN" \
    "$API/droplets/$id" | jq -r '.droplet.name')
  if [[ "$actual" != "$name" ]]; then
    echo "Refusing to destroy id=$id: expected $name, found $actual" >&2
    exit 1
  fi
done

for role in decode prefill; do
  id=$(jq -r ".${role}.id" "$STATE")
  curl --fail-with-body --silent --show-error -X DELETE \
    -H "Authorization: Bearer $DIGITALOCEAN_ACCESS_TOKEN" \
    "$API/droplets/$id"
  echo "Destroyed $role droplet id=$id"
done

mv "$STATE" "$STATE.destroyed.$(date -u +%Y%m%dT%H%M%SZ)"

