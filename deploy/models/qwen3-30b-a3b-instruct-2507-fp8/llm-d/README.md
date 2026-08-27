# Qwen3 30B A3B Instruct FP8 — llm-d

Stable control workload: vLLM through llm-d (GAIE `InferencePool` + EPP in front
of modelservice-managed workers). Deployment mechanics are identical to
`../../nemotron-3.5-lightning-30b-a3b-nvfp4/llm-d/`; only names differ.

| File | Purpose |
| --- | --- |
| `helmfile.yaml.gotmpl` | Both releases and their pinned chart versions |
| `gaie-values.yaml` | InferencePool + EPP (runs on `controller`) |
| `aggregated-values.yaml` | Single decode worker |
| `disaggregated-values.yaml` | 1 prefill + 1 decode |

Releases created: `gaie-qwen3-control-comparison` (EPP) and
`llm-d-qwen3-control-<mode>` (workers).

## Prerequisites

- GAIE CRDs at **v1.5.0** — see the Nemotron llm-d README for the check and the
  `kubectl apply -k` upgrade command.
- `hf-token` secret in `token-labs`.
- Free GPU share on **spark-01**.

## Deploy

```bash
cd deploy/models/qwen3-30b-a3b-instruct-2507-fp8/llm-d
MODE=aggregated NAMESPACE=token-labs helmfile apply     # or MODE=disaggregated
```

## Verify

```bash
kubectl get pods -n token-labs -l token-labs/scenario=qwen3-30b-control
POD=$(kubectl get pod -n token-labs -l llm-d.ai/model=qwen3-30b-control-llm-d -o name | head -1)
kubectl exec -n token-labs $POD -c vllm -- curl -s localhost:8200/v1/models
```

## Rollback

```bash
helm rollback llm-d-qwen3-control-aggregated -n token-labs
```

## Notes

- **No gateway route exists for this model.** Nothing under
  `deploy/platform/gateway/` matches `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`, so
  it is reachable in-cluster only. Add a route modelled on
  `nemotron35-llm-d-route.yaml` before driving it from outside.
- `modelArtifacts.name` is still the bare `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`.
  If this model is ever served from Dynamo at the same time, both served names
  need disambiguating suffixes first — the gateway routes on model name alone,
  so two stacks advertising one name collide. See
  `../../nemotron-3.5-lightning-30b-a3b-nvfp4/` for the `-llm-d` / `-dynamo`
  convention.
- Same chart pinning and `Recreate` caveats as the Nemotron llm-d README.
