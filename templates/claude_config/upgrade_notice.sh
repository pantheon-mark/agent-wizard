#!/bin/bash
# SessionStart upgrade notice — quietly checks whether a newer version of this
# system's bundle is available and, if so, prints a plain-language heads-up with
# instructions for how to review and decide. It NEVER changes any file, NEVER
# blocks the session, and NEVER executes fetched content (JSON parsing only).
#
# Wired as a SessionStart hook in .claude/settings.json so it runs once at the
# start of every operator session.
#
# How the check works:
#   1. Reads the local bundle version from .wizard/manifest.json.
#   2. Fetches the public registry JSON (short timeout) to find the latest available.
#   3. If a newer version exists: prints a plain-language notice with the review command.
#   4. If current, if offline, or if anything goes wrong: exits 0 silently.
#
# Test seam: set UPGRADE_NOTICE_REGISTRY_URL to override the default registry URL.
# This lets tests point at a local file:// path or an unreachable address without
# touching the real network.
#
# Note on WIZARD_HOME: the review command below uses $WIZARD_HOME (defaulting to
# "$HOME/agent-wizard") to locate the wizard distribution. If your wizard is
# installed elsewhere, set WIZARD_HOME in your shell environment before starting
# a session. Portable machinery-location resolution (auto-detecting the wizard
# install path) is a documented follow-on improvement.

# Fail-open: any unhandled error exits 0 — a bug in this script must never block
# a session.
set -e
trap 'exit 0' ERR

WIZARD_HOME="${WIZARD_HOME:-$HOME/agent-wizard}"

# Default public registry URL — overridable via env for testing.
_REGISTRY_URL="${UPGRADE_NOTICE_REGISTRY_URL:-https://raw.githubusercontent.com/pantheon-mark/agent-wizard/main/registry/foundation-bundles.json}"

# python3 is required for JSON parsing and (optionally) network fetch.
# If unavailable, exit silently.
command -v python3 >/dev/null 2>&1 || exit 0

# All logic lives in Python for portability (bash JSON parsing is fragile).
python3 - "$_REGISTRY_URL" "$WIZARD_HOME" <<'PY' 2>/dev/null || exit 0
import sys
import os
import json

registry_url = sys.argv[1] if len(sys.argv) > 1 else ""
wizard_home = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.expanduser("~"), "agent-wizard")

# --- 1. Read local bundle version ---
manifest_path = os.path.join(os.getcwd(), ".wizard", "manifest.json")
try:
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
except Exception:
    sys.exit(0)

local_version = manifest.get("foundation_bundle_version")
if not local_version or not isinstance(local_version, str):
    sys.exit(0)

# --- 2. Fetch the registry ---
registry_text = None

# Try file:// first (test seam and offline-file scenario).
if registry_url.startswith("file://"):
    file_path = registry_url[len("file://"):]
    try:
        with open(file_path, encoding="utf-8") as fh:
            registry_text = fh.read()
    except Exception:
        sys.exit(0)
else:
    # Try curl first, then fall back to Python urllib — both with a short timeout.
    import subprocess
    import shutil
    fetched = False

    if shutil.which("curl"):
        try:
            result = subprocess.run(
                ["curl", "--max-time", "6", "-fsS", registry_url],
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0 and result.stdout.strip():
                registry_text = result.stdout
                fetched = True
        except Exception:
            pass

    if not fetched:
        try:
            import urllib.request
            req = urllib.request.Request(registry_url, headers={"User-Agent": "wizard-upgrade-notice/1"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                registry_text = resp.read().decode("utf-8", errors="replace")
        except Exception:
            sys.exit(0)

if not registry_text:
    sys.exit(0)

# --- 3. Parse registry and find latest version ---
try:
    registry = json.loads(registry_text)
except Exception:
    sys.exit(0)

bundles = registry.get("bundles")
if not isinstance(bundles, list) or not bundles:
    sys.exit(0)

# Extract version strings; skip malformed entries.
versions = []
for b in bundles:
    if not isinstance(b, dict):
        continue
    # The registry's bundle entries key the version as "foundation_bundle_version"
    # (the live public-registry shape); tolerate a bare "version" as a fallback.
    v = b.get("foundation_bundle_version") or b.get("version")
    if isinstance(v, str) and v:
        versions.append(v)

if not versions:
    sys.exit(0)

# Semver comparison: strip leading 'v', parse as tuple of ints.
def _semver(v):
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except Exception:
        return (0,)

latest_version = max(versions, key=_semver)
local_ver_tuple = _semver(local_version)
latest_ver_tuple = _semver(latest_version)

# --- 4. Print notice only if newer available ---
if latest_ver_tuple <= local_ver_tuple:
    sys.exit(0)

review_cmd = (
    f'python3 "{wizard_home}/scripts/wizard_upgrade.py" upgrade-plan '
    f'--to {latest_version} '
    f'--manifest-path .wizard/manifest.json '
    f'--registry-path "{wizard_home}/registry/foundation-bundles.json"'
)

# IMPORTANT: this text is printed by a SessionStart hook, so it lands in the
# assistant's session-start context — NOT in a message the operator can see. The
# operator only learns about the update if the assistant RELAYS it. So the notice is
# written as an INSTRUCTION TO THE ASSISTANT, not as operator-facing prose. It tells
# the assistant to relay the news in plain language and to withhold the paths/command
# (those are for the assistant to run). This is what keeps the notice from being
# silently dropped under a "greet plainly / show no internal details (file names)"
# orientation — the earlier operator-prose version was suppressed exactly that way.
print("")
print("[SYSTEM-UPDATE NOTICE — instruction for the assistant; the operator cannot see this]")
print("")
print(f"A newer version of this system is available ({latest_version}). This message was")
print("delivered into your session-start context, so the operator has NOT seen it. Treat an")
print("available update as something needing the operator's attention.")
print("")
print("DO THIS as part of your greeting: tell the operator, in plain, non-technical language,")
print("that an update to their system is available and that it improves how their system runs")
print("(its operating guidelines, skills, and safety routines). Then offer them a choice —")
print("(a) you can show them exactly what would change, or (b) you can apply it — and make")
print("clear that nothing changes until they say so. The operator is always in control.")
print("")
print("DO NOT show the operator the file paths or the command below — those are for YOU to")
print("run on their behalf if they ask to proceed. Keep your message to them plain and free of")
print("technical detail (no file names, no commands).")
print("")
print("If the operator asks to see what would change, run this command yourself and summarize")
print("the result for them in plain language:")
print("")
print(f"  {review_cmd}")
print("")

PY

# If python3 itself exited non-zero (not a sys.exit(0)), the trap exits 0.
exit 0
