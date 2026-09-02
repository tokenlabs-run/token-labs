# Qwen3-30B vLLM disaggregated comparison

Requested topology: prefill on spark-01, decode on spark-02. Model:
Qwen/Qwen3-30B-A3B-Instruct-2507-FP8. Both workers use the same pinned
vLLM-runtime image, with Dynamo 1.4.0 and vLLM 0.26.1rc1.dev306+gcb8104839.
NIXL uses UCX TCP over the direct 192.168.100.10/11 link. This differs from
the earlier SGLang runtime and its Mooncake connector; results apply to the
recorded vLLM configuration, not every backend version or connector.

The SGLang deployments and their fix ConfigMap were removed at the user's
request; Nemotron was also removed to free spark-02. Restore manifests and
pod snapshots are under snapshot/. The Nemotron configuration ConfigMap and
model cache were retained for restoration.

The initial automatic DeepGEMM kernel selection failed during weight loading
with `Unknown SF transformation` on GB10. Its log is preserved under
startup-deepgemm/. This is not an n>1 reproduction. The adjusted manifest
selects Marlin for FP8 linear and expert kernels, disables DeepGEMM, and sets the runtime-required VLLM_TEST_FORCE_FP8_MARLIN=1 override. Logs confirm both Marlin backends are selected.

Manifest: deploy/reproductions/dynamo-14098/vllm-30b-disaggregated.yaml.
Probe: deploy/reproductions/dynamo-14098/probe.py, frontend port 18100,
served model Qwen/Qwen3-30B-A3B-Instruct-2507-FP8-14098-vllm-pd.

Runtime/version files and completed probes will accompany this record.

## Result

The immediate SGLang-style n=2 hang did not reproduce in this vLLM configuration.

| Request | HTTP | Seconds | Choices |
| --- | --- | --- | --- |
| n=1 baseline | 200 | 1.347 | 0 |
| n=2 | 200 | 1.380 | 0, 1 |
| n=1 recovery | 200 | 1.378 | 0 |
| Fresh-prompt n=2, natural completion | 200 | 0.472 | 0, 1 |

Both fresh-prompt choices answered 437 correctly and ended with finish_reason=stop.
The response reports zero cached prompt tokens. The initial n=1 warmup also
succeeded (35.314 seconds); it is separate from the warmed comparison.

NIXL prefill logged `Potentially invalid KV blocks for unrecognized request`
for an n=2 child. The requests still completed. This test does not establish
that long-running/high-load parallel sampling is free of KV-release leaks;
no sustained-load claim is made.

All three final pods are Ready, with zero restarts: prefill on spark-01,
decode on spark-02, frontend on spark-02. Snapshot and logs: final/.
The SGLang deployments, services, pods, and fix ConfigMap are removed.
Nemotron is stopped; its configuration and model cache remain restorable.

SGLang fix branch: fix/sglang-disagg-parallel-sampling, pushed to origin,
commit 979dfddd32b8383c8489b3e8bbb00ba827739276. Replacement review PR:
https://github.com/elizabetht/dynamo/pull/4 (PR #3 closed by branch rename).
