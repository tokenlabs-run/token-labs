# vLLM batching experiment: blocked at capacity preflight

Inspection date: 2026-10-15 UTC. No benchmark requests were sent and no cluster resources were changed.

Both DGX Sparks have one NVIDIA GB10 GPU, and each GPU is allocated exclusively to an active production inference worker. GPU sharing is disabled. Starting a second server by bypassing GPU allocation would share production compute and unified memory and would not provide the required isolation. AGENTS.md requires stopping when independent spare capacity is unavailable.

| Node | Active model | Precision | Available host unified memory at inspection | GPU allocation |
| --- | --- | --- | --- | --- |
| spark-01 | meta-models/Muse-Glimmer-30B | bfloat16 | 14.19 GiB | 1 of 1 allocated |
| spark-02 | nvidia/Qwen3.6-35B-A3B-NVFP4 | NVFP4 weights, FP8 KV | 11.31 GiB | 1 of 1 allocated |

Both workers use vLLM 0.28.0 in the same pinned Dynamo 1.5.1 image. Exact revisions, digest, arguments and runtime measurements are in provenance.json, inspect-pods.json and spark-*-runtime.txt. Both workers were ready with zero restarts since October 7. This is evidence of an existing single-Spark deployment, not an isolated benchmark reliability result. Qwen is a potential existing model for the experiment once separate capacity is available.

NVIDIA driver: 580.95.05. Each Spark reports approximately 119.6 GiB total host unified memory. nvidia-smi dedicated GPU total/free memory reports N/A, not zero. Available host memory is not a guarantee of safe additional GPU capacity. Point-in-time GPU observations were 0% utilization, 45/44 C and 11.65/11.49 W for spark-01/02. These are idle inspection samples, not evidence of a serving bottleneck. DCGM profiling was not measured.

| max_num_seqs | Status | Completed benchmark requests |
| --- | --- | --- |
| 1 | Blocked: no independent spare capacity | 0 |
| 2 | Blocked: no independent spare capacity | 0 |
| 4 | Blocked: no independent spare capacity | 0 |
| 8 | Blocked: no independent spare capacity | 0 |

No warmed baseline or frozen experimental threshold exists. No sustainable capacity, improvement, variability, or bottleneck can be inferred. No workload, benchmark runner, per-request data or throughput plot was produced because execution stopped at the required capacity gate. comparison.csv records blocked points with absent measurement values.

Production Service selectors remained unchanged. Both active model-list APIs returned HTTP 200, and workers remained ready with zero restarts. See final-health.json. No test deployment existed or was created, so no restoration was necessary. Generation health was not exercised.

To proceed, provide one additional available DGX Spark with an unallocated GPU and enough unified memory for a separate model instance. Do not free capacity by stopping either active worker. The baseline, sweep and alternating confirmation runs remain outstanding.

The default kube context pointed to AWS production and its credentials were expired. All homelab inspection commands explicitly selected kubernetes-admin@kubernetes; no context change or AWS reauthentication was performed.


## Follow up after explicit downtime authorization

The later authorization allowed the controlled study to run using the cached model on spark-02. See the [completed study](../2026-10-15-vllm-batching-maintenance/REPORT.md), including all raw evidence and restoration checks. The original capacity-blocked inspection above is retained as history.
