#!/usr/bin/env bash
# Wire Claude Code (CLI + desktop app) into the homelab agentmemory server.
# Idempotent: re-run after upgrading @agentmemory/agentmemory to refresh script paths.
set -euo pipefail

AGENTMEMORY_URL="${AGENTMEMORY_URL:-http://controller.taila28ba1.ts.net:31111}"
AGENTMEMORY_SECRET="${AGENTMEMORY_SECRET:?export AGENTMEMORY_SECRET=<token> before running}"

echo "==> installing @agentmemory/agentmemory globally"
npm i -g @agentmemory/agentmemory@latest >/dev/null

SCRIPTS="$(npm root -g)/@agentmemory/agentmemory/plugin/scripts"
[ -d "$SCRIPTS" ] || { echo "plugin scripts not found at $SCRIPTS" >&2; exit 1; }
echo "==> plugin scripts: $SCRIPTS"

echo "==> health check"
curl -fsS -H "Authorization: Bearer $AGENTMEMORY_SECRET" \
  "$AGENTMEMORY_URL/agentmemory/health" >/dev/null && echo "    server OK"

AGENTMEMORY_URL="$AGENTMEMORY_URL" AGENTMEMORY_SECRET="$AGENTMEMORY_SECRET" SCRIPTS="$SCRIPTS" \
python3 - <<'PY'
import json, os

URL     = os.environ["AGENTMEMORY_URL"]
SECRET  = os.environ["AGENTMEMORY_SECRET"]
S       = os.environ["SCRIPTS"]

EVENTS = [
    ("SessionStart",       "session-start.mjs",      None),
    ("UserPromptSubmit",   "prompt-submit.mjs",      None),
    ("PreToolUse",         "pre-tool-use.mjs",       "Edit|Write|Read|Glob|Grep"),
    ("PostToolUse",        "post-tool-use.mjs",      None),
    ("PostToolUseFailure", "post-tool-failure.mjs",  None),
    ("PreCompact",         "pre-compact.mjs",        None),
    ("SubagentStart",      "subagent-start.mjs",     None),
    ("SubagentStop",       "subagent-stop.mjs",      None),
    ("Notification",       "notification.mjs",       None),
    ("TaskCompleted",      "task-completed.mjs",     None),
    ("Stop",               "stop.mjs",               None),
    ("SessionEnd",         "session-end.mjs",        None),
]

def load(p, default):
    try:
        with open(p) as f: return json.load(f)
    except FileNotFoundError:
        return default

def save(p, d, mode=None):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f: json.dump(d, f, indent=2)
    os.replace(tmp, p)
    if mode: os.chmod(p, mode)

# --- MCP: ~/.claude.json (literal values; the desktop app has no shell env) ---
cj = os.path.expanduser("~/.claude.json")
d = load(cj, {})
if os.path.exists(cj):
    import shutil; shutil.copy2(cj, cj + ".bak.agentmemory")
d.setdefault("mcpServers", {})["agentmemory"] = {
    "command": "npx",
    "args": ["-y", "@agentmemory/mcp"],
    "env": {"AGENTMEMORY_URL": URL, "AGENTMEMORY_SECRET": SECRET, "AGENTMEMORY_TOOLS": "all"},
}
save(cj, d, 0o600)
print("    MCP  -> ~/.claude.json")

# --- Hooks + env: ~/.claude/settings.json ---
sp = os.path.expanduser("~/.claude/settings.json")
st = load(sp, {})
if os.path.exists(sp):
    import shutil; shutil.copy2(sp, sp + ".bak.agentmemory")
st.setdefault("env", {}).update({
    "AGENTMEMORY_URL": URL,
    "AGENTMEMORY_SECRET": SECRET,
    "AGENTMEMORY_TOOLS": "all",
    "AGENTMEMORY_INJECT_CONTEXT": "true",
})
hooks = st.setdefault("hooks", {})
for ev, script, matcher in EVENTS:
    cmd = 'node "%s/%s"' % (S, script)
    entry = {"hooks": [{"type": "command", "command": cmd}]}
    if matcher: entry["matcher"] = matcher
    kept = [g for g in hooks.get(ev, [])
            if not any("agentmemory" in h.get("command", "") for h in g.get("hooks", []))]
    kept.append(entry)
    hooks[ev] = kept
save(sp, st)
print("    hooks-> ~/.claude/settings.json (%d events)" % len(EVENTS))
PY

echo "==> smoke test"
CLAUDE_PROJECT_DIR="$PWD" \
AGENTMEMORY_URL="$AGENTMEMORY_URL" AGENTMEMORY_SECRET="$AGENTMEMORY_SECRET" AGENTMEMORY_INJECT_CONTEXT=true \
  bash -c "echo '{\"session_id\":\"connect-smoke\",\"cwd\":\"$PWD\",\"source\":\"startup\"}' | node '$SCRIPTS/session-start.mjs'" >/dev/null \
  && echo "    hook OK"

echo
echo "Done. Restart Claude Code (CLI and the desktop app) to load the MCP server + hooks."
echo "Viewer: http://controller.taila28ba1.ts.net:31113/"
