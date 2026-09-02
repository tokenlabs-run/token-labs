# CPU vLLM compliance validation

Changes are staged on spark-01 in `/home/nvidia/src/github.com/elizabetht/dynamo-vllm-cpu-compliance`, branch `fix/vllm-cpu-compliance`. No PR was created and the local implementation commit was undone with a soft reset at the user's request.

The upstream CPU runtime is used as the baseline, matching the existing XPU approach. Both platforms were captured with Syft v1.34.2 using the repository capture script. Capture logs record layer-prefix checks; drift-check.log verifies the pinned upstream index digest.

## Focused container regression

Run from the repository build context:

```sh
docker buildx build --platform linux/amd64 -f ComplianceRegression.Dockerfile --progress=plain --output type=cacheonly .
docker buildx build --platform linux/amd64 -f ComplianceRegression.Dockerfile --build-arg BASELINE_SBOM_FILE=vllm-openai-cpu@5292939d --progress=plain --output type=cacheonly .
docker buildx build --platform linux/amd64 -f ComplianceRegression.Dockerfile --build-arg BASELINE_SBOM_FILE=vllm-openai-cpu@5292939d --build-arg ADD_DENIED_PROBE=true --progress=plain --output type=cacheonly .
```

Expected outcomes: first fails with 110 inherited-package policy violations; second passes; third fails with one new prohibited package. These are recorded in regression-*.log.

## Cluster

A temporary Kubernetes pod on spark-01 ran the digest-pinned upstream CPU image natively on aarch64. The repository compliance generators processed its Python and dpkg packages using the ARM64 baseline, then the unchanged policy validator passed. See cluster-arm64.log. The validation namespace was deleted afterward.

## Full build

```sh
python3 container/render.py --framework vllm --target runtime --device cpu --platform linux/amd64 --output-short-filename
docker buildx build --platform linux/amd64 --target licenses -f container/rendered.Dockerfile --progress=plain --output type=cacheonly .
```

The full build log is collected when the build terminates. Focused regressions do not by themselves establish full-runtime build success.
