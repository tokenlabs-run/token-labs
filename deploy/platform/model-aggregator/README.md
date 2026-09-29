# Live model discovery

Render with `kubectl kustomize deploy/platform/model-aggregator`. Kustomize bundles
`aggregator.py` into a versioned ConfigMap. For production changes, deploy a separate
aggregator candidate and diagnostic Service, verify it, then change only the stable
Service selector. Keep the previous aggregator ready for rollback; do not apply a
pod-template change to the Deployment selected by the production Service.

Every 28 seconds the aggregator lists Services in its own namespace and queries
`/v1/models` on llm-d decode services, Dynamo frontends, and any other serving
Service labeled `token-labs/model=true`. `MODEL_BACKEND_SERVICES` optionally limits
those candidates to comma-separated Service names in the same namespace. Production
currently allows only `glm47-flash-dynamo-disagg-frontend`; inactive and
experimental Services are not probed or used for chat routing. Update the allowlist
through a separate aggregator candidate when the approved serving Service changes.
An empty/unset allowlist restores automatic discovery. An unavailable allowlisted
backend is still reported and is never replaced by an unapproved Service.
Services need an `http` port or port
8000. Model IDs come exclusively from successful backend responses. Unavailable
or removed backends disappear on the next refresh; duplicate model IDs merge.
A failed Kubernetes discovery returns 503, never a static or stale fallback.

`GET /openrouter/models` serves the checked-in OpenRouter schema-2.4 document
from `models.json`. Kustomize packages it in the versioned
`openrouter-model-document` ConfigMap and rolls the Deployment when it changes.
Validate every edit against OpenRouter's current provider schema before deploy.
The response is served exactly as checked in and does not depend on live model
discovery. Update `is_ready` explicitly when enabling or disabling OpenRouter
traffic. Pricing is deliberately omitted until
commercial terms are approved; never publish placeholder prices. The static
catalog is currently empty: retired Qwen entries were removed, and GLM provider
metadata has not been approved. Live `/v1/models` and authenticated
`/openrouter/v1/models` advertise GLM from backend discovery.

OpenRouter should use `https://api.tokenlabs.run/openrouter/v1` as its API base.
Both `/models` and `/chat/completions` under that base require a bearer key from
the `openrouter-provider-auth` Secret's `api-key` entry. They return 503 while
the Secret is absent and 401 for a missing or incorrect credential; the separate
schema-2.4 provider catalog remains public at `/openrouter/models`.
The chat route admits at most `OPENROUTER_MAX_CONCURRENCY` requests and returns
HTTP 429 plus `Retry-After` immediately above the limit. Accepted streaming
requests hold their slot until the upstream stream closes, so slow streams cannot
create an unbounded hidden queue. Set the limit only from public-path benchmark
evidence; 16 is a conservative launch value, not a claimed final capacity.

The route-specific EnvoyExtensionPolicy lets the two exact model-list paths
reach this aggregator instead of the AI processor's configured model inventory.
Inference routes and SecurityPolicies are unchanged.

Run tests with `python -m unittest discover -s deploy/platform/model-aggregator`
in an environment with FastAPI and httpx installed.

## GLM-only rollout — 2026-09-29

The stable `model-aggregator` Service now selects
`app=model-aggregator-glm47-candidate`. The previous
`model-aggregator-candidate` Deployment remains ready for rollback. Its failed
pod `model-aggregator-candidate-7fc65dcfd7-5bnwr` was deleted; the healthy pod
was retained.

Validation: 14 aggregator tests and seven gateway-generator tests passed. The
new candidate uses the same application code as the previous live instance.
Candidate health, GLM-only discovery, authenticated completion, and streaming
passed before the selector switch. After cutover, public `/v1/models` and
authenticated `/openrouter/v1/models` returned only `glm-4.7-flash`; public
non-streaming and streaming completions returned HTTP 200, with `[DONE]` on
the stream. `/openrouter/models` returned the intentionally empty static catalog.
No GPU worker template was changed or restarted. These are functional checks,
not a model quality or load-capacity certification.

Rollback changes only the stable Service selector back to
`app=model-aggregator-candidate`; that restores the previous Qwen allowlist and
static catalog as well, so review the model inventory before rolling back.
