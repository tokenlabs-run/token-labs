#!/usr/bin/env bash
set -euo pipefail
wheel=${1:?Usage: build-flint.sh FLINT_WHEEL IMAGE_TAG [BUILDER]}
image_tag=${2:?Usage: build-flint.sh FLINT_WHEEL IMAGE_TAG [BUILDER]}
recipe_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
expected=ab15466f499748a527ad4ef5afa3b6d67927f4c300074f8ab2987abd5a836721
test "$(sha256sum "$wheel" | cut -d' ' -f1)" = "$expected"
dynamo_image=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["qwen"]["image"])' "$recipe_directory/images.json")
context_directory=$(mktemp -d /tmp/dynamo160-flint.XXXXXX)
trap 'rm -rf "$context_directory"' EXIT
mkdir "$context_directory/flint-wheels"
cp "$wheel" "$context_directory/flint-wheels/"
for file in Dockerfile.flint flint_text_compat.py flint-constraints.txt check_dependency_delta.py; do
  cp "$recipe_directory/$file" "$context_directory/"
done
builder_args=()
if [[ -n ${3:-} ]]; then builder_args=(--builder "$3"); fi
docker buildx build "${builder_args[@]}" --platform linux/arm64 \
  --build-arg "DYNAMO_IMAGE=$dynamo_image" \
  --label "run.tokenlabs.dynamo-image=$dynamo_image" \
  --label run.tokenlabs.vllm-revision=aed08d76a682f1475957c0730ea1f5ecb150fda0 \
  --file "$context_directory/Dockerfile.flint" \
  --tag "$image_tag" --push "$context_directory"
