#!/usr/bin/env bash
set -euo pipefail

docker rm -f dynamo-etcd >/dev/null 2>&1 || true
docker run -d \
  --name dynamo-etcd \
  --network host \
  quay.io/coreos/etcd:v3.5.18 \
  /usr/local/bin/etcd \
  --name dynamo-etcd \
  --data-dir /etcd-data \
  --listen-client-urls http://127.0.0.1:2379 \
  --advertise-client-urls http://127.0.0.1:2379 \
  --listen-peer-urls http://127.0.0.1:2380
