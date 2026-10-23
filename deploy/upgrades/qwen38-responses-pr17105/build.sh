#!/usr/bin/env bash
set -euo pipefail

source_checkout=${1:?Usage: build.sh SOURCE_CHECKOUT IMAGE_TAG [CONTEXT_DIRECTORY]}
image_tag=${2:?Usage: build.sh SOURCE_CHECKOUT IMAGE_TAG [CONTEXT_DIRECTORY]}
context_directory=${3:-$(mktemp -d /tmp/qwen-pr17105-build.XXXXXX)}
recipe_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source_revision=$(git -C "$source_checkout" rev-parse HEAD)
base_revision=3763cee6080ce6a8ab4156f055d8ce72d984458c
fix_revision=a7ed39ca919128918241193760d138a448d6d12b

test -z "$(git -C "$source_checkout" status --porcelain)"
git -C "$source_checkout" merge-base --is-ancestor "$base_revision" HEAD
# Require the merged fix's exact patch, rather than relying on the branch name.
expected_patch=$(git -C "$source_checkout" show "$fix_revision" --format= | git patch-id --stable | cut -d' ' -f1)
actual_patch=$(git -C "$source_checkout" diff "$base_revision" HEAD | git patch-id --stable | cut -d' ' -f1)
test "$expected_patch" = "$actual_patch"

mkdir -p "$context_directory/source"
git -C "$source_checkout" archive HEAD | tar -x -C "$context_directory/source"
cp "$recipe_directory/Dockerfile" "$context_directory/Dockerfile"
docker build --progress=plain --build-arg "SOURCE_REVISION=$source_revision" \
  --tag "$image_tag" "$context_directory"
docker image inspect "$image_tag" --format '{{json .}}' > "$context_directory/image.json"
printf 'Built %s from %s; context: %s\n' "$image_tag" "$source_revision" "$context_directory"
