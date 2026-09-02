# Dynamo #14098: Qwen3 + SGLang reproduction

Target: https://github.com/ai-dynamo/dynamo/issues/14098

## Current vLLM experiment

The SGLang deployments and fix ConfigMap have been removed at the user's
request. Their saved manifests and results below remain historical evidence.
Nemotron is also stopped, with restore manifests under
`results/2026-09-01-dynamo-14098/vllm-disaggregated/snapshot/`.

`vllm-30b-disaggregated.yaml` deploys Qwen3-30B with prefill on spark-01 and
decode on spark-02. Both workers use the same pinned vLLM image; the frontend
uses KV routing. NIXL uses UCX TCP over the direct 192.168.100.x link.
The serving name is `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8-14098-vllm-pd`.

```sh
kubectl --context kubernetes-admin@kubernetes -n token-labs port-forward svc/vllm-qwen3-pd-14098-frontend 18100:8000
python3 deploy/reproductions/dynamo-14098/probe.py --url http://127.0.0.1:18100 --model Qwen/Qwen3-30B-A3B-Instruct-2507-FP8-14098-vllm-pd
```

The SGLang fix review now lives at https://github.com/elizabetht/dynamo/pull/4,
branch `fix/sglang-disagg-parallel-sampling`.

## Controlled mode comparison

The completed 2×2 comparison reproduced the hang with **both Qwen3-0.6B
and Qwen3-30B-A3B-Instruct-2507-FP8 in disaggregated mode**. Both models
returned two choices with HTTP 200 in aggregated mode. All valid sequences
had successful n=1 requests before and after n=2.

See `results/2026-09-01-dynamo-14098/mode-comparison/RESULT.md` for controls,
exact timings, and fix validation. The `comparison-{06b,30b}-{aggregated,disaggregated}.yaml`
files hold the matched configurations. Files ending in `-fixed.yaml` mount
the three-module fix from `fix-overlay.yaml`; apply that ConfigMap first.
Each mode reuses its DGD name, so applying a different model replaces that
mode's existing test workload. Do not deploy every comparison file together.

Use `kubectl --context kubernetes-admin@kubernetes -n token-labs` to inspect
the real GPU cluster; the default context is a separate development cluster.

## Initial reproduction: Qwen3-0.6B prefill/decode

The sections below record the initial experiment, before the controlled
comparison and fix validation changed the live test workloads.

The reported hang is reproduced by `disaggregated.yaml`: one prefill and one
decode worker on `spark-01`, using SGLang 0.5.18, Dynamo 1.5.0.dev20260830,
Mooncake with `MC_FORCE_TCP=1`, and KV frontend routing. Both workers share the
GB10 with the existing aggregated model. Each has a 2,048-token KV-cache cap,
1,024-token context limit, and CUDA graphs disabled.

The working reproduction sequence returned:

| Request | Result | Duration |
| --- | --- | --- |
| n=1 baseline | HTTP 200, 64 output tokens | 19.412 s (first decode warmup) |
| n=2 | curl timeout, zero response bytes | 30.009 s |
| n=1 recovery | HTTP 200, 64 output tokens | 0.588 s |

For the failing request `c5703975-c800-4d33-9f3a-fe8d8b9e1bf1`, prefill completed
at 14:53:02.456951 UTC. Decode received it at 14:53:02.426563 UTC and did not
complete it during the client deadline. Subsequent decode metrics showed two
requests still waiting for KV transfer while the recovery request generated.
This matches the issue's reported disaggregated symptom. The aggregated
Qwen3-30B case below did not hang.

```sh
kubectl --context kubernetes-admin@kubernetes apply -f deploy/reproductions/dynamo-14098/disaggregated.yaml
kubectl --context kubernetes-admin@kubernetes -n token-labs wait --for=condition=Ready dgd/sglang-qwen3-pd-14098 --timeout=10m
kubectl --context kubernetes-admin@kubernetes -n token-labs port-forward svc/sglang-qwen3-pd-14098-frontend 18099:8000
```

After `/v1/models` lists `Qwen/Qwen3-0.6B-14098-pd`, run in another terminal:

```sh
python3 deploy/reproductions/dynamo-14098/probe.py \
  --url http://127.0.0.1:18099 \
  --model Qwen/Qwen3-0.6B-14098-pd
```

Evidence: `results/2026-09-01-dynamo-14098/disaggregated/run-3-tcp-ready/`,
with adjacent prefill, decode, and frontend logs and live deployment objects.
`run-1` hit a separate NVLink transfer error; `run-2-tcp` ran before model
registration and returned 404. Neither is a valid reproduction baseline.

Repeated hanging requests can accumulate pending transfers. To reset only the
small P/D workers, delete their pods and let the deployment recreate them:

```sh
kubectl --context kubernetes-admin@kubernetes -n token-labs delete pod -l 'token-labs/experiment=issue-14098-disaggregated,nvidia.com/dynamo-component-type in (prefill,decode)'
```

Check the labels before using that selector if the operator version changes.
Alternatively, delete and reapply `disaggregated.yaml` to reset the whole P/D
experiment. Reconnect the port forward if the frontend pod is recreated.

The existing Qwen3-30B aggregated and Nemotron deployments remain running.
No teardown was necessary. Restorable snapshots for both are under
`results/2026-09-01-dynamo-14098/pre-two-spark-snapshot/`; their `*.restore.yaml`
files passed server-side dry-run validation.

## Aggregated comparison

This deployment uses one aggregated SGLang GPU worker on `spark-01`, a Dynamo
frontend, Kubernetes discovery, and the existing Dynamo NATS service. The model
is `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`, loaded from the node's Hugging Face
cache. It does not require a disaggregated prefill/decode pair.

Use the GPU cluster context explicitly; the workstation's default context is a
separate kind development cluster.

```sh
kubectl --context kubernetes-admin@kubernetes apply -f deploy/reproductions/dynamo-14098/aggregated.yaml
kubectl --context kubernetes-admin@kubernetes -n token-labs get pods -l token-labs/experiment=issue-14098-aggregated
kubectl --context kubernetes-admin@kubernetes -n token-labs port-forward svc/sglang-qwen3-agg-14098-frontend 18098:8000
```

In another terminal:

```sh
python3 deploy/reproductions/dynamo-14098/probe.py
```

The probe sends the issue's non-streaming arithmetic prompt with `n=1`, `n=2`,
and then `n=1` again to check recovery. Each request has a 30-second deadline.
It writes the request body, response body, headers, curl status, elapsed time,
and choice indices to a timestamped results directory. A baseline must succeed
before an `n=2` timeout can be interpreted as reproducing the symptom. A healthy
`n=2` response contains two completed choices with indices 0 and 1.

For a manual request:

```sh
curl --max-time 30 http://127.0.0.1:18098/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen3-30B-A3B-Instruct-2507-FP8","messages":[{"role":"user","content":"What is 17 * 23?"}],"n":2,"temperature":0.1,"max_tokens":64,"stream":false}'
```

To remove only this reproduction:

```sh
kubectl --context kubernetes-admin@kubernetes -n token-labs delete dgd sglang-qwen3-agg-14098
```

## Observed result — 2026-09-01

Both pods reached Ready. The frontend uses `--router-mode kv`; `direct` requires
an explicit worker ID and rejects the ordinary probe with HTTP 400.

The hang was **not reproduced** in this aggregated configuration. Two complete
probe sequences returned HTTP 200 throughout. The `n=2` requests returned choices
0 and 1 in 1.505 and 1.261 seconds, both with `finish_reason: length` at the
requested 64-token limit. Follow-up `n=1` requests succeeded.

Runtime versions: Dynamo `1.5.0.dev20260830`, SGLang `0.5.18`, PyTorch
`2.13.0+cu130`, FlashInfer `0.6.17`. The installed Dynamo decode handler is
byte-for-byte identical to that file at the issue's cited commit
`1e3478dfe09bdd305d7c58f412fda2dfe5bec7ed`; this does not establish that every
runtime component is identical to the reporter's build.

Evidence is in `results/2026-09-01-dynamo-14098/`: `run-2` and `run-3` contain
the valid KV-routing probes; `run-1` records the initial direct-routing error.
The directory also contains package versions, worker/frontend logs, live
Kubernetes objects, and image metadata. The saved manifest pins the image
digests that were tested; the live deployment was started with `latest`.

Nemotron remains running separately in `vllm-agg-gb10-dspark` on `spark-02`.
The old llm-d Qwen3 deployment is scaled to zero; this reproduction occupies
`spark-01`.

A fresh-prompt `n=2` check also completed naturally: both choices returned `399`
with `finish_reason: stop` in 0.793 seconds (`cold-eos/` evidence). The 64-token
limit in the original probe is therefore not hiding a natural-EOS hang here.
