# Zero-downtime model promotion runbook

**Scope:** promote an immutable model/runtime candidate validated on `spark-02`
to the public model endpoint while the current version continues serving on
`spark-01`.

**Status:** procedure defined from repository evidence; the rehearsal in
"Validation required before first production use" is still required before
this runbook may be treated as production-validated.

## Decision

Use blue/green deployment behind one stable Kubernetes Service. The blue
Deployment on `spark-01` and green Deployment on `spark-02` have unique slot
labels. The public `AIGatewayRoute` continues to reference one stable backend;
cutover changes only the stable Service's slot selector. Keep blue running and
ready until green has passed its observation window and all blue requests have
drained.

Do not update the current Deployment in place. The checked-in Qwen production
candidates use one replica, a node selector, and `strategy: Recreate`; changing
their pod template necessarily creates a period with no ready replica. Do not
run experiments and production traffic in the same Spark-02 process. Freeze the
candidate, stop the experimental workload, verify the GPU is free, and deploy a
fresh green workload from immutable inputs.

A weighted canary is a future option, not the first rollout mechanism. The
current gateway generator emits one backend per served model and does not
deduplicate two workloads with the same `--served-model-name`. Implement and
test explicit multi-backend weights before using a public canary.

## Preconditions and invariants

- An incident commander/operator and an independent verifier are named.
- No availability or error-budget freeze is active.
- Spark 1 can carry 100% of traffic throughout green preparation; Spark 2 can
  carry 100% after cutover. If either statement is false, add a third node.
- Blue and green use the same public served name and API/schema contract.
- The model revision, container image, tokenizer, chat template, runtime flags,
  and configuration are pinned by digest or commit. Never promote `latest` or
  an unpinned Hugging Face revision.
- Blue and green have separate Deployments and selectors. The stable Service is
  the only object selected by the public Backend.
- Blue is not scaled down, modified, or used for experiments during rollout.
- Green is not publicly selected before readiness, warm-up, conformance,
  quality, overload, and capacity gates pass.
- A cutover never includes a gateway advertisement change. `/v1/models` is a
  route declaration in this repository, not a backend health signal.

Example labels (replace `<model>` and version values):

```yaml
# Blue pod template
token-labs/model-id: <model>
token-labs/slot: blue
token-labs/version: <old-version>

# Green pod template
token-labs/model-id: <model>
token-labs/slot: green
token-labs/version: <new-version>

# Stable Service selector
token-labs/model-id: <model>
token-labs/slot: blue
```

The stable Service must not select on `version`; rollback is a one-field slot
change. Give each slot a separate diagnostic Service so green can be exercised
without public traffic.

## Go/no-go gates

Record every query result, command output, artifact digest, timestamp, and
approver in a rollout evidence directory. A missing measurement is a no-go.

| Gate | Pass condition |
| --- | --- |
| Cluster | Both nodes `Ready`; Envoy Gateway controller and data plane ready; no firing critical alerts |
| Isolation | Experimental Spark-02 pods stopped; `nvidia-smi` and Kubernetes show no unexpected GPU consumer |
| Identity | Expected model revision, image digest, tokenizer/template hashes, flags, and served name recorded and returned by green |
| Readiness | Startup complete; readiness continuously true for 10 minutes; diagnostic Service has exactly one green ready endpoint |
| Warm-up | At least one request for every supported path, including streaming and maximum supported feature shape; no warm-up errors |
| API | `check_api_conformance.py` passes all repetitions against green |
| Quality | Approved deterministic evaluation set is at or above the release baseline; no critical regression or safety-policy failure |
| Capacity | Green sustains the published production concurrency and workload mix for 30 minutes with zero 5xx/engine errors |
| Latency | At published load, p95 TTFT and p95 end-to-end latency are no worse than the approved release limits and no more than 10% worse than blue |
| Saturation | KV cache remains below 90%; no OOM, restart, GPU Xid, thermal, or node-pressure event |
| Overload | `check_early_429.py` passes; rejection is bounded and includes `Retry-After` |
| Rollback | Blue remains ready, directly probeable, and able to accept 100% load |

The repository's current generic SLO is availability >=99.5% and five-minute
engine error rate <1%. Those are incident thresholds, not rollout permission:
use the stricter zero-error capacity gate above and roll back on any unexplained
5xx during the cutover observation window.

## Procedure

Set explicit values in the operator shell. Do not copy the examples without
replacing them:

```bash
export NS=token-labs
export MODEL_ID='<stable-service-name>'
export BLUE_DEPLOY='<blue-deployment>'
export GREEN_DEPLOY='<green-deployment>'
export GREEN_DIAG_SERVICE='<green-diagnostic-service>'
export NEW_REVISION='<immutable-model-revision>'
export EVIDENCE_DIR="results/$(date -u +%F)-${MODEL_ID}-rollout"
mkdir -p "$EVIDENCE_DIR"
```

### 1. Freeze and approve the candidate

1. Record the experiment report and approval that selected the candidate.
2. Resolve the model repository revision to a commit and the runtime image to a
   digest. Record hashes for tokenizer, chat template, and non-secret config.
3. Render the green manifest and review its diff. The only intentional changes
   from blue should be the pinned candidate inputs and the slot/node identity.
4. Confirm that secrets are references, never copied into evidence.

No-go if any input is mutable, the served model name changes unintentionally,
or the result cannot be reproduced from the recorded inputs.

### 2. Establish a clean green node

```bash
kubectl get nodes spark-01 spark-02
kubectl get pods -A -o wide --field-selector spec.nodeName=spark-02
kubectl get events -A --sort-by=.lastTimestamp
```

Stop only the explicitly identified experimental workload through its owning
Deployment/StatefulSet/job. Do not delete an unidentified pod. Verify there are
no terminating/zombie CUDA processes and that expected GPU memory is free.
The 2026-04-14 incident showed that an `Error` pod can leave a CUDA child
holding memory, so pod phase alone is insufficient evidence.

### 3. Deploy green without public traffic

Apply a separately named green Deployment pinned to `spark-02` and a diagnostic
Service selecting only `slot=green`. The public stable Service must still
select `slot=blue`.

```bash
kubectl apply --server-side --dry-run=server -f '<green-manifest.yaml>'
kubectl apply -f '<green-manifest.yaml>'
kubectl rollout status -n "$NS" deployment/"$GREEN_DEPLOY" --timeout=60m
kubectl get endpointslice -n "$NS" -l kubernetes.io/service-name="$GREEN_DIAG_SERVICE" -o yaml
kubectl get service -n "$NS" "$MODEL_ID" -o jsonpath='{.spec.selector.token-labs~1slot}{"\n"}'
```

Abort if the last command is not `blue`.

The readiness check must prove more than process liveness: `/v1/models` must
contain the exact public served name and a small deterministic completion must
succeed through the diagnostic Service. Run sustained warm-up before measuring
latency.

### 4. Execute the green gates

Port-forward the diagnostic Service or use an authenticated internal test
route that cannot receive public traffic. Run, at minimum:

```bash
python3 scripts/openrouter/check_api_conformance.py --help
python3 scripts/openrouter/run_public_matrix.py --help
python3 scripts/openrouter/check_early_429.py --help
```

Invoke them with the candidate URL, exact model ID, approved API credential
environment variable, published concurrency, and evidence output paths. Also
run the approved quality suite. The `--help` commands above are discovery, not
validation; evidence must contain actual passing runs.

Have the verifier compare results with the go/no-go table and sign the cutover
record. Do not waive a failed gate during the change window.

### 5. Cut over atomically at the stable Service

Capture the current selector and endpoints first:

```bash
kubectl get service -n "$NS" "$MODEL_ID" -o yaml > "$EVIDENCE_DIR/service-before.yaml"
kubectl get endpointslice -n "$NS" -l kubernetes.io/service-name="$MODEL_ID" -o yaml > "$EVIDENCE_DIR/endpoints-before.yaml"
```

Start a continuous authenticated synthetic stream through the public gateway
before cutover. It must record request ID, start/end timestamps, status, TTFT,
completion status, and backend version/slot telemetry without recording prompt
or completion content.

Switch only the slot selector, using a JSON patch that fails if blue is no
longer the current value:

```bash
kubectl patch service -n "$NS" "$MODEL_ID" --type=json -p='[
  {"op":"test","path":"/spec/selector/token-labs~1slot","value":"blue"},
  {"op":"replace","path":"/spec/selector/token-labs~1slot","value":"green"}
]'
```

Watch until every ready endpoint for the stable Service is green, then verify
the public path. Do not regenerate `aigatewayroute-models.yaml`: the public
model and stable backend have not changed.

```bash
kubectl get endpointslice -n "$NS" -l kubernetes.io/service-name="$MODEL_ID" -w
kubectl get service -n "$NS" "$MODEL_ID" -o jsonpath='{.spec.selector.token-labs~1slot}{"\n"}'
```

Expect a short overlap in established proxy connections. Both slots are healthy
by construction, so overlap is safe. Do not terminate blue to force connection
migration.

### 6. Observe and drain

Observe green for at least 30 minutes and at least the duration of the longest
supported request, whichever is longer. Compare green with the pre-cutover blue
baseline. Watch public success/error status, TTFT, end-to-end latency, active and
waiting requests, KV cache, GPU memory/temperature, restarts, node conditions,
and Envoy upstream failures.

Blue is drained only when all are true:

- the stable Service has selected only green for longer than the maximum
  request duration;
- blue reports zero running and waiting requests for two consecutive scrape
  intervals;
- the continuous synthetic stream shows no dropped, truncated, or failed
  request spanning cutover;
- green has completed the observation window without a rollback trigger.

Keep blue deployed and directly probeable for a 24-hour rollback window unless
capacity cost or policy explicitly sets a longer period. Afterward, scale blue
to zero; do not delete its manifest or immutable artifacts until the release
retention period ends.

## Rollback

Rollback immediately for any of the following during the observation window:

- any unexplained 5xx, stream truncation, or dropped in-flight request;
- green readiness loss, restart, OOM, GPU Xid, or Spark-02 `NotReady`;
- five-minute engine error rate >=0.5% (warning threshold) or any critical
  correctness/safety regression;
- p95 TTFT or p95 end-to-end latency >10% above the approved blue baseline for
  five minutes at comparable load;
- KV cache >=90% for five minutes, sustained queue growth, or inability to
  honor the advertised capacity;
- missing/ambiguous telemetry that prevents judging the preceding conditions.

Rollback changes only the stable Service selector:

```bash
kubectl patch service -n "$NS" "$MODEL_ID" --type=json -p='[
  {"op":"test","path":"/spec/selector/token-labs~1slot","value":"green"},
  {"op":"replace","path":"/spec/selector/token-labs~1slot","value":"blue"}
]'
kubectl get endpointslice -n "$NS" -l kubernetes.io/service-name="$MODEL_ID" -w
```

Confirm the public synthetic request reaches blue and succeeds. Leave green
running but isolated for evidence collection unless it threatens node health;
if it does, scale the named green Deployment to zero after blue is confirmed in
service. Target rollback selector restoration within 60 seconds and public
success restoration within 2 minutes. Declare an incident if either target is
missed.

## Validation required before first production use

The procedure is not validated merely because manifests render. Rehearse it
with non-customer traffic and preserve evidence:

1. Run a continuous mix of streaming and non-streaming requests, including
   requests whose lifetime spans the selector change.
2. Perform blue-to-green cutover and green-to-blue rollback.
3. During a second run, fail green readiness and prove it is never selected
   before healthy; after cutover, inject a defined green failure and execute
   rollback.
4. Assert zero unexpected HTTP errors, zero truncated streams, zero missing
   request completions, and no request-ID duplication.
5. Measure EndpointSlice propagation, last blue request completion, first green
   request start, selector rollback, and restored public success.
6. Verify rollback meets 60-second selector and 2-minute public recovery
   targets.
7. Have an operator who did not write this runbook execute the rehearsal.

Attach the report to the rollout ticket. Any required stable-Service/slot-label
manifests, gateway-generator canary support, backend-version telemetry, or
automated rehearsal harness must be completed as separate implementation work
before claiming production validation.

## Current-state evidence and known gaps

- `plain-vllm/deployment.yaml` and `plain-sglang/production-deployment.yaml`
  each define one replica with `strategy: Recreate`, pinned to one Spark.
- Both define startup/readiness probes, but `/health` alone does not validate
  the exact model identity, tokenizer/template compatibility, or output quality.
- `gen_aigwroute.py` discovers live intent, not readiness, and emits one route
  backend per served name. Route regeneration is therefore not a safe cutover
  primitive for two same-name slots.
- `prometheusrules-slo.yaml` contains stale model/job-specific assumptions in
  parts of its availability and TTFT rules. Validate alert coverage for the
  actual Qwen production labels before relying on it as a rollout gate.
- The current manifests do not define a stable blue/green Service, slot labels,
  a `preStop` drain hook, a PodDisruptionBudget, backend-version response
  telemetry, or a selector-switch rehearsal harness. This runbook specifies the
  required procedure but does not pretend those implementation gaps are closed.

