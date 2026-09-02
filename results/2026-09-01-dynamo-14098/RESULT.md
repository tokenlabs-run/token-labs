# Final result: reproduced in P/D mode

Qwen3-0.6B on a same-node SGLang prefill/decode pair reproduces #14098 using
Mooncake TCP (`MC_FORCE_TCP=1`). Both workers are on spark-01; the frontend is
on controller. The model is served as Qwen/Qwen3-0.6B-14098-pd on local port
18099 through a port forward. Image digests are pinned in disaggregated.yaml.

Authoritative sequence: disaggregated/run-3-tcp-ready/summary.json.
- n=1: HTTP 200 in 19.412s (initial warmup), one 64-token completion.
- n=2: curl exit 28 after 30.009s, zero response bytes.
- n=1: HTTP 200 in 0.588s, one 64-token completion.

Failing request ID: c5703975-c800-4d33-9f3a-fe8d8b9e1bf1.
Prefill completes at 14:53:02.456951 UTC. Decode receives the request but does
not finish it during the client deadline; recovery metrics report two pending
transfer requests. The saved TCP worker logs contain no KVTransferError for
this reproduction. Initial default-transport failures are saved separately.

All three Dynamo deployments were Ready at final verification. Qwen3-30B
aggregated and Nemotron remain running. Two-node teardown was not necessary;
both model configurations were nevertheless snapshotted with validated
restoration manifests in pre-two-spark-snapshot/.

The aggregated model did not reproduce the hang; its evidence follows.

# Aggregated comparison

Deployment succeeded; the reported hang was not reproduced in aggregated mode.

- GPU cluster: kubernetes-admin@kubernetes; namespace: token-labs.
- Qwen3 worker: spark-01 (GB10); frontend: controller.
- Model: Qwen/Qwen3-30B-A3B-Instruct-2507-FP8.
- Dynamo 1.5.0.dev20260830; SGLang 0.5.18; frontend router mode kv.
- run-2: n=1 4.783s, n=2 1.505s, n=1 1.362s; all HTTP 200.
- run-3: n=1 1.222s, n=2 1.261s, n=1 1.222s; all HTTP 200.
- Both n=2 responses contained indices [0,1], terminated at max_tokens=64.
- run-1 was an invalid baseline: direct routing rejected all requests because no worker ID was supplied.
- installed-decode-handler.py matches the corresponding upstream file at 1e3478dfe09bdd305d7c58f412fda2dfe5bec7ed exactly.

Deployment and local port-forward on 18098 were left running for investigation.

Additional cold-prompt / natural-EOS check: `cold-eos/` returned HTTP 200 in
0.793 seconds. Both choices returned `399` with `finish_reason: stop`.
Thus neither a previously warmed exact prompt nor the 64-token cutoff is
required for successful n=2 completion in this deployment.

The aggregated failure was not observed in this build. The confirmed P/D
reproduction is described above.
