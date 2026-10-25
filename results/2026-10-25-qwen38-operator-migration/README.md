# Qwen3.8 Dynamo operator migration — 2026-10-25

Qwen3.8 now runs as `DynamoGraphDeployment/qwen38-nvfp4-dynamo-agg` on
Spark-01. The operator manages separate frontend and vLLM worker pods and
Kubernetes discovery. The graph reports `Ready=True`, state `successful`.

Downtime on Spark-01 was explicitly authorized. The previous
`qwen38-nvfp4-blue` Deployment is retained at zero replicas. Its model revision,
image digest, cache paths, FlashInfer settings, MTP=3, FP8 KV cache, 131072-token
context and admission limit of four were preserved. Qwen3.6 on Spark-02 was
not changed and passed public inference checks during the migration.

## Routing

At 18:56:23 UTC, a resource-version-guarded patch changed only the stable
`qwen38-nvfp4` Service selector to the operator frontend. The aggregator still
uses this same stable Service. No aggregator code, configuration or restart
was needed. Its next discovery poll restored Qwen3.8 in the catalog.

The applied graph, diagnostic Service and PodMonitor are in
`deploy/models/qwen3.8-27b-nvfp4/dynamo/aggregated*.yaml`.
`aggregated-public-service.yaml` records the stable Service's new desired state.
`scripts/qwen38-27b/promote_operator.py` reproduces the guarded selector change
and defaults to a server-side dry run.

## Verification

- `conformance.json`: all 19 checks passed, including streaming, tool calls,
  structured output, error responses and deterministic arithmetic.
- `benchmark-c4.json`: 12 requests at concurrency four, zero errors,
  83.43 aggregate output tokens/sec, p95 TTFT 2.00 seconds and p95 end-to-end
  latency 12.60 seconds. This is a short migration check, not a new sustained
  capacity qualification. Previous 30-minute qualification remains in
  `results/2026-10-25-qwen38-spark/`.
- `aggregator-api.json`, `public-api.json`: both models passed authenticated
  streaming and non-streaming inference; anonymous provider requests rejected.
- `direct-public-route.json`: Qwen3.8 also passed `/v1/chat/completions`.
- `portal.json`: Chromium loaded the live portal, found both models, selected
  Qwen3.8, and recorded no JavaScript errors. Authenticated inference was tested
  separately against the public API, not by injecting credentials into Chromium.
- `public-observation.json`: 5 successful rounds over 122.0 seconds
  after cutover, testing both models through the public API.
- `overload.json`: four requests admitted, four rejected with HTTP 429 and
  Retry-After; maximum rejection latency 386.53 ms.
- `graph-ready.json`, `pods-ready.json`, `health-after.json`: operator ownership,
  ready frontend/worker, zero restarts, healthy nodes and unchanged aggregator
  Service specification.
- `metrics-up.json`: frontend and worker Prometheus targets are up. The worker
  is selected by both the existing general Dynamo monitor and the explicit
  model monitor; queries should select one job to avoid double-counting.
- Spark-01 kernel journal since 18:49 UTC had no GPU Xid or OOM entries.

The first frontend pod failed because empty container args caused the operator
to append default module arguments. The renderer now uses `command: [python3]`
and `args: [-m, dynamo.frontend]`, matching the Qwen3.6 layout. The replacement
frontend passed all checks without restarts. The initial public and browser
checks ran before the discovery poll converged; fresh checks passed afterward.

## Rollback

The saved previous Deployment and Service specifications are in this directory.
Because both layouts require the same GPU, rollback also requires downtime:
scale the operator worker to zero, wait for GPU release, restore the previous
Deployment to one replica, verify its diagnostic endpoint, then atomically
restore the stable Service's previous selector. Do not run both GPU workers at
once. The aggregator route remains unchanged.
