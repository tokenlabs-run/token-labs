# Live model discovery

Deploy with `kubectl apply -k deploy/platform/model-aggregator`. Kustomize bundles
`aggregator.py` into a versioned ConfigMap and rolls the deployment on changes.

Every 28 seconds the aggregator lists Services in its own namespace and queries
`/v1/models` on llm-d decode services, Dynamo frontends, and any other serving
Service labeled `token-labs/model=true`. Services need an `http` port or port
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
commercial terms are approved; never publish placeholder prices.

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
