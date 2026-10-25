# Host the TokenLabs Codex catalog

This catalog configuration records the October 24 deployment. Flint was retired on October 25; its configured entry is filtered out when the backend is unavailable. Qwen3.8 publication through the model aggregator and playground is configured separately in `deploy/platform/model-aggregator/`.

`https://api.tokenlabs.run/codex/models` serves an authenticated Codex-native
catalog for Qwen3.6 NVFP4 and Flint. Ordinary `/v1/models` keeps its existing
OpenAI-compatible response.

The catalog runs in its own CPU-only Deployment and exact HTTPRoute. It does
not change model pods, the model aggregator, or inference routes. Every catalog
request probes the two stable model Services without forwarding the caller's
credential. Only models with a successful live inventory response and a valid
context limit are advertised. If neither backend is available, the endpoint
returns HTTP 503. Authentication runs before discovery.

## Configure a client

Merge the following settings into the existing provider configuration. Replace
the example environment variable with your own credential delivery mechanism.
Keep the first two settings before any TOML table.

```toml
model = "nvidia/Qwen3.6-35B-A3B-NVFP4"
model_provider = "tokenlabs"

[model_providers.tokenlabs]
name = "TokenLabs"
base_url = "https://api.tokenlabs.run/v1"
model_catalog_url = "https://api.tokenlabs.run/codex/models"
wire_api = "responses"
env_key = "DGX_TOKENLABS_KEY"
```

Remove any effective `model_catalog_json`, which takes precedence over remote
discovery. Restart the client after changing provider configuration. The
credential must reach the client process. A desktop or remote app-server does
not necessarily inherit an interactive terminal's environment.

This installation uses the supported command-backed authentication mechanism
instead of `env_key`. Its helper at `~/.codex/tokenlabs-credential.py` resolves
`DGX_TOKENLABS_KEY` from the process environment or the existing literal
assignment in `~/.zshrc`. It does not evaluate shell commands. Never run the
helper directly in a terminal or agent tool, because its authentication contract
prints the credential to stdout. Codex consumes that output privately.

```toml
[model_providers.tokenlabs.auth]
command = "/usr/bin/python3"
args = ["/home/nvidia/.codex/tokenlabs-credential.py"]
timeout_ms = 5000
refresh_interval_ms = 300000
```

Do not combine this auth table with `env_key`, `experimental_bearer_token`, or
`requires_openai_auth`. The catalog accepts the configured operator credential;
it does not discover or authorize every tenant key. Its Kubernetes Secret
contains only the SHA-256 digest, not the plaintext credential.

## Verify the service

From the repository root:

```bash
python3 -m unittest discover -s deploy/platform/codex-catalog -v
python3 deploy/platform/codex-catalog/verify.py
codex debug models
```

The public verification rejects missing and incorrect keys, checks Qwen is
present, and passes the returned document through the installed Codex parser.
The catalog has been tested with Codex 0.164.0. Context limits come from the live
backend inventories. Both entries conservatively advertise text input and no
provider-hosted search, service tiers, reasoning-effort controls, or original
image-detail capability. These metadata choices do not certify model quality.

## Deploy a new slot

`kustomization.yaml` bundles the code and model definitions in a versioned
ConfigMap. `route.yaml` is intentionally separate so a candidate can be verified
before publication.

1. Inspect the active `codex-catalog` Service selector and save it for rollback.
2. Create a distinct Deployment and diagnostic Service with a new slot label.
   Do not apply a pod-template change to the selected production slot.
3. Mount `codex-catalog-auth`, whose `sha256` entry is the configured credential's
   lowercase SHA-256 hex digest. Never put the credential in a manifest or log.
4. Wait for readiness. Directly probe the candidate's health, denied anonymous
   request, and authenticated model listing.
5. For the initial installation, apply `route.yaml` only after these probes pass.
   For later promotions, change only the stable Service's slot selector.
6. Run `verify.py` through the public endpoint and confirm inference still works.
   Retain the previous slot during the observation and rollback window.

The initial slot uses a pinned Python image, has no package-install step, and
needs no Kubernetes API credentials. Its ServiceAccount token is not mounted.

## Model format and mobile scope

Match model metadata to the deployed Codex schema before upgrading clients.
Use the official [model catalog specification](https://learn.chatgpt.com/docs/model-catalogs)
and [provider setup instructions](https://learn.chatgpt.com/docs/enterprise/connect-to-a-gateway).

A successful desktop or app-server `model/list` response proves backend model
discovery. It does not prove that an iPhone client renders custom models or that
a cloud task reads this computer's configuration. Verify that separately in the
mobile UI. Existing conversations retain their session model selection.
