# Qwen3 30B FP8 single-Spark vLLM tuning

Date: 2026-09-02 UTC

This is a public-path capacity experiment for
`qwen/qwen3-30b-a3b-instruct-2507` on one DGX Spark. Requests traversed
`https://api.tokenlabs.run/openrouter/v1`, including authentication, bounded
admission, the Token Labs proxy, and a single plain-vLLM replica.

## Decision

- Keep vLLM's default token batch budget. Explicit 4,096- and 8,192-token
  budgets did not improve the balanced-workload throughput/latency frontier.
- Set provider admission to **4 concurrent requests**. This is the highest
  tested concurrency that passes both production profiles using the fixed
  guardrails below.
- Treat **8 concurrent requests** as interactive-only capacity, not the global
  provider limit.
- Raw maximums are capacity observations, not launch SLOs: 192.27 output
  tokens/s at interactive c16 and 152.70 output tokens/s at balanced c16.

Guardrails: TTFT p95 <= 2,000 ms and streaming TPOT proxy (inter-token latency
p95) <= 50 ms. All admitted points must also have zero errors and exact output
lengths. Chat-template wrapper tokens are measured server-side and may add at
most 64 tokens to the requested synthetic content length.

## Baseline

| Profile | Concurrency | Output tok/s | TTFT p95 | ITL p95 | Result |
|---|---:|---:|---:|---:|---|
| interactive (512/128) | 1 | 50.65 | 237 ms | 18.21 ms | pass |
| interactive (512/128) | 2 | 75.18 | 351 ms | 25.28 ms | pass |
| interactive (512/128) | 4 | 102.37 | 475 ms | 37.37 ms | pass |
| interactive (512/128) | 8 | 148.73 | 704 ms | 45.81 ms | pass |
| interactive (512/128) | 16 | 192.27 | 1,242 ms | 60.64 ms | fail ITL |
| balanced (2048/1024) | 4 | 98.68 | 1,237 ms | 40.15 ms | pass |
| balanced (2048/1024) | 8 | 130.56 | 2,333 ms | 50.83 ms | fail both |
| balanced (2048/1024) | 16 | 152.70 | 3,494 ms | 77.33 ms | fail both |

## Scheduler sweep at balanced c8

| Token batch budget | Output tok/s | TTFT p95 | ITL p95 | Result |
|---|---:|---:|---:|---|
| vLLM default | 130.56 | 2,333 ms | 50.83 ms | fail both |
| 4,096 | 130.30 | 2,087 ms | 50.58 ms | fail both |
| 8,192 | 130.18 | 2,090 ms | 50.43 ms | fail both |

The larger budgets reduced TTFT but did not cross either guardrail and slightly
reduced throughput. Prefix caching remained off because these synthetic prompts
do not intentionally share prefixes; enabling it would test a different workload.

## Admission test

With the final provider cap of four, an eight-request simultaneous burst returned
four HTTP 200 responses and four HTTP 429 responses. All rejections completed in
0.559--0.561 seconds and included `Retry-After: 1`; excess requests were not
queued behind model work.

## Evidence and exclusions

The valid dataset contains 212 measured requests and 91,648 measured output
tokens. Each export is retained below its suite directory with AIPerf JSON/CSV,
logs, and a redacted command record. The first balanced c4 attempt revealed a
10-second HTTPRoute timeout. It is retained as
`balanced__baseline-mem70-seq64-nopc-c4.invalid-gateway-timeout-10s` and excluded
from every table. The route was corrected to 3,600 seconds before all valid
balanced measurements.

This is a one-replica capacity result. It does not measure multi-replica routing,
KV-aware routing, failover, price, model quality, or long-duration reliability.
