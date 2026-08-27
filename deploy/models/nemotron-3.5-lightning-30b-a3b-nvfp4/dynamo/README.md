# Nemotron 3.5 Lightning — Dynamo

vLLM served through NVIDIA Dynamo: a `DynamoGraphDeployment` (DGD) reconciled by
the dynamo-operator in `dynamo-system`.

| File | Purpose |
| --- | --- |
| `aggregated.yaml` | ConfigMap + DGD `vllm-agg-gb10-dspark` (Frontend + single worker) |
| `disaggregated.yaml` | ConfigMap + DGD `vllm-disagg-gb10-dspark` (Frontend + prefill + decode) |

Each file carries its own `*-config` ConfigMap holding the DSpark speculative
decoding config consumed via `--speculative-config=$(SPECULATIVE_CONFIG)`.

## Prerequisites

- `dynamo-platform` operator running in `dynamo-system`.
- `hf-token` secret in `token-labs`.
- Free GPU share on **spark-02** — Frontend and worker both pin there. llm-d
  pins to spark-01, so the two stacks do not contend.

## Deploy

```bash
kubectl apply -f deploy/models/nemotron-3.5-lightning-30b-a3b-nvfp4/dynamo/aggregated.yaml
kubectl get dynamographdeployment -n token-labs
kubectl get pods -n token-labs -l app.kubernetes.io/name=vllm-agg-gb10-dspark
```

Plain `kubectl apply` — no helmfile. Teardown is `kubectl delete -f <file>`.

### Gateway route is not created for you

The operator creates the Frontend **Service**, and can generate a
`networking.k8s.io/Ingress` or an Istio `VirtualService` via the per-component
`ingress` block. It holds **no RBAC for `aigateway.envoyproxy.io` or
`gateway.networking.k8s.io`**, so it cannot create the `AIGatewayRoute` this
cluster routes on. That file is authored by hand:
`deploy/platform/gateway/nemotron35-dynamo-route.yaml`.

Do **not** expose Dynamo with its own `ingress.enabled`. That builds a parallel
ingress path bypassing Envoy AI Gateway, losing model-based routing and
`llmRequestCosts` token accounting — and making llm-d vs Dynamo benchmarks a
comparison of two different data paths rather than two serving stacks.

After the first deploy, read the generated Service name and put it in the
route's `Backend`:

```bash
kubectl get svc -n token-labs | grep vllm-agg-gb10-dspark
kubectl apply -f deploy/platform/gateway/nemotron35-dynamo-route.yaml
```

## Verify

```bash
kubectl get dynamographdeployment -n token-labs vllm-agg-gb10-dspark
kubectl logs -n token-labs -l app.kubernetes.io/name=vllm-agg-gb10-dspark -c main --tail=20

curl -s https://api.tokenlabs.run/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-dynamo",
       "messages":[{"role":"user","content":"Say OK"}],"max_tokens":16}'
```

## Notes

- `--model` (the Hugging Face repo to load) and `--served-model-name` (what
  clients address) are deliberately different. The served name carries a
  `-dynamo` suffix so it cannot collide with the llm-d deployment of the same
  weights — the gateway discriminates purely on model name, so two stacks
  advertising one name is an unroutable ambiguity.
- Workers request `nvidia.com/gpu.shared: "1"`, which is the GPU Operator's
  time-sliced resource (`replicas: 3` per physical GB10). With
  `--gpu-memory-utilization 0.85`, two of these landing on one node will OOM —
  time-slicing gives no memory isolation.
- Keep vLLM args aligned with `../llm-d/aggregated-values.yaml` when the point
  of the run is comparing the two stacks.
