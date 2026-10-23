# Qwen3.8-27B-FP8 throughput on EKS

Single Dynamo/vLLM worker, TP4 across four NVIDIA L4 GPUs on g6.12xlarge. Direct frontend benchmark over port-forward, bypassing gateway quotas. Results describe the deployed settings, not a theoretical model maximum.

Highest measured aggregate output throughput: **118.83 tokens/s**, or **29.71 tokens/s/GPU**, at concurrency 16, ISL 128 / OSL 512.

Validated 12 points and 544 measured requests, with zero request errors and exact server-reported input/output lengths.

**100 output tok/s/user target: 0 tested simultaneous users met the target on mean per-request decode rate.** This is a measured result for these workloads and engine settings, not a theoretical hardware limit. Aggregate tokens/s divided by 100 does not establish this capacity when single-user decode is below 100.

| Input/output tokens | Concurrency | Output tok/s total | Output tok/s/GPU | Decode tok/s/user | TTFT p50 ms | Request p50 ms |
|---|---:|---:|---:|---:|---:|---:|
| 128/512 | 1 | 18.71 | 4.68 | 20.69 | 283.6 | 24995.0 |
| 128/512 | 2 | 30.50 | 7.62 | 18.25 | 432.8 | 27871.0 |
| 128/512 | 4 | 54.98 | 13.75 | 17.41 | 441.2 | 32573.2 |
| 128/512 | 8 | 114.22 | 28.55 | 18.61 | 450.8 | 27927.3 |
| 128/512 | 16 | 118.83 | 29.71 | 18.69 | 30192.2 | 57850.5 |
| 128/512 | 32 | 117.13 | 29.28 | 17.93 | 94760.4 | 127065.6 |
| 1024/512 | 1 | 14.14 | 3.53 | 15.54 | 693.0 | 38977.4 |
| 1024/512 | 2 | 26.68 | 6.67 | 15.31 | 911.3 | 42135.3 |
| 1024/512 | 4 | 52.44 | 13.11 | 16.09 | 925.8 | 40448.4 |
| 1024/512 | 8 | 91.84 | 22.96 | 14.66 | 945.6 | 43298.7 |
| 1024/512 | 16 | 97.11 | 24.28 | 14.39 | 41072.8 | 79842.8 |
| 1024/512 | 32 | 102.69 | 25.67 | 15.02 | 116005.2 | 152042.7 |

Per-user decode rate is AIPerf's per-request output throughput. It is not total throughput divided by submitted concurrency. The engine admits eight active sequences; higher concurrency can queue.

Envoy token quotas do not apply to this direct frontend test. The public API still enforces its configured quotas. A quota of 6000 total tokens/minute is an allowance averaged over a window, not a guarantee of 100 output tokens/second.

These are synthetic fixed-length completions with MTP speculation enabled. Prompt content changes speculative acceptance, so real chat or coding throughput can differ. The small exploratory sample does not establish latency-tail SLOs. See EXPERIMENT.md, config.json, runtime-versions.txt, immutable deployment snapshots, and raw exports.

![Throughput tradeoff](pareto.png)

GPU shutdown verified at 2026-10-17T06:43:19.096598+00:00. EC2 instance `i-0aca84eb33f0124b2` is terminated; GPU node count is zero. The model is stopped and its Flux reconciliation is suspended. CPU nodes and the portal were retained. See shutdown-complete.json for evidence and RESUME.md for resumption instructions.
