# One-Spark OpenRouter production candidate

This is the launch topology for the single-DGX-Spark experiment: one aggregated
vLLM process, no Dynamo frontend, no llm-d EPP, and no disaggregated prefill. The
provider admission service supplies the bounded public queue and early HTTP 429;
vLLM supplies continuous batching and its local KV cache.

The Deployment is committed at zero replicas because another operator explicitly
scaled the experimental stacks down. Before scaling this candidate to one, verify
that no other GPU worker is running on `spark-01` and record the authorization in
the benchmark run state.

The served name is the exact OpenRouter ID:
`qwen/qwen3-30b-a3b-instruct-2507`. This is deliberately different from the
Hugging Face artifact ID used to load the FP8 weights.

Baseline knobs are fixed to the control experiment: TP=1, 32,768-token context,
64 maximum sequences, 0.70 GPU memory utilization, and prefix caching disabled.
Change one factor at a time. Prefix caching is the first A/B candidate; Dynamo or
llm-d routing is not a one-worker optimization and should be reconsidered only
when Token Labs operates at least two independent Spark replicas.

Render and validate without changing the cluster:

```bash
kubectl apply --dry-run=client \
  -f deploy/models/qwen3-30b-a3b-instruct-2507-fp8/plain-vllm/deployment.yaml
```

Once the infrastructure owner authorizes use of `spark-01`, apply the manifest
and scale exactly one replica. Do not set the provider document `is_ready` flag
until the public matrix, conformance suite, overload 429 test, quality gate, and
soak all pass against this deployment.
