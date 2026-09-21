# Gateway

Envoy Gateway + Envoy AI Gateway. Everything a client reaches on
`api.tokenlabs.run` passes through here, and `www.tokenlabs.run` renders what
this layer advertises.

| File | Purpose |
| --- | --- |
| `gateway.yaml`, `gatewayclass.yaml`, `envoyproxy-infra.yaml` | The Gateway itself |
| `aigatewayroute-models.yaml` | **Generated.** Every model's Service/Backend/AIServiceBackend + the single AIGatewayRoute |
| `buffer-policy.yaml`, `cors-policy.yaml`, `extproc-streaming-policy.yaml` | Traffic policy |

## Deploying a model

Write the model's `llm-d/*-values.yaml` or `dynamo/*.yaml` under
`deploy/models/<model>/`, then run one command:

```bash
scripts/common/deploy_model.sh deploy/models/<model> <llm-d|dynamo> [aggregated|disaggregated]
```

That deploys the workload, regenerates this directory's route from live cluster
state, applies it, waits for readiness, and validates every model through the
public gateway. Teardown is the same command with `--teardown`, and it
un-advertises the model in the same pass.

There is deliberately **no route file to edit by hand**. That step is what got
forgotten before: a Nemotron llm-d model stayed advertised on the public site
for 13 days with no pods behind it, and a deployed model stayed unreachable
until someone noticed.

```bash
python3 scripts/common/gen_aigwroute.py --check   # CI: fails if route != cluster
```

## Two things that will bite you

**Exactly one `AIGatewayRoute` may exist on this Gateway.** Each one compiles to
an HTTPRoute whose final rule is a bare `PathPrefix: /` catch-all that
direct-responds 500 for an unknown model. Gateway API breaks cross-route ties by
oldest `creationTimestamp`, and Envoy Gateway evaluates the older route's rules
— catch-all included — before any rule of a newer route. So a second route is
silently shadowed: every model it owns returns 500 while it still reports
`Accepted`. `gen_aigwroute.py --apply` warns when it finds a stray.

> `aigwroute.yaml` used to sit here defining a second `AIGatewayRoute`
> (`llm-inference`) for four archived models. Flux never applied it — `platform`
> is commented out of `deploy/kustomization.yaml` — so it was inert, and
> enabling `platform` would have detonated it: being the oldest route, its
> catch-all would have shadowed `token-labs-models` and 500'd every model, with
> the cause looking entirely unrelated to the change. Deleted; its models live
> in `deploy/archive/models/`. A new model reaches the gateway through
> `deploy_model.sh`, never through a second route.

Some inert `Service`/`Backend`/`AIServiceBackend` objects from those archived
models still exist in the cluster with no endpoints and no route referencing
them. They are harmless, and `deploy/platform/monitoring/` still points at some
of the Services, so they were left in place.

**Catalog and routing are separate.** The public `/v1/models` endpoint is
served by the model aggregator, which probes serving Services every 28 seconds.
Discovering a model there does not create its inference route.

The generator defaults to workload intent. It recognizes Dynamo `worker`,
`prefill`, and `decode` components, deduplicating prefill/decode names behind
one frontend. To discover actual model IDs and aliases from live backends:

```bash
python3 scripts/common/gen_aigwroute.py --discovery live --stdout > /tmp/routes.yaml
```

Live mode selects Dynamo frontend Services, llm-d decode Services, and Services
labeled `token-labs/model=true`, matching the aggregator. It probes Services
with ready EndpointSlices via the Kubernetes Service proxy, so the invoking
host does not need cluster DNS. The kubectl identity needs list access to
Services/EndpointSlices and get access to `services/proxy`. HTTP ports other
than 8000 are preserved when named `http`.

This is a snapshot, not a continuous controller. Services without ready
endpoints are omitted; failed probes, malformed inventories, and empty
inventories on ready Services abort generation. Duplicate model names across
Services and colliding generated object names also abort rather than choosing
a traffic destination implicitly. `--discovery live --apply` is disabled.
Review the output against existing routes: temporary unavailability must not
remove a production route, and discovering a candidate must not promote it.
Follow `deploy/models/MODEL_ROLLOUT_RUNBOOK.md` for production changes.

Run discovery tests with:

```bash
python3 -m unittest discover -s scripts/common -p 'test_gen_aigwroute.py'
```

## Control plane

If route edits appear to do nothing, check this first:

```bash
kubectl get deploy envoy-gateway -n envoy-gateway-system   # MUST be 1/1
```

The data plane keeps serving its last-known route table when the control plane
is down, so a dead controller looks exactly like a config bug — edits apply
cleanly to the API server, report `Accepted`, and change nothing at the proxy.
This ran at `0/1` for nine days ("leader election lost", two pods contending
with one wedged in `Terminating`).
