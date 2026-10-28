# Qwen3.8 Responses gateway repair

The public `POST /v1/responses` route returned `404 {"detail":"Not Found"}`.
The Qwen3.8 Dynamo frontend already implemented Responses, but the gateway's
aggregator exposed only Chat Completions. The repair forwards Responses through
the same live model mapping and admission counters, preserving native payloads,
SSE, namespace tools, and tool-result history.

## Deployment

A separate CPU aggregator, `model-aggregator-responses-green`, was cloned from
the active deployment. Its code ConfigMap is immutable and content-addressed.
The source before the patch exactly matched production. The candidate retained
the production image, dependencies, backend allowlist, and concurrency limits.
Only the stable `model-aggregator` Service selector changed at cutover. Neither
model's GPU worker, frontend, image, Service, or serving configuration changed.
The previous `model-aggregator-qwen38-blue` remains ready and directly probeable.
This was a gateway code repair, not a model/runtime promotion.

## Verification

- All 23 unit tests passed, including native payload preservation, streaming,
  cross-protocol admission, cancellation, and upstream error propagation.
- Candidate and public Responses checks passed for unary and streaming text,
  namespace function calls, and function-result continuation.
- Authenticated model discovery and unary/streaming Chat Completions passed for
  both Qwen3.6 and Qwen3.8 before and after cutover.
- Four concurrent mixed-protocol streams held the model's four admission slots.
  A fifth Responses request received 429 with `Retry-After: 1`; capacity recovered.
- A real Codex CLI 0.164.0 public turn returned `CODEX_PUBLIC_RESPONSES_OK`.
- An existing authenticated Qwen3.6 stream spanned cutover and completed all
  2,048 output tokens with `[DONE]` and token usage.
- All four public continuity rounds passed across 92 seconds spanning cutover.
- Kustomize output and server dry run passed; the active deployment was unchanged
  by the manifest dry run. Code ConfigMap content matched its hash and source.

A separate Codex shell-tool smoke turn reached the backend and completed after
receiving tool errors. This host's existing bubblewrap error prevented shell
execution: `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`.
The API repair does not change host sandbox configuration. The isolated Codex
home also reported missing model metadata and used fallback metadata.

## Rollback

Keep both aggregators running. Confirm the old diagnostic Service still has a
ready endpoint, then use a JSON Patch with a test of the current selector:

```bash
kubectl --context=kubernetes-admin@kubernetes -n token-labs patch svc model-aggregator --type=json -p '[{"op":"test","path":"/spec/selector","value":{"app":"model-aggregator-responses-green"}},{"op":"replace","path":"/spec/selector","value":{"app":"model-aggregator-qwen38-blue"}}]'
```

Re-run both-model public chat verification after rollback. The old aggregator
restores existing chat behavior and also restores the previous Responses 404.
No old deployment or model resource was restarted, scaled down, or deleted.
