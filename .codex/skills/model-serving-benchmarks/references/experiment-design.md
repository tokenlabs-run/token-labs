# Experiment design

## Match the claim to the request path

Document the client endpoint and every hop to the inference worker. Verify the
live path rather than inferring it from installed components. A framework
comparison requires its scheduler or router to be in the request path and to
have meaningful choices. With one worker, report integration overhead and vLLM
engine behavior as a single-worker baseline.

For distributed routing, give each framework at least two equivalent workers.
For disaggregated serving, use separate prefill and decode workers and verify
remote KV transfer. Run one framework at a time when the available hardware
cannot host equivalent arms simultaneously.

## Controls

Keep model revision, quantization, engine version and image digest, tensor
parallelism, KV dtype, cache policy, max model length, max sequences, GPU memory
fraction, speculative decoding, endpoint type, tokenizer, prompt generator,
seed, request count, warmup count, and timeouts matched. Record node placement.
Swap nodes or repeat on the same nodes when hardware variation could explain the
result.

Generate load away from the inference workers when possible. Confirm clocks,
thermals, memory pressure, and competing workloads are comparable. Do not mix
results across a node outage, pod restart, changed cache capacity, or altered
configuration.

## Sampling and interpretation

Two waves with a minimum of four requests is suitable for exploratory throughput
curves, but it is weak evidence for latency tails. Increase independent waves
and request counts for p95/p99 claims. Exact long-output tests can take a long
time before the first request completes; scheduler token throughput is useful
progress evidence but is not a completed benchmark result.

Aggregate output tokens/s measures system capacity. Output tokens/s/user is a
per-request decode-rate metric and commonly approximates the reciprocal of ITL;
it is not aggregate throughput divided by concurrency in every implementation.
Report TTFT separately for prefill and admission effects.

## Publication gate

Publish only validated exports with the planned request count, zero request
errors, exact server-reported token lengths, finite nonnegative metrics, a full
matrix, and machine-readable provenance. State topology limitations beside the
chart. Preserve raw exports, exact commands, configuration, software versions,
and any excluded failure artifacts.
