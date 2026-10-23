# Token Labs Flint provider

The served model ID is `RecursiveSI/flint`. Its OpenRouter mapping is
`recursive/flint-v1.0`. The provider API is
`https://api.tokenlabs.run/openrouter/v1`; its public model document is
`https://api.tokenlabs.run/openrouter/models`.

The portal uses `https://inference.tokenlabs.run/v1`. A dedicated AWS bridge
forwards Flint requests to the authenticated DGX provider API. The bridge reads
`inference/flint-provider-auth`, key `api-key`, through a Secret reference.
It never forwards a portal user's bearer token to DGX. The authoritative AWS
deployment and relay code live in the `inference-platform` GitOps repository;
the relay and tests here are a reference copy.

Both paths share a DGX admission limit of one concurrent Flint request. Rejected
requests receive HTTP 429 with `Retry-After`. Qwen retains its existing backend.
Flint's context limit is 32,768 tokens, including the requested output.

## Prepare and validate a gateway candidate

Follow `deploy/models/MODEL_ROLLOUT_RUNBOOK.md`. Keep the active worker and
gateway unchanged while testing the separate candidate. Never apply a runtime
template change to the active Flint Deployment.

`scripts/openrouter/render_flint_gateway.py --out <evidence-directory>` creates
the separate gateway Deployment, immutable code/catalog ConfigMaps, diagnostic
Service, and a snapshot of the active stable Service. Review and dry-run that
manifest before applying it. The renderer refuses to reuse its candidate name
once that candidate is active.

Run the API conformance, sustained capacity, quality, latency, saturation, and
early-429 checks through the diagnostic Service. The provider model document
defaults to `is_ready: false`; use the generator's `--ready` flag only after
the release gates pass. Render the new immutable catalog into the candidate
before selecting it for public traffic.

Capture the stable Service selector and prove the candidate has ready endpoints.
Promote by changing only `model-aggregator.spec.selector` to
`app: model-aggregator-flint-green` with a JSON-patch test of its previous value.
Keep the previous Deployment and its diagnostic Service ready for rollback.
`rollback-gateway-service.yaml` exposes the retained previous gateway as
`model-aggregator-previous` without changing its Deployment.

`scripts/openrouter/add_flint_route.py --out <evidence-directory>` renders an
additive change to the existing DGX AI route. Its `--apply` mode requires the
validated gateway to be selected and ready. It preserves every existing rule
and uses a resource-version guard. Do not regenerate the entire live AI route:
it contains Qwen InferencePool rules that must remain intact.

## AWS release and rollback

The GitOps change adds the bridge, a Flint-only AI route, and a separate portal
candidate. Test the bridge privately and the candidate portal catalog before
merging. The previous public portal keeps its exact pod template and diagnostic
Service. Publish the new portal by changing only the stable Service selector.

The GitOps repository's `scripts/check-flint-provider.py` exercises authenticated
arithmetic, complete streaming with usage, tool arguments, and public auth
enforcement. It creates a disposable tenant/key and revokes the key in `finally`.
Recheck both existing Qwen aliases after release. Record evidence without keys
or generated content and retain the previous deployments during observation.
The portal Flux Kustomization depends on `inference-gateway` so a new catalog
cannot publish before its API route reconciles.

After the observation stream finishes, run
`scripts/openrouter/check_portal_overload.py --output <report.json>` to verify
that the public portal API preserves HTTP 429 and `Retry-After`. It creates
and revokes a disposable portal key inside AWS; the key stays inside that
process. Stop other operator Flint probes during this check so the test can
admit one request and reject the remaining seven.

To roll back DGX, restore the recorded `model-aggregator` Service selector.
To roll back the portal, restore `app: inference-portal-public` and revert that
selector in GitOps. Withdraw only the Flint route if needed; retain Qwen's
existing rules. OpenRouter application approval and endpoint activation remain
separate from deploying this API.
