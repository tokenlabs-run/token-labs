# Dynamo heterogeneous H200 → MI300X P/D benchmark

## Outcome

The 21-point benchmark completed successfully with no request failures. The
runtime was a Dynamo 1.4.2 frontend and prefill worker on one NVIDIA H200,
connected through Mooncake 0.3.13 TCP to a Dynamo 1.4.2 decode worker on one
AMD MI300X. Both workers used vLLM 0.26.0 and
`Qwen/Qwen3-30B-A3B-Instruct-2507-FP8` with tensor parallel size 1.

```text
benchmark client (H200 loopback)
  -> Dynamo frontend (H200)
  -> Dynamo + vLLM prefill (H200)
  -> Mooncake TCP (8 lanes, public cross-cloud network)
  -> Dynamo + vLLM decode (MI300X)
```

This is a compatibility/performance result for a cross-cloud public-TCP path,
not a recommended production topology. H200 and MI300X were not in a shared
VPC and no RDMA path was available.

## Validation

- Matrix: 21/21 requested points, 381/381 requests, zero request failures.
- Exact token totals: 2,210,816 input and 2,210,816 output tokens.
- Every point produced exactly the requested ISL and OSL; the validator rejects
  missing, short, or failed requests.
- Prefix caching was disabled on both workers. Startup logs record
  `enable_prefix_caching=False`, and Dynamo frontend snapshots report zero
  cached tokens throughout the run.
- Dynamo routing logs identify distinct prefill and decode worker IDs for each
  completed request.
- Both workers record `MC_FORCE_TCP is set, using TCP transport only` and use
  Mooncake's heterogeneous HND KV-cache layout.
- Mooncake reported zero failed transfers, zero failed receives, and zero
  expired KV requests in the benchmark telemetry.

### KV transfer byte proof

For this model and cache format, KV payload is 98,304 bytes per input token.
The exact matrix therefore required **217,332,056,064 bytes (202.40625 GiB)**
of application KV payload.

Mooncake's periodic metrics are sampled/windowed, not a cumulative counter.
Their 63.0 GiB sum (31.13% of the derived total) is retained as supporting
telemetry but is not misrepresented as full byte accounting. Independent
single-request probes measured both input sizes using cumulative TCP
`bytes_sent` across the eight Mooncake data sockets:

| ISL | Derived KV payload | Mooncake record | TCP payload delta | Protocol overhead | Result |
|---:|---:|---:|---:|---:|:---:|
| 1,024 | 100,663,296 B | 96 MiB | 100,744,384 B | 0.0806% | pass |
| 8,192 | 805,306,368 B | 768 MiB | 805,896,192 B | 0.0732% | pass |

The probes validate the byte geometry at every ISL used by the matrix. Combined
with exact per-request input-token counts, this proves the matrix's required KV
payload. Raw counters and logs are under `wire-byte-verification/`.

## Performance results

Output throughput in tokens/s (the full CSV also contains request throughput,
duration, median/P99 TTFT, and median/P99 TPOT):

| ISL / OSL | c=1 | c=2 | c=4 | c=8 | c=16 | c=32 | c=64 | Peak |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1k / 8k | 125.2 | 244.5 | 449.7 | 782.7 | 1,306.6 | **1,971.1** | 1,788.6 | c=32 |
| 8k / 8k | 109.6 | 209.3 | 347.6 | 569.5 | 755.7 | **878.9** | 809.1 | c=32 |
| 8k / 1k | 102.5 | 180.6 | 279.8 | 304.6 | 334.8 | 351.0 | **393.9** | c=64 |

Long-input overload is visible in TTFT. For 8k/8k, median TTFT rose from
1.28 s at c=1 to 77.38 s at c=32 and 136.24 s at c=64. Throughput peaked at
c=32 and regressed at c=64, so c=64 is beyond the efficient operating point
for this one-prefill/one-decode cross-cloud configuration.

## Reproduce and audit

- `matrix-summary.csv`: normalized 21-point results.
- `validation-summary.json`: machine-readable validation and byte probes.
- `matrix/`: raw vLLM benchmark JSON/logs, per-point Dynamo Prometheus
  snapshots, and benchmark-interval/full H200 logs.
- `node-metadata/`: H200 and MI300X container/image inspection plus MI300X
  decode logs.
- `wire-byte-verification/`: exact 1k and 8k probe results, TCP counters, and
  matching Mooncake metrics.
- `SHA256SUMS`: checksums for the published artifact set.

Run the validator from the repository root:

```bash
python3 deploy/digitalocean/heterogeneous-pd/analyze_dynamo_matrix.py \
  results/2026-08-30-dynamo-heterogeneous-mooncake-kv-production/matrix \
  results/2026-08-30-dynamo-heterogeneous-mooncake-kv-production/matrix/prefill-benchmark.log \
  results/2026-08-30-dynamo-heterogeneous-mooncake-kv-production/wire-byte-verification
```

The command exits zero only when all 21 exact-token points, zero transfer
failures, and both independent byte probes validate.
