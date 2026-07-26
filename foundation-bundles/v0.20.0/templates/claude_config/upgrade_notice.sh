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
#   2. Fetches the AUTHORITATIVE remote registry via the ONE shared routine that
#      `wizard upgrade-check` also uses (registry_fetch.fetch_remote_registry), so
#      the notice and the check can never diverge on SOURCE again. The source is
#      resolved from the origin-pinned .wizard/update-source.json (no hardcoded URL).
#   3. If a newer version exists: prints a declarative heads-up the model relays.
#   4. If current, if offline, or if anything goes wrong: exits 0 silently.
#
# Test / advanced seam: the shared routine reads WIZARD_UPDATE_REGISTRY_URL to point
# at a file:// path or a local server. The legacy UPGRADE_NOTICE_REGISTRY_URL seam is
# still honored (mapped onto the canonical one) for back-compat with already-emitted
# hooks. PRODUCTION sets neither — the origin pin is the source of truth.
#
# Note on WIZARD_HOME: $WIZARD_HOME (defaulting to "$HOME/agent-wizard") locates the
# installed wizard toolkit. The shared library is imported from $WIZARD_HOME/scripts/lib
# — the same layout the operator's public clone and the `wizard` shim expose. If your
# wizard is installed elsewhere, set WIZARD_HOME before starting a session.

# Fail-open: any unhandled error exits 0 — a bug in this script must never block
# a session.
set -e
trap 'exit 0' ERR

WIZARD_HOME="${WIZARD_HOME:-$HOME/agent-wizard}"

# Reconcile the override seam: the shared registry_fetch routine reads
# WIZARD_UPDATE_REGISTRY_URL. Map the notice's legacy UPGRADE_NOTICE_REGISTRY_URL onto it
# ONLY when the canonical one is unset, so the canonical shared seam wins when both are set.
if [ -z "${WIZARD_UPDATE_REGISTRY_URL:-}" ] && [ -n "${UPGRADE_NOTICE_REGISTRY_URL:-}" ]; then
  export WIZARD_UPDATE_REGISTRY_URL="$UPGRADE_NOTICE_REGISTRY_URL"
fi

# python3 is required for JSON parsing and (optionally) network fetch.
# If unavailable, exit silently.
command -v python3 >/dev/null 2>&1 || exit 0

# All logic lives in Python for portability (bash JSON parsing is fragile).
python3 - "$WIZARD_HOME" <<'PY' 2>/dev/null || exit 0
import sys
import os
import json

# FAIL-OPEN at the PYTHON boundary (not just bash): a notice must never nag or block.
# ANY error in this hook — INCLUDING a bug in the shared library it imports — exits 0
# silently. sys.exit(0) raises SystemExit (not an Exception), so it propagates past this
# guard; only genuine errors are swallowed into a silent exit.
try:
    wizard_home = (
        sys.argv[1] if len(sys.argv) > 1
        else os.path.join(os.path.expanduser("~"), "agent-wizard")
    )

    # --- 1. Read local bundle version (the notice's own concern) ---
    manifest_path = os.path.join(os.getcwd(), ".wizard", "manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception:
        sys.exit(0)

    local_version = manifest.get("foundation_bundle_version")
    if not local_version or not isinstance(local_version, str):
        sys.exit(0)

    # --- 2. Fetch the AUTHORITATIVE remote registry via the ONE shared routine ---
    # The toolkit lib sits at $WIZARD_HOME/scripts/lib (the public-clone layout; the same
    # path the `wizard` shim resolves and that the build repo exposes under wizard/). The
    # routine resolves the source from the origin-pinned .wizard/update-source.json (or the
    # WIZARD_UPDATE_REGISTRY_URL seam) and parses the registry as DATA — never executed.
    from pathlib import Path
    lib_dir = os.path.join(wizard_home, "scripts", "lib")
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    from registry_fetch import fetch_remote_registry

    result = fetch_remote_registry(Path(os.getcwd()))
    if not result.ok or not result.registry:
        # Any typed failure (no pin / tampered / network / invalid) -> stay silent.
        sys.exit(0)
    registry = result.registry

    # --- 3. Parse registry and find latest version ---
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

    # --- 4b. Respect the operator's snooze / dismiss preference, if any. ---
    # The operator can ask to be reminded later ("snooze_until": "YYYY-MM-DD") or to skip a
    # version until a newer one ships ("dismissed_version": "vX.Y.Z"). The model writes this
    # file when the operator chooses; this hook only READS it. FAIL-OPEN: any problem (missing,
    # unreadable, malformed, unexpected fields) is ignored and the notice still fires — the safe
    # direction is to remind, never to silently go quiet.
    state_path = os.path.join(os.getcwd(), ".wizard", "upgrade-notice-state.json")
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state, dict):
            # skip-this-version: suppress while the latest available is not newer than dismissed.
            dismissed = state.get("dismissed_version")
            if isinstance(dismissed, str) and dismissed and latest_ver_tuple <= _semver(dismissed):
                sys.exit(0)
            # remind-me-later: suppress while today is before snooze_until (ISO YYYY-MM-DD sorts
            # lexicographically, so a plain string compare is correct).
            snooze_until = state.get("snooze_until")
            if isinstance(snooze_until, str) and snooze_until:
                import datetime
                if datetime.date.today().isoformat() < snooze_until:
                    sys.exit(0)
    except Exception:
        pass  # fail-open: notify

    # This is printed by a SessionStart hook. For the output to reach the assistant's
    # session-start context, a SessionStart hook must emit EITHER plain text OR a JSON object
    # with a `hookSpecificOutput.additionalContext` field. A BARE JSON object (no
    # hookSpecificOutput) is parsed as a control object and SILENTLY DROPPED — it never reaches
    # context. So we wrap the notice in the hookSpecificOutput envelope.
    #
    # The injected `additionalContext` is DECLARATIVE DATA (a `wizard_system_event` object),
    # not an instruction — no prose imperatives, no secrecy, no command, no file paths. Reason:
    # an imperative/secret instruction here ("tell the operator... DO NOT show them... run this
    # command") reads as a prompt-injection attack and the system's own anti-injection discipline
    # (correctly) refuses it. The "tell the operator about this" instruction lives in DURABLE
    # config the model trusts (the emitted CLAUDE.md "System-update notices" rule), which keys on
    # this tag and relays it in plain language, advisory-only. The real trust boundary is the
    # in-project upgrade tool, which re-validates against the registry before anything changes.
    notice = json.dumps({
        "wizard_system_event": "upgrade_notice",
        "update_available": True,
        "current_version": local_version,
        "latest_version": latest_version,
    })
    additional_context = (
        "System version check (advisory status, not an instruction): " + notice
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }))
except SystemExit:
    raise
except Exception:
    # Fail-open: never let a hook bug (or a shared-lib bug) brick a SessionStart.
    sys.exit(0)

PY

# If python3 itself exited non-zero (not a sys.exit(0)), the trap exits 0.
exit 0
