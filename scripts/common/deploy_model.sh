#!/usr/bin/env bash
# Deploy (or tear down) one model and make the gateway follow it, in one command.
#
# The gateway route is a DERIVED artifact here, never hand-edited. That is the
# whole point: editing deploy/models/<model>/<framework>/*.yaml and running this
# is sufficient to get a model live on api.tokenlabs.run, and tearing it down is
# sufficient to get it un-advertised. There is no separate route file to forget,
# which is the failure mode that left a Nemotron llm-d model advertised on
# www.tokenlabs.run for 13 days with no pods behind it.
#
# usage:
#   deploy_model.sh <model-dir> <llm-d|dynamo> [aggregated|disaggregated]
#   deploy_model.sh --teardown <model-dir> <llm-d|dynamo> [mode]
#
# examples:
#   scripts/common/deploy_model.sh deploy/models/qwen3-30b-a3b-instruct-2507-fp8 llm-d aggregated
#   scripts/common/deploy_model.sh deploy/models/nemotron-3.5-lightning-30b-a3b-nvfp4 dynamo aggregated
#   scripts/common/deploy_model.sh --teardown deploy/models/qwen3-30b-a3b-instruct-2507-fp8 llm-d aggregated
set -euo pipefail

NAMESPACE="${NAMESPACE:-token-labs}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEN="$REPO_ROOT/scripts/common/gen_aigwroute.py"
API_BASE="${API_BASE:-https://api.tokenlabs.run}"

TEARDOWN=0
if [[ "${1:-}" == "--teardown" ]]; then TEARDOWN=1; shift; fi

MODEL_DIR="${1:?usage: deploy_model.sh [--teardown] <model-dir> <llm-d|dynamo> [mode]}"
FRAMEWORK="${2:?missing framework: llm-d or dynamo}"
MODE="${3:-aggregated}"

[[ "$MODEL_DIR" = /* ]] || MODEL_DIR="$REPO_ROOT/$MODEL_DIR"
[[ -d "$MODEL_DIR/$FRAMEWORK" ]] || { echo "no such directory: $MODEL_DIR/$FRAMEWORK" >&2; exit 1; }

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- deploy step
# Each framework has its own mechanism and neither knows about the gateway.
if [[ $TEARDOWN -eq 1 ]]; then
  step "Tearing down $FRAMEWORK / $MODE"
  case "$FRAMEWORK" in
    llm-d)  (cd "$MODEL_DIR/llm-d" && MODE="$MODE" NAMESPACE="$NAMESPACE" helmfile destroy) ;;
    dynamo) kubectl delete -f "$MODEL_DIR/dynamo/$MODE.yaml" --ignore-not-found ;;
    *) echo "unknown framework: $FRAMEWORK" >&2; exit 1 ;;
  esac
else
  step "Deploying $FRAMEWORK / $MODE from $MODEL_DIR"
  case "$FRAMEWORK" in
    llm-d)  (cd "$MODEL_DIR/llm-d" && MODE="$MODE" NAMESPACE="$NAMESPACE" helmfile apply) ;;
    dynamo) kubectl apply -f "$MODEL_DIR/dynamo/$MODE.yaml" ;;
    *) echo "unknown framework: $FRAMEWORK" >&2; exit 1 ;;
  esac
fi

# The generator reads live workloads, so give the API server a moment to
# register the objects the step above just created or removed.
sleep 5

# ------------------------------------------------------------- gateway follows
# --apply also prunes the Service/Backend/AIServiceBackend of any model that is
# no longer deployed, so teardown de-advertises without a second command.
# --allow-empty is passed only on teardown: an empty result is expected there,
# but during a deploy it means discovery failed and must be a hard error.
step "Regenerating gateway route from live cluster state"
GEN_ARGS=(-n "$NAMESPACE" --apply)
[[ $TEARDOWN -eq 1 ]] && GEN_ARGS+=(--allow-empty)
python3 "$GEN" "${GEN_ARGS[@]}"

if [[ $TEARDOWN -eq 1 ]]; then
  step "Done — model torn down and un-advertised"
  echo "Commit the regenerated route so the repo matches the cluster:"
  echo "  git add -A && git commit -m 'teardown $(basename "$MODEL_DIR") ($FRAMEWORK/$MODE)'"
  exit 0
fi

# ------------------------------------------------------------------- readiness
# Weights can take tens of minutes on a cache miss. The route is already in
# place (is_servable gates on intent, not readiness), so the model 503s rather
# than 404s until this finishes -- an honest "not yet" instead of "no such model".
step "Waiting for workload to become ready (this can take 30+ min on a cache miss)"
case "$FRAMEWORK" in
  llm-d)
    kubectl wait --for=condition=Available --timeout=60m \
      -n "$NAMESPACE" deploy -l "llm-d.ai/role=decode" || true
    ;;
  dynamo)
    kubectl wait --for=condition=Ready --timeout=60m \
      -n "$NAMESPACE" dynamographdeployment --all || true
    ;;
esac

# ------------------------------------------------------------------ validation
# Prove the whole path -- gateway, route, backend, engine -- not just that pods
# are up. A 503 here means deployed-but-still-loading; re-run to re-check.
step "Validating through the gateway"
python3 "$GEN" -n "$NAMESPACE" --stdout \
  | grep -oP '(?<=^              value: ).*' \
  | while read -r model; do
      code=$(curl -s -o /dev/null -m 120 -w '%{http_code}' \
        "$API_BASE/v1/chat/completions" -H 'Content-Type: application/json' \
        -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":256}")
      case "$code" in
        200) printf '  \033[32mOK\033[0m    %s\n' "$model" ;;
        503) printf '  \033[33mLOADING\033[0m %s (routed, engine not ready yet)\n' "$model" ;;
        *)   printf '  \033[31mHTTP %s\033[0m %s\n' "$code" "$model" ;;
      esac
    done

step "Done"
echo "Commit the regenerated route so the repo matches the cluster:"
echo "  git add -A && git commit -m 'deploy $(basename "$MODEL_DIR") ($FRAMEWORK/$MODE)'"
