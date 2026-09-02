# llm-d versus Dynamo comparison scenarios

These manifests hold the model, worker image, vLLM configuration, topology, and
GPU allocation constant while changing the orchestration layer.

## Suites

| Suite | Model | Worker image | Purpose |
|---|---|---|---|
| `qwen3-30b-control` | `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8` | `nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.3.1` | Stable no-spec control |
| `nemotron35-dspark` | Nemotron 3.5 Lightning NVFP4 | `nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.5.0-nemotron-3.5-lightning-dev.1` | Experimental DSpark |

Within a suite, llm-d runs `vllm serve` and Dynamo runs
`python -m dynamo.vllm` from the same image.

Each suite contains aggregate and 1-prefill/1-decode manifests. llm-d is pinned
to `spark-01`; Dynamo is pinned to `spark-02`. Every GPU worker requests one
`nvidia.com/gpu.shared` slice. Do not deploy both modes simultaneously because
each worker loads another model copy into the GB10 unified-memory pool.

## Deploy from controller

Create the common secret once:

```bash
kubectl -n token-labs create secret generic hf-token \
  --from-literal=HF_TOKEN="${HF_TOKEN}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Deploy llm-d:

```bash
cd deploy/models/qwen3-30b-a3b-instruct-2507-fp8/llm-d
MODE=disaggregated NAMESPACE=token-labs helmfile apply
```

Deploy the matching Dynamo scenario from the repository root:

```bash
kubectl apply -f \
  deploy/models/qwen3-30b-a3b-instruct-2507-fp8/dynamo/disaggregated.yaml
```

For Nemotron, use `deploy/models/nemotron-3.5-lightning-30b-a3b-nvfp4/`.
Select `aggregated` or `disaggregated` as needed, and remove the old mode before
deploying another. The Qwen3 aggregated comparison uses 32K context, up to 64 sequences,
0.70 GPU-memory utilization, and disabled prefix caching for the fixed-length
concurrency matrix. Qwen3 disaggregated and the Nemotron suite retain their
original one-sequence, 0.40-memory starting settings. Nemotron uses one DSpark speculative token on both
P and D workers, as required for compatible NIXL cache metadata.

Repeat benchmarks with the node selectors swapped to control for differences
between `spark-01` and `spark-02`; keep all engine arguments unchanged.

## Qwen3 Spark single-replica controls (stopped)

The 2026-09-01 Qwen3 matrix was stopped after 26 of 42 points because its
one-worker topology cannot measure distributed framework behavior. See
`results/2026-09-01-qwen3-spark-pareto/README.md` for the validated partial
results and limitations. Its experiment class is `single-replica-control`:
use it only for per-replica capacity and frontend/orchestration overhead. Do not
publish it as evidence of multi-replica routing, scaling, or framework behavior.

For future model and hardware experiments, copy
`scripts/benchmarks/example-config.json` and use the configuration-driven
`scripts/benchmarks/run_aiperf_matrix.py` runner and
`scripts/benchmarks/aggregate_aiperf_matrix.py` validator. The repository-local
`model-serving-benchmarks` Codex skill documents topology controls and the
publication gate.
