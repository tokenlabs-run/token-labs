# Qwen3.8-27B-FP8 on EKS

Status: benchmark complete. All 12 planned points passed exact token-length, request-count, and zero-error validation. See RESULTS.md and pareto.json for final measurements; shutdown-complete.json records the separately verified GPU shutdown.

One g6.12xlarge, four NVIDIA L4 GPUs, one Dynamo/vLLM worker with tensor parallelism 4. Runtime versions and immutable deployment configuration are saved beside this file. This measures the deployed configuration, including eager execution, max-num-seqs 8, FP8 KV cache, and three-token MTP speculation. It is not a claim about the model’s theoretical maximum or alternative engine settings.

Request path: local AIPerf → kubectl port-forward → green diagnostic Service → Dynamo frontend → single Dynamo/vLLM worker → four L4 GPUs. Gateway, external authentication, token quotas and ALB are bypassed. Per-GPU throughput is total output throughput divided by four.

Synthetic completions use exact fixed input and output lengths, ignore EOS, temperature 0, and seed 42. Workloads are ISL128/OSL512 and ISL1024/OSL512. Concurrency sweep is 1,2,4,8,16,32, with four request waves and at least 16 measured requests per point, plus two warm-up requests. This exploratory sample does not support strong p95/p99 latency claims. Prefix cache stays enabled as deployed; cache metrics are preserved with raw server metrics. Synthetic token sequences can have lower speculative acceptance than conversational text.

Raw exports must pass exact server-reported input/output token lengths, expected request count, and zero request errors before aggregation. Tokenizer files were copied from the pinned deployed snapshot. Special_tokens_map.json is absent upstream; tokenizer.json, tokenizer_config.json and config.json were copied successfully.

Shutdown requested explicitly by the operator after the experiment. Save the pre-shutdown Service selector, graph replicas, Flux state, NodePool and EC2 instance ID. Scale only this model and remove only its GPU node; retain CPU nodes and portal. Node-local model weights will disappear with the GPU instance and must be fetched on the next startup.
