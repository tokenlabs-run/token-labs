# Muse Glimmer 30B on Dynamo

`aggregated.yaml` creates `muse-glimmer-30b-dynamo-agg` in `token-labs`.
One vLLM worker performs prefill and decode on `spark-01`; the frontend runs on
`controller`. The frontend uses `localhost/dynamo-frontend:muse-pr316-69f3f02` with
`imagePullPolicy: Never`, so that image must already exist on `controller`.
The worker uses the pinned Dynamo 1.5.0 image shared with Qwen.

The model is `meta-models/Muse-Glimmer-30B`, pinned to
`a4e59da52a7bc87ae7251dd5545c0dd437c44b68`. The candidate uses BF16, tensor
parallelism 1, a 32,768-token context, four sequences, and 80% GPU memory
utilization. The context limit is a conservative starting point, not the model's
maximum. No quantization is enabled. DFlash speculative decoding uses the BF16
`meta-models/Muse-Glimmer-30B-assistant` checkpoint, pinned to
`e8192f3a8f617f74be2ce220360c89ef4789f39f`. Its 16-position block includes the last
accepted token, so `num_speculative_tokens` is 15. The drafter adds about 5.11 GB
of weights plus execution and cache overhead. The target checkpoint's generation
configuration supplies sampling defaults. Both Dynamo parser flags
use `muse_glimmer`.
Do not pass `--enable-auto-tool-choice` to `dynamo.vllm`: it is a standalone
vLLM API-server flag and this worker rejects it. Dynamo handles tool parsing
through `--dyn-tool-call-parser`.

## Prerequisites and validation

- Dynamo operator supporting `nvidia.com/v1beta1` and its discovery dependencies.
- Independent spare GPU capacity on `spark-01` with sufficient memory for roughly
  60 GB of target weights plus 5.11 GB of draft weights, KV cache, vision encoder
  execution, and runtime overhead.
  A shared `nvidia.com/gpu` allocation does not prove memory isolation.
- `/home/nvidia/.cache/huggingface` exists on both selected nodes, with storage
  for the checkpoint and access to Hugging Face for any missing files.
- Confirm both pinned images support Muse Glimmer. A locally cached image tagged
  Dynamo 1.5.0 exposes the model architecture and both parser names, but that
  check does not establish the contents of either remote image digest.

After reserving independent capacity, validate against the installed CRD:

```bash
kubectl apply --dry-run=server -f deploy/models/muse-glimmer-30b/dynamo/aggregated.yaml
```

On 2026-10-02, the live graph matched this manifest and both pods were ready.
The public gateway routes `meta-models/Muse-Glimmer-30B` to this graph.
This check-in verifies deployed configuration, not model quality or performance.
For future changes, validate startup, streaming text, image requests, reasoning
separation, and tool-call round trips through a separate candidate frontend. Measure memory and latency at the
configured context and concurrency limits. Compare decode latency and draft-token
acceptance against a run without `--speculative-config`; no speedup has been
measured for this candidate.

Follow the [rollout runbook](../../MODEL_ROLLOUT_RUNBOOK.md) for deployment and
promotion. Use distinct blue/green Deployments and diagnostic Services on
separate capacity, and change only the stable Service selector after all gates
pass. Never reapply this graph with a changed pod template while it serves
production traffic. The public route is recorded in
`deploy/platform/gateway/aigatewayroute-models.yaml`. This directory does not
join GitOps reconciliation.

## Sources

- [Model and checkpoint files](https://huggingface.co/meta-models/Muse-Glimmer-30B)
- [Meta's vLLM serving notes](https://github.com/meta-models/meta-oss-cookbook/blob/main/inference-server/vllm.md)

- [vLLM Muse Glimmer recipe and DFlash configuration](https://recipes.vllm.ai/meta-models/Muse-Glimmer-30B)
- [Official drafter](https://huggingface.co/meta-models/Muse-Glimmer-30B-assistant)

## Host cache permissions

Like the GLM aggregated manifest, this manifest has no explicit security context
and uses the runtime image's default user. Prepare the target and drafter caches
on the worker node as the host cache owner, and ensure the container user can
read the files. Any downloads or cache updates performed by the worker also
require write access; removing the security context does not grant that access.

Dynamo's model prefetch resolves the repository name independently of the vLLM
`--revision` argument. A download by commit SHA can leave `refs/main` absent,
causing prefetch to attempt another download despite a complete snapshot.
For this candidate, the target and drafter cache references on `spark-01` were
created only after verifying upstream `main` matched their pinned revisions.
Do not point `refs/main` at an arbitrary revision or overwrite an existing
reference without checking it. This cache workaround must be rechecked when
updating either checkpoint.
