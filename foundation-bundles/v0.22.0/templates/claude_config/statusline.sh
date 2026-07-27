#!/bin/bash
# Status line for this system's Claude Code sessions.
#
# Prints a one-line status —
#   "<model> | ctx: N% | 5h: N% resets HH:MM | 7d: N% resets Mon DD"
# — and also writes the raw session status JSON to a temp file so the context
# monitor (.claude/context_monitor.sh) can read the ACTUAL context-window usage.
# The context percentage and the plan usage limits come from Claude Code's
# built-in session status data, so they are real measurements, not estimates.
# Uses python3 (present on macOS); if anything is missing it degrades quietly
# rather than erroring.
input=$(cat)
printf '%s' "$input" | python3 -c '
import sys, json, os, datetime
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    print("Claude")
    sys.exit(0)

# Dump the raw status JSON (keyed by project basename) for the context monitor.
ws = d.get("workspace") or {}
cwd = ws.get("current_dir") or d.get("cwd") or ""
base = os.path.basename(cwd.rstrip("/")) if cwd else ""
if base:
    try:
        with open("/tmp/%s_statusline.json" % base, "w") as fh:
            fh.write(raw)
    except Exception:
        pass

parts = [(d.get("model") or {}).get("display_name") or "Claude"]

used = (d.get("context_window") or {}).get("used_percentage")
if used is not None:
    parts.append("ctx: %.0f%%" % float(used))

def limit(window, label, datefmt):
    w = (d.get("rate_limits") or {}).get(window) or {}
    pct = w.get("used_percentage")
    if pct is None:
        return None
    s = "%s: %.0f%%" % (label, float(pct))
    resets = w.get("resets_at")
    if resets:
        try:
            s += " resets " + datetime.datetime.fromtimestamp(float(resets)).strftime(datefmt)
        except Exception:
            pass
    return s

for s in (limit("five_hour", "5h", "%H:%M"), limit("seven_day", "7d", "%b %d")):
    if s:
        parts.append(s)

print(" | ".join(parts))
'
