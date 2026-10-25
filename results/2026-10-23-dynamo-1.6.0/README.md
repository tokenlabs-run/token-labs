# DGX Dynamo 1.6.0 upgrade evidence

Qwen on `spark-02` and Flint on `spark-01` are running Dynamo 1.6.0 with
PR #17105. Both 30-minute load runs passed: 3,455 requests in total, zero
errors. API, protocol, internal-gateway, overload, and runtime-identity checks
passed. Fifty observation samples reported no model readiness, restart, Spark
pressure, or KV-cache saturation errors. No separate quality benchmark ran.

After explicit user approval for the HTTPS destination, each model passed all
24 authenticated public checks at `https://api.tokenlabs.run/openrouter/v1`.
They cover authentication, generation, streaming, tools, and structured output.
Unauthenticated public checks returned 200 for the catalog and 401 for protected
model discovery. The internal provider gateway also passed for both models.

| Evidence | Purpose |
| --- | --- |
| `validation-summary.json` | Combined results and measurement limitations |
| `deployed-state.json` | Final resource specifications, node conditions, and preserved Service selectors |
| `running-runtime-versions.json` | Versions and immutable image IDs from all five running containers |
| `gpu-final.json` | Final GPU telemetry and kernel Xid/OOM checks |
| `downtime-exception.json` | Explicit user authorization for this one-time rollout |
| `approved-before-*.json` | Fresh resource specifications immediately before mutation |
| `preparation-drift-check.json` | Prepared inputs matched the fresh pre-rollout specifications |
| `*-160-api.json`, `*-160-protocols.jsonl` | Actual new-runtime API, tool, namespace, and Responses regression checks |
| `*-160-internal-gateway.json`, `*-160-overload.json` | Gateway conformance and early rejection checks |
| `*-160-load.json`, `*-160-load.jsonl` | Completed 30-minute runs and individual request measurements |
| `observation*.jsonl` | Readiness and metrics samples spanning the load runs |
| `*-160-public-gateway.json` | Passing public HTTPS conformance checks |
| `public-approval-status.json` | Explicit destination approval and verification completion |

The baseline and image-inspection reports were collected before deployment.
`production-state.json` records the earlier preparation phase, when production
had not been changed; use `deployed-state.json` for the final state.

`flint-160-load-64tokens.*` and `flint-160-load-512tokens.*` retain the initial
content-only load probes. Flint could spend their entire budgets on reasoning.
The completed capacity run explicitly counts reasoning tokens, records channel
character counts, and does not claim every bounded request contains a final
answer. Separate API checks verify completed answers and tools.

`flint-160-gateway-test-url-error.json` retains a test invocation that duplicated
`/v1` and received 404 responses. The URL construction was corrected before the
passing three-repetition gateway runs. This report is excluded from the final
conformance summary.

Build, deployment, and rollback details are in
[the upgrade record](../../deploy/upgrades/dynamo-1.6.0/README.md) and
[the image build guide](../../deploy/upgrades/dynamo-1.6.0/BUILD_IMAGES.md).
