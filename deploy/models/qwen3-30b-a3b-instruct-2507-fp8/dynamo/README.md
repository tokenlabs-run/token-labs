# Qwen3 30B A3B Instruct FP8 — Dynamo

Stable control workload served through NVIDIA Dynamo. Mechanics are identical to
`../../nemotron-3.5-lightning-30b-a3b-nvfp4/dynamo/`; only names differ.

| File | Purpose |
| --- | --- |
| `aggregated.yaml` | DGD `qwen3-30b-control-dynamo-agg` |
| `disaggregated.yaml` | DGD `qwen3-30b-control-dynamo-disagg` |

## Prerequisites

- `dynamo-platform` operator running in `dynamo-system`.
- `hf-token` secret in `token-labs`.
- Free GPU share on **spark-02**.

## Deploy

```bash
kubectl apply -f deploy/models/qwen3-30b-a3b-instruct-2507-fp8/dynamo/aggregated.yaml
kubectl get dynamographdeployment -n token-labs qwen3-30b-control-dynamo-agg
```

Teardown: `kubectl delete -f <file>`.

## Verify

```bash
kubectl get pods -n token-labs -l app.kubernetes.io/name=qwen3-30b-control-dynamo-agg
kubectl logs -n token-labs -l app.kubernetes.io/name=qwen3-30b-control-dynamo-agg -c main --tail=20
```

## Notes

- **No gateway route exists for this model**, and the operator will not create
  one: it holds RBAC for Services, Ingresses and Istio VirtualServices, but none
  for `aigateway.envoyproxy.io`. Author a route by hand, modelled on
  `deploy/platform/gateway/nemotron35-dynamo-route.yaml`, if this needs external
  access. Avoid the per-component `ingress.enabled` shortcut — it bypasses Envoy
  AI Gateway and its token accounting.
- `--served-model-name` is still the bare `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`,
  matching the llm-d side. Suffix both before running the two stacks
  concurrently, or the gateway cannot tell them apart.
- Workers request the time-sliced `nvidia.com/gpu.shared`, which provides no
  memory isolation — see the Nemotron Dynamo README.
