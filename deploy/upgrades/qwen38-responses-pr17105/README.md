# Qwen RunPod runtime with Responses tool-choice fix

This candidate backports merged Dynamo PR #17105 to the deployed runtime source.
It keeps vLLM, the model checkpoint, tokenizer, context limit, and serving flags
from the production configuration.

## Immutable inputs

- Base image: `nvcr.io/nvidia/ai-dynamo/vllm-runtime-nightly@sha256:197284c3fd3037d4301ffa8282ed330446a5a371c0223fe1da448529930f064b`.
- Base source: `3763cee6080ce6a8ab4156f055d8ce72d984458c`.
- Merged fix: `a7ed39ca919128918241193760d138a448d6d12b`.
- Backport source: `899463586e30a0192d0078e3b1801169a7ee3d83`.
- Runtime package: `1.6.0.dev20261018+pr17105`. The local version suffix
  preserves the base Python package's nightly dependency constraint.
- Rust toolchain and feature set match the base source's runtime wheel recipe.

The base already contains the Responses tool namespace fix from Dynamo #15401.
This backport adds #17105 without replacing that fix. The model context limit
remains 131,072 tokens; larger Codex sessions still require compaction.

## Build

Prepare a clean Dynamo checkout at the base source and cherry-pick the merged
fix with `git cherry-pick -x --signoff`. The script verifies that the complete
source diff has the merged fix's patch ID before exporting the build context.

```bash
bash deploy/upgrades/qwen38-responses-pr17105/build.sh \
  /tmp/dynamo-qwen-runpod-pr17105 \
  tokenlabs/dynamo-qwen:pr17105-899463586e \
  /tmp/qwen-pr17105-build-20261022
```

The final stage installs only the rebuilt Dynamo runtime wheel. Build tools and
source stay in the builder stage. The frontend import/help check runs during
the image build. Record the published digest before creating a RunPod pod.

## Rollout

Use a separate Terraform root and encrypted state key for the candidate.
The candidate root is `terraform/environments/runpod-pr17105` in the isolated
inference-platform checkout; it manages no existing production resources.

Keep the selected production relay and GPU pod unchanged. Give the new relay a
unique slot label and diagnostic Service. Require readiness, warm-up, Responses
regression cases, namespace/tool continuation, real Codex, quality, overload,
capacity, and matched latency evidence before switching the stable selector.
Retain the old pod through observation and the rollback window.

Follow [the model rollout runbook](../../models/MODEL_ROLLOUT_RUNBOOK.md).
Evidence for this run belongs in `results/2026-10-22-qwen38-pr17105/`.
Store credentials only in the designated private state and secret files.

## Build and provisioning result

Published image:
`elizabetht/dynamo-frontend@sha256:0c47313604ae26b6f8866ab4c194d715053a0617854ff26ed44c3a22386d107e`.
Anonymous manifest access and the frontend import check passed. Package versions
match the inputs above, with vLLM `0.31.0`; dependency diagnostics match the base.

RunPod rejected the separate candidate creation because no matching instance
was available in `US-MO-2`. Inventory confirmed that only the existing production
pod remains. The candidate state contains its generated credential and no GPU
resource. Production was not changed.

Resume only with independent spare capacity. Generate a new plan against the
existing candidate state, run the plan guard, and apply that reviewed plan.
Do not reuse the earlier saved plan or replace the active pod. Relay definitions
in the infrastructure worktree are unfinished and have not been published or
applied; they still need the new origin and encrypted credential.
