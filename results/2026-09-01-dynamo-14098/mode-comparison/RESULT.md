# Dynamo #14098: mode versus model comparison

On 2026-09-01, the hang reproduced with both Qwen3-0.6B and
Qwen3-30B-A3B-Instruct-2507-FP8 in disaggregated mode. Both models returned
two choices in aggregated mode. This conclusion is scoped to these tested
configurations, not every possible SGLang deployment.

| Model | Aggregated n=2 | Disaggregated n=2 | Disaggregated n=1 recovery |
| --- | --- | --- | --- |
| Qwen3-0.6B | HTTP 200, indices [0,1], 0.647 s | timeout, 0 bytes, 30.009 s | HTTP 200, 0.612 s |
| Qwen3-30B-A3B-Instruct-2507-FP8 | HTTP 200, indices [0,1], 1.847 s | timeout, 0 bytes, 30.008 s | HTTP 200, 1.824 s |

Every valid sequence began with a successful n=1 request. The initial 30B
aggregated cold-start timeouts are preserved separately and excluded because
n=1 also timed out during kernel compilation. A successful long-deadline
warmup preceded the 30B disaggregated comparison.

## Controls and evidence

All four comparison manifests pin the same ARM64 worker and AMD64 frontend
image digests, Dynamo 1.5.0.dev20260830 / SGLang 0.5.18, KV frontend routing,
spark-01 GB10, TP=1, page size 16, 2,048 KV tokens, context 1,024,
max-running-requests 4, memory fraction 0.8, disabled CUDA graphs, and
MC_FORCE_TCP=1. Disaggregation uses Mooncake, one prefill and one decode
worker on the same node. Memory resource limits differ with model size.

The four named result directories contain exact requests, HTTP responses,
summary.json, deployment.json, pods.json (including image IDs), and logs.
Manifests are under deploy/reproductions/dynamo-14098/comparison-*.yaml.

## Fix

The fix is based on upstream main fb7169ed65d9586c16a13c837564df568e61a25e,
in a separate worktree on spark-01. It validates parallel sampling before
allocating a prefill bootstrap room or starting decode work. Disaggregated
n>1 receives HttpError(400); aggregated parallel sampling remains enabled.
It covers token, OpenAI, wrapped, and native SGLang request formats.

The full current-source handler test file passes: 124 tests, including 14
new regression cases. Test execution uses the pinned runtime's dependencies
with current SGLang backend source on PYTHONPATH. An earlier mixed-source
run had two failures caused by the older image's handler base; matching the
source dependencies resolved both. Repository pre-commit checks passed.

Cluster validation uses a ConfigMap overlay of the three changed Python
modules on the pinned runtime. It does not claim a rebuild of all current
upstream Rust components. Fixed manifests and exact overlay are saved beside
the comparison manifests.

Fix commit: `979dfddd3` (DCO Signed-off-by).

30B disaggregated after fix: n=1 HTTP 200 in 1.889 s; n=2 HTTP 400 in
0.026 s; n=1 recovery HTTP 200 in 1.803 s. The response explains that
SGLang disaggregated serving supports only n=1 and suggests aggregated
serving or separate n=1 requests. Small-model aggregated after fix still
returns indices [0,1], HTTP 200 in 0.656 s.

Small-model disaggregated after fix: n=1 HTTP 200 (19.556 s cold), n=2
HTTP 400 in 0.024 s, n=1 recovery HTTP 200 in 0.705 s.

## Complete before/after matrix

| Configuration | n=2 HTTP status (000 = no response) | Seconds |
| --- | --- | --- |
| 06b-aggregated | 200 | 0.647 |
| 06b-aggregated-fixed | 200 | 0.656 |
| 06b-disaggregated | 000 | 30.009 |
| 06b-disaggregated-fixed | 400 | 0.024 |
| 30b-aggregated | 200 | 1.847 |
| 30b-aggregated-fixed | 200 | 2.056 |
| 30b-disaggregated | 000 | 30.008 |
| 30b-disaggregated-fixed | 400 | 0.026 |

All eight sequences have successful n=1 baseline and recovery responses.

Review PR: https://github.com/elizabetht/dynamo/pull/3
Only the fork received branches and a PR. Original checkout staged changes were preserved.

Final live state: patched Qwen3-30B aggregated and patched Qwen3-0.6B P/D on spark-01; Nemotron remains on spark-02. Use context kubernetes-admin@kubernetes, namespace token-labs.

GitHub pre-commit and DCO checks pass. Fork CI configuration failures: label permission, missing approval-job token, and absent fork helm-tester image.

Branch renamed to `fix/sglang-disagg-parallel-sampling` at user request. GitHub closed PR #3 on head-branch rename; replacement review: https://github.com/elizabetht/dynamo/pull/4 (same commit).
