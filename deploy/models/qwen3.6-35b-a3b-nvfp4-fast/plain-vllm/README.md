# Qwen3.6 35B-A3B NVFP4 Fast on DGX Spark

This is the TOK-25 green candidate for
`unsloth/Qwen3.6-35B-A3B-NVFP4-Fast`. The weights are pinned to Hugging Face
revision `1c3f884bc99aac2524f6d49bcbac8c88401afd66`.

The manifest follows Unsloth's DGX Spark guidance: `CUTE_DSL_ARCH=sm_121a` and
the `flashinfer_b12x` MoE backend. Do not substitute Marlin. Before applying,
verify the selected `vllm/vllm-openai` image contains flashinfer-python 0.6.13
or newer and nvidia-cutlass-dsl 4.5.2 or newer. Resolve the tested image to an
approved digest before production promotion; never promote a mutable tag.

Deploy and exercise green through its diagnostic Service:

```bash
kubectl apply --server-side --dry-run=server -f deployment.yaml
kubectl apply -f deployment.yaml
kubectl rollout status -n token-labs deployment/qwen36-35b-nvfp4-vllm-green --timeout=60m
kubectl port-forward -n token-labs service/qwen36-35b-nvfp4-green 8000:8000
```

Green is the active production slot. Do not apply pod-template changes to this
Deployment while the stable Service selects `green`; its `Recreate` strategy
would cause an outage. Build the next candidate as a separately named `blue`
Deployment on independent capacity, exercise it through a blue diagnostic
Service, and run every conformance, quality, capacity, and rollback gate in
`../../MODEL_ROLLOUT_RUNBOOK.md`. Only after blue is ready and approved should
the stable Service be switched atomically:

```bash
kubectl patch service -n token-labs qwen36-35b-nvfp4 --type=json -p='[
  {"op":"test","path":"/spec/selector/token-labs~1slot","value":"green"},
  {"op":"replace","path":"/spec/selector/token-labs~1slot","value":"blue"}
]'
```

Keep green ready through the observation and rollback window. The checked-in
OpenRouter catalog entry is `is_ready: true`; live discovery still forces it
false whenever the stable Service has no ready endpoint.
