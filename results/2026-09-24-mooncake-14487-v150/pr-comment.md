## Validation update: Dynamo 1.5.0 on two nodes

Tested branch head `303def2253ae36fad89eb34dc66a7245003743f8` on 2026-09-24 using `nvidia/Qwen3.6-35B-A3B-NVFP4`, with one prefill on spark-02 and one decode on spark-01. This supersedes the runtime assessment from the earlier Dynamo 1.3.1 test; it does not establish that this model is categorically unsupported.

The official `nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.5.0` image was pinned to index digest `sha256:d7f73fdc1a66d2e1e0bdec2a74f49093ff6c85bc5e9f5ddf8296634418abe761`. Inspected versions: Dynamo 1.5.0, vLLM 0.28.0, PyTorch 2.13.0+cu130, Mooncake transfer engine CUDA13 0.3.13.post1. The exact branch protocol file was mounted through a ConfigMap, SHA256 `90c6d9eaf32b1f36366d1034e8fc3b63afffd4f8bdc2507f5dad0d6bb2fa08a2`. This was a file overlay on a release runtime, not a complete branch image build. The shared operator remained 1.3.1.

The experiment derives from the supplied `deploy/models/qwen3.6-35b-a3b-nvfp4/dynamo/disaggregated.yaml`. Both cases use ordinary DP1/TP1, Mooncake producer/consumer roles, TCP, bootstrap port 8998, eager execution, max model length 8192, max sequences 1, and disabled prefix caching. No DigitalOcean or heterogeneous manifests were used.

| Case | Prefill advertised-host override | Result |
| --- | --- | --- |
| A | Unset | Prefill failed cache registration at 18:09:03 UTC; decode reproduced the same failure at 18:14:51 UTC. |
| B | `DYN_VLLM_MOONCAKE_BOOTSTRAP_ADVERTISE_HOST` from `status.podIP`, resolving to `10.244.1.212` | Prefill failed at the same cache-registration line at 18:18:55 UTC. |

Both cases reached newer Mooncake hybrid-cache initialization but failed inside vLLM before model readiness:

```text
MooncakeConnectorWorker.register_kv_caches
  conv, _ = cache_or_caches
ValueError: too many values to unpack (expected 2)
```

Both `/v1/models` probes returned HTTP 200 with an empty model list. Both `/v1/chat/completions` probes returned HTTP 404. Opening bootstrap port 8998 during startup does not establish engine discovery or successful KV transfer. **No successful remote engine discovery, reachable registered worker endpoint set, or two-node inference request was demonstrated.** The advertised-address fix remains blocked from end-to-end validation by this independent cache-registration failure.

### Python and CI

The current protocol test module ran in the 1.5.0 container: **69 passed, zero skipped**, with 20 pytest warnings from the isolated test environment. Real vLLM ParallelConfig/helper tests cover ordinary DP1, external/hybrid LB, centralized DP and multi-node model-parallel ownership, with and without the override. They verify helper port and transfer metadata preservation and that local registration remains unchanged. Separate URL regressions cover raw IPv6 serialization and malformed hosts. These tests do not claim end-to-end IPv6 support.

Current-head PR checks were successful, including operator CI and pre-commit. Rust tests and clippy were skipped. The captured check list does not establish a full GPU CI run.

### vLLM 0.30.0 assessment

ARM64 image and wheel artifacts exist. Its Mooncake source handles raw page tensors directly in the corresponding registration path, eliminating the specific failing unpack operation by source inspection. However, Dynamo 1.5.0 declares an exact vLLM 0.28.0 dependency. A clean dry run resolving `ai-dynamo[vllm]==1.5.0` together with `vllm==0.30.0` failed with `ResolutionImpossible`. No 0.30 package was installed or deployed. A custom integration and a successful two-node request are still needed before calling this combination validated.

### Evidence

Saved in token-labs under `results/2026-09-24-mooncake-14487-v150/`: exact manifests, applied DGD, pod snapshots, startup logs, HTTP request/results, image/version metadata, reproducible Python runner and test output, dependency-resolution output, current-head CI snapshot, source comparison, and SHA256 checksums. The previous 1.3.1 evidence is retained separately. This comment is a local draft and has not been posted.
