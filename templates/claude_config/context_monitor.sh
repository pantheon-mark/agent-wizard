#!/bin/bash
# Context monitor — surfaces the session's ACTUAL context usage so this system
# can follow its context-integrity protocol on real data instead of guessing.
#
# Wired as a UserPromptSubmit + Stop hook in .claude/settings.json. It reads the
# session status JSON the status line dumped to /tmp (Claude Code's built-in
# context measurement), prints a short readout, and warns when usage crosses the
# thresholds. Defaults: 65% = wrap-up soon, 80% = start a fresh session before
# any new large work unit. (Your project_instructions.md records this system's
# own pre-flight and mid-execution thresholds.)
#
# Degrades quietly: if python3 or the status file is missing, it prints nothing
# and exits cleanly so it never blocks a session.
proj="${CLAUDE_PROJECT_DIR:-$(pwd)}"
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
