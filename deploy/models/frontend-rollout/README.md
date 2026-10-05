# Independent Dynamo frontend rollout

Status: deployed on 2026-10-05 under an explicitly approved maintenance window.
Both stable Services select green on Dynamo `1.6.0.dev20261004`. Blue and the
original graph frontends remain running for rollback. Worker pod identities,
restart counts, images, and model revisions did not change.

The earlier staging attempt hit disk pressure and evicted Muse's frontend and
the aggregator. Both were restored before this maintenance deployment. For this
attempt, 51.57 GB of unused BuildKit cache older than seven days was reclaimed
before pulling the candidate. Serving images and model caches were retained.
Evidence is under `results/2026-10-05-frontend-nightly/maintenance/`.

## Image and scope

Green uses `nvcr.io/nvidia/ai-dynamo/dynamo-frontend-nightly:20261004-1cbc578`,
pinned to multi-platform digest
`sha256:38286598fd3a514a36bfddb90c2f8751350ccb787fabd307361673a534e46c4f`.
At inspection this was the latest published frontend nightly. Its source is
`1cbc57870a0a716e21a6ba7b532b12fc78eab87f`, a descendant of the merged
[Responses namespace fix](https://github.com/ai-dynamo/dynamo/pull/15401),
`f67423f6ad2fa14ead0765232609fb61e68251ea`.

Only CPU frontends change. Both slots discover the existing workers through
that graph's Kubernetes discovery namespace and service account. Keep the
original graph and service account alive. Candidate requests consume capacity
on the shared workers; do not run saturation tests against customer traffic
without an approved load budget.

Blue records the existing frontend image and configuration. Muse's image was
only locally tagged. Its containerd manifest digest is now recorded in the
blue manifest, with `imagePullPolicy: Never`. That digest reference was registered in controller's containerd image store
during recovery. Before starting blue, verify it still resolves to the existing
image; kubelet garbage collection can remove unused images. Do not pull it from localhost or rebuild it.

The nightly passed direct API smoke checks against both existing workers,
including Muse parser behavior and colliding namespace tool calls. These checks
do not establish a sustained capacity or latency benchmark.

## Files

Each active model's `dynamo/` directory contains:

- `frontend-blue.yaml`: a separate Deployment using the previous image.
- `frontend-green.yaml`: a separate Deployment using the pinned nightly.
- `frontend-diagnostics.yaml`: private Services for both slots.
- `frontend-service.yaml`: the stable Service, now selecting green.

`services.json` maps graph names to stable Services for the gateway generator.
The generated gateway Backends and Qwen/Muse agent API routes now reference these
Services in both repository and live state. GLM's existing route is unchanged.
The aggregator recognizes the stable Service label and its
`token-labs/replaces-service` annotation. It ignores diagnostic Services and
never falls back to the replaced Service if a stable Service fails.

Do not apply the model directory recursively. Do not apply the changed gateway
files before both stable Services have tested, ready blue endpoints.

## Gateway connection draining

The AI gateway's FQDN Backends connect to stable Service ClusterIPs. Existing
pooled connections can keep reaching blue after a selector change. The
`model-frontend-connections.yaml` BackendTrafficPolicy bounds connection reuse
to 60 seconds on the generated model route while retaining the 10 MiB buffer.
This is a connection lifetime, not a request or stream deadline. Envoy drains
active streams as described in its [timeout documentation](https://www.envoyproxy.io/docs/envoy/latest/faq/configuration/timeouts).

Native agent APIs use `/models/qwen/v1` and `/models/muse/v1`. The generic
`/v1/messages` path is not supported by the AI gateway; use the model-specific
prefix for Anthropic Messages. Generic `/v1/responses` also receives the new
frontend after pooled connections drain.

## Initial migration

Follow [MODEL_ROLLOUT_RUNBOOK.md](../MODEL_ROLLOUT_RUNBOOK.md), including operator
and verifier assignment, readiness duration, quality, capacity, latency,
overload, and rollback gates. This implementation does not waive those gates.

1. Restore controller disk headroom above its eviction reserve, verify node
   health, and reserve CPU and memory for the additional frontends. Before any
   image pull, account for compressed layers, unpacked snapshots, and a safety
   margin above the kubelet eviction reserve; current free space alone is not
   enough. Do not
   delete active images or model caches to make room.
2. Record public Service selectors, endpoints, image identities, and worker
   identities. Verify Muse's blue digest reference as described above.
3. Server-dry-run and apply the separate blue and green Deployments and
   diagnostic Services. Their labels cannot match the old operator Services.
4. Test each diagnostic Service directly. Run `scripts/serving/check_agent_apis.py`
   with `--base-url` and `--model`. It includes unary and streaming namespace
   collisions, `tool_choice: none`, and required crm/billing namespace selection.
   Complete the runbook's additional gates and the model-specific Muse tests.
5. Only after blue passes, create each stable Service and prove its ready
   endpoint is exactly the tested blue frontend. The old public path still
   serves the original frontend.
6. Migrate gateway Backend hostnames and the agent routes to the stable
   Services. Deploy the aggregator discovery change with its existing
   zero-unavailable rolling strategy after verifying its readiness behavior.
   Verify every public path, including catalog and OpenRouter proxy requests.
   This is a one-time routing migration with the previous frontend version.

## Nightly promotion and rollback

After the one-time migration and all green gates pass, atomically change only
`spec.selector.token-labs/slot` on the stable Service from `blue` to `green`,
using the runbook's JSON patch with a `test` of the previous value. Record the
same selector in that model's `frontend-service.yaml`. Gateway references,
workers, graph templates, and diagnostic Services remain unchanged.

Keep blue ready throughout observation and the 24-hour rollback window. To
roll back, test that the current selector is green and replace only the slot
with blue, then verify the public API. Keep the original operator frontends
running throughout this initial migration as well; do not modify the active
graph to retire them during this change.

Evidence for the initial blocked attempt and the exact old-frontend HTTP 400 is under
`results/2026-10-05-frontend-nightly/`.
