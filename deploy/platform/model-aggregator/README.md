# Live model discovery

Deploy with `kubectl apply -k deploy/platform/model-aggregator`. Kustomize bundles
`aggregator.py` into a versioned ConfigMap and rolls the deployment on changes.

Every 28 seconds the aggregator lists Services in its own namespace and queries
`/v1/models` on llm-d decode services, Dynamo frontends, and any other serving
Service labeled `token-labs/model=true`. Services need an `http` port or port
8000. Model IDs come exclusively from successful backend responses. Unavailable
or removed backends disappear on the next refresh; duplicate model IDs merge.
A failed Kubernetes discovery returns 503, never a static or stale fallback.

`GET /openrouter/models` serves the approved OpenRouter schema-2.4 document from
the `openrouter-model-document` Secret. The Secret must contain a `models.json`
key generated and validated by `scripts/openrouter/generate_model_document.py`.
It is optional at deploy time, but the endpoint fails closed with 503 while it
is absent or malformed. A configured `is_ready: true` is dynamically reduced to
false unless that exact model ID is present on a live backend.

OpenRouter should use `https://api.tokenlabs.run/openrouter/v1` as its API base.
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
