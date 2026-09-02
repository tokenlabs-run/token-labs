# Dynamo configuration handoff investigation

Status: source investigation and CPU validation complete; automatic configuration-driven inference handoff and GPU measurements remain unverified.

## Source and environment

Investigated upstream `ai-dynamo/dynamo` main at `09681acd7c68e1a11a21be4b819ce0cede7bb387`, then fetched and tested public `elizabetht/dynamo` main at `1df553558adb0465409c282eb27b1775ff1f60ba`. The legacy GMS vLLM worker, shutdown helper and snapshot election lifecycle were identical between these revisions; V1 has differences, so do not conflate versions.

SSH to the requested `spark-01` failed with `No route to host`. Consequently its local remote configuration, origin/main revision, installed engine versions and GPU capacity were not verified. Public fork main is a useful source substitute, not proof of that checkout's origin/main. Local `nvidia-smi` is unavailable. No deployed service was changed.

## What is already implemented

The following links pin the tested fork revision:

- [Shutdown helper](https://github.com/elizabetht/dynamo/blob/1df553558adb0465409c282eb27b1775ff1f60ba/components/src/dynamo/common/utils/graceful_shutdown.py): unregister endpoint instances, wait a discovery grace period, invoke optional drain/lifecycle/cleanup callbacks, then shut down the runtime. Default grace is five seconds; optional drain and cleanup callbacks have 30-second timeouts and proceed on failure. This helper alone is not proof of lossless draining for every backend. vLLM main wires lifecycle withdrawal; other request drain behavior belongs to endpoint and engine serving code.
- [Worker factory](https://github.com/elizabetht/dynamo/blob/1df553558adb0465409c282eb27b1775ff1f60ba/components/src/dynamo/vllm/worker_factory.py): serving endpoint construction is the integration seam for backend routing and graceful shutdown.
- [GMS vLLM worker](https://github.com/elizabetht/dynamo/blob/1df553558adb0465409c282eb27b1775ff1f60ba/lib/gpu_memory_service/integrations/vllm/worker.py): imports shared weights, supports scratch KV initialization, sleep/wake, and optional committed KV allocation reuse.
- [GMS ownership](https://github.com/elizabetht/dynamo/blob/1df553558adb0465409c282eb27b1775ff1f60ba/lib/gpu_memory_service/server/session.py): readers can share published weights. All writer requests, including `RW_DATA_OR_RW`, are exclusive. Mutable KV ownership cannot overlap on one domain.
- [Shadow election](https://github.com/elizabetht/dynamo/blob/1df553558adb0465409c282eb27b1775ff1f60ba/components/src/dynamo/common/snapshot/lifecycle.py): an already-paused engine waits for a process flock before waking. A paused standby can report healthy while waiting. Health is therefore insufficient to authorize traffic cutover.

## Can memory service be reused?

Yes, as an allocation owner beneath the replacement controller. It does not itself watch configuration, spawn replacements, switch routing, or reconstruct active requests.

Shared, compatible model weights are the strongest reuse opportunity. Keep GMS alive independently of worker replacement and let both workers import its published weights. Model identity, revision, dtype, quantization, tensor-parallel topology and layouts must be compatible. A structural layout hash is not a content identity check.

KV needs more care. The default path creates fresh KV backing on wake. `DYN_GMS_PERSIST_KV` opts into committing the allocation layout so pages survive worker exit; a successor may adopt them using `RW_DATA`. The code explicitly requires matching geometry and can fail wake if the successor's layout differs. Surviving bytes and allocation IDs do not establish preservation of scheduler queues, request-to-block tables, random state, streaming ownership or active decoding progress. These were not tested.

The scratch-KV shadow prepares cheaply but cannot perform ordinary inference on its aliased scratch backing. Before serving it must wake and obtain real KV ownership. The exclusive lock and failover election mean the existing same-domain shadow path is sequential: drain/release the old owner, then wake the successor. This does not provide the requested overlap where new requests run on B while A drains.

For overlap, use separate mutable KV pools, sharing only weights. Either use native per-process KV allocation where supported by the chosen integration, or add independently named KV domains. Current socket naming is GPU UUID plus tag under `GMS_SOCKET_DIR`; simply changing that directory separates weights as well. A clean implementation needs a common weights domain and per-generation KV domains. This is a proposed integration change, not a tested feature.

Peak device memory must cover one shared weight set plus both KV pools, activation/workspace pools, CUDA graph allocations and per-process overhead. Shared weights remove only one part of overlap cost. If this does not fit, use another device/replica or explicitly accept a queued transition while the old worker drains.

The experimental GMS V1 snapshot path preserves process structures and addresses from a captured engine and rebuilds KV backing. It should not be assumed to turn arbitrary startup flags into runtime settings; restoring a captured process also restores its configuration unless a supported update mechanism changes it.

## Recommended controller

Use a versioned desired-configuration record and a separate applied-generation record. A watcher/reconciler should implement:

1. Validate the new record, classify settings and reserve overlap capacity. Snapshot per-request policy such as deadlines at admission where semantics allow. Apply queue limits in the admission owner with defined behavior for already queued work. Treat speculative depth as engine-dependent until its actual update API is verified.
2. Launch B with an immutable copy of generation N+1, distinct ports and a private registration/routing target. Keep A active. A candidate must not join the public serving set merely because it has registered.
3. Verify B has completed weight import, KV allocation and warmup; issue a real generation request against B. A healthy sleeping shadow fails this readiness criterion.
4. Atomically switch the stable admission point to B, fencing the update with generation/version checks. Capture each request's target once and retain it through the full stream. With multiple admission replicas, account for propagation and acknowledgements; discovery removal plus a fixed sleep is not a globally atomic switch.
5. Stop admitting new work to A, retain all in-flight streams and any outstanding prefill/KV transfers, then retire A when they reach zero. Record queue, active-request and transfer counts separately. A drain deadline needs an explicit timeout policy; do not silently label forced cancellation lossless.
6. On candidate startup/readiness failure, retain A and mark the desired generation failed. Serialize or coalesce rapid config updates. Persist desired/applied versions so a controller restart can reconcile surviving workers. If B dies after cutover, rollback requires A still be available or another ready replica.

A stable frontend/admission process plus replaceable engine workers is the first target. Changes to frontend-owned startup flags may require a separate frontend handoff or moving the setting into per-request policy. Replacing only a worker does not apply every knob in the stack.

## Evidence obtained

`tests.xml`: **42 passed, 1 deselected, 1.74 seconds**, Python 3.11.15, on the public fork revision above:

- 6 actual OS/process flock tests: contention, release and process death ownership transfer.
- 29 actual GMS server/client socket-flow tests using upstream FakeVMM: publication, reader sharing, writer exclusion, stale-layout detection, replacement and committed-allocation adoption.
- 7 shutdown helper tests using upstream mocked runtime/endpoints: callback ordering and failure/timeout handling.

The one excluded test requires real GPU allocation/NVML. These checks do not measure CUDA memory sharing, inference latency, request continuity, routing convergence, automatic config updates or replacement startup. They establish control and ownership behavior only. Initial direct shutdown-test collection failed because parent package imports require native Dynamo; the unchanged implementation and upstream test were copied to a temporary standalone layout, preserving their relative paths. The reproduction script does the same. Unrelated warning filters and suite addopts are disabled, not assertions; timeout support remains installed.

Run `bash reproduce.sh` from any directory. It uses an isolated temporary checkout and environment and writes the JUnit result beside the script.

## Experiment still required on spark-01

First record local origin URL and origin/main SHA and inspect existing workloads. Use an isolated checkout and reserved ports/GPU capacity. Keep the production frontend untouched.

Run a continuous identified streaming workload against a stable experimental admission endpoint. Trigger a real database configuration revision changing a worker startup parameter. Capture old/new PIDs, generation and worker IDs, readiness timestamps, cutover, last old admission, last old completion and retirement. Require new-generation requests to finish while an intentionally long old-generation request is still active; this distinguishes overlap from stop-and-start failover.

Compare independent workers without GMS, shared weights with independent KV, and the existing sequential shadow mode. Measure errors/cancellations, token completeness, TTFT and inter-token latency, startup/warmup/cutover/drain times and device peak memory. Exercise failed replacement startup, readiness timeout, rapid revisions and controller restart. Only test persisted KV with compatible geometry, and separately test a geometry-changing revision to verify rejection or rebuilding.

Completion remains unproven until the config watcher, real engine processes, routing switch and old-worker drain have run together. The present finding is a source-backed design and bounded ownership validation, not a successful zero-interruption inference rollout.
