#!/bin/bash
# Status line for this system's Claude Code sessions.
#
# Prints a one-line status — "<model> | ctx: N%" — and also writes the raw
# session status JSON to a temp file so the context monitor
# (.claude/context_monitor.sh) can read the ACTUAL context-window usage. The
# context percentage comes from Claude Code's built-in session status data, so
# it is a real measurement, not an estimate. Uses python3 (present on macOS);
# if anything is missing it degrades quietly rather than erroring.
input=$(cat)
printf '%s' "$input" | python3 -c '
import sys, json, os
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    print("Claude")
    sys.exit(0)
ws = d.get("workspace") or {}
cwd = ws.get("current_dir") or d.get("cwd") or ""
base = os.path.basename(cwd.rstrip("/")) if cwd else ""
if base:
    try:
        with open("/tmp/%s_statusline.json" % base, "w") as fh:
            fh.write(raw)
    except Exception:
        pass
model = (d.get("model") or {}).get("display_name") or "Claude"
used = (d.get("context_window") or {}).get("used_percentage")
if used is None:
    print(model)
else:
    print("%s | ctx: %.0f%%" % (model, float(used)))
'
