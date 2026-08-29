# llm-d + vLLM on RunPod MI300X

This deployment uses llm-d Router v0.10.0 in standalone file-discovery mode:

- Envoy exposes the OpenAI-compatible API on port 8000.
- llm-d EPP selects the backend through the external-processing protocol.
- vLLM serves `Qwen/Qwen3.8-27B` on loopback port 8100 (the RunPod base image reserves 8001 for nginx).

The RunPod pod ID used for this deployment is `vebip8q5g4pgh2`.
