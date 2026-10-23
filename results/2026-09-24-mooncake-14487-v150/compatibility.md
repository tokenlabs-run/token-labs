# vLLM 0.30.0 compatibility check

Dynamo 1.5.0 declares `vllm[flashinfer,otel,runai]==0.28.0`. Its official ARM64 runtime was inspected and contains vLLM 0.28.0, PyTorch 2.13.0+cu130, and mooncake-transfer-engine-cuda13 0.3.13.post1.

A clean dependency-resolution dry run with `ai-dynamo[vllm]==1.5.0` and `vllm==0.30.0` failed with ResolutionImpossible. No package replacement was performed. See `dynamo-requirements.txt` and `vllm030-resolver-clean.log`.

ARM64 vLLM 0.30.0 image and wheel artifacts exist. See `vllm030-arm64-manifest.json` and `vllm030-package.txt`. Artifact availability does not establish integration compatibility.

The observed 0.28.0 startup failure is in MooncakeConnectorWorker.register_kv_caches: `conv, _ = cache_or_caches` raises ValueError when given the model's raw-page tensor. In the 0.30.0 source, this method handles raw page tensors directly. This removes the specific failing unpack operation by source inspection, but has not been tested on the live model in 0.30.0. A custom Dynamo runtime with dependency review, import/API tests and two-node request validation is required before declaring that combination usable.

Sources:
- https://docs.dynamo.nvidia.com/dynamo/reference/releases/v1-5-0
- https://pypi.org/pypi/ai-dynamo/1.5.0/json
- https://pypi.org/pypi/vllm/0.30.0/json
- https://github.com/vllm-project/vllm/releases/tag/v0.30.0
- https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/distributed/kv_transfer/kv_connector/v1/mooncake/mooncake_connector.py
- https://github.com/vllm-project/vllm/blob/v0.30.0/vllm/distributed/kv_transfer/kv_connector/v1/mooncake/mooncake_connector.py
