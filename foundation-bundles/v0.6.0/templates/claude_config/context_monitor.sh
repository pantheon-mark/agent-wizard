#!/bin/bash
# Context monitor — surfaces the session's ACTUAL context usage so this system
# can follow its context-integrity protocol on real data instead of guessing,
# AND guards against an idle exit while a build phase is still waiting for the
# operator's acceptance.
#
# Wired as a UserPromptSubmit + Stop hook in .claude/settings.json. It reads the
# session status JSON the status line dumped to /tmp (Claude Code's built-in
# context measurement), prints a short readout, and warns when usage crosses the
# thresholds. Defaults: 65% = wrap-up soon, 80% = start a fresh session before
# any new large work unit. (Your project_instructions.md records this system's
# own pre-flight and mid-execution thresholds.)
#
# Idle-exit guard (Stop event only): if the build ledger shows a phase that has
# been brought into operation but not yet accepted, the session must not go idle
# and strand the operator. On the Stop event the hook blocks the stop ONCE and
# tells the operator exactly what to type. It is loop-safe: when Claude Code is
# already continuing because of a prior block (stop_hook_active is true), the
# guard does nothing, so it cannot wedge the session in a continue loop.
#
# Degrades quietly: if python3, the stdin payload, or a state file is missing or
# malformed, it does nothing for that path and exits cleanly so it never blocks
# a session. A bug in this script must never wedge a session.
proj="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Read the hook stdin payload once (it carries hook_event_name + stop_hook_active).
# Stdin is consumed here; the context readout below does not need it.
hook_input="$(cat 2>/dev/null)"

# --- Idle-exit guard (Stop event only) -------------------------------------
# Decide whether to block this stop because a phase is awaiting acceptance.
# python3 prints the literal token BLOCK on its own line followed by the JSON to
# emit, or prints nothing (allow the stop / not a Stop event / loop-safe no-op /
# any error). Everything degrades to "allow stop".
guard_out="$(printf '%s' "$hook_input" | python3 -c '
import sys, json, os, re

try:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
except Exception:
    sys.exit(0)
if not isinstance(payload, dict):
    sys.exit(0)

# Only the Stop event arms the idle guard.
if payload.get("hook_event_name") != "Stop":
    sys.exit(0)

# Loop-safe: if Claude Code is already continuing because of a prior Stop-hook
# block, do NOT block again (Claude Code overrides a Stop hook after a run of
# consecutive blocks). Allow the stop.
if payload.get("stop_hook_active") is True:
    sys.exit(0)

proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
ledger = os.path.join(proj, "build_progress.md")
try:
    with open(ledger, encoding="utf-8") as f:
        text = f.read()
except Exception:
    sys.exit(0)

# A phase is awaiting the operator only when it has been brought into operation
# (built / technically-reviewed / supervised) but is NOT yet accepted. These
# state words come from the ledger State vocabulary; "not-started" has nothing
# to act on, and "accepted" / "provisionally-accepted" are already closed.
AWAITING = ("built", "technically-reviewed", "supervised")
ACCEPTED = ("accepted", "provisionally-accepted")

pending_phase = None
for line in text.splitlines():
    s = line.strip()
    # Phase rows are markdown table rows: | <phase> | <capability> | <state> | ...
    if not s.startswith("|"):
        continue
    cells = [c.strip() for c in s.strip("|").split("|")]
    if len(cells) < 3:
        continue
    phase, state = cells[0], cells[2].lower()
    # Skip the header / separator rows (non-numeric phase cell).
    if not re.fullmatch(r"\d+", phase):
        continue
    if state in ACCEPTED:
        continue
    if state in AWAITING:
        pending_phase = phase
        break

if pending_phase is None:
    sys.exit(0)

reason = (
    "[WAITING FOR YOU]: Phase " + pending_phase + " is built and waiting for your "
    "acceptance — say \"I accept\" to continue, or tell me what'\''s wrong. "
    "(Type \"what now\" any time for your bearings.)"
)
print("BLOCK")
print(json.dumps({"decision": "block", "reason": reason}))
' 2>/dev/null)"

# If the guard decided to block, emit ONLY the block JSON and exit. The JSON must
# be the sole thing on stdout, so the context-% readout is skipped for this turn.
if [ "${guard_out%%$'\n'*}" = "BLOCK" ]; then
    printf '%s\n' "${guard_out#*$'\n'}"
    exit 0
fi

# --- Context-% readout (unchanged) -----------------------------------------
base="$(basename "$proj")"
status_file="/tmp/${base}_statusline.json"
[ -f "$status_file" ] || exit 0
python3 -c '
import sys, json
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
used = (d.get("context_window") or {}).get("used_percentage")
if used is None:
    sys.exit(0)
used = float(used)
msg = "Context: %.0f%% used (actual)." % used
if used >= 80:
    msg += (" HIGH — finish the current step, save state to disk, then start a"
            " fresh session (/clear) before beginning any new large work unit.")
elif used >= 65:
    msg += " Getting full — do not begin a new large work unit; wrap up and checkpoint soon."
print(msg)
' "$status_file"
