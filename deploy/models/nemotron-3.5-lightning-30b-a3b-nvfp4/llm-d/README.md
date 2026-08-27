# Nemotron 3.5 Lightning — llm-d

vLLM served through llm-d: a GAIE `InferencePool` + endpoint-picker (EPP) in
front of modelservice-managed decode/prefill workers.

| File | Purpose |
| --- | --- |
| `helmfile.yaml.gotmpl` | Both releases and their pinned chart versions |
| `gaie-values.yaml` | InferencePool + EPP (routing brain, runs on `controller`) |
| `aggregated-values.yaml` | Single decode worker, no P/D split |
| `disaggregated-values.yaml` | 1 prefill + 1 decode |

Releases created: `gaie-nemotron35-dspark-comparison` (EPP) and
`llm-d-nemotron35-dspark-<mode>` (workers).

## Prerequisites

- GAIE CRDs at **v1.5.0**. The chart emits `appProtocol` on the InferencePool,
  which older bundles silently prune. Check and upgrade:
  ```bash
  kubectl get crd inferencepools.inference.networking.k8s.io \
    -o jsonpath='{.metadata.annotations.inference\.networking\.k8s\.io/bundle-version}'
  # if not v1.5.0:
  kubectl apply -k "https://github.com/kubernetes-sigs/gateway-api-inference-extension/config/crd?ref=v1.5.0"
  ```
  The version is tracked in `deploy/infrastructure/sources/git-repositories.yaml`,
  but that GitRepository is **not** reconciled by Flux — the CRDs are applied by
  hand.
- `hf-token` secret in `token-labs` (gated model download).
- Free GPU share on **spark-01** — both modes pin there via `nodeSelector`.

## Deploy

```bash
cd deploy/models/nemotron-3.5-lightning-30b-a3b-nvfp4/llm-d
MODE=aggregated NAMESPACE=token-labs helmfile apply     # or MODE=disaggregated
```

`MODE` selects the values file; `NAMESPACE` defaults to `token-labs`. The EPP
release is shared between modes and is installed first via `needs:`.

### Gateway route is separate

`helmfile apply` does not touch ingress. External access comes from
`deploy/platform/gateway/nemotron35-llm-d-route.yaml`, which matches on the
model name:

```yaml
value: nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-llm-d
```

**This must equal `modelArtifacts.name` in the values file.** Change one without
the other and the model becomes unreachable through the gateway in both
directions. Apply route changes first — the worker restart window covers the
transition:

```bash
kubectl apply -f ../../../platform/gateway/nemotron35-llm-d-route.yaml
```

## Verify

```bash
POD=$(kubectl get pod -n token-labs -l llm-d.ai/role=decode -o name | head -1)

# served name matches modelArtifacts.name
kubectl exec -n token-labs $POD -c vllm -- curl -s localhost:8200/v1/models

# exactly one --served-model-name (two means a duplicate in container args)
kubectl get -n token-labs $POD -o jsonpath='{range .spec.containers[0].args[*]}{@}{"\n"}{end}' \
  | grep -c served-model-name

# end to end
curl -s https://api.tokenlabs.run/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-llm-d",
       "messages":[{"role":"user","content":"Say OK"}],"max_tokens":16}'
```

Expect `2/2 Running` after roughly 4-5 min: 52 safetensors shards, then
FlashInfer kernel warmup before the startup probe passes.

## Rollback

```bash
helm rollback llm-d-nemotron35-dspark-aggregated -n token-labs
```

Revert the route's model name in the same step if it changed. Rollback pays the
full weight-load window again.

## Notes

- `decode.strategy: Recreate` — one replica, so an upgrade means a real outage
  window, not a rolling handover.
- `--served-model-name` is injected by the chart from `modelArtifacts.name`.
  Do **not** also set it in `containers[].args`: the chart's copy is emitted
  first, so a duplicate in args wins and silently overrides
  `modelArtifacts.name`.
- `modelArtifacts.uri` is what gets downloaded; `modelArtifacts.name` is what
  clients address. Keep `uri` on the real Hugging Face repo when suffixing the
  served name.
- Chart versions are pinned in `helmfile.yaml.gotmpl`
  (`inferencepool` v1.5.0, `llm-d-modelservice` v0.4.16). The sidecar image and
  the modelservice chart must move together — v0.4.16 emits
  `--model-server-port`/`--kv-connector`, which older sidecar images reject.
