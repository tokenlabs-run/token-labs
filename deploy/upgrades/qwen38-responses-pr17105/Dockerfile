# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE=nvcr.io/nvidia/ai-dynamo/vllm-runtime-nightly@sha256:197284c3fd3037d4301ffa8282ed330446a5a371c0223fe1da448529930f064b
FROM ${BASE_IMAGE} AS builder
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl libaio-dev libclang-dev libnuma-dev \
    libprotobuf-dev libssl-dev libzmq3-dev patchelf pkg-config protobuf-compiler python3-dev \
    && rm -rf /var/lib/apt/lists/*
ENV RUSTUP_HOME=/opt/build-rustup CARGO_HOME=/opt/build-cargo
ENV PATH=/opt/build-cargo/bin:${PATH}
RUN curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o /tmp/rustup-init.sh \
    && sh /tmp/rustup-init.sh -y --profile minimal --default-toolchain 1.96.1 --no-modify-path \
    && rm /tmp/rustup-init.sh
RUN python3 -m pip install --no-cache-dir maturin==1.9.6
COPY source/ /source/
ARG SOURCE_REVISION
ENV DYNAMO_COMMIT_SHA=${SOURCE_REVISION}
RUN python3 -c 'from pathlib import Path; p=Path("/source/lib/bindings/python/pyproject.toml"); s=p.read_text(); assert s.count("version = \"1.6.0\"")==1; p.write_text(s.replace("version = \"1.6.0\"", "version = \"1.6.0.dev20261018+pr17105\"", 1))'
ENV CARGO_BUILD_JOBS=2 CARGO_TARGET_DIR=/build-target
WORKDIR /source/lib/bindings/python
RUN --mount=type=cache,id=qwen-pr17105-registry,target=/opt/build-cargo/registry \
    --mount=type=cache,id=qwen-pr17105-git,target=/opt/build-cargo/git \
    --mount=type=cache,id=qwen-pr17105-release,target=/build-target \
    maturin build --release --locked \
      --features kv-indexer,slot-tracker,select-service,mm-routing,ais-forward-pass,request-trace-s3,nvtx \
      --auditwheel skip --out /wheels

FROM ${BASE_IMAGE} AS runtime
USER root
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision=${SOURCE_REVISION} \
      run.tokenlabs.dynamo.base-revision=3763cee6080ce6a8ab4156f055d8ce72d984458c \
      run.tokenlabs.dynamo.fix-revision=a7ed39ca919128918241193760d138a448d6d12b
ENV DYNAMO_COMMIT_SHA=${SOURCE_REVISION}
COPY --from=builder /wheels/ /opt/tokenlabs/pr17105/wheels/
RUN python3 -m pip install --no-deps --force-reinstall /opt/tokenlabs/pr17105/wheels/*.whl \
    && python3 -m dynamo.frontend --help >/dev/null
USER dynamo
