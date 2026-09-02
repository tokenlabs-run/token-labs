## Overview

SGLang disaggregated requests with `n > 1` can wait indefinitely: prefill creates one bootstrap room while decode expands the parallel samples into separate transfers. Reject these requests with HTTP 400 before the handoff begins, while preserving aggregated parallel sampling and disaggregated `n=1`.

## Details

- Validate cardinality at both prefill and decode entry points, including token, OpenAI, wrapped, and native SGLang payloads.
- Return an actionable error suggesting aggregated serving or separate `n=1` requests.
- Add regression tests for rejection before engine/room work and successful supported sampling.

This PR is for review in `elizabetht/dynamo` only. Its base branch snapshots upstream main `fb7169ed65d9586c16a13c837564df568e61a25e`; this keeps the diff limited to the fix without changing the fork's main branch.

## Where should the reviewer start?

`components/src/dynamo/sglang/_disagg.py`, then the two handler entry points and `tests/test_sglang_decode_handler.py`.

## Validation

- Repository pre-commit checks pass for all four changed files.
- Full handler test file: 124 passed, including 14 new regression cases, using current backend source with the SGLang runtime dependencies.
- Final aggregate regression: Qwen3-30B `n=2` returns HTTP 200 with indices [0,1] in 2.056 s, with successful `n=1` before/after (3.147 s / 1.781 s).
- After fix: Qwen3-0.6B disaggregated `n=2` returns HTTP 400 in 24 ms; `n=1` succeeds before and after (19.556 s cold / 0.705 s).
- After fix: Qwen3-30B disaggregated `n=2` returns HTTP 400 in 26 ms, bracketed by successful `n=1` responses (1.889 s / 1.803 s). Qwen3-0.6B aggregated `n=2` still returns two choices in 0.656 s.
- Before fix: both Qwen3-0.6B and Qwen3-30B-A3B-Instruct-2507-FP8 return two choices in aggregated mode; both time out after 30 seconds with zero bytes in disaggregated mode. `n=1` succeeds before and after each failure.
- Cluster: GB10, SGLang 0.5.18, Dynamo 1.5.0.dev20260830, KV frontend routing, same-node Mooncake P/D with TCP, pinned images and matched inference limits. The three changed Python modules are mounted as a checksum-verified ConfigMap overlay; this is not a full rebuild of current upstream Rust components.

## Fork CI note

The initial fork automation has three configuration failures: `Lint PR` reports `Resource not accessible by integration` while adding its label, and `ok-to-test` has an empty `GH_TOKEN`. The copyright job cannot pull the absent fork image `ghcr.io/elizabetht/dynamo/helm-tester:0.1.1` (`manifest unknown`). GitHub pre-commit, DCO, codeowners, and link checks pass. These are separate from the locally passing pre-commit/handler tests and the cluster validation; no workflow permissions or approval gates were changed.

## Related Issues

Relates to ai-dynamo/dynamo#14098.
