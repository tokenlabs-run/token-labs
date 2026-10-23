# Dynamo 1.5.0 Mooncake validation

This run upgrades the Qwen3.6 Mooncake experiment from Dynamo 1.3.1 to the digest-pinned official Dynamo 1.5.0 ARM64 runtime. It uses the supplied token-labs model manifest as its starting point. No DigitalOcean or heterogeneous deployment manifests were used.

The branch protocol file is mounted through a ConfigMap. This validates that file against the release runtime, not a complete branch image. The shared operator remains 1.3.1. The source production manifest is unchanged; the exact experiment manifests are `unset.yaml` and `pod-ip.yaml`.

See `metadata.json` for versions, model revision, runtime digest, nodes, and test settings. The previous Dynamo 1.3.1 evidence remains in the sibling `2026-09-24-mooncake-14487` directory.

## Validation

- `real-helper-tests.log`: 69 passing Python regressions, zero skips. The saved `run-regressions.py` loads the exact branch protocol file and invokes the saved test module inside the 1.5.0 probe image. Tests cover real ParallelConfig/helper paths for ordinary DP1, external and hybrid LB, centralized DP, and multi-node model-parallel bootstrap ownership. Separate URL cases exercise raw IPv6 and invalid input. Twenty warnings are from running the isolated module without the repository pytest marker configuration.
- `unset/`: baseline startup and HTTP evidence. `prefill-previous.log` contains the first upgraded prefill failure; `unset/decode-previous.log` contains the matching decode failure.
- `pod-ip/`: prefill pod-IP case startup and HTTP evidence.
- `pr-checks.json`: current-head PR checks, including successful operator and pre-commit checks; Rust tests and clippy were skipped. This is not evidence of a full GPU CI run.
- `compatibility.md`: vLLM 0.30.0 source and dependency-resolution assessment. vLLM 0.30.0 was not installed or deployed.

Each live case runs one prefill on spark-02 and one decode on spark-01, with Mooncake TCP and bootstrap port 8998. The protocol file hash is recorded in metadata. HTTP probes use a model-specific request through the experiment frontend. A frontend HTTP 200 with an empty model list is not successful model readiness.

The image-copy fallback was stopped after the registry pull completed and both nodes started the pinned image. Its unexpected-EOF log is from that intentional cancellation, not an engine failure.

Reproduce the Python regression in a container holding this directory with `python3 run-regressions.py`. To rerun either cluster case, ensure the protocol ConfigMap is present and apply the corresponding YAML. These manifests use the experiment resource name and do not repoint the public production gateway.
