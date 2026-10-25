# Build Dynamo 1.6.0 images with PR #17105

Build one standard vLLM runtime per CPU architecture. Each runtime includes
both `python3 -m dynamo.frontend` and `python3 -m dynamo.vllm`.
Use the standard AMD64 image for Qwen on RunPod and the ARM64 image for Qwen
on DGX Spark. The Flint compatibility build below targets DGX ARM64 only.
A separate frontend build and EPP are not required for these deployments.

Flint also needs the derived ARM64 image in step 5 because the standard
vLLM 0.31.0 runtime lacks its model implementation.

## 1. Prepare the patched source

On the controller, create a checkout of the release and backport the merged fix:

```bash
mkdir -p "$HOME/src/github.com/elizabetht"
cd "$HOME/src/github.com/elizabetht"
git clone --branch v1.6.0 https://github.com/ai-dynamo/dynamo.git dynamo-160-pr17105
cd dynamo-160-pr17105
git switch -c fix/tokenlabs-160-pr17105
git fetch origin a7ed39ca919128918241193760d138a448d6d12b
git cherry-pick a7ed39ca919128918241193760d138a448d6d12b
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
```

Skip cloning/cherry-picking if you are using the existing patched checkout.
The release commit is `701da25292ecca8f64d770cc0b17d389200019a1`.
The patched tree must be `a2a83a1b92dd62902a6e3a17ebead5369ecccfd2`.
PR #17105 fixes Responses requests with `tool_choice: "auto"` and no function tools.

Create an independent checkout for ARM64 before rendering either Dockerfile:

```bash
git worktree add --detach ../dynamo-160-pr17105-arm64 HEAD
```

Two terminals may build concurrently when they use separate checkouts.
`container/render.py --output-short-filename` writes
`container/rendered.Dockerfile`; two renders in the same checkout can overwrite
that shared file with different architecture settings.

## 2. Prepare each native build host

Use the AMD64 controller for the AMD64 build and an ARM64 Spark host for the
ARM64 build. GPUs are not needed to compile the runtime image. GPU startup and
inference must be checked separately after deployment.

Make the patched ARM64 checkout available on Spark, for example by copying
from the controller to a separate destination on `spark-01`:

```bash
rsync -a --exclude=.git --exclude=target --exclude=.venv \
  "$HOME/src/github.com/elizabetht/dynamo-160-pr17105-arm64/" \
  nvidia@192.168.1.76:/home/nvidia/src/github.com/elizabetht/dynamo-160-pr17105-arm64/
```

On the controller, check disk space before starting builds. This cluster's
kubelet evicts workloads below 15% free space (about 125 GiB on its 836 GiB
filesystem). Leave additional headroom for Cargo artifacts and pulled images;
building down to that threshold can stop ingress. Recheck node pressure during
the build:

```bash
df -h /
kubectl --context=kubernetes-admin@kubernetes get nodes
kubectl --context=kubernetes-admin@kubernetes get node controller \
  -o jsonpath='{.status.conditions[?(@.type=="DiskPressure")].status}{"\n"}'
```

Run these checks on each build host:

```bash
uname -m
docker version
docker ps
docker login docker.io
```

The controller must report `x86_64`; Spark must report `aarch64`.
If Docker reports that it cannot connect to `/var/run/docker.sock`, start its
daemon on that host and check again:

```bash
sudo systemctl start docker
docker ps
```

If Docker reports socket permission denied, use the host's configured Docker
access or have an administrator grant it. A registry login does not fix a
stopped daemon.

On each host, install the Dockerfile renderer dependencies in a virtualenv:

```bash
python3 -m venv "$HOME/.venvs/dynamo160-render"
source "$HOME/.venvs/dynamo160-render/bin/activate"
python3 -m pip install jinja2 pyyaml
```

Run the ARM64 build on native ARM64 BuildKit. The initial ARM64 build through
AMD64/QEMU failed extracting hwloc; the completed build used native Spark
BuildKit. Reserve CPU, memory, and disk space while serving models on the host.

## 3. Render, build, and push each architecture

On the AMD64 controller:

```bash
cd "$HOME/src/github.com/elizabetht/dynamo-160-pr17105"
source "$HOME/.venvs/dynamo160-render/bin/activate"
export SOURCE_SHA=$(git rev-parse --short=12 HEAD)
export IMAGE_REPO=docker.io/elizabetht/dynamo
export IMAGE_TAG="1.6.0-pr17105-${SOURCE_SHA}-amd64"

python3 container/render.py --framework=vllm --target=runtime \
  --platform=linux/amd64 --output-short-filename

docker buildx create --name dynamo160-amd64 --driver docker-container
docker buildx inspect dynamo160-amd64 --bootstrap
docker buildx build --builder dynamo160-amd64 \
  --platform linux/amd64 --file container/rendered.Dockerfile \
  --build-arg CARGO_BUILD_JOBS=8 --build-arg MAX_JOBS=8 \
  --label "org.opencontainers.image.revision=$SOURCE_SHA" \
  --tag "$IMAGE_REPO:$IMAGE_TAG" --push .
```

On Spark, use the copied ARM64 checkout. Set `SOURCE_SHA` to the source commit
printed in step 1, since the copied checkout excludes Git metadata:

```bash
cd "$HOME/src/github.com/elizabetht/dynamo-160-pr17105-arm64"
source "$HOME/.venvs/dynamo160-render/bin/activate"
export SOURCE_SHA=6fa7c96c63e7  # Existing published ARM64 source; use yours for a new build.
export IMAGE_REPO=docker.io/elizabetht/dynamo
export IMAGE_TAG="1.6.0-pr17105-${SOURCE_SHA}-arm64"

python3 container/render.py --framework=vllm --target=runtime \
  --platform=linux/arm64 --output-short-filename

docker buildx create --name dynamo160-arm64 --driver docker-container
docker buildx inspect dynamo160-arm64 --bootstrap
docker buildx build --builder dynamo160-arm64 \
  --platform linux/arm64 --file container/rendered.Dockerfile \
  --build-arg CARGO_BUILD_JOBS=8 --build-arg MAX_JOBS=8 \
  --label "org.opencontainers.image.revision=$SOURCE_SHA" \
  --tag "$IMAGE_REPO:$IMAGE_TAG" --push .
```

If a named builder already exists, reuse it and skip `buildx create`.
`--push` publishes the result; a successful render only creates a Dockerfile.
The completed AMD64 and ARM64 builds used different cherry-pick commit IDs but
have the same source tree:

- AMD64: `docker.io/elizabetht/dynamo:1.6.0-pr17105-9f76684aabd7-amd64`.
- ARM64: `docker.io/elizabetht/dynamo:1.6.0-pr17105-6fa7c96c63e7-arm64`.

## 4. Verify the published runtime

Inspect each tag, then pull and inspect it on a matching native host:

```bash
export IMAGE=docker.io/elizabetht/dynamo:1.6.0-pr17105-6fa7c96c63e7-arm64
docker buildx imagetools inspect "$IMAGE"
docker pull --platform linux/arm64 "$IMAGE"
docker image inspect "$IMAGE" --format '{{.Os}}/{{.Architecture}}'
docker run --rm --entrypoint python3 "$IMAGE" -c \
  'import importlib.metadata as m; print({p:m.version(p) for p in ("ai-dynamo", "ai-dynamo-runtime", "vllm", "torch")})'
docker run --rm --entrypoint python3 "$IMAGE" -m dynamo.frontend --help
```

For AMD64, replace the tag and platform with their AMD64 values.
Expect Dynamo and runtime `1.6.0`, vLLM `0.31.0`, and Torch `2.13.0+cu130`.
Worker `--help` can initialize CUDA and fail on a CPU-only host; that is not a
GPU serving test.

The registry index must contain a real `linux/arm64` or `linux/amd64` image
manifest. An additional `unknown/unknown` manifest annotated
`attestation-manifest` is expected. It is provenance, not a runnable image.
Pulling that digest directly produces `unsupported media type
application/vnd.in-toto+json`.

Use the real platform manifest digest for Kubernetes image references.
[`images.json`](images.json) records the published ARM64 references and hashes.

To retag and push an entire published index without downloading its layers:

```bash
docker buildx imagetools create \
  --tag docker.io/elizabetht/dynamo:NEW_TAG \
  docker.io/elizabetht/dynamo-160-pr17105:ORIGINAL_TAG
```

For an image already loaded into the local Docker daemon:

```bash
docker tag docker.io/elizabetht/dynamo-160-pr17105:ORIGINAL_TAG \
  docker.io/elizabetht/dynamo:NEW_TAG
docker push docker.io/elizabetht/dynamo:NEW_TAG
```

A destination tag must not include `@sha256:...`. Copy the full original index
when using `imagetools create`; selecting only its attestation creates an
unpullable tag.

## 5. Build the Flint-compatible ARM64 runtime

Run from this `token-labs` repository on a host with access to native ARM64
BuildKit. The helper takes a cached Flint vLLM wheel, a destination tag, and an
optional buildx builder name:

```bash
export FLINT_WHEEL=/home/nvidia/.cache/huggingface/flint-vllm-pr/aed08d76a682f1475957c0730ea1f5ecb150fda0/wheels/vllm-0.32.0.dev0+pr62938.aed08d76.precompiled-cp312-cp312-linux_aarch64.whl
bash deploy/upgrades/dynamo-1.6.0/build-flint.sh \
  "$FLINT_WHEEL" \
  docker.io/elizabetht/dynamo:1.6.0-pr17105-6fa7c96c63e7-flint-arm64 \
  dynamo160-arm64
```

The cached wheel is on `spark-01`. Copy it to the build-client host if needed.
The helper verifies SHA-256
`ab15466f499748a527ad4ef5afa3b6d67927f4c300074f8ab2987abd5a836721`
and uses an isolated temporary build context. It reads the Dynamo image from
`images.json`; update that immutable reference if rebuilding from new source.

If the cached wheel is unavailable, build it using
[`build-pr-runtime.py`](../../models/flint-nvfp4/plain-vllm/build-pr-runtime.py)
in the pinned ARM64 base below. This command builds Python/JIT changes with the
base's native extensions; it does not require GPU access:

```bash
export TOKENLABS_ROOT=$(pwd)
docker run --rm --platform linux/arm64 --entrypoint python3 \
  --mount "type=bind,src=$TOKENLABS_ROOT/deploy/models/flint-nvfp4/plain-vllm/build-pr-runtime.py,dst=/tmp/build-pr-runtime.py,readonly" \
  --mount "type=bind,src=$HOME/.cache/huggingface,dst=/model-cache" \
  --tmpfs /runtime:rw,size=2g \
  vllm/vllm-openai:flint@sha256:5641d14b70c991f8b78c3a5baf0281cb73dbd2ea69932dd6a328820f420ec4bc \
  /tmp/build-pr-runtime.py
```

A regenerated wheel may have a different archive hash because of build
metadata. Compare its source/native provenance before updating the helper's
expected hash; do not bypass the check.

The derived image retains vLLM PR #62938 and Torch `2.14.0+cu130`, installs the
patched Dynamo wheels and native libraries, and applies the scoped text-worker
compatibility changes described in [the upgrade README](README.md).
Inspect and pull its tag as in step 4, then run GPU startup and API checks.

These instructions build images only. Deployment manifests and rollback
snapshots are in this directory; applying them to the active DGX workers uses
the user's explicitly approved one-time downtime exception.
