"""Durable, read-only update-source reference for an operator system.

This module owns `.wizard/update-source.json` — the SINGLE source of truth for
"where this system's updates come from". It records the pinned public distribution
repository (owner / name), the HTTPS clone + raw base URLs, the branch, the
last-known-good published commit the operator is pinned to, and the convention for
where the update toolkit is installed on the operator's machine.

Why a durable on-disk reference (rather than an env var or a URL hardcoded in the
session-start notice hook): one auditable, version-controlled record that the notice
hook, the engine, and the guided self-update step all agree on. It removes the
two-URL / two-parser split where the notice hook hardcodes a registry URL and the
engine guesses an install path independently.

SAFETY (load-bearing): this file is READ-ONLY to the assistant. It is added to the
emitted `.claude/settings.json` `permissions.deny` set (Edit / Write denied), the
same anti-self-bypass pattern that protects `.claude/**`. Rationale: a
prompt-injection attempt must never be able to repoint the system's update source at
an attacker-controlled repository. The assistant reads this file; only the operator
(by hand) or the guarded self-update step (which verifies the pinned origin before
recording a new commit) ever changes it.

Stdlib-only, pip-install-free. JSON is the runtime contract surface.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional


# The operator-project-relative path of the durable reference.
UPDATE_SOURCE_REL = ".wizard/update-source.json"

# Schema version for the reference document. Bump on any field change so a future
# loader can branch on shape rather than guess.
UPDATE_SOURCE_SCHEMA_VERSION = "update-source-v1"

# The canonical public distribution repository the wizard publishes to. These are the
# single source of truth the session-start notice hook's URLs are derived from too, so
# the hook and this reference cannot drift to different origins.
CANONICAL_REPO_OWNER = "pantheon-mark"
CANONICAL_REPO_NAME = "agent-wizard"
CANONICAL_BRANCH = "main"

# HTTPS only. The clone URL is the canonical origin the self-update step verifies the
# installed toolkit's git remote against; the raw base is where the session-start hook
# fetches the registry JSON from. Both are derived from the canonical owner/repo so
# there is exactly one place the origin is defined.
CANONICAL_HTTPS_URL = f"https://github.com/{CANONICAL_REPO_OWNER}/{CANONICAL_REPO_NAME}.git"
CANONICAL_RAW_BASE_URL = (
    f"https://raw.githubusercontent.com/{CANONICAL_REPO_OWNER}/{CANONICAL_REPO_NAME}/{CANONICAL_BRANCH}"
)

# Documented placeholder for last_known_good_commit when the published commit is not
# known at emit time. The first guarded self-update fills it with a verified commit.
LAST_KNOWN_GOOD_PLACEHOLDER = "(unset — recorded by the first verified self-update)"

# The convention for where the update toolkit (the public clone) is installed. The
# session-start notice hook reads $WIZARD_HOME with the same default; this records the
# convention durably so the engine and the operator agree.
TOOLKIT_INSTALL_CONVENTION = "$WIZARD_HOME (defaults to ~/agent-wizard)"


class UpdateSourceError(Exception):
    """Raised when `.wizard/update-source.json` cannot be loaded or validated.
    Fail-closed: a missing / malformed / wrong-origin reference is an error, never a
    silent default, because the wrong answer here is a supply-chain hazard."""


def render_update_source(
    *,
    last_known_good_commit: Optional[str] = None,
    repo_owner: str = CANONICAL_REPO_OWNER,
    repo_name: str = CANONICAL_REPO_NAME,
    branch: str = CANONICAL_BRANCH,
) -> Dict[str, Any]:
    """Build the update-source reference dict.

    Single canonical body, shared by the setup-time emitter and the upgrade-time
    control-plane refresh, so the operator's copy stays current as the pinned origin
    evolves. `last_known_good_commit` defaults to the documented placeholder the first
    verified self-update fills in.
    """
    https_url = f"https://github.com/{repo_owner}/{repo_name}.git"
    raw_base_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch}"
    return {
        "schema_version": UPDATE_SOURCE_SCHEMA_VERSION,
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "https_url": https_url,
        "raw_base_url": raw_base_url,
        "branch": branch,
        "last_known_good_commit": (
            last_known_good_commit if last_known_good_commit else LAST_KNOWN_GOOD_PLACEHOLDER
        ),
        "toolkit_install_convention": TOOLKIT_INSTALL_CONVENTION,
        "_note": (
            "This file is the single source of truth for where this system's updates "
            "come from. It is read-only to the assistant (denied in .claude/settings.json) "
            "so a prompt-injection attempt cannot repoint the update source. Only you (by "
            "hand) or a verified self-update may change it."
        ),
    }


def render_update_source_json(**kwargs: Any) -> str:
    """The canonical serialized body (deterministic: sorted keys, 2-space indent,
    trailing newline) — matches the emitter/control-plane refresh writer so a freshly
    emitted file reads back byte-identical to a re-render."""
    return json.dumps(render_update_source(**kwargs), indent=2, sort_keys=True) + "\n"


def emit_update_source(staging_dir: Path, *, last_known_good_commit: Optional[str] = None) -> Path:
    """Emit `.wizard/update-source.json` into the staging tree (deterministic; no clock,
    no randomness). Returns the path written."""
    dest = staging_dir / UPDATE_SOURCE_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        render_update_source_json(last_known_good_commit=last_known_good_commit),
        encoding="utf-8",
    )
    return dest


def record_last_known_good_commit(operator_project_dir: Path, commit: str) -> Path:
    """Record a new last-known-good commit into `.wizard/update-source.json`, preserving
    every other field.

    This is the ONLY legitimate writer of the otherwise read-only reference. The file is
    denied to the assistant in `.claude/settings.json`; only the guarded self-update path
    (which verified the pinned origin + lineage before getting here) or the operator by
    hand should change it. Re-validates the loaded reference first (fail-closed) so a
    tampered file is never silently rewritten.
    """
    data = load_update_source(operator_project_dir)
    data["last_known_good_commit"] = commit
    dest = operator_project_dir / UPDATE_SOURCE_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def load_update_source(operator_project_dir: Path) -> Dict[str, Any]:
    """Load + validate the operator project's `.wizard/update-source.json`.

    This is the single loader the engine / CLI uses to learn the pinned update source.
    Fail-closed (UpdateSourceError) on: missing file, non-regular file, malformed JSON,
    non-object root, missing required field, non-HTTPS transport, or an https_url whose
    owner/repo does not match the recorded repo_owner/repo_name (an internally
    inconsistent reference is treated as tampered).
    """
    path = operator_project_dir / UPDATE_SOURCE_REL
    if not path.exists():
        raise UpdateSourceError(
            f"update-source reference not found at {path}; this system has no update "
            "source configured. (It is written when the system is first set up.)"
        )
    if not path.is_file():
        raise UpdateSourceError(f"update-source path is not a regular file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise UpdateSourceError(f"update-source reference at {path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise UpdateSourceError(f"update-source reference at {path} must be a JSON object")

    required = ("repo_owner", "repo_name", "https_url", "branch")
    missing = [k for k in required if not (isinstance(data.get(k), str) and data.get(k))]
    if missing:
        raise UpdateSourceError(
            f"update-source reference at {path} missing required field(s): {missing}"
        )

    https_url = data["https_url"]
    if not https_url.startswith("https://"):
        raise UpdateSourceError(
            f"update-source reference at {path} has a non-HTTPS https_url {https_url!r}; "
            "only HTTPS transport is accepted (fail-closed)."
        )

    # Internal consistency: the https_url must point at the recorded owner/repo. A
    # mismatch means the reference has been tampered with into an inconsistent state.
    expected_https = f"https://github.com/{data['repo_owner']}/{data['repo_name']}.git"
    if _normalize_repo_url(https_url) != _normalize_repo_url(expected_https):
        raise UpdateSourceError(
            f"update-source reference at {path} is internally inconsistent: https_url "
            f"{https_url!r} does not match repo_owner/repo_name "
            f"{data['repo_owner']}/{data['repo_name']} (treated as tampered; fail-closed)."
        )
    return data


def _normalize_repo_url(url: str) -> str:
    """Normalize a GitHub HTTPS repo URL for comparison: lowercase, drop a trailing
    `.git`, drop a trailing slash. Used so `https://github.com/o/r.git` and
    `https://github.com/o/r` compare equal."""
    u = url.strip().lower()
    if u.endswith("/"):
        u = u[:-1]
    if u.endswith(".git"):
        u = u[: -len(".git")]
    return u
