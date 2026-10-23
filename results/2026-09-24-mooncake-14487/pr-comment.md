Tested the advertised-host change from commit `303def2253ae36fad89eb34dc66a7245003743f8` on two NVIDIA GB10 nodes with `nvidia/Qwen3.6-35B-A3B-NVFP4`. **The end-to-end result is blocked by a Qwen3.6/Mooncake initialization incompatibility; this run does not establish that the cross-node request is fixed.**

### Configuration

- Derived from `deploy/models/qwen3.6-35b-a3b-nvfp4/dynamo/disaggregated.yaml`; no DigitalOcean or heterogeneous deployment manifests were used.
- One prefill replica and one decode replica on different nodes; TP=1 and DP=1.
- `MooncakeConnector`, producer/consumer roles, TCP transport, bootstrap port `8998`.
- Runtime: Dynamo `1.3.1`, vLLM `0.23.0`, Mooncake Transfer Engine `0.3.10.post2`.
- Image digest: `sha256:f70399e3181c33d19906f3c5100a01476071c66e0d701e7f1e6b19aea4d1cbc2`.
- The exact `kv_connector_protocols.py` from the tested commit was mounted into both workers via ConfigMap. Its live SHA256 was `90c6d9eaf32b1f36366d1034e8fc3b63afffd4f8bdc2507f5dad0d6bb2fa08a2`. This was a Python-module overlay on the existing runtime, not a full image build from the branch.
- Model revision observed in runtime resolution: `1355db6a052410cfd62085d94b58866fd0f2c3c5`.
- Functional-test settings: 8192 maximum sequence length, one concurrent sequence, eager execution, prefix caching disabled. Both cases used identical settings; only the prefill advertised-host env entry differed.

### A/B results

| Case | Prefill override | Result |
| --- | --- | --- |
| A | `DYN_VLLM_MOONCAKE_BOOTSTRAP_ADVERTISE_HOST` unset | Prefill failed during Mooncake initialization at 2026-09-24 17:14:06 UTC. No model registered. Chat request returned HTTP 404. |
| B | Override from `status.podIP`; verified in the running container | Prefill failed at the same initialization path at 2026-09-24 17:19:37 UTC. No model registered. Chat request returned HTTP 404. |

Both cases loaded the Qwen weights and reached Mooncake initialization. The common failure was:

```text
The Mooncake Transfer Engine is using tcp as its protocol.
Detected attention backend GDN_ATTN
MooncakeConnectorWorker.__init__
  -> TransferTopology.__post_init__
  -> attn_backend.get_kv_cache_shape(...)
  -> NotImplementedError
```

The installed Mooncake worker constructs `TransferTopology` with `is_mamba=False` and the first attention backend. For this model, that backend is `GDN_ATTN`, whose `get_kv_cache_shape` reaches the unimplemented base method. This happens before the prefill worker registers its endpoints with the bootstrap server. The override changes Dynamo's advertised URL, not this engine initialization path.

For both cases, `GET /v1/models` returned HTTP 200 with `{"object":"list","data":[]}`. `POST /v1/chat/completions` returned HTTP 404 with an empty body. Consequently, neither case demonstrated remote-engine discovery, reachable registered worker endpoints, KV transfer, or successful generation. The original loopback request failure was not reached in this model/runtime combination.

### Additional validation

Ran the branch's protocol regression file inside the runtime against the actual installed vLLM helper: **67 passed, 2 failed, 0 skipped**. The two failures were the model-parallel cases: the tests expect `master_addr`, while this vLLM version returns `127.0.0.1`. DP1, external LB, hybrid LB, centralized DP, and IPv6 cases passed. The isolated test invocation emitted marker/dependency warnings; it was not a full repository CI run.

A separate CPU protocol probe using the real helper confirmed:

| Override | Advertised URL | Local helper result |
| --- | --- | --- |
| Unset | `http://127.0.0.1:8998` | `127.0.0.1:8998` |
| Prefill pod IP | `http://<prefill-pod-IP>:8998` | `127.0.0.1:8998` |
| `fd00::17` | `http://[fd00::17]:8998` | `127.0.0.1:8998` |

These are address-serialization checks, not cross-node inference evidence or end-to-end IPv6 validation.

### Remaining validation

A Qwen3.6-compatible Mooncake engine is needed before this model can exercise the reported request failure. Alternatively, a separately agreed Mooncake-supported model can isolate the address fix. The model-parallel test expectations also need to be reconciled with the supported engine version. No full-CI success is claimed by this run.

Evidence is saved locally under `results/2026-09-24-mooncake-14487/`: `unset.yaml`, `pod-ip.yaml`, `metadata.json`, both cases' `prefill.log`, `pods.json`, and `http.json`, plus `real-helper-tests.log` and `real-helper-addresses.log`. The evidence has not been uploaded; attach the relevant logs when posting this comment.
