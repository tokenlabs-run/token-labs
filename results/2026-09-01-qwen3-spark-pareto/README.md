# Qwen3 30B FP8 single-replica controls

Experiment class: **`single-replica-control`**.

These are one-box aggregated controls for each serving arm, not a
distributed-serving framework comparison. Each arm has exactly one model
replica: one vLLM worker on one Spark. Therefore neither
framework can demonstrate multi-worker routing, load balancing, or
prefill/decode disaggregation in this matrix.

Status: stopped by design after 26 of 42 points validated. Both serving stacks
were scaled to zero to release the Spark nodes. The interrupted 8192/8192 c=64
artifacts are preserved with a `stopped-single-worker-baseline` suffix and are
not valid benchmark points. No Pareto curve from this incomplete matrix should
be published as a framework comparison.

Allowed use: per-replica capacity and orchestration/frontend overhead controls.
Disallowed use: claims about multi-replica KV-aware routing, load balancing,
horizontal scaling efficiency, high availability, or failover.

- Model: Qwen/Qwen3-30B-A3B-Instruct-2507-FP8 (MoE, 30.5B total / 3.3B activated parameters per token).
- spark-01: llm-d modelservice-managed vLLM and routing sidecar.
- spark-02: Dynamo frontend and aggregated vLLM worker.
- Controller-side NVIDIA AIPerf, streaming text completions.
- ISL/OSL: 1024/8192, 8192/8192, 8192/1024.
- Concurrency: 1, 2, 4, 8, 16, 32, 64; 21 points per framework.
- Each point: max(4, 2 * concurrency) measured requests plus one warmup.
- Fixed lengths, seed 42, temperature 0, ignore_eos=true; use server token counts.
- Both engines: TP=1, max_model_len=32768, max_num_seqs=64,
  gpu_memory_utilization=0.70, prefix caching disabled, BF16 KV, no speculation.
- Pareto axes: aggregate output tokens/s and output tokens/s/user; higher is
  better for both. Dominance is calculated separately for each ISL/OSL pair.
- Results must pass request-count, error, and output-length validation before
  publication. Small sample sizes do not support strong tail-latency claims.

The llm-d endpoint is the modelservice routing sidecar's Service. This cluster's
Envoy Gateway does not support InferencePool backendRefs, so the EPP is not on
the request path. That arm measures a modelservice-managed, single-worker vLLM
path rather than llm-d scheduling performance. The Dynamo arm passes through
the Dynamo frontend, but its frontend has only one aggregated vLLM worker to
select. It therefore measures single-worker frontend/integration overhead, not
distributed Dynamo scheduling. Node placement is also a potential confounder
because no node-swap control was run.

The prior `vllm-qwen3-pd-14098` two-node reproduction was removed to free the
GPUs. Its existing reproduction files and restoration evidence were preserved.

During the first llm-d 8192/8192 c=16 attempt, spark-01 stopped heartbeating at
2026-09-02T01:12:35Z and Kubernetes marked it NotReady. All 32 in-flight
requests failed after the service endpoint disappeared, so AIPerf emitted no
summary and the validator accepted no result. That attempt is preserved under
`raw/isl8192-osl8192__llm-d-c16.failed-spark01-node-outage-20260902T011235Z*`;
the canonical c=16 point is rerun from scratch after node recovery.

Throughput interpretation: each framework uses one Spark. Aggregate output
throughput is measured output tokens divided by the measurement duration;
per-user output throughput is the reciprocal of inter-token latency, averaged
across requests. At concurrency 1 these are close, with a small difference from
prefill and request overhead. The model is sparse MoE: dense-30B estimates that
assume reading every weight per generated token do not apply. See the model's
[architecture specification](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507-FP8).
