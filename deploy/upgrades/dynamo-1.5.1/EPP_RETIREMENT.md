# Qwen EPP retirement and health-check maintenance

On 2026-10-22 the user explicitly authorized using the same GPU and accepted service disruption. This overrides the independent-capacity requirement for this maintenance only. The prior zero-downtime candidate was not applied.

The Qwen worker was stopped in `qwen36-nvfp4-dynamo-agg-151-epp` and its pinned configuration moved to the existing `qwen36-nvfp4-dynamo-agg` graph on spark-02. The old graph worker uses component type `worker` and runtime override 1.5.1. `DYN_HEALTH_CHECK_ENABLED=false` disables the inference-payload canary responsible for queue-related false liveness failures. The runtime's engine monitor remains enabled. Model revision, image digest, context length, sequence limit and generation/parser arguments were preserved.

The graph Frontend component is disabled. It was temporarily restored on spark-02 to satisfy its immutable minimum availability, but the pinned old frontend image is amd64-only and failed with `exec format error` on ARM. It was scaled back to zero. Public serving continues through the existing blue frontend Deployment on the amd64 controller. The stable Service selector is unchanged.

Grove recreated the GPU worker during the frontend template update despite its unchanged worker template. A stale in-progress Grove rollout was cleared by recreating only the graph-owned PodCliqueSet. This caused an additional model reload within the user-approved disruption. The final worker includes its original frontend sidecar and has the explicit canary-disable flag. DGD readiness stayed false during the in-progress Grove rollout. An initial suspicion that the disabled frontend would permanently prevent readiness proved incorrect: after the final worker became ready, the operator reported `All resources are ready`. The embedded frontend remains disabled and the external blue frontend serves traffic.

The old frontend's six namespace-tool cases remain a known limitation. The generic public `/v1/chat/completions` path returned HTTP500 before maintenance and is a separate unresolved fault. Validation uses `/models/qwen/v1/chat/completions`. Controller disk pressure remains a separate availability risk.

`inputs/qwen-epp-free-graph.yaml` is the new generator input. `generate.py` renders the EPP-free graph and a diagnostic Service pointing to the blue frontend. It no longer renders a Qwen EPP graph or routes to its pool. Existing route retirement was performed with `disable_qwen_epp.py --routes-only`.

The earlier isolated candidate and independent-capacity instructions below are historical preparation, not the actual maintenance path. Before/after snapshots, rollback manifests, user authorization, API checks and queue observations are saved under `results/2026-10-22-qwen36-same-gpu-maintenance/`. The maintenance report there records actual outcomes.

---

## Prior preparation

# Qwen EPP retirement and health-check candidate

The stable `qwen36-nvfp4-frontend` Service now selects the existing blue Deployment. It runs the same pinned frontend image as the old graph frontend. Chat, streaming chat and forced tool calls passed through its diagnostic Service before the selector-only switch. The old frontend's six namespace-tool cases remain a known limitation; the current nightly frontend had passed all fifteen API cases. The user selected the old frontend after that comparison.

The Qwen EPP InferencePool rule was removed from `AIGatewayRoute/token-labs-models`. The Qwen upgrade canary now references the stable frontend Service directly. Other model routes were preserved. The active GPU Pod UID, Pod specification, container IDs and restart counts were checked before and after. The GPU worker was not restarted or modified. The separate model-specific public chat path passed after the switch. The generic `/v1/chat/completions` path returned HTTP500 both before and after route retirement; that pre-existing fault remains unresolved.

EPP has been removed from these traffic paths, but its component and Pod remain. Server-side dry runs rejected both supported-looking in-place approaches:

- Setting EPP replicas to zero: `EPP component must have exactly 1 replica`.
- Removing EPP from the existing DGD: `component topology is immutable and cannot be modified after creation: components removed: [Epp]`.

Deleting the existing DGD would delete the active GPU worker. Deleting EPP child Pods or workloads would allow their owning controllers to recreate them. The parent must be retained until a separately validated worker replaces it.

The manifest generator preserves the existing graph topology, renders the blue stable selector and stops generating Qwen EPP traffic references. `disable_qwen_epp.py --routes-only` provides guarded, repeatable route retirement. Its default behavior does not change production; `--apply` is explicit. It records the stable selector, ready endpoints, worker identity, server-side dry runs and before/after probes.

## Health-check candidate

The failed AgentX attempt showed repeated `Health check timeout for generate` warnings, followed by HTTP503 liveness responses and a kubelet restart. In pinned Dynamo 1.5.1 source at commit `2093662a4d4e5fd318732935213dde08dc7be818`, both `/health` and `/live` use the same health handler. The active worker enables an inference-payload canary and uses generate-endpoint health for those probes. Long queued work can therefore cause a canary failure to become a liveness failure.

The prepared candidate explicitly sets `DYN_HEALTH_CHECK_ENABLED=false` on the main worker. This disables the extra inference canary, not the independent `VllmEngineMonitor` that calls `engine_client.check_health()`. The pinned engine monitor still initiates shutdown on engine death or its own health-check timeout; its default check timeout is thirty seconds. This is a proposed configuration fix requiring behavioral validation, not a claim that production health checks are fixed.

`qwen-healthfix-candidate.yaml` creates a new EPP-free graph with the old frontend and the pinned worker, in a separate Kubernetes namespace. The worker settings, model revision and image remain copied from the serving graph except for the canary flag and candidate GPU placement. The old frontend's runtime version was verified as 1.6.0 from installed package metadata. The candidate's node selector deliberately contains `SPARE-GPU-NODE-REQUIRED`. No candidate resources were created. A server-side dry run in the existing namespace accepted the new graph topology, and local tests verify route preservation and worker-setting isolation.

Both available Spark GPUs are occupied: Flint on spark-01 and Qwen on spark-02. Independent capacity is required before applying, warming or loading this candidate. Follow `deploy/models/MODEL_ROLLOUT_RUNBOOK.md`; do not change the active worker's Pod template to apply the canary flag in place.

Validation must show that requests can remain queued without failing liveness, that successful streams and tool calls still work, and that an actual engine failure is still detected. Then complete readiness, quality, overload, capacity, latency and rollback gates on the independent candidate. Verify namespace isolation prevents production discovery from finding the candidate before cutover. Only after cutover and the observation window may the previous worker graph be retired, which removes its EPP permanently.

Evidence is retained in `results/2026-10-22-qwen36-epp-removal/`. The earlier benchmark failure is in the separate Qwen3.6 AgentX result directory. No additional GPU was rented.
