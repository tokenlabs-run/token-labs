# Qwen3.8-27B-NVFP4 on Spark-01

The model runs as DynamoGraphDeployment `qwen38-nvfp4-dynamo-agg`, with separate
operator-managed worker and frontend pods on Spark-01.
Qwen3.6 remains on Spark-02. Both models are published through `model-aggregator` and the Token Labs portal.
Evidence is in `results/2026-10-25-qwen38-spark/`.
The 30-minute post-publication observation passed all 61 rounds, with no worker
restarts, readiness drops, thermal throttling, or node-pressure events.

## Operator-managed aggregated manifest

`aggregated.yaml` follows the Qwen3.6 `DynamoGraphDeployment` layout, with separate
`Frontend` and `VllmWorker` components on Spark-01. The worker combines prefill and
decode. The Dynamo operator supplies Kubernetes discovery, the graph namespace,
and service-account permissions. Both components use the pinned 1.6.0 runtime.

`aggregated-service.yaml` provides a separate diagnostic endpoint.
`aggregated-podmonitor.yaml` selects the operator-managed worker for metrics.
These manifests are applied. `aggregated-public-service.yaml` points the stable
`qwen38-nvfp4` Service to the operator frontend. The previous
`qwen38-nvfp4-blue` Deployment is scaled to zero and retained for rollback; both
layouts require the same Spark-01 GPU. Migration evidence is in
`results/2026-10-25-qwen38-operator-migration/`.

`scripts/qwen38-27b/render_aggregated.py` regenerates `aggregated.yaml` from the
validated `candidate.json` settings. The existing public Service and aggregator
configuration remain separate from these manifests.

## Model and runtime

| Setting | Value |
| --- | --- |
| Served model | `nvidia/Qwen3.8-27B-NVFP4` |
| Model revision | `482ca0f3832238542f8f5295dde86b5f22711d80` |
| Runtime | Dynamo 1.6.0 with vLLM 0.31.0, ARM64 |
| Image digest | `docker.io/elizabetht/dynamo@sha256:4a317828d3fb5f4eb1ae433ddfbca8dbbaeacd1eec36333bec3e99409a1e82f4` |
| GPU | One GB10 on Spark-01 |
| Input | Text only |
| Maximum context | 131,072 tokens, including output |
| Speculation | MTP, three draft tokens |
| KV cache | FP8 |
| Attention | FlashInfer |
| NVFP4 linear kernel | Automatic selection, observed FlashInfer CUTLASS |
| Prefill chunk limit | 2,048 tokens |
| Engine sequence limit | Eight |
| Aggregator admission limit | Four requests for this model |
| GPU memory fraction | 0.75 |
| Default thinking mode | Disabled |
| Prefix cache | Enabled |

`candidate.json` contains the complete worker and frontend configuration.
`model-input-sha256.txt` in the evidence directory records tokenizer, template,
configuration, and quantization hashes. Credentials remain Kubernetes Secret
references. The manifests contain no credential values.

## Measured performance

The comparison used one request at a time, three prompt families, nine measured
requests, and 256 output tokens per request. Each configuration received three
warm-up requests. Decode rate uses completion-token usage and first-to-last
content timing. Time to first token includes the request path.

| Configuration | Median decode tokens/sec | p95 first token, seconds |
| --- | ---: | ---: |
| FlashInfer, MTP 3 | 27.83 | 0.224 |
| Marlin, MTP 3 | 27.28 | 0.227 |
| FlashInfer, MTP 5 | 26.45 | 0.260 |
| Selected configuration, repeat | 27.55 | 0.226 |
| Selected configuration, public API | 27.44 | 0.286 |

This is the best measured configuration for the stated single-user objective,
not a global optimum. The differences between the two kernels are small.
The EAGLE-4 wheel examined during preparation supports x86_64, not this ARM64
host. An 8,192-token prefill candidate stalled during kernel autotuning and was
replaced before publication.

The initial four-request workload reached 83.61 aggregate output tokens/sec,
with p95 time to first token of 1.96 seconds. That workload uses repeated short,
medium, and long contexts with prefix caching. The 30-minute sustained run completed 588 requests without errors at 83.10
aggregate output tokens/sec. Its p95 first-token latency was 1.97 seconds, and
its p95 request latency was 12.87 seconds.

## Services and evidence

`qwen38-nvfp4-dynamo-agg` is the diagnostic model Service. `qwen38-nvfp4` is the stable
model Service. `model-aggregator-qwen38-blue` is the active shared aggregator for both models.
Its Deployment, discovery allowlist, concurrency limits, Services and ConfigMaps
are maintained in `deploy/platform/model-aggregator/`.
The existing aggregator remains available for rollback. The public portal reads
the live aggregator catalog, so publication requires no static portal model list.

`aggregated-podmonitor.yaml` collects operator worker metrics through the named
`system` port. `podmonitor.yaml` belongs to the previous Deployment layout.
`direct-backend.yaml` connects the new model route to aggregator admission control.
The static OpenRouter commercial catalog remains empty.

The scripts in `scripts/qwen38-27b/` provide the following checks and operations:

- `render_aggregated.py` renders the active operator graph from the pinned settings.
- `promote_operator.py` checks graph readiness, endpoints, API and load evidence
  before atomically switching the stable model Service; it defaults to dry run.
- `render_candidate.py` renders the previous plain Deployment manifest.
- `apply_candidate.py` refuses to modify a candidate selected by any Service
  other than its diagnostic Service.
- `run_variant.py` applies an unpublished candidate and measures single-user speed.
- `benchmark.py` measures decode speed, latency, errors, and concurrent throughput.
- `verify_candidate.py` checks API conformance and deterministic arithmetic.
- `check_long_context.py` tests a prompt near the context limit inside the worker.
- `verify_gateway.py` checks both models with the provider key held in memory.
- `observe.py` records readiness, restarts, node health, cache use, and GPU state.
- `promote_aggregator.py` requires passing evidence before changing only the stable
  aggregator selector. The default is a server-side dry run.
- `add_route.py` appends only the new model rule with a resource-version check.
- `verify_portal.py` checks model discovery and selection in Chromium.
- `watch_public.py` checks authenticated inference during the observation window.
- `check_cutover_stream.py` verifies an existing request survives the selector switch.
- `finalize_report.py` checks completed observations and the live selectors before
  marking the report complete.

The model is frozen once its stable Service exists. A future runtime change needs
separate capacity and the repository's model rollout procedure. Applying
`candidate.json` directly to an active deployment would violate that procedure.
