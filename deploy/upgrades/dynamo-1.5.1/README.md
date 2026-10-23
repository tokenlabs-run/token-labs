# Dynamo 1.5.1 with Rust EPP

Deployed on October 7, 2026, under the user's explicit exception to AGENTS.md's
zero-downtime rule. Both new model graphs are ready. Their old GPU workers have
zero replicas. Both stable API Services select `release-151`.

Public `/v1/chat/completions` and `/v1/completions` use native Rust EPP 1.5.1.
Responses and Anthropic Messages retain the fixed nightly frontend because
Rust EPP 1.5.1 parses OpenAI Chat/Completions payloads and rejects Responses and
Anthropic tool schemas. The native API prefixes remain `/models/qwen/v1` and
`/models/muse/v1`. The aggregator also uses the nightly frontends.

## Pinned runtimes

`images.json` records the multi-platform digests for the 1.5.1 operator, workers,
and EPP, plus the retained frontend nightly. The Dynamo release source is
`2093662a4d4e5fd318732935213dde08dc7be818`. Both workers report Dynamo 1.5.1 and
vLLM 0.28.0. The HTTP frontends and direct worker sidecars retain nightly digest
`sha256:38286598fd3a514a36bfddb90c2f8751350ccb787fabd307361673a534e46c4f`.

The model revisions, served names, parser settings, context limits, and Muse
DFlash settings are preserved from the captured live inputs. Each worker
performs both prefill and decode and is classified as `decode` for EPP routing.
Prefix caching and KV event publication are enabled.

`effective-kv-block-sizes.json` records the measured worker cache geometry.
Muse uses 128 tokens per block. Qwen's hybrid cache adjusts the requested
128-token block size to 2176, so its EPP uses 2176. Changing EPP's setting did
not restart Qwen's worker.

## Gateway compatibility

Envoy Gateway remains at v1.9.1. Its extension manager registers
`inference.networking.k8s.io/v1/InferencePool` as a backend resource and preserves
the existing AI gateway hooks. The controller was restarted to load that setting.

AI Gateway 1.1.0 omits `send_body_without_waiting_for_header_response` from its
full-duplex EPP filter. Rust EPP requires it. `ai-gateway-inferencepool.patch`
sets that flag for full-duplex processing and leaves it false for buffered
processing. The focused upstream test passes. The live Envoy configuration was
inspected and real EPP requests succeeded after the fix.

`ai-controller.yaml` retains the existing controller settings and uses the
patched image pinned to
`sha256:71cdab34040213143b8ece4ad1f10bd785d6db9abb34aa6c448831647f53995b`.
It is preloaded on `controller` with `imagePullPolicy: Never`. It is not published
to a registry. The rebuild script preserves the `v1.1.0` configuration version
required by the unchanged data-plane sidecar. An ordinary Helm upgrade of the AI
controller must preserve this patch or use an upstream release containing it.

Public EPP rules match the model header and `x-ai-eg-original-path`, which the
AI gateway sets from the actual request path. AIGatewayRoute 1.1.0 does not
support path fields in its matches. The ordinary frontend rules remain as
fallbacks for Responses and other supported API paths.

## Manifest files

- `platform-values.yaml` configures Dynamo Platform 1.5.1, preserving NATS and
  the bundled Grove/KAI components. KAI stale PodGroup eviction is disabled as
  required by the chart.
- `envoy-gateway-values.yaml` preserves the installed gateway values and adds
  InferencePool backend registration.
- `*-graph.yaml` defines separately named EPP/worker graphs. EPP uses the native
  image entrypoint without `eppConfig`, Go flags, or a Go configuration map.
- `*-api-frontend.yaml` defines the separate nightly frontends for native APIs
  and aggregator forwarding. `*-stable-service.yaml` selects their tested slot.
- `*-diagnostic.yaml` selects worker sidecars for HTTP diagnostics. Direct-mode
  requests need EPP's worker-selection headers, so use the canary for inference.
- `*-canary-route.yaml` exposes the isolated EPP paths
  `/upgrade/dynamo-151/qwen` and `/upgrade/dynamo-151/muse`. Append
  `/v1/chat/completions` or `/v1/completions`.
- `public-routes.yaml` records the final AI and native API route specifications.
  `route-order.json` preserves the deployed backend rule indices.
- `rollback-routes.yaml` and `inputs/*-stable-service.yaml` capture original
  routing. `inputs/` also preserves the original model settings.
- `worker-image-checks.yaml` and `nightly-image-check.yaml` contain completed
  image verification Jobs. `frontend-checks.yaml` records the removed temporary
  1.5.1 HTTP probes.
- `Dockerfile.ai-controller`, `build-controller.sh`, and the controller patch
  reproduce the gateway compatibility fix from upstream v1.1.0 commit
  `c217da8a539570ba3f6014a60c2687c29a945f1f`.

Do not apply this directory recursively. Helm values, temporary probes, model
graphs, and promotion files have different purposes. Do not run the original
gateway generator until it preserves these EPP and API fallback rules.

## Verify and promote

Regenerate and check the manifests:

```sh
python3 deploy/upgrades/dynamo-1.5.1/generate.py
python3 deploy/upgrades/dynamo-1.5.1/verify.py
```

Use `check_api.py` against each native API prefix for the full suite, and use
`--chat-only` against the EPP canary. `promote.py` requires 15 passing direct API
checks and three passing canary chat checks in the specified evidence directory.

For each model, run `promote.py --stage` first. It adds a promotion header to
that model's EPP rule while normal traffic continues through its frontend.
Wait for the data-plane configuration bundle to load, then run the public chat
checks with `--header x-dynamo-epp-promotion=qwen-151` or `muse-151`. Record them
as `*-staged-public.jsonl`. Final promotion requires three passing staged public
checks and removes only the staging header. Existing rule indices are preserved
because they form part of AI Gateway's backend identity.

```sh
python3 deploy/upgrades/dynamo-1.5.1/promote.py --model qwen --stage \
  --evidence-dir results/2026-10-07-dynamo-1.5.1
python3 deploy/upgrades/dynamo-1.5.1/promote.py --model qwen \
  --evidence-dir results/2026-10-07-dynamo-1.5.1
```

Future upgrades follow [the rollout runbook](../../models/MODEL_ROLLOUT_RUNBOOK.md).
The maintenance exception does not carry forward to another upgrade. Preserve
old images and model specifications for rollback. Restoring original routes
alone cannot restore a stopped worker: stop the failed candidate, reload the
captured old worker, restore its API Service selector, and verify public requests.
Do not run both full model processes on the same occupied GPU.

## Deployment verification

Both models passed 15 checks through their public native APIs and three checks
through their final public EPP chat routes. These cover unary and streaming
responses, structured tool calls, and the retained nightly's Responses namespace
collision fix. Envoy access logs confirm that EPP chat traffic reaches the worker
sidecars directly. Both new workers, EPP pods, and API frontends have zero
restarts. The public catalog lists both models.

Evidence is in `results/2026-10-07-dynamo-1.5.1/`. These API checks establish
startup and API behavior, not a sustained capacity or latency benchmark.

## Upstream sources

- [Dynamo 1.5.1 release](https://github.com/ai-dynamo/dynamo/releases/tag/v1.5.1)
- [Tagged Rust EPP example](https://github.com/ai-dynamo/dynamo/blob/v1.5.1/examples/backends/vllm/deploy/gaie/agg.yaml)
- [AI Gateway InferencePool addon](https://github.com/theagentrouter/agent-router/blob/main/examples/inference-pool/envoy-gateway-values-addon.yaml)
