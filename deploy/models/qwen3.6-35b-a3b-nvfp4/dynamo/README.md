# Qwen3.6 35B A3B NVFP4 — Dynamo

The DGX Dynamo 1.6.0 upgrade is tracked in the
[upgrade record](../../../upgrades/dynamo-1.6.0/README.md), with
[image build instructions](../../../upgrades/dynamo-1.6.0/BUILD_IMAGES.md).
That change has an explicitly approved one-time downtime exception; the normal
rollout rules below still apply to other changes.

These candidate manifests serve `nvidia/Qwen3.6-35B-A3B-NVFP4`.

| File | Graph | Runtime |
| --- | --- | --- |
| `aggregated.yaml` | `qwen36-35b-control-dynamo-agg` | Dynamo 1.3.1 |
| `disaggregated.yaml` | `qwen36-35b-control-dynamo-disagg` | Dynamo 1.5.0 frontend, pinned custom workers |

The disaggregated candidate uses Mooncake TCP between spark-02 (prefill) and
spark-01 (decode). Its prefill bootstrap host override requires a worker image
containing the matching Dynamo patch. Upgrading only the operator is insufficient.
The aggregated and disaggregated configurations are separate candidates; this
commit does not establish serving compatibility or performance for either.

Use the [model rollout runbook](../../MODEL_ROLLOUT_RUNBOOK.md) before deployment.
Reserve independent GPU capacity and validate a distinct candidate before changing
the public Service selector. These manifests request shared GPUs, which do not
provide memory isolation. Do not apply a template change to an active production
graph. Gateway configuration is generated with `scripts/common/gen_aigwroute.py`;
review its model inventory before applying a route.
