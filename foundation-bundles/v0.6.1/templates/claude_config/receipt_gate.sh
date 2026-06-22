#!/bin/bash
# Pre-write receipt gate — a PreToolUse hook that protects high-risk, irreversible
# external actions (sending email, writing a sheet, payments, deletes, external API
# calls). Before such an action runs, the agent must have written a fresh, valid
# pre-write receipt to agents/handoffs/.prewrite_receipt.json (backup + evidence-bound
# verification + plan + the operator's verbatim approval). This hook checks for that
# receipt and, if it is missing/invalid/expired, forces the operator's approval dialog
# ("ask") instead of letting the action run silently.
#
# Hook contract (Claude Code PreToolUse): reads a JSON event on stdin carrying
# tool_name and tool_input; returns a decision via stdout JSON
#   {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask"|"allow","permissionDecisionReason":"..."}}
# with exit 0. Benign/local actions are ungated (print nothing, exit 0) so the session
# never stalls on reads/edits.
#
# Degrade-safe: the gate never hard-fails a session on its own bug. On any internal
# error it exits 0. The one safety asymmetry: if it has already determined the action
# is high-risk and THEN errors, it fails toward "ask" (never "allow") — a gate bug must
# not silently wave a high-risk write through.

# All logic (stdin JSON parse, payload classification, receipt validation, ISO8601
# expiry math, decision emission) lives in python3 — bash 3.2 has no JSON and the
# date math is not portable. If python3 is unavailable we cannot evaluate the gate;
# degrade safe (ungated, exit 0) rather than blocking every action.
command -v python3 >/dev/null 2>&1 || exit 0

INPUT="$(cat)"

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}" \
python3 - "$INPUT" <<'PY'
import sys, os, json, re

ASK_REASON = ("No fresh pre-write receipt for this high-risk action — run the "
              "high-risk action protective sequence (back up, verify, plan, confirm) "
              "and write the receipt first.")

def emit(decision, reason=None):
    out = {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
    }}
    if reason is not None:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    sys.stdout.write(json.dumps(out))

def ungated():
    # benign/local action: print nothing, let it through
    sys.exit(0)

def ask():
    emit("ask", ASK_REASON)
    sys.exit(0)

def allow():
    emit("allow")
    sys.exit(0)

# --- 1+2. parse the hook event; extract tool_name + the command/input text ---
# Before we know the action is high-risk, an internal error degrades to ungated
# (do not stall the session on our own parse bug for an action we cannot classify).
try:
    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}
except Exception:
    ungated()

tool_name = event.get("tool_name") or ""
tool_input = event.get("tool_input") or {}
if not isinstance(tool_input, dict):
    tool_input = {}

# The text we scan for a high-risk signal: the Bash command if present, else the
# stringified tool_input. The tool_name itself is included so MCP write-tools
# (mcp__*__send/update/create/delete/post) are classified even when their args are benign.
parts = [tool_name]
cmd = tool_input.get("command")
if isinstance(cmd, str):
    parts.append(cmd)
try:
    parts.append(json.dumps(tool_input))
except Exception:
    parts.append(str(tool_input))
payload = "\n".join(parts)

# --- 3. PAYLOAD FILTER: high-risk pattern match (case-insensitive) ---
# Matches: external transfer/CLI tools, destructive fs ops, mail transport, and MCP
# write verbs. Benign reads/local edits (ls, cat, grep, Read/Edit/Write of local files)
# do not match and pass freely so the session does not stall.
HIGH_RISK = re.compile(
    r"(curl|wget|gcloud|aws |gh |rm |sendmail|smtp|"
    r"mcp__.*__(update|send|create|delete|post)|"
    r"\bDELETE\b|\bdrop\s+table\b)",
    re.IGNORECASE,
)
if not HIGH_RISK.search(payload):
    ungated()

# --- 4. high-risk: validate the receipt. From here, an internal error fails to "ask". ---
try:
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    receipt_path = os.path.join(proj, "agents", "handoffs", ".prewrite_receipt.json")

    if not os.path.isfile(receipt_path):
        ask()

    try:
        with open(receipt_path, "r", encoding="utf-8") as fh:
            receipt = json.load(fh)
    except Exception:
        ask()  # unparseable receipt == invalid == no receipt

    if not isinstance(receipt, dict):
        ask()

    if receipt.get("schema") != "prewrite-receipt-v1":
        ask()

    required = ("schema", "action_class", "target_id", "operation", "backup_ref",
                "verifications", "operator_confirmation", "created_at",
                "expires_after_seconds")
    for field in required:
        if field not in receipt:
            ask()

    # --- expiry: created_at + expires_after_seconds > now (ISO8601 UTC) ---
    from datetime import datetime, timezone
    raw = receipt.get("created_at")
    if not isinstance(raw, str):
        ask()
    s = raw.strip()
    # normalise a trailing 'Z' to an explicit +00:00 offset for fromisoformat
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        created = datetime.fromisoformat(s)
    except Exception:
        ask()  # unparseable timestamp == invalid
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    try:
        ttl = float(receipt.get("expires_after_seconds"))
    except Exception:
        ask()

    now = datetime.now(timezone.utc)
    age = (now - created).total_seconds()
    if age >= ttl:
        ask()  # expired

    # valid, fresh receipt for this high-risk action
    allow()
except SystemExit:
    raise
except Exception:
    # gate bug on an action we have ALREADY classified high-risk: fail toward asking,
    # never toward allowing.
    ask()
PY

# python3 itself failing to run (not a hook-decision exit) must not block the session.
exit 0
