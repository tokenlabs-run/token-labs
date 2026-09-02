#!/usr/bin/env python3
"""Render deploy/platform/gateway/aigatewayroute-models.yaml from live cluster state.

Envoy AI Gateway synthesizes /v1/models from the AIGatewayRoute's rule list --
it never polls a backend -- and docs/index.html (www.tokenlabs.run) fetches that
response and renders it. A hand-maintained rule list therefore drifts in two
directions, both of them publicly visible: a model that was torn down keeps
being advertised and 503s when anyone calls it, and a freshly deployed one stays
unreachable until someone remembers to edit YAML. Regenerating from what is
actually running is what keeps the advertised set honest.

Exactly ONE AIGatewayRoute is emitted, and that is not a style preference. Each
AIGatewayRoute compiles to an HTTPRoute whose final rule is a bare
`PathPrefix: /` catch-all with no backendRefs that direct-responds 500 for an
unknown model. Gateway API breaks cross-route ties by oldest creationTimestamp,
and Envoy Gateway evaluates an older route's rules -- catch-all included --
before any rule of a newer route. So a second AIGatewayRoute is silently
shadowed: every model it owns returns 500 from the older route's fallback while
it still reports Accepted and looks healthy.

Discovery, per framework:
  dynamo -- DynamoGraphDeployment CRs. --served-model-name comes off the worker
            components; the dynamo-operator already publishes <dgd>-frontend,
            so no Service is emitted for these.
  llm-d  -- Deployments whose POD TEMPLATE carries llm-d.ai/role=decode. The
            labels are on spec.template.metadata.labels, not on the Deployment's
            own metadata, so `kubectl get deploy -l llm-d.ai/role=decode`
            matches nothing -- every Deployment has to be fetched and filtered
            here. The modelservice chart creates no Service the gateway can
            target, so one is emitted selecting the decode pods directly.
            Envoy Gateway v1.4.6 cannot use an InferencePool as a backendRef;
            point these Backends at the pool once it can.

usage:
  gen_aigwroute.py                 # write the file
  gen_aigwroute.py --stdout        # print it, write nothing
  gen_aigwroute.py --check         # exit 1 if the file is stale (CI / pre-commit)

The output is repo state, not cluster state: write it, commit it, then apply it
the way every other change to this repo is applied.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass

GATEWAY_NAME = "token-labs-gateway"
ROUTE_NAME = "token-labs-models"
SERVICE_PORT = 8000
# Every emitted object carries this so `kubectl apply --prune -l ...` can delete
# the objects of a model that has been torn down. Without it, undeploying leaves
# an orphaned Backend behind and the model keeps being advertised -- the same
# phantom the generator exists to prevent, one layer down.
MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "gen-aigwroute"
DEFAULT_OUT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "deploy/platform/gateway/aigatewayroute-models.yaml"
)


@dataclass
class Model:
    """One advertised model and the gateway objects that carry traffic to it."""

    served_name: str  # what clients put in the request's "model" field
    framework: str  # "dynamo" | "llm-d" | "plain"
    slug: str  # DNS-safe name shared by Service/Backend/AIServiceBackend
    backend_host: str  # in-cluster FQDN the Backend points at
    source: str  # workload this was discovered from, for the comment
    selector: dict | None = None  # llm-d only: emit a Service with this selector


def kubectl(*args: str) -> dict:
    proc = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"kubectl {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout)


def served_name(args: list[str]) -> str | None:
    """Return the name vLLM actually serves, given a container's argv.

    The modelservice chart injects --served-model-name from modelArtifacts.name
    and a values file may add another one after it. vLLM parses this flag with
    nargs='+', so argparse keeps the LAST occurrence -- taking the first would
    report a name the server does not answer to.
    """
    found = [args[i + 1] for i, a in enumerate(args) if a == "--served-model-name" and i + 1 < len(args)]
    return found[-1] if found else None


def slug(served: str) -> str:
    """DNS-1123 name derived from the served model name."""
    s = re.sub(r"[^a-z0-9]+", "-", served.split("/")[-1].lower())
    return s.strip("-")[:63].strip("-")


def is_servable(obj: dict, framework: str) -> bool:
    """Decide whether a discovered workload should be advertised on the gateway.

    `obj` is the full DynamoGraphDeployment (framework="dynamo") or Deployment
    (framework="llm-d") JSON. Return True to give it a rule in the route.

    This gates on INTENT (is this workload meant to be serving?) rather than on
    READINESS (is it answering right now?). Both are defensible; intent is the
    right choice here for three reasons:

      - A model's weights take tens of minutes to land on first deploy. Gating
        on readiness would leave it unrouted for that whole window, so the first
        request after "deployed" would 404 rather than 503 -- a worse signal.
      - Readiness makes the route file churn twice per deploy (pods appear, then
        go ready) and churn again on every restart, which turns `--check` in CI
        into noise and makes a briefly crash-looping model silently vanish from
        routing rather than reporting an error.
      - Whether a model is *answering* is a display concern, and the route table
        structurally cannot express it. Liveness belongs to the prober that
        feeds the site, not to the routing layer.

    The consequence is deliberate: a model that is deployed but still loading is
    routed and returns 503 until it is ready. That is the honest answer to
    "deployed but not serving yet" -- unlike 404, which claims it does not exist.
    """
    if obj["metadata"].get("deletionTimestamp"):
        return False

    if framework == "dynamo":
        # No top-level replica count on a DGD; intent lives on the components.
        # A worker scaled to zero is a paused benchmark, not a served model.
        return any(
            (comp.get("replicas") or 0) > 0
            for comp in (obj["spec"].get("components") or [])
            if comp.get("type") == "worker"
        )

    # llm-d: readyReplicas is ABSENT rather than 0 before anything goes ready,
    # so it is not usable here even if we wanted readiness -- spec.replicas is
    # the declared intent and is always present.
    return (obj["spec"].get("replicas") or 0) > 0


def discover_dynamo(ns: str) -> list[Model]:
    models = []
    for item in kubectl("get", "dynamographdeployment", "-n", ns, "-o", "json")["items"]:
        name = item["metadata"]["name"]
        if not is_servable(item, "dynamo"):
            continue
        for comp in item["spec"].get("components") or []:
            if comp.get("type") != "worker":
                continue
            for c in comp.get("podTemplate", {}).get("spec", {}).get("containers", []):
                served = served_name(c.get("args") or [])
                if served:
                    models.append(
                        Model(
                            served_name=served,
                            framework="dynamo",
                            slug=slug(served),
                            backend_host=f"{name}-frontend.{ns}.svc.cluster.local",
                            source=f"DynamoGraphDeployment/{name}",
                        )
                    )
    return models


def discover_llmd(ns: str) -> list[Model]:
    models = []
    for item in kubectl("get", "deploy", "-n", ns, "-o", "json")["items"]:
        labels = item["spec"]["template"]["metadata"].get("labels") or {}
        if labels.get("llm-d.ai/role") != "decode":
            continue
        if not is_servable(item, "llm-d"):
            continue
        for c in item["spec"]["template"]["spec"]["containers"]:
            if c["name"] != "vllm":
                continue
            served = served_name(c.get("args") or [])
            if not served:
                continue
            s = slug(served)
            models.append(
                Model(
                    served_name=served,
                    framework="llm-d",
                    slug=s,
                    backend_host=f"{s}.{ns}.svc.cluster.local",
                    source=f"Deployment/{item['metadata']['name']}",
                    selector={
                        "llm-d.ai/inference-serving": "true",
                        "llm-d.ai/model": labels["llm-d.ai/model"],
                        "llm-d.ai/role": "decode",
                    },
                )
            )
    return models


def discover_plain(ns: str) -> list[Model]:
    """Discover explicitly labeled OpenAI services with serving replicas."""
    services = kubectl("get", "service", "-n", ns, "-l", "token-labs/model=true", "-o", "json")["items"]
    deployments = kubectl("get", "deploy", "-n", ns, "-o", "json")["items"]
    models = []
    for service in services:
        selector = service.get("spec", {}).get("selector") or {}
        if not selector:
            continue
        matches = [
            deployment
            for deployment in deployments
            if all(
                deployment["spec"]["template"]["metadata"].get("labels", {}).get(key) == value
                for key, value in selector.items()
            )
        ]
        for deployment in matches:
            if not is_servable(deployment, "plain"):
                continue
            for container in deployment["spec"]["template"]["spec"]["containers"]:
                served = served_name(container.get("args") or [])
                if not served:
                    continue
                service_name = service["metadata"]["name"]
                models.append(
                    Model(
                        served_name=served,
                        framework="plain",
                        slug=slug(served),
                        backend_host=f"{service_name}.{ns}.svc.cluster.local",
                        source=f"Service/{service_name}",
                    )
                )
    return models


HEADER = """# GENERATED by scripts/common/gen_aigwroute.py -- do not edit by hand.
# Regenerate after any deploy or teardown:
#   python3 scripts/common/gen_aigwroute.py && kubectl apply -f {out}
#
# A rule here is an advertisement. Envoy AI Gateway synthesizes /v1/models from
# this list alone -- it never polls a backend -- and docs/index.html
# (www.tokenlabs.run) renders that response directly, so a rule whose workload is
# gone shows up publicly as an available model and 503s on use.
#
# There must be exactly ONE AIGatewayRoute on this Gateway. Each one compiles to
# an HTTPRoute ending in a bare `PathPrefix: /` catch-all that direct-responds
# 500 for an unknown model, and Gateway API breaks cross-route ties by oldest
# creationTimestamp -- so a second route is silently shadowed by the older one's
# catch-all: every model it owns 500s while it still reports Accepted.
"""


def render(models: list[Model], ns: str, out: pathlib.Path) -> str:
    parts = [HEADER.format(out=out.relative_to(pathlib.Path(__file__).resolve().parents[2]))]

    for m in models:
        if m.selector:
            sel = "\n".join(f"    {k}: {json.dumps(v)}" for k, v in m.selector.items())
            parts.append(
                f"""---
# {m.served_name} ({m.framework}) -- from {m.source}
# Selects decode pods directly: Envoy Gateway v1.4.6 cannot use an InferencePool
# as a backendRef, so this bypasses the EPP. External traffic gets round-robin,
# not llm-d's KV-cache-aware endpoint picking.
apiVersion: v1
kind: Service
metadata:
  name: {m.slug}
  namespace: {ns}
  labels:
    {MANAGED_BY_LABEL}: {MANAGED_BY_VALUE}
spec:
  selector:
{sel}
  ports:
    - name: http
      port: {SERVICE_PORT}
      targetPort: {SERVICE_PORT}"""
            )

        parts.append(
            f"""---
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: Backend
metadata:
  name: {m.slug}
  namespace: {ns}
  labels:
    {MANAGED_BY_LABEL}: {MANAGED_BY_VALUE}
spec:
  endpoints:
    - fqdn:
        hostname: {m.backend_host}
        port: {SERVICE_PORT}
---
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: AIServiceBackend
metadata:
  name: {m.slug}
  namespace: {ns}
  labels:
    {MANAGED_BY_LABEL}: {MANAGED_BY_VALUE}
spec:
  schema:
    name: OpenAI
  backendRef:
    group: gateway.envoyproxy.io
    kind: Backend
    name: {m.slug}"""
        )

    rules = "".join(
        f"""
    # {m.served_name} ({m.framework}) -- from {m.source}
    - matches:
        - headers:
            - type: Exact
              name: x-ai-eg-model
              value: {m.served_name}
      backendRefs:
        - name: {m.slug}"""
        for m in models
    ) or "\n    []"

    parts.append(
        f"""---
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: AIGatewayRoute
metadata:
  name: {ROUTE_NAME}
  namespace: {ns}
  labels:
    {MANAGED_BY_LABEL}: {MANAGED_BY_VALUE}
spec:
  schema:
    name: OpenAI
  # Declared once here so token accounting applies uniformly to every model and
  # both serving stacks.
  llmRequestCosts:
    - metadataKey: llm_input_token
      type: InputToken
    - metadataKey: llm_output_token
      type: OutputToken
    - metadataKey: llm_total_token
      type: TotalToken
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: {GATEWAY_NAME}
  rules:{rules}
"""
    )
    return "\n".join(parts)


def run(*args: str) -> None:
    proc = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"kubectl {' '.join(args)} failed:\n{proc.stderr.strip()}")
    if proc.stdout.strip():
        print(proc.stdout.strip())


# Kinds the generator owns. Anything carrying the managed-by label in one of
# these kinds but absent from the freshly generated file belonged to a model
# that is gone, and is deleted.
PRUNABLE = [
    "service",
    "backend.gateway.envoyproxy.io",
    "aiservicebackend.aigateway.envoyproxy.io",
]


def apply_and_prune(path: pathlib.Path, ns: str, models: list[Model]) -> None:
    run("apply", "-f", str(path))

    desired = {m.slug for m in models}
    selector = f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}"
    for kind in PRUNABLE:
        existing = kubectl("get", kind, "-n", ns, "-l", selector, "-o", "json")["items"]
        for obj in existing:
            name = obj["metadata"]["name"]
            if name not in desired:
                print(f"pruning {kind}/{name} (no longer backs a deployed model)")
                run("delete", kind, name, "-n", ns)

    # A second AIGatewayRoute silently shadows this one; surface it loudly
    # rather than let it produce mystery 500s.
    routes = kubectl("get", "aigatewayroute", "-n", ns, "-o", "json")["items"]
    strays = [r["metadata"]["name"] for r in routes if r["metadata"]["name"] != ROUTE_NAME]
    if strays:
        print(
            f"WARNING: extra AIGatewayRoute(s) on this gateway: {', '.join(strays)}.\n"
            f"         Whichever is oldest shadows the others with its catch-all 500 "
            f"rule.\n         Fold their models into {ROUTE_NAME} and delete them.",
            file=sys.stderr,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-n", "--namespace", default="token-labs")
    ap.add_argument("-o", "--out", type=pathlib.Path, default=DEFAULT_OUT)
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    ap.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    ap.add_argument(
        "--allow-empty",
        action="store_true",
        help="permit generating a route with no models (a full teardown)",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="kubectl apply the result and prune objects of torn-down models",
    )
    args = ap.parse_args()

    models = (
        discover_dynamo(args.namespace)
        + discover_llmd(args.namespace)
        + discover_plain(args.namespace)
    )
    models.sort(key=lambda m: m.served_name)

    # An empty result is indistinguishable from "everything is torn down", and
    # applying it silently de-advertises every live model. Refuse by default:
    # the overwhelmingly likely causes are a wrong namespace or an is_servable()
    # that rejects everything (it returns None until implemented, and None is
    # falsy -- so an unimplemented predicate yields a route that serves nothing).
    if not models and not args.allow_empty:
        sys.exit(
            f"discovered no servable models in namespace {args.namespace!r}.\n"
            "Applying this would remove every model from the gateway and from "
            "www.tokenlabs.run. Check is_servable() and the namespace; pass "
            "--allow-empty if a full teardown is genuinely what you mean."
        )

    seen: dict[str, Model] = {}
    for m in models:
        if m.served_name in seen:
            sys.exit(
                f"two workloads advertise {m.served_name!r} "
                f"({seen[m.served_name].source} and {m.source}). The gateway routes on "
                "model name alone, so this is unroutable -- give one a distinguishing "
                "--served-model-name suffix."
            )
        seen[m.served_name] = m

    text = render(models, args.namespace, args.out)

    if args.stdout:
        print(text, end="")
        return 0
    if args.check:
        current = args.out.read_text() if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is stale -- run: python3 {pathlib.Path(__file__).name}", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date ({len(models)} models)")
        return 0

    args.out.write_text(text)
    print(f"wrote {args.out} ({len(models)} models)")
    for m in models:
        print(f"  {m.framework:7} {m.served_name}")

    if args.apply:
        apply_and_prune(args.out, args.namespace, models)
    return 0


if __name__ == "__main__":
    sys.exit(main())
