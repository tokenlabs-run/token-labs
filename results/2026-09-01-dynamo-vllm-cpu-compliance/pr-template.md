Title: fix(container): capture vLLM CPU compliance baselines (upstream issue 11706)

## Overview:

Fix CPU vLLM compliance failures caused by validating packages inherited from the upstream runtime as Dynamo additions. Configure architecture-specific baselines for the upstream vLLM CPU image, following the existing XPU approach.

## Details:

- Capture CycloneDX baselines for the amd64 and arm64 variants of `vllm/vllm-openai-cpu:v0.27.1`.
- Record image digests and platforms in the baseline manifest, with layer-prefix verification enabled during capture.
- Set the CPU `baseline_sbom` in the container context so license and source generation use baseline subtraction.
- Preserve the existing license policy: dependencies added above the upstream baseline remain subject to validation.

Validation:
- Both architecture-specific CPU Dockerfiles render with the configured baseline; live image digest checks pass.
- An amd64 container regression reproduces 110 policy violations without the baseline and passes with it.
- A synthetic GPL-3.0-only addition is still rejected after baseline subtraction.
- Native ARM64 compliance generation and policy validation pass in a Kubernetes pod on spark-01.
- Full amd64 licenses-target build attempted: runtime wheel compilation succeeds, but the existing wheel-builder stage stops at `auditwheel: command not found`, before reaching the compliance gate. Full-image validation remains unverified.

## Where should the reviewer start?

Start with `container/context.yaml`, then the new CPU entries in `container/compliance/base_sboms/manifest.json`. The two accompanying `vllm-openai-cpu@5292939d-*.cdx.json` files are generated baseline artifacts.

## Related Issues

**This PR is NOT linked to an issue:**
- [x] Confirmed — no issue link is included in this description.
