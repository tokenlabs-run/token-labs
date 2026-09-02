# Tokenlabs OpenRouter provider plan: one DGX Spark

## Selected candidate and license gate

Serve `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8` as a provider for OpenRouter's
canonical `qwen/qwen3-30b-a3b-instruct-2507` model.

The exact FP8 checkpoint and its base checkpoint both declare Apache-2.0, are
public and ungated, and contain a `LICENSE` file with no separate acceptable-use
policy or NOTICE file. Apache-2.0 permits commercial use and hosted inference.
Tokenlabs must retain the license and copyright notices in any distributed
bundle, mark modified files, reproduce a NOTICE if upstream later adds one, and
avoid implying Qwen/Alibaba endorsement. Recheck and record both model revisions
and license files immediately before provider submission.

OpenRouter already lists the canonical model and accepts `fp8` as a provider
quantization. The provider model document must use:

```text
id: qwen/qwen3-30b-a3b-instruct-2507
hugging_face_id: Qwen/Qwen3-30B-A3B-Instruct-2507
served checkpoint: Qwen/Qwen3-30B-A3B-Instruct-2507-FP8
quantization: fp8
```

## Baseline configuration

- Aggregated vLLM; one worker and tensor parallelism 1.
- 32,768-token served context for the initial Spark capacity envelope.
- 64 maximum sequences and 0.70 GPU-memory utilization.
- BF16 KV cache, streaming on, prefix cache off, no speculative decoding.
- Public TLS gateway path identical to the intended OpenRouter path.

## Serving architecture decision

For the one-Spark launch, use **Envoy Gateway/Kuadrant directly in front of one
plain vLLM worker**:

```text
OpenRouter -> Envoy Gateway (TLS, auth, limits, early 429) -> vLLM
```

Do not place Dynamo, an llm-d Endpoint Picker, or a second inference gateway in
the request path for the initial deployment. KV-aware routing chooses among
multiple workers; with one worker every request has the same destination. A
second copy on the same Spark would duplicate model weights, reduce available
KV cache, and compete for the same GPU, so it is not a useful way to manufacture
a routing choice. Prefill/decode disaggregation on the same GPU has the same
resource-contention problem.

Enable vLLM automatic prefix caching only after an A/B run shows a benefit on
representative repeated-prefix traffic. That reuses KV state inside the sole
worker and does not require an external KV-aware router.

The existing Qwen3 comparison does not establish a routing advantage: both
paths contain one vLLM worker, the llm-d EPP is explicitly bypassed, and the
workers are on different Spark nodes without a node-swap control. For the 1K
input / 8K output profile, measured concurrency-64 throughput is approximately
299.6 tokens/s through Dynamo and 301.3 through the llm-d-sidecar service path.
The small difference is not a reason to add either control plane.

Scale-out trigger: when the same model has at least two workers on distinct
Sparks, insert **llm-d EPP** between the existing Envoy Gateway and vLLM
replicas, then validate prefix-locality, queue-depth routing, failures, and
end-to-end throughput against round robin. llm-d is the preferred first
scale-out option because Tokenlabs already uses Kubernetes Gateway API and
Envoy. Evaluate Dynamo instead when prefill/decode disaggregation, heterogeneous
GPU pools, or Dynamo-native orchestration becomes a concrete requirement. Do
not run Dynamo and llm-d together for the same routing decision.

If “SMG” means SGLang or an SGLang gateway, treat SGLang as a competing serving
engine in a controlled benchmark, not as a proxy in front of vLLM. Only one
engine should own batching, KV allocation, tokenization, and generation.

Qwen3-30B-A3B has 30.5B total and about 3.3B activated parameters. Existing
Tokenlabs measurements show about 50 output tokens/s at concurrency 1 and about
300 aggregate output tokens/s at concurrency 64 for 1K input / 8K output.
Qwen2.5-7B is the throughput control; historical results are not a controlled
head-to-head selection test.

## Optimization objective

Maximize sustained end-to-end output tokens/s through the public gateway among
configurations that pass every API, tool-use, quality, latency, reliability,
license, and economic gate. OpenRouter includes fetch latency, TTFT, streaming,
and provider queueing in throughput, so engine-only peak throughput is not the
selection metric.

## Reproducible experiment

Run one model at a time on the same dedicated Spark. Pin model and tokenizer
revisions, image digest, runtime, arguments, gateway configuration, Spark power
mode, and client location. Randomize candidate order and retain raw artifacts.

Screen, in order:

1. The baseline above.
2. One change at a time: FP8 KV cache, prefix caching, chunked prefill, batch
   limits, CUDA graphs, then supported speculative decoding.
3. Combine only improvements that preserve all gates and confirm the top three.
4. Run the identical production suite on Qwen2.5-7B as the throughput control.

Do not run an uncontrolled full Cartesian search or compare results collected
with different prompts, gateway paths, power modes, or model revisions.

### Traffic profiles

| Profile | Input / output tokens | Purpose |
|---|---:|---|
| Interactive | 512 / 128 | Short chat and latency |
| Tool use | 1,024 / 256 | OpenRouter tool traffic |
| Balanced | 2,048 / 1,024 | General inference |
| Long prefill | 8,192 / 512 | Context and TTFT pressure |
| Long decode | 1,024 / 8,192 | Decode ceiling |
| Long mixed | 8,192 / 8,192 | KV-cache stress |

Test concurrency 1, 2, 4, 8, 16, 32, and 64. After warmup, collect at least
100 requests and 10 minutes of steady state per point. Confirm the throughput
knee and maximum admissible point for 30 minutes in three time windows.

Capture aggregate/per-request output tokens/s; request and total-token
throughput; p50/p95/p99 TTFT, inter-token latency, and total latency; success,
429, 5xx, cancellation, malformed-output, and mid-stream error rates; queue
time, active sequences, and KV-cache use; unified-memory high-water mark, power,
temperature, throttling, health, and restarts.

The primary score is the geometric mean of aggregate output tokens/s across
Interactive, Tool use, Balanced, and Long prefill at the highest concurrency
passing every gate. Report Long decode and Long mixed separately so an
unrealistic 8K generation cannot choose the production configuration.

### Hard gates

- 100% OpenAI response-schema and SSE-frame conformance.
- At least 99.5% successful deterministic tool calls; no malformed tool names
  or JSON in the strict subset.
- At most 1% relative quality regression from the reference, and at most 2% on
  tool, structured-output, or safety subsets.
- At least 99.5% successful requests excluding deliberate early 429s, with zero
  mid-stream failures.
- p95 TTFT no more than 2 seconds for Interactive and Tool use, 5 seconds for
  Balanced, and 15 seconds for Long prefill.
- No unbounded queue, OOM, node loss, or thermal throttling.
- Positive unit economics after power, network, operations, OpenRouter
  economics, and Spark amortization.

Select in this order: every gate passes; highest primary throughput; lower p95
TTFT; higher gross margin per Spark-hour; simpler recovery path.

## Capacity and reliability

Declare initial production capacity at 80% of the highest arrival rate passing
all gates. Use a short bounded queue and return an early standards-compliant
429 above the limit. OpenRouter prefers early 429s over queueing that lowers
measured throughput.

Run a 72-hour public-path soak containing production shapes, bursts,
cancellations, invalid requests, tools, and controlled runtime/gateway
restarts. Require 99.9% successful-request uptime excluding user errors and
429s; no incorrect HTTP 200, mid-stream error, or error finish reason; p95 TTFT
and throughput within 10% of the capacity confirmation; and recovery within 5
minutes.

One Spark remains a single failure domain. Set `is_ready: false` before planned
maintenance. Hardware redundancy is a later scale-out requirement.

## Provider-readiness checklist

- Submit <https://openrouter.ai/how-to-list>.
- Expose public HTTPS OpenAI-compatible inference with dedicated, rotatable
  OpenRouter credentials.
- Implement the current modality-based model-list document: exact identity,
  FP8 quantization, context/output limits, streaming, parameters, prices,
  conservative request/token capacity, region, compliance, and readiness.
- Verify correct 400, 401, 404, 413, 429, 500-class, cancellation, and streaming
  behavior; never send an error payload with HTTP 200.
- Arrange automatic top-up or invoicing.
- Monitor uptime, TTFT, throughput, tool success, 429s, 5xx, mid-stream errors,
  queues, memory, thermals, and reachability.
- Prepare overload, crash, gateway, credential-rotation, withdrawal, and
  maintenance runbooks.

### Generate the provider model document

Download the current official schema at submission time, then generate the
document only with measured capacity and approved prices:

```bash
curl -L --fail \
  https://openrouter.ai/docs/assets/provider-monitor-schema-v2.openapi.json \
  -o /tmp/provider-monitor-schema-v2.openapi.json

python3 scripts/openrouter/generate_model_document.py \
  --schema /tmp/provider-monitor-schema-v2.openapi.json \
  --output deploy/openrouter/models.json \
  --prompt-price "${TOKENLABS_PROMPT_PRICE_PER_TOKEN}" \
  --completion-price "${TOKENLABS_COMPLETION_PRICE_PER_TOKEN}" \
  --prompt-tpm "${TOKENLABS_MEASURED_PROMPT_TPM}" \
  --completion-tpm "${TOKENLABS_MEASURED_COMPLETION_TPM}" \
  --requests-per-minute "${TOKENLABS_MEASURED_RPM}" \
  --concurrency "${TOKENLABS_MEASURED_CONCURRENCY}" \
  --country "${TOKENLABS_COUNTRY_CODE}" \
  --datacenter-region "${TOKENLABS_DATACENTER_REGION}" \
  --deployment-region "${TOKENLABS_DEPLOYMENT_REGION}"
```

The generator requires every price and capacity value, rejects non-positive or
scientific-notation prices, validates against the downloaded OpenAPI document,
and defaults to `is_ready: false`. Add `--tools`, `--structured-outputs`, `--zdr`,
`--hipaa`, or `--ready` only after the corresponding gate is evidenced. Test
values belong under `/tmp`; do not commit a production-looking model document
until capacity, economics, location, and compliance are known.

### Prove API conformance

After the public inference route is restored, run the strict suite without
writing the bearer token to disk:

```bash
export TOKENLABS_BENCH_API_KEY='<dedicated-test-key>'

python3 scripts/openrouter/check_api_conformance.py \
  --url https://api.tokenlabs.run \
  --model qwen/qwen3-30b-a3b-instruct-2507 \
  --output results/openrouter-conformance/report.json \
  --repetitions 200 \
  --tools \
  --structured-outputs
```

The suite checks authenticated discovery, unauthenticated rejection,
non-streaming response and usage schemas, SSE framing and `[DONE]`, streamed
usage, unknown-model and malformed-request status codes, exact deterministic
tool calls, and strict JSON-schema output. The report stores only sanitized
evidence and failures. Do not add `--tools` or `--structured-outputs` to the
provider model document unless all corresponding repetitions pass.

## Execution order

1. Finish and validate all 42 canonical Qwen3 points.
2. Aggregate only after every request count, error check, and exact input/output
   length passes.
3. Add Interactive, Tool use, Balanced, and Long prefill public-path suites.
4. Run the identical production suite on Qwen2.5-7B.
5. Run conformance, tool-call, compact quality, and economic gates.
6. Tune and confirm the leading eligible Qwen3 configuration.
7. Complete the soak, freeze capacity and price, generate the provider model
   document, and submit onboarding.

## Evidence sources

- Benchmark: `results/2026-09-01-qwen3-spark-pareto/`
- Runner and validator: `scripts/qwen3-30b/`
- Exact FP8 checkpoint and license:
  <https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507-FP8>
- Base checkpoint and license:
  <https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507>
- OpenRouter provider requirements:
  <https://openrouter.ai/docs/guides/community/for-providers>
