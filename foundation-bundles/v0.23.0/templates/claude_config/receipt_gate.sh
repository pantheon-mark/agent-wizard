#!/bin/bash
# Pre-write receipt gate — a PreToolUse backstop for high-risk, irreversible
# external actions (sending email, writing a sheet, payments, deletes, external API
# calls). This hook is a backstop, not the primary enforcement mechanism. The
# primary controls are the build-time bypass scanner (which rejects any write path
# that routes around the approved write channel) and the operator acting as approver
# of record. This hook handles the tool-shaped writes it CAN see (MCP write-verbs,
# destructive bash commands); it is blind to interpreter-script runs (python3 x.py)
# and other external-write paths outside its classification scope — those are the
# build-time scanner's domain.
#
# Before such an action runs, the agent must have written a fresh, valid pre-write
# receipt to agents/handoffs/.prewrite_receipt.json (backup + evidence-bound
# verification + plan + the operator's verbatim approval). This hook checks for that
# receipt and, if it is missing/invalid/expired, forces the operator's approval dialog
# ("ask") instead of letting the action run silently — a backstop for cases where the
# receipt was not written before the action was attempted.
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
import sys, os, json, re, shlex

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

# --- 3. CLASSIFY BY ACTION SHAPE (tool + action) — never by scanning the prose
# CONTENT of a local edit. An earlier design stringified the whole tool_input and
# substring-grepped it, so an Edit's new_string text — everyday words like "firm",
# "High", "through" — falsely matched rm/gh/aws and the gate cried wolf on ordinary
# markdown edits, which trains operators to rubber-stamp every prompt. A local file
# write is benign regardless of the words in it. This is command-ENTRYPOINT detection
# under an honest-agent ceiling: a tripwire for an honest-but-fallible agent, NOT an
# evasion-resistant sandbox — deliberate obfuscation (eval, $(...), base64|sh) is
# explicitly out of scope (a project-scope hook is materially-harder + detectable, not
# a root of trust).

# Local/benign tools never perform an irreversible external action -> ungate them
# unconditionally, whatever their content. (Local writes that could disable THIS gate
# itself — .claude/** and settings — are blocked by the SEPARATE permissions.deny rules
# in settings.json, not here. .env is reversible-on-own-machine + a separate secret
# posture.) Documented honest-ceiling gaps NOT detected here: interpreter script runs
# (python x.py / bash x.sh) and package-manager/IaC publishes (npm publish / docker push /
# terraform apply) — the in-prompt high-risk protective sequence is the primary control,
# this hook is the backstop; output redirection (> file) is local + reversible.
LOCAL_BENIGN = {
    "Edit", "Write", "MultiEdit", "Read", "NotebookEdit", "Glob", "Grep",
    "LS", "TodoWrite", "Task", "WebFetch", "WebSearch",
}

# Bash command words that are destructive or outgoing regardless of subcommand.
# Matched CASE-SENSITIVELY against the resolved command word (shell command names are
# case-sensitive — this alone kills the "High"->gh / "firm"->rm class of false match).
COARSE_DANGER = {
    "rm", "rmdir", "shred", "dd", "mkfs", "truncate",
    "curl", "wget", "ssh", "scp", "rsync", "nc", "telnet",
    "sendmail", "mail", "mailx", "mutt", "msmtp", "ssmtp",
}
# Broad multiplexer CLIs whose READ subcommands are common + benign -> gate only when a
# write/mutate verb is present, so `aws s3 ls` / `gh issue list` do NOT over-fire.
MULTIPLEXERS = {"aws", "gh", "gcloud", "az"}
MULTIPLEXER_WRITE_VERBS = {
    "rm", "cp", "mv", "sync", "put", "push", "apply", "create", "update",
    "delete", "remove", "set", "deploy", "add", "grant", "invite", "send",
    "publish", "upload",
}
SIMPLE_WRAPPERS = {"sudo", "env", "command", "time", "nohup"}  # look THROUGH to the real command
GIT_PUSH_DESTRUCTIVE = {"--force", "-f", "--force-with-lease", "--delete", "--mirror"}

# MCP tools are classified by the trailing verb of tool_name (args may be benign).
# Write verb -> gate; read verb -> pass; UNKNOWN verb on an external connector -> gate
# (the MCP surface is exactly where irreversible external writes happen).
MCP_WRITE_VERBS = {
    "send", "update", "create", "delete", "post", "write", "append", "remove",
    "insert", "upsert", "upload", "publish", "deploy", "invite", "grant",
    "share", "replace", "move", "rename", "copy", "restore", "execute", "run",
    "mutate",
}
MCP_READ_VERBS = {
    "get", "list", "read", "search", "fetch", "query", "download", "preview",
    "validate", "check", "inspect", "describe",
}

def _is_op(tok):
    # a token consisting solely of shell operator punctuation acts as a segment separator
    return bool(tok) and all(c in ";|&<>()" for c in tok)

def _tokenize(command):
    # Quote-aware tokenization that ALSO emits shell operators as their own tokens
    # (punctuation_chars). So `echo "a ; rm b"` keeps `; rm b` INSIDE the quoted string
    # (no false rm) while `echo a ; rm b` splits into segments (the real rm is caught).
    lex = shlex.shlex(command, posix=True, punctuation_chars=";|&<>()")
    lex.whitespace_split = True
    return list(lex)

def _segment_high_risk(seg):
    t = list(seg)
    while t and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t[0]):   # strip leading VAR=val
        t.pop(0)
    while t and os.path.basename(t[0]) in SIMPLE_WRAPPERS:     # look through sudo/env/...
        t.pop(0)
        while t and t[0].startswith("-"):
            t.pop(0)
    if not t:
        return False
    lead = os.path.basename(t[0])
    bases = [os.path.basename(x) for x in t]
    if lead in COARSE_DANGER:
        return True
    if lead == "xargs":                       # xargs runs a command taken from its args
        return any(b in COARSE_DANGER for b in bases[1:])
    if lead in MULTIPLEXERS:
        return any(b in MULTIPLEXER_WRITE_VERBS for b in bases[1:])
    if lead == "find":
        if "-delete" in t:
            return True
        for j, x in enumerate(t):
            if x in ("-exec", "-execdir") and j + 1 < len(t):
                if os.path.basename(t[j + 1]) in COARSE_DANGER:
                    return True
        return False
    if lead == "git":
        return "push" in bases and any(x in GIT_PUSH_DESTRUCTIVE for x in t)
    return False

def _bash_high_risk(command):
    if not isinstance(command, str) or not command.strip():
        return False
    try:
        tokens = _tokenize(command)
    except ValueError:
        return False        # unbalanced quotes etc. — cannot classify -> ungated (honest ceiling)
    segments, cur = [], []
    for tok in tokens:
        if _is_op(tok):
            if cur:
                segments.append(cur); cur = []
        else:
            cur.append(tok)
    if cur:
        segments.append(cur)
    return any(_segment_high_risk(s) for s in segments)

def _mcp_high_risk(name):
    parts = name.split("__")
    if len(parts) < 3:
        return True                       # malformed mcp__ name -> gate (be safe)
    verb = parts[-1].split("_")[0].lower()
    if verb in MCP_READ_VERBS:
        return False
    return True                           # write verb OR unknown verb -> gate

# Dispatch — the ONLY thing that decides high-risk (receipt validation below is
# unchanged). An unrecognised non-MCP tool is ungated (coverage-limited by design).
if tool_name in LOCAL_BENIGN:
    ungated()
elif tool_name.startswith("mcp__"):
    if not _mcp_high_risk(tool_name):
        ungated()
elif tool_name == "Bash":
    if not _bash_high_risk(tool_input.get("command")):
        ungated()
else:
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
