#!/usr/bin/env bash
# Run a text-only harness smoke test. No model-generated tool execution is requested.
set -euo pipefail
if [[ $# != 3 ]]; then
  echo 'Usage: check_harness_client.sh codex|claude BASE_URL MODEL' >&2
  exit 2
fi
client=$1
base_url=${2%/}
model=$3
case "$client" in
  codex)
    timeout 180 codex exec --ephemeral --skip-git-repo-check --sandbox read-only \
      -C /tmp --model "$model" \
      -c 'model_provider="tokenlabs"' \
      -c 'model_providers.tokenlabs.name="Token Labs"' \
      -c "model_providers.tokenlabs.base_url=\"$base_url/v1\"" \
      -c 'model_providers.tokenlabs.wire_api="responses"' \
      -c 'model_providers.tokenlabs.requires_openai_auth=false' \
      -c 'model_providers.tokenlabs.supports_websockets=false' \
      --json 'Reply with exactly OK. Do not use tools or inspect files.'
    ;;
  claude)
    # The public native route currently does not validate this placeholder key.
    # Override TOKENLABS_API_KEY when the gateway requires a real credential.
    env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL="$base_url" \
      ANTHROPIC_API_KEY="${TOKENLABS_API_KEY:-tokenlabs-smoke-test}" \
      timeout 180 claude --bare --setting-sources '' --strict-mcp-config \
      --tools '' --no-session-persistence --model "$model" \
      --output-format json -p 'Reply with exactly OK.'
    ;;
  *) echo 'Unknown harness' >&2; exit 2 ;;
esac
