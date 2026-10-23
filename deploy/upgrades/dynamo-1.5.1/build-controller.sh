#!/usr/bin/env bash
set -euo pipefail
upgrade_dir=$(cd -- "$(dirname -- "$0")" && pwd)
build_dir=$(mktemp -d /tmp/token-labs-ai-controller.XXXXXX)
git clone --depth 1 --branch v1.1.0 https://github.com/envoyproxy/ai-gateway.git "$build_dir/source"
test "$(git -C "$build_dir/source" rev-parse HEAD)" = c217da8a539570ba3f6014a60c2687c29a945f1f
git -C "$build_dir/source" apply "$upgrade_dir/ai-gateway-inferencepool.patch"
(
  cd "$build_dir/source"
  CGO_ENABLED=0 go test ./internal/extensionserver -run TestBuildHTTPFilterForInferencePool_Defaults -count=1
  CGO_ENABLED=0 go build -trimpath -ldflags='-s -w -X github.com/envoyproxy/ai-gateway/internal/version.version=v1.1.0-0-gc217da8' -o "$build_dir/controller" ./cmd/controller
)
docker build -f "$upgrade_dir/Dockerfile.ai-controller" -t localhost/token-labs/ai-gateway-controller:1.1.0-rust-epp "$build_dir"
