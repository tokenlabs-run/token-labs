# Controlled vLLM batching experiment

Status: complete.

Increasing max_num_seqs from 1 to 4 demonstrated a sustainable output-throughput improvement of 12.4% between confirmation means. All six selected confirmations at the final operating rates met the frozen limit; the conservative throughput and variability gates passed.

Frozen experimental P99 limit: 2.260152 seconds, 1.2 times the warmed 1,000-request light-load max_num_seqs=1 baseline P99 of 1.883460 seconds at 0.280590 RPS. This is not a customer-derived SLO.

A single NVIDIA GB10 on spark-02 served the cached nvidia/Qwen3.6-35B-A3B-NVFP4 revision 1355db6a052410cfd62085d94b58866fd0f2c3c5 with NVFP4 weights, bfloat16 compute and FP8 KV. The pinned Dynamo 1.5.1 image contains vLLM 0.28.0. The test used its standalone vLLM API, bypassing Dynamo routing. Load came from controller. Qwen downtime was explicitly authorized; Muse and production routing were not changed.

Controls were 4,096-token context, 2,048 max batched tokens, 2 GiB KV budget, the image's default CUDA graph policy, no prefix caching and no speculative decoding. Only max_num_seqs varied across configurations. These results apply to this test configuration, not the original 262,144-token production configuration. Exact manifests and startup logs are saved under config-*.

The saved seed-20261015 dataset contains 30,000 unique prompts, verified by round-tripping the exact cached tokenizer to 512 tokens. Every measured response is checked for 512 input and exactly 128 output tokens. Requests set ignore_eos, min_tokens=128 and max_tokens=128. Each run uses a distinct dataset slice. Streaming log probabilities verify total generated token counts, and coalesced output events are retained and counted. Client-observed ITL is the P99 of token arrival gaps; tokens delivered in the same event share that observed arrival timestamp. P99 per-request average ITL is also saved, using last-token arrival minus first-token arrival divided by 127. Internal engine timings inside coalesced events are unavailable. End-to-end latency includes dispatch delay from the scheduled open-loop arrival. Completed-request output throughput includes final request drain. Raw records retain partial output token counts for failed requests; observed throughput across all statuses is saved separately. Failed, cancelled, wrong-length and timed-out requests remain in raw records and invalidate the point.

Best passing exploratory points (short runs; confirmation decides the result):

| max_num_seqs | Best passing exploratory RPS | Output tok/s | P99 s | Completed | Sampled peak running |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.5561 | 71.19 | 1.8512 | 100 | 1 |
| 2 | 0.6680 | 85.27 | 2.1339 | 100 | 2 |
| 4 | 0.6904 | 88.01 | 2.1856 | 80 | 2 |
| 8 | 0.6904 | 88.00 | 2.1527 | 80 | 2 |

Calibration and individual confirmation runs:

| Run | Seqs | Completed | Offered RPS | Achieved RPS | Output tok/s | P99 s | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| confirm-s1-r1 | 1 | 1000 | 0.5561 | 0.5561 | 71.18 | 1.8757 | True |
| confirm-s1-r2-lower-rate | 1 | 1000 | 0.5561 | 0.5561 | 71.18 | 1.9333 | True |
| confirm-s1-r3-lower-rate | 1 | 1000 | 0.5561 | 0.5561 | 71.18 | 1.8913 | True |
| confirm-s4-r1 | 4 | 1000 | 0.6904 | 0.6901 | 88.33 | 2.2883 | False |
| confirm-s4-r1-lower-rate | 4 | 1000 | 0.6250 | 0.6249 | 79.99 | 2.1028 | True |
| confirm-s4-r2-lower-rate | 4 | 1000 | 0.6250 | 0.6249 | 79.98 | 2.1270 | True |
| confirm-s4-r3-lower-rate | 4 | 1000 | 0.6250 | 0.6249 | 79.99 | 2.1437 | True |
| threshold-baseline-s1 | 1 | 1000 | 0.2806 | 0.2807 | 35.93 | 1.8835 | True |

Confirmation sample counts and run-to-run variability at the selected operating rates (all other attempts remain in the individual table):

| Seqs | Confirmation runs | Completed | Output tok/s mean ± sample SD | Range | P99 range, s | Every run passes |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 3 | 3000 | 71.184 ± 0.001 | 71.183–71.185 | 1.8757–1.9333 | True |
| 4 | 3 | 3000 | 79.986 ± 0.001 | 79.985–79.987 | 2.1028–2.1437 | True |

Stars in the plot are confirmation runs; crosses are invalid or latency-limit-violating points. All points and errors are in comparison.csv and raw/*/requests.jsonl. Percentiles and throughput were recomputed from those client records by report_batching_experiment.py.

![Throughput versus P99](throughput-versus-p99.png)

At the lowest tested failing seqs=1 rate, 0.5785 requests/s, sampled running requests peaked at 1 and waiting requests at 2. P99 TTFT changed from 0.2298 s in the light baseline to 3.7366 s. P99 ITL changed from 0.0266 s to 0.0305 s.

The waiting queue and TTFT increase show admission queueing at the single-sequence limit. This identifies an observed scheduling limit at that load; it does not identify the physical GPU bottleneck.

The passing exploratory seqs=4 point reached 88.01 output tokens/s while sampled running requests peaked at 2, below its configured cap. Its per-request post-first-token P99 was 2.0385 s, versus 1.6986 s at the passing seqs=1 point. Larger configured caps were therefore not fully occupied at the selected rates. Four and eight produced essentially equal exploratory throughput; the short sweeps do not establish that four is superior to eight.

Kernel timings and memory-bandwidth counters were not collected. Neither a kernel bottleneck nor a memory-bandwidth bottleneck is established by this experiment.

Across selected confirmations, sampled host MemAvailable stayed at or above 78.04 GiB, KV-cache use peaked at 8.42%, and observed preemption-counter increases totaled 0. Memory-capacity pressure was not observed at these operating rates. Dedicated GPU memory.total/free readings are unavailable on this unified-memory platform.

The telemetry contains sampled running/waiting requests, KV use, preemption counters, host memory and available GPU utilization, temperature and power. Missing values remain null. DCGM profiling fields are unavailable unless explicitly exported. Utilization alone does not establish a memory-bandwidth or kernel bottleneck.

Failures and exclusions:

- sweep-s1-3: 0 errors, 0 timeouts, 5 cancellations; stop reasons: ["Sustained backlog growth: [0.4, 1.0, 1.75, 2.25, 2.75, 3.5]", "request 1292: cancelled, length_valid=False", "request 1294: cancelled, length_valid=False", "request 1293: cancelled, length_valid=False", "request 1295: cancelled, length_valid=False", "request 1296: cancelled, length_valid=False"].

Higher offered-rate confirmation attempts remain visible and do not qualify the selected lower-rate operating point:

- confirm-s4-r1: offered 0.690356 RPS, 1000 completed, P99 2.288324 s, passes frozen limit: False.

All latency-limit violations remain in comparison.csv, including completed requests at failed rates. Earlier setup failures and their restoration evidence remain in the parent directory and attempts 02–04. Those failures included an unavailable exporter command, an unsupported logging argument, a client namespace-selection bug and a coalesced-token validation assumption; their artifacts have not been deleted.

Confirmation decision and sample counts:

```json
{
  "candidate": 4,
  "candidate_offered_rps": 0.625,
  "confirmation_stats": {
    "1": {
      "completed": 3000,
      "every_run_passes": true,
      "mean_output_tokens_per_second": 71.18377930461065,
      "std_output_tokens_per_second": 0.0007531740083949376,
      "min_output_tokens_per_second": 71.18328068281232,
      "max_output_tokens_per_second": 71.18464570813948,
      "p99_seconds": [
        1.8757182321192523,
        1.9332565942063227,
        1.891327634578629
      ]
    },
    "4": {
      "completed": 3000,
      "every_run_passes": true,
      "mean_output_tokens_per_second": 79.98575305600694,
      "std_output_tokens_per_second": 0.001148370153672993,
      "min_output_tokens_per_second": 79.98473569099477,
      "max_output_tokens_per_second": 79.98699827115578,
      "p99_seconds": [
        2.102773748633626,
        2.126980768921494,
        2.14368828322622
      ]
    }
  },
  "selected_confirmation_runs": {
    "1": [
      "confirm-s1-r1",
      "confirm-s1-r2-lower-rate",
      "confirm-s1-r3-lower-rate"
    ],
    "4": [
      "confirm-s4-r1-lower-rate",
      "confirm-s4-r2-lower-rate",
      "confirm-s4-r3-lower-rate"
    ]
  },
  "mean_improvement_fraction": 0.12365139695281924,
  "improvement_demonstrated": true,
  "frozen_limit_seconds": 2.260152011719183,
  "best_passing_s1_output_tokens_per_second": 71.19296360176575,
  "rule": "Every selected operating-point confirmation passes; all failed higher-rate attempts retained; candidate minimum >=1.1 times best passing seqs=1 and exceeds observed throughput ranges",
  "complete": true
}
```

The first generation probe immediately after worker readiness returned HTTP 404. Later inventory and generation probes returned HTTP 200 without further service mutations; restoration was then verified. The event is retained in restoration-initial-probe-failure.json. The exported rerun orchestrator now retries generation readiness for up to 120 seconds. The original measured orchestrator is preserved under scripts/recorded, with hashes and the operational-only change in script-provenance.json.

Reproduction requires controller access to the homelab context, the pinned model cached on spark-02, and explicit downtime authorization. Prepare a fresh output directory with original-dgd.json from the current DGD and workload.jsonl, then run:

```sh
python3 scripts/benchmarks/check_batching_open_loop.py
python3 scripts/benchmarks/run_batching_experiment.py --out <fresh-result-directory> --authorized-downtime
python3 scripts/benchmarks/report_batching_experiment.py --root <fresh-result-directory>
```

The orchestrator restores the original Qwen worker in a finally block and verifies original DGD specification, unchanged Service selectors, Qwen generation and Muse model-list health. Restoration evidence is in restoration.json. The selected confirmation run names are explicit in the decision JSON when a lower offered rate is retested. The comparison establishes a tested sustainable lower bound, with short exploratory runs bracketing higher rates; it does not establish an exact capacity maximum. The original production arguments are restored rather than promoting the test configuration. The immutable frozen threshold and its SHA256 record, pinned deployment manifests, startup logs, client environment, workload hash and script snapshots are retained alongside the raw results.
