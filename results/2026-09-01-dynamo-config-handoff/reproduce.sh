#!/usr/bin/env bash
set -euo pipefail
# CPU control/ownership evidence only. No inference engine or GPU is launched.
artifact_dir=$(cd -- "$(dirname -- "$0")" && pwd)
experiment_dir=$(mktemp -d)
trap 'rm -rf -- "$experiment_dir"' EXIT
revision=1df553558adb0465409c282eb27b1775ff1f60ba
git clone --quiet https://github.com/elizabetht/dynamo.git "$experiment_dir/source"
git -C "$experiment_dir/source" checkout --quiet --detach "$revision"
uv venv --python 3.11 "$experiment_dir/venv"
uv pip install --python "$experiment_dir/venv/bin/python" \
  pytest==9.1.1 pytest-asyncio==1.4.0 pytest-timeout==2.4.0 msgspec==0.21.1 uvloop==0.22.1
# Upstream shutdown tests stub dynamo._core, but their package parent imports
# native Dynamo during collection. Preserve the source/test relative layout
# outside that package; both files are copied byte-for-byte, without edits.
mkdir -p "$experiment_dir/shutdown/tests"
cp "$experiment_dir/source/components/src/dynamo/common/utils/graceful_shutdown.py" "$experiment_dir/shutdown/"
cp "$experiment_dir/source/components/src/dynamo/common/utils/tests/test_graceful_shutdown.py" "$experiment_dir/shutdown/tests/"
cd "$experiment_dir/source"
PYTHONPATH=lib "$experiment_dir/venv/bin/python" -m pytest -q \
  -o addopts='' -o filterwarnings='' \
  lib/gpu_memory_service/tests/test_failover_lock.py \
  lib/gpu_memory_service/tests/test_runtime_flows.py \
  "$experiment_dir/shutdown/tests/test_graceful_shutdown.py" \
  -k 'not large_allocation' --junitxml="$artifact_dir/tests.xml"
