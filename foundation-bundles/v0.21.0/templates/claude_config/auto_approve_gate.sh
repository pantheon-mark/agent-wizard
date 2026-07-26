#!/bin/bash
# Read-only auto-approve gate — a PreToolUse hook (Cut 1.1 Cluster C / Task C2,
# F-78) that lets a non-technical operator run the emitted verify/scan/self-QA
# commands WITHOUT hitting Claude Code's auto-mode permission prompt, while a
# live-write command still always prompts.
#
# WHY THIS EXISTS: a self-QA / read-only-scan command (e.g. a capability's
# invariant check, or its read-only bulk-review scanner) is blocked by the
# auto-mode classifier the same way any Bash command is — nothing
# distinguished "this only reads and prints a report" from "this could
# mutate something". `permissions.allow` in
# settings.json (a static, coarse allowlist keyed to the SAME command manifest
# this hook reads) is the primary fix; this hook is the dynamic, belt-and-
# suspenders backstop that re-derives eligibility at the moment of the call,
# from the one canonical source (`command_manifest.py`), rather than trusting
# a static list alone.
#
# THE ONE THING THIS HOOK IS ALLOWED TO DO: emit {"permissionDecision":"allow"}
# for a Bash command that is ENTIRELY (not merely "starts with") an
# allowlist-eligible read-only command per the manifest. It NEVER emits "ask"
# or "deny" itself — those are settings.json's job (permissions.ask on the
# live-write prefixes, permissions.deny on the self-protect rules). This hook
# only ever adds an "allow" for a command it can positively verify; for
# everything else (a live-write command, an unrecognized command, a
# non-Bash tool, a malformed hook event, or any failure to read the manifest)
# it prints NOTHING and exits 0 — deferring to whatever the rest of the
# permission machinery (settings.json ask/deny, the harness default) decides.
# Printing nothing is not "safe" by itself; it is safe BECAUSE it never grants
# anything — the actual safety property is "this hook cannot cause an action
# to run that would not otherwise have been allowed".
#
# SAFETY INVARIANTS (load-bearing; tested in test_allowlist_gate.py):
#   1. FAIL CLOSED on uncertainty. An unparseable hook event, a non-Bash tool,
#      a missing/unimportable/erroring command_manifest module, or a command
#      that does not exactly match an eligible prefix — ALL of these defer
#      (print nothing, exit 0). This hook NEVER auto-approves on uncertainty;
#      the only path to "allow" is a positive, fully-verified match.
#   2. CANNOT approve a live-write. is_allowlist_eligible() (via
#      manifest_as_dicts()'s "allowlist_eligible" field) is re-derived FRESH
#      from the manifest on every invocation — this hook holds no second,
#      independently-maintained list of "safe" commands. Per Q4 (the
#      Cluster C plan), a matching `permissions.ask` rule in settings.json
#      would still force a prompt even if this hook mistakenly said "allow"
#      (deny -> ask -> allow precedence) — but this hook does NOT rely on
#      that as its only defense: it independently refuses to approve any
#      command that is not itself manifest-eligible, belt-and-suspenders.
#   3. WHOLE-COMMAND match, not prefix-substring match. A command must be a
#      SINGLE shell segment (no ;, &&, ||, |, <, >, subshell parens) whose
#      leading tokens equal an eligible manifest command_prefix's tokens.
#      "python3 agents/lib/external_write/scan.py; rm -rf /" is NOT approved
#      even though it starts with an eligible prefix textually — a command
#      that CHAINS anything after/around the eligible invocation is refused,
#      because this hook cannot verify the appended part is safe.
#   4. SAFE-CHARACTER ALLOWLIST on the RAW command string (an adversarial
#      review proved this invariant necessary, Cut 1.1 C2 review, Critical):
#      a denylist of shell metacharacters is non-exhaustive by construction,
#      and shlex tokenization is not a safety boundary on its own -- shlex
#      treats a newline as ordinary whitespace (so "<eligible prefix>\n<any
#      command>" tokenizes as if the second command were just more args) and
#      a backtick is not a shlex-special char at all (so `` `cmd` `` command
#      substitution is invisible to a chaining check built only on shlex
#      tokens). Both let a live write ride through with NO operator prompt.
#      So this hook checks the ENTIRE raw command string, before/independent
#      of shlex, against a conservative safe-character allowlist (ASCII
#      letters, digits, space/tab, and `_ . / = : - ,`) and DEFERS the moment
#      any other character is present -- newline, CR, backtick, `$`, `|`,
#      `&`, `;`, redirects, parens/braces/brackets, quotes, `\`, `*`, `?`,
#      `~`, `!`, `#`, or anything else not on the safe list. An unusual but
#      legitimate read-only command that needs a character outside this set
#      simply defers to a normal operator prompt -- that is an acceptable
#      false-negative (the operator sees one extra prompt); a false-positive
#      "allow" on a smuggled live write is not acceptable at any rate, so
#      this list is kept deliberately narrow and is not to be widened to
#      accommodate a specific command without equal scrutiny of what else it
#      would newly permit.
#
# Hook contract (Claude Code PreToolUse): reads a JSON event on stdin carrying
# tool_name and tool_input; may print a decision JSON
#   {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"..."}}
# with exit 0, or print nothing (defer) with exit 0.
#
# Degrade-safe: on ANY internal error this hook exits 0 having printed
# nothing — a bug here must never wedge a session, and (per invariant #1)
# must never accidentally grant an allow it did not positively earn.

command -v python3 >/dev/null 2>&1 || exit 0

INPUT="$(cat)"

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}" \
python3 - "$INPUT" <<'PY'
import json
import os
import shlex
import sys


def defer():
    # No decision printed -> the rest of the permission machinery (settings.json
    # ask/deny, or the harness default) decides. This is the ONLY way this hook
    # ever handles uncertainty or a non-eligible command.
    sys.exit(0)


def allow(reason):
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _is_operator_token(tok):
    # A token made solely of shell operator punctuation acts as a segment
    # separator (;, &&, ||, |, <, >, (, )). Any such token present means the
    # command is not a single, self-contained invocation.
    return bool(tok) and all(c in ";|&<>()" for c in tok)


# Conservative SAFE-CHARACTER allowlist (invariant #4 above). Anything not in
# this set defers -- this is checked against the RAW command string, before
# and independent of shlex, precisely because shlex tokenization is not
# itself a safety boundary (see invariant #4). Kept deliberately narrow;
# widen only with the same scrutiny as adding a new eligible command.
_SAFE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " \t_./=:-,"
)


def _is_safe_char_only(s):
    return all(c in _SAFE_CHARS for c in s)


# --- 1. parse the hook event -----------------------------------------------
try:
    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}
except Exception:
    defer()

if not isinstance(event, dict):
    defer()

# --- 2. only Bash commands are ever eligible for auto-approval here --------
if event.get("tool_name") != "Bash":
    defer()

tool_input = event.get("tool_input")
if not isinstance(tool_input, dict):
    defer()

command = tool_input.get("command")
if not isinstance(command, str) or not command.strip():
    defer()

# --- 3. SAFE-CHARACTER ALLOWLIST on the raw command string (invariant #4) --
# Checked on the untouched raw string, before/independent of shlex tokenizing,
# so nothing that shlex would treat as inert (a newline) or wouldn't even see
# as an operator (a backtick) can ride onto an eligible prefix. Any character
# outside the conservative safe set -> cannot positively verify the whole
# string is a single clean invocation -> defer. This check runs regardless of
# whether the command textually resembles an eligible prefix, because the
# smuggled part is exactly what makes a textual-prefix-only check insufficient.
if not _is_safe_char_only(command):
    defer()

# --- 4. load the command manifest from THIS project's own runtime copy ----
# The manifest is the single source of truth for eligibility (command_manifest.py
# docstring); this hook re-derives eligibility fresh on every call instead of
# holding any list of its own. Any failure to locate/import/read it is treated
# exactly like an unrecognized command: defer, never allow.
proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
manifest_dir = os.path.join(proj, "agents", "lib", "external_write")

eligible_prefixes = None
try:
    if manifest_dir not in sys.path:
        sys.path.insert(0, manifest_dir)
    import command_manifest as _cm  # type: ignore  # noqa: E402

    eligible_prefixes = tuple(
        entry["command_prefix"]
        for entry in _cm.manifest_as_dicts()
        if entry.get("allowlist_eligible") is True
    )
except Exception:
    defer()  # manifest missing / unimportable / malformed -> fail closed

if not eligible_prefixes:
    defer()

# --- 5. the command must be a SINGLE shell segment (no chaining) -----------
try:
    lex = shlex.shlex(command, posix=True, punctuation_chars=";|&<>()")
    lex.whitespace_split = True
    tokens = list(lex)
except ValueError:
    defer()  # unbalanced quotes etc. -> cannot verify safety -> defer

if not tokens:
    defer()

if any(_is_operator_token(t) for t in tokens):
    defer()  # command chaining/redirection present -> refuse to approve

# --- 6. the WHOLE command's leading tokens must equal an eligible prefix ---
for prefix in eligible_prefixes:
    prefix_tokens = prefix.split()
    if not prefix_tokens:
        continue
    if tokens[: len(prefix_tokens)] == prefix_tokens:
        allow(
            "read-only command manifest-eligible (allowlist_eligible=True); "
            "auto-approved so the operator is not blocked on a safe check."
        )

defer()
PY

# python3 itself failing to run (not a hook-decision exit) must not block the session.
exit 0
