# Qwen3-30B-A3B throughput tuning on DGX Spark GB10

## Outcome

The exact Qwen3-30B-A3B-Instruct-2507 family exceeds the 250 output-token/s
target on one exclusive NVIDIA GB10. The highest-throughput checkpoint is
`NVFP4/Qwen3-30B-A3B-Instruct-2507-FP4`:

- **1,337.20 output tok/s** short-run maximum at client concurrency 384 with
  256 active requests (ISL 512 / OSL 128).
- **1,346.02 output tok/s sustained for 389.51 seconds**, covering 4,096
  requests and 524,288 generated tokens at concurrency 256.
- **677.81 output tok/s** for the exact long profile at concurrency 64
  (ISL 2048 / OSL 1024).
- The tuned FP8 fallback peaks at **524.88 output tok/s** at concurrency 64.

All reported AIPerf points completed the exact request count and exact token
lengths with zero errors. Inputs used seed 42, temperature 0, `ignore_eos=true`,
and two request waves.

## Topology

- `spark-01` and `spark-02`, one NVIDIA GB10 each, about 122.5 GiB reported by
  PyTorch
- exclusive Kubernetes `nvidia.com/gpu=1`; no shared-GPU resource/time slicing
- one isolated SGLang benchmark replica on Spark 1, TP=1, no distributed
  framework; production FP8 remained healthy on Spark 2
- pinned image digest `8e410361...180abcb`

Spark 1 was idle before testing, so its device-plugin profile was changed from
three time-sliced shares to one exclusive `nvidia.com/gpu` allocation. Spark 2
was not interrupted.

## ISL 512 / OSL 128

| MoE config | C | Output tok/s | TTFT p50 ms | ITL p50 ms |
|---|---:|---:|---:|---:|
| generic auto | 1 | 50.48 | 135.60 | 18.87 |
| generic auto | 4 | 114.47 | 379.24 | 31.96 |
| generic auto | 8 | 168.17 | 605.20 | 43.08 |
| generic auto | 16 | 253.84 | 998.81 | 55.84 |
| generic auto | 32 | 361.82 | 1,231.16 | 78.82 |
| generic auto | 64 | 519.75 | 2,099.35 | 107.22 |
| GB10 tuned | 16 | 256.09 | 997.82 | 55.10 |
| GB10 tuned | 32 | 370.33 | 1,233.74 | 77.24 |
| GB10 tuned | 64 | **524.88** | 2,362.35 | 104.03 |
| GB10 tuned, c96 queued | 96 | 522.01 | 3,775.11 | 106.05 |
| GB10 tuned, c128 queued | 128 | 522.64 | 17,720.11 | 105.89 |

Queueing beyond the 64 active slots did not increase throughput and sharply
increased TTFT. Concurrency 64 is the useful short-profile peak.

## ISL 2048 / OSL 1024

| MoE config | C | Output tok/s | TTFT p50 ms | ITL p50 ms |
|---|---:|---:|---:|---:|
| generic auto | 16 | 215.16 | 2,485.46 | 72.06 |
| generic auto | 32 | 298.54 | 4,407.16 | 103.15 |
| generic auto | 64 | **394.79** | 8,338.51 | 154.21 |
| GB10 tuned | 16 | 218.84 | 2,505.99 | 70.75 |
| GB10 tuned | 32 | 298.08 | 4,623.91 | 102.92 |
| GB10 tuned | 64 | 388.96 | 8,217.32 | 156.82 |

The tuned table is workload-dependent: it helps the short profile and long c16,
but generic auto is 1.5% faster for long c64.

## NVFP4 and speculative decoding results

| Checkpoint / backend | Active max | Client C | Output tok/s | TTFT p50 ms | ITL p50 ms |
|---|---:|---:|---:|---:|---:|
| FP8 tuned | 64 | 64 | 524.88 | 2,362.35 | 104.03 |
| FP8 + EAGLE3 | 64 | 16 | 190.25 | 1,042.09 | 65.01 |
| FP8 + EAGLE3 | 64 | 32 | 312.65 | 794.44 | 80.34 |
| FP8 + EAGLE3 | 64 | 64 | 461.58 | 936.96 | 101.29 |
| NVFP4 auto/CUTLASS | 64 | 16 | 377.93 | 764.94 | 37.04 |
| NVFP4 auto/CUTLASS | 64 | 32 | 575.89 | 1,085.39 | 47.59 |
| NVFP4 auto/CUTLASS | 64 | 64 | 816.03 | 1,708.15 | 65.77 |
| NVFP4 cuDNN | 64 | 64 | 802.29 | 1,975.29 | 65.67 |
| NVFP4 auto/CUTLASS | 128 | 128 | 1,091.64 | 2,966.37 | 94.47 |
| NVFP4 auto/CUTLASS | 256 | 192 | 1,237.34 | 4,591.87 | 119.83 |
| NVFP4 auto/CUTLASS | 256 | 256 | 1,333.47 | 6,139.60 | 144.34 |
| NVFP4 auto/CUTLASS | 256 | 384 | **1,337.20** | 9,979.27 | 145.58 |

EAGLE3 used the exact `lmsys/SGLang-EAGLE3-Qwen3-30B-A3B-Instruct-2507-
SpecForge-Nex` draft and the author-published 3-step/top-k-1/4-draft-token
settings. It was slower than non-speculative tuned FP8 at all measured points.

The strict sustained NVFP4 c256 run delivered **1,346.02 output tok/s** for 389.51
seconds: 4,096 requests, 524,288 output tokens, exact lengths, and zero errors.
It cycled a fixed pool of 128 exact-length prompts with SGLang radix caching
disabled, so repeated text could not create a prefix-cache speedup. The c384
short-run point reached 1,337.20 tok/s with materially higher TTFT.

For ISL 2048 / OSL 1024, NVFP4 auto delivered **677.81 output tok/s** at c64
with exact lengths and zero errors. A c128 raw run reached 833.60 tok/s but was
excluded because one synthetic prompt tokenized to 2,049 rather than 2,048.

## Recommended measured combinations

Maximum-throughput NVFP4 server flags:

```text
--model-path NVFP4/Qwen3-30B-A3B-Instruct-2507-FP4
--served-model-name qwen/qwen3-30b-a3b-instruct-2507-nvfp4
--tp 1
--context-length 32768
--max-running-requests 256
--mem-fraction-static 0.70
--page-size 16
--disable-radix-cache
--quantization modelopt_fp4
--fp4-gemm-backend auto
--trust-remote-code
```

- Practical sustained maximum: client concurrency 256, 1,346.02 output tok/s.
- Absolute measured maximum: client concurrency 384 with 256 active requests,
  1,337.20 output tok/s, at the cost of higher TTFT.
- Lower-latency choices: c16 gives 377.93 tok/s; c32 gives 575.89 tok/s.

FP8 fallback flags:

```text
--model-path Qwen/Qwen3-30B-A3B-Instruct-2507-FP8
--tp 1
--context-length 32768
--max-running-requests 64
--mem-fraction-static 0.70
--page-size 16
--disable-radix-cache
--trust-remote-code
```

Set `SGLANG_MOE_CONFIG_DIR=/model-cache/sglang-moe-configs` for the short FP8
profile; use c64 for 524.88 tok/s or c16 for 256.09 tok/s. Omit the custom table
for long FP8 generations, where generic auto reached 394.79 tok/s at c64.

The GB10 tuner searched 24 Triton candidates for batch sizes 1 through 8192 in
265.29 seconds. SGLang used the generated up-projection table and reused it for
the down projection without TMA because no separate down table was available.

## Other tested or prepared paths

- Spark 1 vLLM FP8 peaked at 192.27 tok/s (512/128 c16) and 152.70 tok/s
  (2048/1024 c16), below target in the tested range.
- TensorRT-LLM 1.3.0rc11 loaded weights but crashed in FP8 block-scaled MoE
  profile selection during CUDA-graph capture; disabling its autotuner did not
  avoid the same failure.
- The exact 0.366 GB EAGLE3 draft and its published 3-step/top-k-1/4-token
  settings were measured; it peaked at 461.58 tok/s at c64 and trailed plain
  tuned FP8 at every tested concurrency.
- The exact 18.119 GB NVFP4 checkpoint was cached on both Spark nodes. SGLang
  selected the GB10 `flashinfer_cutlass` path and sustained 1,346.02 tok/s;
  explicit `flashinfer_cudnn` peaked at 802.29 tok/s in the c16/c32/c64 sweep.
- The installed runtime exposes DFlash, but no verified public DFlash draft for
  this exact 2507 target checkpoint has been identified.

Raw JSON/CSV exports, logs, command manifests, configs, and the tuned MoE table
are retained in this directory. Re-run with `scripts/benchmarks/run_aiperf_matrix.py`
and validate with `scripts/benchmarks/aggregate_aiperf_matrix.py`.
