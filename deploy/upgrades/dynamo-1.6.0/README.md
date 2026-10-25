# Upgrade DGX Qwen and Flint to Dynamo 1.6.0

This is the October 23 upgrade record. Flint was retired on October 25. Current Qwen3.8 operator manifests are in `deploy/models/qwen3.8-27b-nvfp4/dynamo/`; shared aggregator manifests are in `deploy/platform/model-aggregator/`. The saved Flint manifests are historical rollback artifacts, not the current deployment.

Status: both models are deployed. GPU, API, internal and public gateway,
overload, and 30-minute load checks passed. The user explicitly approved a one-time
exception to the repository's blue/green-only rule for Qwen and Flint, including
stopping each old GPU worker before starting its inspected replacement.
`results/2026-10-23-dynamo-1.6.0/downtime-exception.json` records that approval.
Fresh pre-upgrade specifications are saved in the same evidence directory.

See [Build Dynamo 1.6.0 images with PR #17105](BUILD_IMAGES.md) for the complete
source, native AMD64/ARM64 build, publish, verification, retagging, and Flint
image instructions.

## Runtime inputs

`images.json` records immutable image references and source identities. The
Dynamo source is `v1.6.0` (`701da25292ecca8f64d770cc0b17d389200019a1`) with
merged PR #17105 (`a7ed39ca919128918241193760d138a448d6d12b`) backported.
The ARM64 source commit is `6fa7c96c63e71db39ce05c49aa53dd906c3af7f0`.
Its Git tree matches the AMD64 source commit `9f76684aabd77faac5f80f54658dfaa1dca0ca5e`:
`a2a83a1b92dd62902a6e3a17ebead5369ecccfd2`.

The standard ARM64 vLLM runtime contains both frontend and worker entrypoints.
It reports `ai-dynamo==1.6.0`, `ai-dynamo-runtime==1.6.0`, vLLM `0.31.0`,
and Torch `2.13.0+cu130`. Its Spark inspection also verifies that the installed
Rust library matches the supplied wheel byte-for-byte.

Before this upgrade, Flint used plain vLLM with the Flint implementation from vLLM PR
#62938. Standard vLLM 0.31.0 lacks that implementation. The derived Flint image
therefore keeps the exact existing native base and vLLM wheel, then installs
the patched Dynamo wheels. It also copies the Dynamo-specific shared libraries
required by the Rust runtime. `flint_text_compat.py` makes two scoped changes:

- Defer the embedding-only vLLM import that was removed in vLLM 0.32. Flint
  uses the text-generation path, not the shared embedding-process path.
- Use `hf_config_path` for tokenizer/configuration metadata when a separate
  checkpoint file is supplied. Rust model-card loading requires a directory;
  Flint's weights are a GGUF file.

`flint-constraints.txt` preserves the serving stack's protobuf and gRPC versions.
The build rejects dependency conflicts introduced beyond those in the pinned
serving base. GPU startup, model identity, generation, tools, structured output, and Responses
regression checks have passed with this adapter. Its 30-minute capacity run
also passed.

## Deployment changes

- Qwen: use the patched ARM64 runtime for its worker, diagnostic sidecar,
  and public frontend. Move the frontend from the controller to `spark-02`;
  it was Pending because of pre-existing controller disk pressure.
- Flint: preserve its checkpoint, tokenizer, served name, context limit,
  and engine flags. Run a Dynamo worker plus a Dynamo frontend in the same
  pod, with a shared file-discovery volume.
- Flint metrics: retain the existing metrics Service, but target the worker's
  `system` port instead of the frontend's `http` port.
- Preserve public Service selectors, gateway routes, credentials, and the
  installed Kubernetes operator. No EPP deployment is involved.

`inputs/` contains the captured configuration. `manifests/` contains the deployed
resources. `rollback/` contains the original specifications. Do not apply the
whole directory: inputs, proposals, and rollback files have different purposes.
The user approved this in-place rollout as a one-time exception.

## Reproduce the artifacts

`prepare_qwen.py --image <digest-reference>` and
`prepare_flint.py --image <digest-reference>` regenerate the manifests and
rollback specifications from the captured inputs. Rendered resources have
passed Kubernetes server-side dry runs; that does not establish GPU serving
compatibility.

`build-flint.sh FLINT_WHEEL IMAGE_TAG [BUILDER]` builds the derived ARM64 image
using the Dynamo image in `images.json`. It verifies the existing Flint wheel's
SHA-256 before creating an isolated build context. The wheel is reproducible
with `deploy/models/flint-nvfp4/plain-vllm/build-pr-runtime.py` against its pinned
native base. It is not committed here.

## Validation evidence

Evidence is in `results/2026-10-23-dynamo-1.6.0/`:

- Responses unit tests: 82 passed.
- Frontend HTTP validation tests: 17 passed.
- Existing Qwen: generation, streaming, and structured tool calls passed;
  132 streaming load requests at concurrency four completed without errors.
- Existing Flint: model identity, generation, streaming, and structured tool
  calls passed; 89 streaming load requests at concurrency one completed
  without errors.
- New standard ARM64 image: package imports, architecture, versions, and
  installed Rust-library hash passed on `spark-02`.
- New Flint ARM64 image: package imports, actual checkpoint metadata resolution,
  and Rust-library hash passed on `spark-01`. Both images contain the same
  compiled Rust library. No dependency conflicts were introduced beyond the
  two conflicts already present in the pinned Flint base.

Both new-runtime load runs completed with zero errors:

| Model | Concurrency | Duration | Requests | p95 first token | p95 total |
| --- | --- | --- | --- | --- | --- |
| Qwen | 4 | 30 minutes | 2,084 | 2.97 s | 6.61 s |
| Flint | 1 | 30 minutes | 1,371 | 1.30 s | 2.12 s |

Qwen passed 15 protocol cases; Flint passed 12 applicable cases. Each passed
all four PR #17105 regression cases, 24 internal-gateway conformance checks,
and 24 authenticated public-HTTPS checks (three repetitions per gateway). Qwen's overload check admitted 16 requests and rejected
eight; Flint admitted one and rejected eight. Every rejection included
`Retry-After`; p95 rejection latency was below 60 ms for both.

`running-runtime-versions.json` verifies Dynamo 1.6.0 in both workers and all
three frontend containers. `deployed-state.json` records the final resources
and confirms that public Service selectors were preserved.

Generate the combined evidence summary after all checks finish:

```bash
python3 deploy/upgrades/dynamo-1.6.0/summarize.py \
  --evidence results/2026-10-23-dynamo-1.6.0
```

The baseline runs lasted two minutes. See the rollout record below for
measurement differences and limits.

## DGX rollout record

The user approved a one-time exception to the repository's blue/green-only
policy for this upgrade. There were no spare GPUs. The normal rule in
`AGENTS.md` was not edited.

1. Capture fresh resource specifications and public Service selectors in
   `approved-before-*.json` under the evidence directory.
2. Set Qwen's DGD worker replicas to zero. Wait for its PodClique replica count
   to reach zero, the old pod to disappear, and CUDA processes to exit.
3. Set the new worker and sidecar image references while replicas remain zero.
   Wait for the PodClique template to contain the new images before setting
   replicas to one. A DGD template update does not guarantee that Grove has
   stopped using its previous template; verify the actual pod image IDs.
4. Apply the pinned Qwen frontend manifest on `spark-02`. Its old controller
   placement was Pending because of controller disk pressure.
5. Verify Qwen generation, streaming, tools, Anthropic, namespace tools, and the
   four PR #17105 Responses cases before replacing Flint.
6. Apply the Flint deployment and metrics-Service manifest. Wait for both
   worker and frontend to be ready, then repeat the applicable API checks.
7. Run sustained load, watch readiness/restarts and engine metrics, and check
   the existing gateway's conformance and overload controls.

Use the four resources in `manifests/` only for this recorded deployment.
The `rollback/` resources restore the earlier specifications; restarting an old
GPU runtime also takes downtime. The fresh `approved-before-*.json` snapshots
provide the state immediately before this rollout.

### Load interpretation

`check_api.py` verifies completed responses and tool behavior. `check_protocols.py`
checks the enabled protocol and namespace-tool paths. `check_gateway.py` runs
three repetitions of the repository's gateway conformance suite, including
authentication, tools, and structured output. It keeps the referenced provider
credential in memory. The user explicitly approved using it only as an HTTPS
Authorization header to `https://api.tokenlabs.run/openrouter/v1` for these
checks. Both models passed all 24 authenticated public checks, including
authentication, generation, streaming, tools, and structured output.
Unauthenticated public checks returned 200 for the provider catalog and 401
for protected model discovery after ingress recovery.

`load_check.py` measures stream completion, generated tokens, errors, and
latency at three input sizes. The baseline runs lasted two minutes; the new
runs last 30 minutes, so prefix-cache warm-up differs. Qwen's old baseline
used its direct worker-sidecar frontend; the new run uses its stable frontend
Service. These results are operational comparisons, not a controlled runtime
benchmark. Flint can use its entire output budget for
reasoning. The initial 64-token and 512-token content-only load attempts stopped
on a response without final-answer content; those reports are retained as
`flint-160-load-64tokens.*` and `flint-160-load-512tokens.*`.
The sustained Flint capacity run uses `--include-reasoning --max-tokens 64`,
counting `reasoning_content` as generated tokens and recording its character
count separately from answer content. A passing capacity request establishes
stream/token production, not a completed final answer. Latency comparisons with
the old plain-vLLM content-only baseline have that channel-semantics limitation.

`observe.py` records model pod readiness, restarts, Spark node pressure, queues,
and KV-cache utilization during the load run. These checks and the arithmetic
and protocol probes are upgrade validation; no separate model-quality benchmark
was run.

### Controller ingress recovery

Controller disk pressure was present before the GPU rollout and had already stopped
public ingress. The internal provider gateway continued running on `spark-01`.
After the models were upgraded, recovery removed this task's completed Cargo
artifacts, its local AMD64 runtime/base copies (the published image remains on
Docker Hub), unused BuildKit cache, and unused Python package caches. No model weights or active model
containers were removed. The controller had about 138 GiB free afterward.

The pinned localhost AI-gateway-controller image was also missing from containerd.
Restore the unchanged image from its Docker cache into Kubernetes containerd:

```bash
docker image save --output /tmp/ai-gateway-controller.tar \
  localhost/token-labs/ai-gateway-controller:1.1.0-rust-epp
sudo ctr -n k8s.io images import --digests /tmp/ai-gateway-controller.tar
sudo ctr -n k8s.io images ls | grep ai-gateway-controller
```

Verify that the imported manifest is
`sha256:71cdab34040213143b8ece4ad1f10bd785d6db9abb34aa6c448831647f53995b`
before restoring its digest reference:

```bash
sudo ctr -n k8s.io images tag \
  localhost/token-labs/ai-gateway-controller:1.1.0-rust-epp \
  localhost/token-labs/ai-gateway-controller@sha256:71cdab34040213143b8ece4ad1f10bd785d6db9abb34aa6c448831647f53995b
```

The existing image tag includes `rust-epp`; restoring it preserves the installed
controller. This upgrade does not deploy or use EPP. Once disk pressure cleared,
the controllers and Envoy proxy recovered without a deployment-template change.
