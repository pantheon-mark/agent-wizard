"""Foundation-bundle upgrade engine.

Library module for `wizard upgrade-check`, `wizard upgrade --to <version> --plan-only`
(preview), and the plan record consumed by the merge-apply path. Engine functions +
data records; argparse shim lives in `wizard/scripts/wizard_upgrade.py`; the merge-apply
mutator lives in the sibling `upgrade_apply.py`.

Stdlib-only — no PyYAML, no third-party deps. JSON sidecars are the runtime contract
surface; YAML manifests are human-facing companions. Operator-side CLI consumes
`.wizard/manifest.json` only at v0 (YAML+JSON sync emitted by generator-side
`wizard/scripts/generate_bundle.py`).

v0 scope:
    - Both paths available: plan-only preview (this module) and apply
      (sibling `upgrade_apply.py`, exposed as `wizard upgrade --to <version> --apply`).
    - Standing auto-approval disabled at v0 (per the foundation-versioning policy's own
      v0 deferral): every upgrade is operator-explicit; the CLI reports
      `requires_operator_approval` regardless of `excluded_when:` content.
    - No bespoke auto-merge engine at v0: apply either clean-adopts the new bundle
      content or saves the new version to a review sidecar when the operator has edited
      a file; it never silently merges conflicting edits.
    - Library-first split: engine here + argparse shim in wizard_upgrade.py.

Authority: the foundation-versioning policy (canonical implementation reference).
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple


# ===== Constants =====

CANONICALIZATION_VERSION = "v1"
"""Canonicalization v1 = LF line endings + UTF-8 + no-BOM + no-trailing-whitespace-on-blank-lines.

Defined explicitly so future canonicalization changes are tracked via schema_version bump."""

HASH_ALGORITHM = "sha256-lf"
"""SHA-256 over canonicalized content per CANONICALIZATION_VERSION."""

PROVENANCE_SCHEMA_VERSION = "v1"
"""foundation-bundle.provenance.json schema version. Locked at v0; future expansion
requires explicit minor-additive amendment per the foundation-versioning policy semver tier semantics."""

STANDING_APPROVAL_STATUS_UNAVAILABLE = "requires_operator_approval"
"""v0 status: the CLI reports this regardless of `excluded_when:` content.

Standing auto-approval is disabled at v0 per the foundation-versioning policy's own
v0 deferral of profile-gated standing approval. Until that policy section is activated,
every upgrade is operator-explicit — there is no path by which an upgrade applies without
the operator deciding to apply it. The full normative eligibility evaluation activates
when the foundation-versioning policy lifts that deferral."""

PROVENANCE_FILENAME = "foundation-bundle.provenance.json"
"""Namespaced filename avoids operator-side collisions."""

MANIFEST_JSON_SIDECAR_FILENAME = "manifest.json"
MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME = "migration-manifest.json"
OPERATOR_MANIFEST_JSON_FILENAME = "manifest.json"

# Semver tier classification per the foundation-versioning policy semver tier semantics
TIER_PATCH_MECHANICAL = "patch-mechanical"
TIER_PATCH_BEHAVIORAL = "patch-behavioral"
TIER_MINOR_ADDITIVE = "minor-additive"
TIER_MAJOR_BREAKING = "major-breaking"
TIER_UNKNOWN = "unknown"

# Merge strategy enum per manifest contract (foundation-manifest-hash-baseline-v1)
MERGE_STRATEGY_THREE_WAY = "three_way"
MERGE_STRATEGY_OPERATOR_REVIEW = "operator_review"
MERGE_STRATEGY_WARN_ON_DRIFT = "warn_on_drift"
MERGE_STRATEGY_FROZEN = "frozen"
# Drift-safe refresh policy for wizard-authored control-plane guidance files (the
# operator-facing `.wizard/UPGRADING.md` is the first). These files are produced by a
# Python control-plane emitter at setup, not by a bundle template, so the new wording
# would otherwise freeze at first emit. Apply-time semantics:
#   - live file == the prior emitted baseline (unedited)  -> REPLACE with the freshly
#     re-rendered version (the guidance stays current as commands/scope evolve).
#   - live file has DRIFTED (operator/system annotated it) -> write the new version to
#     the review sidecar and LEAVE the local file intact (never clobber, never markers).
# Distinct from operator_review (which would NEVER refresh an unedited file) and from a
# blind overwrite (which would clobber operator annotations).
MERGE_STRATEGY_CONTROL_PLANE_REFRESH = "control_plane_refresh"

# Operator-project manifest schema versions.
#   manifest-v1: legacy / foundation-docs-only manifests (no manifest_schema_version field).
#   manifest-v2: full-tree-ownership manifests emitted by the operator-system pipeline.
MANIFEST_SCHEMA_V1 = "manifest-v1"
MANIFEST_SCHEMA_V2 = "manifest-v2"

_MERGE_STRATEGIES = {
    MERGE_STRATEGY_THREE_WAY, MERGE_STRATEGY_OPERATOR_REVIEW,
    MERGE_STRATEGY_WARN_ON_DRIFT, MERGE_STRATEGY_FROZEN,
    MERGE_STRATEGY_CONTROL_PLANE_REFRESH,
}
_LOCAL_MODIFICATIONS = {"expected", "allowed", "not_recommended"}

# Drift status
DRIFT_NONE = "no_drift"
DRIFT_DETECTED = "drift_detected"
DRIFT_MISSING_FILE = "managed_file_missing"

# Semver regex (vMAJOR.MINOR.PATCH; pre-v1 vN.M[.P] tolerated)
SEMVER_PATTERN = re.compile(r"^v(\d+)\.(\d+)(?:\.(\d+))?(?:-[a-zA-Z0-9.-]+)?$")


# ===== Engine (toolkit) semantic version =====
# A SEMANTIC version of the upgrade engine itself, distinct from `generator_version`
# (a commit hash). It is the version a bundle's `min_engine_version` is compared
# against to decide whether the locally-installed engine is new enough to apply that
# bundle (MF-2 engine-compatibility gate). Bump the MINOR when a bundle could legitimately
# declare a higher `min_engine_version` than older engines satisfy (i.e. when this engine
# gains an apply capability a future bundle may require); bump MAJOR on a breaking apply
# contract change. NOT auto-derived from git — semantic + hand-maintained.
ENGINE_VERSION = "v1.0.0"

# Bundle-manifest schema version that introduced the engine-compatibility contract.
# A bundle manifest declaring `bundle_manifest_schema_version` >= this value MUST carry a
# `min_engine_version` (else the engine fails closed rather than assume compatibility);
# a manifest that omits `bundle_manifest_schema_version` is a LEGACY (pre-engine-compat)
# bundle and is NOT subject to the gate (engine assumed compatible — applies prospectively,
# so already-released foundation-only bundles keep loading).
BUNDLE_MANIFEST_SCHEMA_ENGINE_COMPAT = "v2"


# ===== C6' typed honest-status contract (the upgrade-check surface) =====
# Every upgrade-check outcome is a TYPED status, not a boolean or LLM free-text. The
# load-bearing invariant: ONLY `CHECKED_CURRENT` may render an "up to date" message; any
# "could not determine" outcome renders "could not check / status unknown" and must never
# be reported as up-to-date. Statuses map to distinct CLI exit codes so a caller can
# branch on WHY a check failed without parsing prose.

class UpdateStatus(Enum):
    """Typed outcome of an update check. Exhaustively handled by `render_update_status`
    + `status_exit_code` (both raise on an unhandled member — no silent default)."""
    UPDATE_AVAILABLE = "update_available"        # checked; a newer target exists
    CHECKED_CURRENT = "checked_current"          # checked; system IS current (ONLY up-to-date status)
    COULD_NOT_CHECK = "could_not_check"          # generic could-not-determine (fetch/IO/unknown)
    TOOLKIT_UNVERIFIED = "toolkit_unverified"    # local toolkit could not be integrity-verified
    SOURCE_UNCONFIGURED = "source_unconfigured"  # no update source wired (the F-OR-3 case)
    ENGINE_TOO_OLD = "engine_too_old"            # an update exists but the local engine must refresh first
    NETWORK_UNAVAILABLE = "network_unavailable"  # could not reach the update source over the network
    CURRENCY_UNCONFIRMED = "currency_unconfirmed"  # a local catalog is readable, but the AUTHORITATIVE remote could not be reached → currency UNKNOWN (the stale-mirror case; never "up to date")
    REGISTRY_INVALID = "registry_invalid"        # registry missing / unparseable / malformed
    CANDIDATE_UNVERIFIED = "candidate_unverified"  # a fetched candidate failed integrity/lineage verification
    UPDATE_SOURCE_TAMPERED = "update_source_tampered"  # the update source did not match its pinned origin


# Statuses that mean "the system FAILED to establish whether an update exists." None of
# these may render up-to-date; all render a could-not-check / status-unknown message.
_COULD_NOT_DETERMINE_STATUSES = frozenset({
    UpdateStatus.COULD_NOT_CHECK,
    UpdateStatus.TOOLKIT_UNVERIFIED,
    UpdateStatus.SOURCE_UNCONFIGURED,
    UpdateStatus.NETWORK_UNAVAILABLE,
    UpdateStatus.CURRENCY_UNCONFIRMED,
    UpdateStatus.REGISTRY_INVALID,
    UpdateStatus.CANDIDATE_UNVERIFIED,
    UpdateStatus.UPDATE_SOURCE_TAMPERED,
    UpdateStatus.ENGINE_TOO_OLD,
})


# ===== CLI exit codes (one per status class; distinct + documented) =====
# 0  = checked-current (no update)            -> EXIT_CHECKED_CURRENT
# 10 = update available                       -> EXIT_UPDATE_AVAILABLE
# 20 = could-not-check (generic)              -> EXIT_COULD_NOT_CHECK
# 21 = toolkit unverified                     -> EXIT_TOOLKIT_UNVERIFIED
# 22 = no update source configured            -> EXIT_SOURCE_UNCONFIGURED
# 23 = engine too old (refresh tool first)    -> EXIT_ENGINE_TOO_OLD
# 24 = network unavailable                    -> EXIT_NETWORK_UNAVAILABLE
# 25 = registry invalid                       -> EXIT_REGISTRY_INVALID
# 26 = candidate failed verification          -> EXIT_CANDIDATE_UNVERIFIED
# 27 = update source tampered / wrong origin  -> EXIT_UPDATE_SOURCE_TAMPERED
# 28 = currency unconfirmed (remote unreached) -> EXIT_CURRENCY_UNCONFIRMED
# (These are distinct from the argparse/tooling exit code 2 used by wizard_upgrade.py for
#  invalid CLI arguments; the could-not-determine band starts at 20 to avoid colliding.)
EXIT_CHECKED_CURRENT = 0
EXIT_UPDATE_AVAILABLE = 10
EXIT_COULD_NOT_CHECK = 20
EXIT_TOOLKIT_UNVERIFIED = 21
EXIT_SOURCE_UNCONFIGURED = 22
EXIT_ENGINE_TOO_OLD = 23
EXIT_NETWORK_UNAVAILABLE = 24
EXIT_REGISTRY_INVALID = 25
EXIT_CANDIDATE_UNVERIFIED = 26
EXIT_UPDATE_SOURCE_TAMPERED = 27
EXIT_CURRENCY_UNCONFIRMED = 28

_STATUS_EXIT_CODES: Dict[UpdateStatus, int] = {
    UpdateStatus.CHECKED_CURRENT: EXIT_CHECKED_CURRENT,
    UpdateStatus.UPDATE_AVAILABLE: EXIT_UPDATE_AVAILABLE,
    UpdateStatus.COULD_NOT_CHECK: EXIT_COULD_NOT_CHECK,
    UpdateStatus.TOOLKIT_UNVERIFIED: EXIT_TOOLKIT_UNVERIFIED,
    UpdateStatus.SOURCE_UNCONFIGURED: EXIT_SOURCE_UNCONFIGURED,
    UpdateStatus.ENGINE_TOO_OLD: EXIT_ENGINE_TOO_OLD,
    UpdateStatus.NETWORK_UNAVAILABLE: EXIT_NETWORK_UNAVAILABLE,
    UpdateStatus.CURRENCY_UNCONFIRMED: EXIT_CURRENCY_UNCONFIRMED,
    UpdateStatus.REGISTRY_INVALID: EXIT_REGISTRY_INVALID,
    UpdateStatus.CANDIDATE_UNVERIFIED: EXIT_CANDIDATE_UNVERIFIED,
    UpdateStatus.UPDATE_SOURCE_TAMPERED: EXIT_UPDATE_SOURCE_TAMPERED,
}


def status_exit_code(status: "UpdateStatus") -> int:
    """Map a status to its distinct CLI exit code. EXHAUSTIVE: raises on any status not
    in the table (no silent default — a new enum member is a compile-time-equivalent
    failure here, surfaced by the all-statuses test)."""
    code = _STATUS_EXIT_CODES.get(status)
    if code is None:
        raise ValueError(
            f"status_exit_code: unhandled UpdateStatus {getattr(status, 'name', status)!r}; "
            "add it to _STATUS_EXIT_CODES (no silent default permitted)."
        )
    return code


@dataclass
class UpdateCheckOutcome:
    """The typed result the upgrade-check surface returns. Carries the typed `status`,
    a stable machine `reason_code`, and structured fields the operator-facing layer
    renders from (NEVER from raw logs). `--json` emits status / reason_code / the
    structured fields verbatim."""
    status: UpdateStatus
    reason_code: str
    current_version: str = ""
    available_targets: List[Dict[str, Any]] = field(default_factory=list)
    detail: str = ""                 # short machine-facing detail (e.g. the registry error text)
    engine_version: str = ENGINE_VERSION
    min_engine_version: str = ""     # populated for ENGINE_TOO_OLD


# Operator-facing message per status. EXHAUSTIVE: `render_update_status` raises on any
# status absent from this table. ONLY CHECKED_CURRENT carries an up-to-date phrase; the
# could-not-determine statuses all carry a "could not check / status unknown" phrase.
_STATUS_MESSAGES: Dict[UpdateStatus, str] = {
    UpdateStatus.CHECKED_CURRENT: (
        "Checked for updates: your system is up to date. There is no newer version to install."
    ),
    UpdateStatus.UPDATE_AVAILABLE: (
        "An update is available for your system. Review what it changes before applying it."
    ),
    UpdateStatus.COULD_NOT_CHECK: (
        "Could not check for updates, so the update status is unknown. The check did "
        "not complete — this is not a confirmation that your system is current."
    ),
    UpdateStatus.TOOLKIT_UNVERIFIED: (
        "Could not check for updates: the update tool on this machine could not be "
        "verified, so the update status is unknown. Refresh the tool, then check again."
    ),
    UpdateStatus.SOURCE_UNCONFIGURED: (
        "Could not check for updates: no update source is connected to this system, so "
        "the update status is unknown. This is not a confirmation that your system is current."
    ),
    UpdateStatus.ENGINE_TOO_OLD: (
        "An update is available, but the update tool on this machine is too old to apply "
        "it safely. Refresh the tool first, then check again. The update was NOT applied."
    ),
    UpdateStatus.NETWORK_UNAVAILABLE: (
        "Could not check for updates: the update source could not be reached over the "
        "network, so the update status is unknown. Check your connection and try again."
    ),
    UpdateStatus.CURRENCY_UNCONFIRMED: (
        "Could not confirm whether an update is available. A local list of versions "
        "exists, but the authoritative source could not be reached, so it was NOT used "
        "to decide — this is not a confirmation that your system is current."
    ),
    UpdateStatus.REGISTRY_INVALID: (
        "Could not check for updates: the list of available versions is missing or "
        "unreadable, so the update status is unknown. This is not a confirmation that "
        "your system is current."
    ),
    UpdateStatus.CANDIDATE_UNVERIFIED: (
        "Could not check for updates: a candidate update failed verification, so the "
        "update status is unknown and nothing was applied."
    ),
    UpdateStatus.UPDATE_SOURCE_TAMPERED: (
        "Could not check for updates: the update source did not match the expected, "
        "trusted origin, so the update status is unknown and nothing was applied."
    ),
}


def render_update_status(outcome: "UpdateCheckOutcome") -> str:
    """EXHAUSTIVE renderer: map a status to its operator-facing string. Raises on any
    status not in `_STATUS_MESSAGES` (no silent default).

    INVARIANT (test-enforced across ALL statuses): only CHECKED_CURRENT yields an
    up-to-date message; every other status renders a non-up-to-date string, and the
    could-not-determine class renders a 'could not check / status unknown' message."""
    status = outcome.status
    msg = _STATUS_MESSAGES.get(status)
    if msg is None:
        raise ValueError(
            f"render_update_status: unhandled UpdateStatus {getattr(status, 'name', status)!r}; "
            "add it to _STATUS_MESSAGES (no silent default permitted)."
        )
    if status == UpdateStatus.ENGINE_TOO_OLD and outcome.min_engine_version:
        msg = (
            msg + f" (needs update tool {outcome.min_engine_version} or newer; this "
            f"machine has {outcome.engine_version})."
        )
    return msg


def classify_update_status(
    source: Any,
    *,
    engine_too_old: bool = False,
    min_engine_version: str = "",
) -> "UpdateCheckOutcome":
    """Map a raw upgrade-check result OR a failure into the typed outcome.

    Accepts:
      - an `UpgradeCheckResult`  -> UPDATE_AVAILABLE (targets present) /
                                    CHECKED_CURRENT (none). If `engine_too_old` is set
                                    AND targets exist -> ENGINE_TOO_OLD (an update exists
                                    but the local engine must refresh first).
      - a `RegistryError`        -> REGISTRY_INVALID (NOT "no updates")
      - any other `UpgradeError` -> COULD_NOT_CHECK (the check did not complete)
      - None                     -> SOURCE_UNCONFIGURED (no source/result at all)

    This is the single funnel that prevents a fetch/parse failure collapsing into a
    false "you're up to date" (F-OR-3)."""
    if source is None:
        return UpdateCheckOutcome(
            status=UpdateStatus.SOURCE_UNCONFIGURED,
            reason_code="no_update_source_configured",
        )
    if isinstance(source, RegistryError):
        return UpdateCheckOutcome(
            status=UpdateStatus.REGISTRY_INVALID,
            reason_code="registry_missing_or_unparseable",
            detail=str(source),
        )
    if isinstance(source, UpgradeError):
        return UpdateCheckOutcome(
            status=UpdateStatus.COULD_NOT_CHECK,
            reason_code="check_did_not_complete",
            detail=str(source),
        )
    if isinstance(source, UpgradeCheckResult):
        targets = list(source.available_targets or [])
        if targets and engine_too_old:
            return UpdateCheckOutcome(
                status=UpdateStatus.ENGINE_TOO_OLD,
                reason_code="local_engine_below_min_engine_version",
                current_version=source.current_version,
                available_targets=targets,
                min_engine_version=min_engine_version,
            )
        if targets:
            return UpdateCheckOutcome(
                status=UpdateStatus.UPDATE_AVAILABLE,
                reason_code="newer_target_available",
                current_version=source.current_version,
                available_targets=targets,
            )
        return UpdateCheckOutcome(
            status=UpdateStatus.CHECKED_CURRENT,
            reason_code="no_newer_target",
            current_version=source.current_version,
        )
    # Unknown source type — fail honest, never current.
    return UpdateCheckOutcome(
        status=UpdateStatus.COULD_NOT_CHECK,
        reason_code="unrecognized_check_result",
        detail=f"unrecognized source type {type(source).__name__}",
    )


def update_outcome_to_dict(outcome: "UpdateCheckOutcome") -> Dict[str, Any]:
    """JSON-emittable dict for `--json` (status value + reason_code + structured fields).
    The operator-facing layer renders from THESE fields, never from raw logs."""
    return {
        "status": outcome.status.value,
        "reason_code": outcome.reason_code,
        "current_version": outcome.current_version,
        "available_targets": outcome.available_targets,
        "detail": outcome.detail,
        "engine_version": outcome.engine_version,
        "min_engine_version": outcome.min_engine_version,
        "message": render_update_status(outcome),
        "exit_code": status_exit_code(outcome.status),
    }


# ===== Exception classes =====

class UpgradeError(Exception):
    """Base for all upgrade-engine errors (library raises; CLI translates to exit code)."""


class OperatorManifestError(UpgradeError):
    """Raised when operator-project `.wizard/manifest.json` cannot be loaded / validated."""


class RegistryError(UpgradeError):
    """Raised when `wizard/registry/foundation-bundles.json` cannot be loaded / validated."""


class BundleNotFoundError(UpgradeError):
    """Raised when a requested target version is absent from the registry."""


class PlanOnlyRequiredError(UpgradeError):
    """Raised when `wizard upgrade --to <version>` is invoked without a mode flag.

    `wizard upgrade --to <version>` requires exactly one of `--plan-only` (preview) or
    `--apply` (perform the upgrade); neither given is an operator error.
    """


class MigrationManifestError(UpgradeError):
    """Raised when target version's migration manifest cannot be loaded or lacks required `from:` entry."""


class EngineDirectoryBoundaryError(UpgradeError):
    """Raised (MF-4) when a data bundle / contract entry would write into the engine's
    own code area. Data bundles may only modify operator-estate files (foundation docs +
    operating-layer render/copy files), NEVER the upgrade engine itself."""


# ===== MF-4 engine-directory boundary =====
# A data-apply must NEVER write into the engine's own code area. The engine code lives
# under `scripts/` in the toolkit (`scripts/wizard_upgrade.py`, `scripts/lib/*.py`); a
# bundle/contract entry resolving into that area (or escaping the operator project via
# `..`) is refused fail-closed. The operator estate never legitimately contains a
# top-level `scripts/` engine directory — operating-layer files live under `.claude/`,
# `agents/`, `foundation/`, `quality/`, root docs, etc.

# The operator-relative path prefixes that constitute the engine's own code area.
_ENGINE_DIR_SEGMENTS = ("scripts",)
# Specific engine entrypoint files (defense-in-depth; covered by the `scripts/` prefix
# too, but named so the intent is explicit and a future relocation is easy to extend).
_ENGINE_FILE_BASENAMES = ("wizard_upgrade.py",)


def target_escapes_engine_dir(relpath: str) -> bool:
    """Pure predicate (MF-4): True if an operator-relative target would land in the
    engine's own code area or escape the operator project.

    Flags:
      - any path whose first normalized segment is an engine dir (`scripts/...`),
      - the named engine entrypoint files anywhere,
      - any path that escapes the operator project root via `..`.

    Normalizes `.`/`..` segments WITHOUT touching the filesystem so a crafted
    `scripts/../scripts/lib/x.py` or `./scripts/...` cannot slip past a naive
    startswith check.
    """
    if not relpath:
        return False
    raw = PurePosixPath(relpath.replace("\\", "/"))
    if raw.is_absolute():
        # An absolute target is never a valid operator-relative estate file.
        return True
    # Normalize . / .. without resolving against the filesystem.
    parts: List[str] = []
    for seg in raw.parts:
        if seg == ".":
            continue
        if seg == "..":
            if not parts:
                # Escapes above the operator project root.
                return True
            parts.pop()
            continue
        parts.append(seg)
    if not parts:
        return False
    if parts[0] in _ENGINE_DIR_SEGMENTS:
        return True
    if parts[-1] in _ENGINE_FILE_BASENAMES:
        return True
    return False


# ===== Canonicalization =====

def canonicalize_bytes(b: bytes) -> bytes:
    """Apply canonicalization v1: LF line endings + UTF-8 + no-BOM + no-trailing-whitespace-on-blank-lines.

    Used consistently across drift detection + provenance emission so identical logical
    content produces identical hashes regardless of platform line-ending / BOM variations.
    """
    if b.startswith(b"\xef\xbb\xbf"):
        b = b[3:]
    text = b.decode("utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out_lines = []
    for line in text.split("\n"):
        if line.strip() == "":
            out_lines.append("")
        else:
            out_lines.append(line)
    return "\n".join(out_lines).encode("utf-8")


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file's canonicalized content."""
    with path.open("rb") as f:
        canon = canonicalize_bytes(f.read())
    return hashlib.sha256(canon).hexdigest()


def sha256_bytes(b: bytes) -> str:
    """SHA-256 hex digest of canonicalized bytes."""
    return hashlib.sha256(canonicalize_bytes(b)).hexdigest()


# Write-only managed frontmatter field whose VALUE the per-bundle render-contract
# invariant forces to track the bundle's section_schema_version. No operator /
# upgrade / runtime consumer reads it; only the build-time validator does. A pure
# bump must NOT be treated as a content change by upgrade change-detection.
_CONTENT_HASH_SCHEMA_VERSION_RE = re.compile(
    r"^(foundation_schema_version:\s*).*$", flags=re.MULTILINE
)


def normalize_for_content_hash(text: str) -> str:
    """Normalize a rendered foundation doc for CONTENT-level hashing (change
    detection + drift), as distinct from the full canonical render hash used by the
    replay-conformance gate.

    SURGICAL: blanks ONLY the volatile write-only `foundation_schema_version` field
    VALUE — it does NOT strip the whole frontmatter block (stripping all would blind
    change-detection to legitimate metadata changes such as `managed_by`). Shared by
    BOTH the producer (scaffold emitter, which writes base_content_hash) and the
    consumer (mutator change-detection) so the two cannot drift.

    The replay hash (base_hash) is NEVER passed through this; only the content hash is."""
    return _CONTENT_HASH_SCHEMA_VERSION_RE.sub(r"\1<normalized>", text)


# ===== Semver tier classification =====

def parse_semver(version: str) -> Optional[Tuple[int, int, int]]:
    """Parse `vMAJOR.MINOR[.PATCH]` to a 3-tuple. PATCH defaults to 0 if absent.

    Returns None for malformed versions (caller handles fail-closed)."""
    m = SEMVER_PATTERN.match(version)
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3)) if m.group(3) else 0
    return (major, minor, patch)


def classify_tier(from_version: str, to_version: str) -> str:
    """Classify upgrade tier per the foundation-versioning policy semver tier semantics.

    Returns one of: patch-mechanical / patch-behavioral / minor-additive / major-breaking / unknown.
    NOTE: patch-mechanical vs patch-behavioral cannot be distinguished from version strings alone
    (per § 2.3 the distinction is whether the change affects operator-visible behavior). At v0
    the engine returns 'patch-behavioral' for any patch-class delta (safer default = review required);
    full discrimination requires reading the target bundle's release-classification metadata.
    """
    f = parse_semver(from_version)
    t = parse_semver(to_version)
    if f is None or t is None:
        return TIER_UNKNOWN
    if t[0] > f[0]:
        return TIER_MAJOR_BREAKING
    if t[0] < f[0]:
        return TIER_UNKNOWN  # downgrade not supported in this version of the engine
    if t[1] > f[1]:
        return TIER_MINOR_ADDITIVE
    if t[1] < f[1]:
        return TIER_UNKNOWN  # minor-downgrade not supported
    if t[2] > f[2]:
        return TIER_PATCH_BEHAVIORAL  # safe default per docstring; v0 doesn't auto-classify mechanical
    if t[2] < f[2]:
        return TIER_UNKNOWN
    return TIER_UNKNOWN  # same version; not an upgrade


# ===== Data records =====

@dataclass
class DriftReportEntry:
    """Per-file drift entry — non-destructive PLANNING only (F-1 ratified)."""
    path: str
    base_hash: str
    current_hash: str
    status: str  # DRIFT_NONE | DRIFT_DETECTED | DRIFT_MISSING_FILE
    merge_strategy: str
    local_modifications: str
    plan_action: str  # human-readable plan description; NO automatic apply at v0


@dataclass
class DriftReport:
    """Bundle-level drift report. Non-destructive planning only at v0."""
    operator_project_path: str
    bundle_version: str
    target_bundle_version: Optional[str]
    entries: List[DriftReportEntry] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return any(e.status != DRIFT_NONE for e in self.entries)

    @property
    def drift_count(self) -> int:
        return sum(1 for e in self.entries if e.status != DRIFT_NONE)


@dataclass
class MigrationEntry:
    """Single migration entry surfaced from the target version's migration-manifest.json."""
    from_version: str
    migration_class: str          # patch-mechanical / patch-behavioral / minor-additive / major-breaking
    requires_operator_approval: Any   # bool OR "not_applicable" string
    stop_condition: str
    breaking_changes_summary: str
    supported: bool
    preflight: Any = "not_applicable"
    rollback: Any = "not_applicable"
    migration_steps: Any = "not_applicable"
    stabilization_exemption: str = ""


@dataclass
class ArtifactAnalysis:
    """Per-artifact analysis entry for the upgrade plan display.

    Joins drift report + merge_strategy + migration-manifest artifact_notes into a
    plain-language summary the operator reviews before deciding to apply.

    Fields:
        relpath    -- relative path of the artifact inside the operator project
        what       -- "new" | "modified" | "unchanged"
        kind       -- "render" (re-rendered from your inputs) | "copy" (install-as-is)
        benefit    -- plain-language why this change helps; from artifact_notes or a default
        risk       -- operator-facing risk label (clean adopt / will merge / saved for
                      review / will warn -- needs --ack / installed as-is)
        how        -- same action phrased as what will happen when applied
    """
    relpath: str
    what: str    # new | modified | unchanged
    kind: str    # render | copy
    benefit: str
    risk: str
    how: str


@dataclass
class UpgradePlan:
    """Plan-only upgrade record: a non-mutating preview of what an upgrade would change.

    This record makes no changes on disk. To perform the upgrade, run
    `wizard upgrade --to <version> --apply` (the sibling merge-apply path). Every apply
    is operator-explicit; standing auto-approval is disabled at v0."""
    operator_project_path: str
    from_version: str
    to_version: str
    tier: str
    drift_report: DriftReport
    standing_approval_status: str
    migration_entry: Optional[MigrationEntry] = None   # populated when target migration manifest contains a `from:` entry
    planned_steps: List[str] = field(default_factory=list)
    requires_review: bool = True
    plan_only: bool = True
    apply_blocked_reason: str = (
        "This is a plan-only preview and changes nothing on disk. "
        "To apply, run `wizard upgrade --to <version> --apply` (operator-explicit; "
        "standing auto-approval is disabled at v0)."
    )
    artifact_analysis: List["ArtifactAnalysis"] = field(default_factory=list)


@dataclass
class UpgradeCheckResult:
    """Result of `wizard upgrade-check` per the foundation-versioning policy upgrade-check command."""
    operator_project_path: str
    current_version: str
    available_targets: List[Dict[str, Any]] = field(default_factory=list)
    drift_report: Optional[DriftReport] = None
    standing_approval_status: str = STANDING_APPROVAL_STATUS_UNAVAILABLE
    notes: List[str] = field(default_factory=list)


# ===== Loaders =====

def _validate_manifest_path_key(key: str, path: Path) -> None:
    """Reject unsafe managed_files path keys (empty / absolute / parent-traversal).
    Defensive for the future apply path — a manifest must not be able to point an
    upgrade at a file outside the operator project."""
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise OperatorManifestError(
            f"manifest at {path}: unsafe managed_files path key {key!r}"
        )


def _validate_manifest_v2(data: Dict[str, Any], path: Path) -> None:
    """Strict manifest-v2 (full-tree-ownership) validation. v2 manifests carry the
    full emitted tree + a generator_version (required unconditionally per the
    foundation-versioning policy § 4.1 F-9) and must pass per-file enum + hash-format
    + path-safety checks so the future apply path can trust them."""
    required = ["foundation_bundle_version", "generator_version", "managed_files"]
    missing = [k for k in required if k not in data]
    if missing:
        raise OperatorManifestError(f"manifest-v2 at {path} missing required keys: {missing}")
    files = data.get("managed_files")
    if not isinstance(files, dict):
        raise OperatorManifestError(f"manifest-v2 at {path}: managed_files must be a JSON object")
    for key, meta in files.items():
        _validate_manifest_path_key(key, path)
        if not isinstance(meta, dict):
            raise OperatorManifestError(
                f"manifest-v2 at {path}: managed_files[{key!r}] must be a JSON object"
            )
        for field in ("base_hash", "current_hash_last_seen"):
            v = meta.get(field, "")
            if not (isinstance(v, str) and v.startswith("sha256:")):
                raise OperatorManifestError(
                    f"manifest-v2 at {path}: managed_files[{key!r}].{field} must be a "
                    f"'sha256:'-prefixed string; got {v!r}"
                )
        if meta.get("merge_strategy") not in _MERGE_STRATEGIES:
            raise OperatorManifestError(
                f"manifest-v2 at {path}: managed_files[{key!r}].merge_strategy "
                f"{meta.get('merge_strategy')!r} not in {sorted(_MERGE_STRATEGIES)}"
            )
        if meta.get("local_modifications") not in _LOCAL_MODIFICATIONS:
            raise OperatorManifestError(
                f"manifest-v2 at {path}: managed_files[{key!r}].local_modifications "
                f"{meta.get('local_modifications')!r} not in {sorted(_LOCAL_MODIFICATIONS)}"
            )


def load_operator_manifest(path: Path) -> Dict[str, Any]:
    """Load operator-project `.wizard/manifest.json`, branching on manifest schema
    version (explicit v1 -> v2 loader branching).

    - Absent `manifest_schema_version` OR `manifest-v1`: legacy / foundation-docs-only
      manifest. Backward-compatible required-key check (foundation_bundle_version +
      managed_files) — existing operator projects keep loading.
    - `manifest-v2`: full-tree-ownership manifest. Strict validation per
      `_validate_manifest_v2` (generator_version required; per-file enum + hash-format
      + path-safety).
    - Any other value: fail-closed (a v2 consumer must never silently treat an unknown
      schema as a known one).

    Runtime CLI consumes the JSON manifest; drift detection (`compute_drift_report`)
    reads the per-file `managed_files` block identically for both versions.

    Raises OperatorManifestError on missing path, malformed JSON, or schema gap.
    """
    if not path.exists():
        raise OperatorManifestError(
            f"operator manifest not found at {path}; expected .wizard/{OPERATOR_MANIFEST_JSON_FILENAME}"
        )
    if not path.is_file():
        raise OperatorManifestError(f"manifest path is not a regular file: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise OperatorManifestError(f"malformed JSON in {path}: {e}") from e
    if not isinstance(data, dict):
        raise OperatorManifestError(f"manifest must be a JSON object; got {type(data).__name__}")

    schema_version = data.get("manifest_schema_version")
    if schema_version in (None, MANIFEST_SCHEMA_V1):
        required = ["foundation_bundle_version", "managed_files"]
        missing = [k for k in required if k not in data]
        if missing:
            raise OperatorManifestError(f"manifest at {path} missing required keys: {missing}")
    elif schema_version == MANIFEST_SCHEMA_V2:
        _validate_manifest_v2(data, path)
    else:
        raise OperatorManifestError(
            f"manifest at {path}: unknown manifest_schema_version {schema_version!r} "
            f"(expected absent / {MANIFEST_SCHEMA_V1!r} / {MANIFEST_SCHEMA_V2!r})"
        )
    return data


def load_registry(path: Path) -> Dict[str, Any]:
    """Load `wizard/registry/foundation-bundles.json` with structural + semver validation.

    Validates per-entry shape (must have `foundation_bundle_version` parseable as semver +
    must have `path`); rejects duplicate versions; fails closed on any malformation.

    Raises RegistryError on missing path / malformed JSON / schema gap / invalid version /
    duplicate version entry."""
    if not path.exists():
        raise RegistryError(f"registry not found at {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RegistryError(f"malformed JSON in registry {path}: {e}") from e
    if not isinstance(data, dict):
        raise RegistryError("registry must be a JSON object")
    if "bundles" not in data or not isinstance(data["bundles"], list):
        raise RegistryError("registry missing required `bundles` list")
    seen_versions = set()
    for i, entry in enumerate(data["bundles"]):
        if not isinstance(entry, dict):
            raise RegistryError(f"registry bundles[{i}] must be a dict; got {type(entry).__name__}")
        version = entry.get("foundation_bundle_version")
        if not isinstance(version, str) or not version:
            raise RegistryError(f"registry bundles[{i}] missing or non-string `foundation_bundle_version`")
        if parse_semver(version) is None:
            raise RegistryError(f"registry bundles[{i}] version {version!r} is not a parseable semver")
        if version in seen_versions:
            raise RegistryError(f"registry bundles[{i}] duplicate version {version!r}")
        seen_versions.add(version)
        if not isinstance(entry.get("path", ""), str):
            raise RegistryError(f"registry bundles[{i}] non-string `path` field")
    return data


def find_bundle_entry(registry: Dict[str, Any], version: str) -> Optional[Dict[str, Any]]:
    """Find a bundle entry in the registry by version; None if absent."""
    for entry in registry["bundles"]:
        if entry.get("foundation_bundle_version") == version:
            return entry
    return None


# ===== Registry schema versions =====
# The registry's `registry_schema_version` (preferred) — or the legacy top-level
# `schema_version`, or absent -> legacy — selects the bundle-path resolution rule.
# Both schemas resolve registry-relative; they differ ONLY in whether the per-entry
# `path` carries the build-repo `wizard/` prefix (legacy) or is already
# toolkit-relative (newer schema). See resolve_bundle_dir for the legacy branch.
REGISTRY_SCHEMA_V1 = "v1"   # legacy: per-entry `path` is build-repo-rooted ("wizard/foundation-bundles/<v>/")
REGISTRY_SCHEMA_V2 = "v2"   # newer schema: per-entry `path` is toolkit-relative ("foundation-bundles/<v>/")
_LEGACY_PATH_PREFIX = "wizard/"


def _registry_schema_version(registry: Dict[str, Any]) -> str:
    """The bundle-path resolution-rule selector.

    Prefers the explicit `registry_schema_version` field; falls back to
    the legacy generic top-level `schema_version`; falls back to REGISTRY_SCHEMA_V1
    (legacy `wizard/`-prefixed paths) when neither is present. Keeping both readable
    means an older registry (no `registry_schema_version`) still resolves correctly."""
    return (
        registry.get("registry_schema_version")
        or registry.get("schema_version")
        or REGISTRY_SCHEMA_V1
    )


def resolve_toolkit_root(registry_path: Path) -> Path:
    """The toolkit root = the directory that CONTAINS `registry/` + `foundation-bundles/`.

    Canonical + layout-agnostic: the registry ALWAYS lives at
    `<toolkit>/registry/foundation-bundles.json`, so the toolkit root is the registry
    file's grandparent in BOTH shipping layouts:

      * BUILD-REPO  : `<root>/wizard/registry/foundation-bundles.json` -> `<root>/wizard`
      * PUBLIC-CLONE: `<clone>/registry/foundation-bundles.json`       -> `<clone>`

    This is deterministic (no filesystem probe, no path string-matching) — it keys only
    on the registry file's own location, which is identical structure in both layouts.
    """
    return registry_path.resolve().parent.parent


def resolve_bundle_dir(
    registry_path: Path,
    registry: Dict[str, Any],
    entry: Dict[str, Any],
) -> Path:
    """Resolve a bundle's on-disk directory REGISTRY-RELATIVE (canonical), layout-agnostic.

    Resolution is anchored on `resolve_toolkit_root(registry_path)` so it produces the
    SAME bundle directory in the build-repo (`<root>/wizard/...`) and the public-clone
    (`<clone>/...`, prefix stripped by the subtree split) layouts.

    Two resolution rules, selected by the registry's top-level `schema_version`:

      * REGISTRY_SCHEMA_V2 (newer schema): the per-entry `path` is ALREADY toolkit-relative
        (e.g. "foundation-bundles/<v>/") and is joined directly to the toolkit root.
      * REGISTRY_SCHEMA_V1 (legacy / absent): the per-entry `path` carries the build-repo
        `wizard/` prefix (e.g. "wizard/foundation-bundles/<v>/"). The subtree publish
        does NOT rewrite these, so a public clone has the files WITHOUT that prefix. The
        LEGACY BRANCH strips a single leading `wizard/` segment, then joins the remainder
        to the toolkit root — which lands on the bundle in BOTH layouts (build-repo's
        toolkit root already IS `<root>/wizard`, so the stripped path re-roots correctly;
        the public clone has no `wizard/` dir, so stripping is exactly right).

    Fail closed (RegistryError) if:
      * the entry `path` is absolute, or
      * the resolved bundle directory escapes the toolkit root (path traversal), or
      * the layout is ambiguous (a legacy-prefixed registry whose toolkit root does not
        plausibly anchor `foundation-bundles/`).
    """
    toolkit_root = resolve_toolkit_root(registry_path)
    rel = entry.get("path", "")
    version = entry.get("foundation_bundle_version", "<unknown>")
    if not rel:
        return toolkit_root

    raw = PurePosixPath(rel)
    if raw.is_absolute():
        raise RegistryError(
            f"registry entry for {version!r} has an absolute `path` {rel!r}; "
            f"bundle paths must be relative to the toolkit root (fail-closed)"
        )

    schema_version = _registry_schema_version(registry)
    parts = raw.parts
    if schema_version == REGISTRY_SCHEMA_V1 or schema_version is None:
        # Legacy branch: strip exactly one leading `wizard/` segment if present. The
        # build-repo toolkit root IS `<root>/wizard`, and the public clone strips the
        # `wizard/` prefix at publish — stripping here lands on the bundle in BOTH.
        if parts and parts[0] == "wizard":
            parts = parts[1:]
        else:
            # A legacy-schema registry whose entry path is NOT wizard/-prefixed is an
            # ambiguous layout we cannot resolve deterministically — fail closed rather
            # than guess.
            raise RegistryError(
                f"registry schema {schema_version!r} entry for {version!r} has a non-`wizard/`-"
                f"prefixed `path` {rel!r}; ambiguous layout (legacy paths must be "
                f"`wizard/`-prefixed). Declare schema_version {REGISTRY_SCHEMA_V2!r} for "
                f"toolkit-relative paths."
            )
    # schema_version == v2 (or any future toolkit-relative schema): use parts as-is.

    rel_under_toolkit = PurePosixPath(*parts) if parts else PurePosixPath()
    resolved = (toolkit_root / Path(*rel_under_toolkit.parts)).resolve()

    # Fail-closed escape guard: the resolved bundle dir MUST remain inside the toolkit root.
    toolkit_resolved = toolkit_root.resolve()
    if resolved != toolkit_resolved and toolkit_resolved not in resolved.parents:
        raise RegistryError(
            f"registry entry for {version!r} resolves to {resolved} which escapes the "
            f"toolkit root {toolkit_resolved} (fail-closed; bundle paths must stay inside "
            f"the toolkit)"
        )
    return resolved


def _resolve_bundle_dir(registry_path: Path, entry: Dict[str, Any], registry: Optional[Dict[str, Any]] = None) -> Path:
    """Back-compat shim around the canonical `resolve_bundle_dir`.

    Older callers pass only (registry_path, entry); they predate the registry-relative
    resolver. When the registry dict is not supplied, load it (cheap; cached by the OS)
    so the schema_version branch is honored. New callers should use `resolve_bundle_dir`
    directly with the already-loaded registry.
    """
    if registry is None:
        registry = load_registry(registry_path)
    return resolve_bundle_dir(registry_path, registry, entry)


# ===== MF-2 engine-compatibility gate =====
# The locally-installed engine (ENGINE_VERSION) must be >= a target bundle's declared
# `min_engine_version` before plan/apply. A new-schema bundle missing the field fails
# closed (never assume compatible); a legacy bundle (no bundle_manifest_schema_version)
# predates the gate and is exempt (the fix applies prospectively).

BUNDLE_MANIFEST_JSON_FILENAME = "manifest.json"


@dataclass
class EngineCompatResult:
    """Result of `check_engine_compatibility`."""
    compatible: bool
    installed_engine_version: str
    min_engine_version: str = ""     # the target's declared minimum (empty if none / legacy)
    reason: str = ""                 # operator/diagnostic reason when NOT compatible


def _semver_ge(a: str, b: str) -> Optional[bool]:
    """True if semver a >= b; None if either is unparseable (caller fails closed)."""
    ta, tb = parse_semver(a), parse_semver(b)
    if ta is None or tb is None:
        return None
    return ta >= tb


def check_engine_compatibility(
    registry_path: Path,
    registry: Dict[str, Any],
    target_entry: Dict[str, Any],
    *,
    installed_engine_version: str = ENGINE_VERSION,
) -> EngineCompatResult:
    """Compare the installed engine version against the target bundle's
    `min_engine_version` (read from the target bundle's manifest.json), fail-closed.

    Rules:
      - legacy bundle (manifest omits `bundle_manifest_schema_version`) -> compatible
        (the gate applies prospectively; existing foundation-only bundles keep loading).
      - new-schema bundle (declares `bundle_manifest_schema_version`) MISSING
        `min_engine_version` -> NOT compatible (fail closed; never assume).
      - min_engine_version present:
          installed >= min -> compatible.
          installed <  min -> NOT compatible (ENGINE_TOO_OLD; refresh the tool first).
          unparseable min  -> NOT compatible (fail closed).
      - manifest.json unreadable / absent -> NOT compatible (cannot establish; fail closed).

    Bundle-dir resolution is registry-relative + layout-agnostic (build-repo + public-clone).
    """
    version = target_entry.get("foundation_bundle_version", "<unknown>")
    try:
        bundle_dir = resolve_bundle_dir(registry_path, registry, target_entry)
    except RegistryError as e:
        return EngineCompatResult(
            compatible=False, installed_engine_version=installed_engine_version,
            reason=f"cannot resolve the target bundle directory for {version!r}: {e}",
        )
    manifest_json = bundle_dir / BUNDLE_MANIFEST_JSON_FILENAME
    if not manifest_json.is_file():
        # No bundle manifest.json at all -> a legacy / foundation-only bundle (the
        # operating-layer/new-schema bundles always ship one). The engine-compat gate
        # applies prospectively, so such a bundle is exempt (compatible). This is what
        # keeps pre-operating-layer bundles (and synthetic foundation-only fixtures)
        # applying; a new-schema bundle declaring the schema-version but missing the
        # min_engine_version field is the fail-closed case handled below.
        return EngineCompatResult(
            compatible=True, installed_engine_version=installed_engine_version,
        )
    try:
        data = json.loads(manifest_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return EngineCompatResult(
            compatible=False, installed_engine_version=installed_engine_version,
            reason=f"the target bundle {version!r} manifest could not be read: {e} (fail-closed).",
        )
    if not isinstance(data, dict):
        return EngineCompatResult(
            compatible=False, installed_engine_version=installed_engine_version,
            reason=f"the target bundle {version!r} manifest is not a JSON object (fail-closed).",
        )

    schema_version = data.get("bundle_manifest_schema_version")
    min_engine = data.get("min_engine_version")

    # Legacy bundle: predates the engine-compat contract -> exempt (compatible).
    if schema_version is None:
        # A legacy bundle that nonetheless declares a min_engine_version is still honored
        # (defensive); otherwise it's exempt.
        if not min_engine:
            return EngineCompatResult(
                compatible=True, installed_engine_version=installed_engine_version,
            )

    # New-schema bundle (or a legacy one that declared min_engine): require + check it.
    if not min_engine or not isinstance(min_engine, str):
        return EngineCompatResult(
            compatible=False, installed_engine_version=installed_engine_version,
            reason=(
                f"the target bundle {version!r} declares schema "
                f"{schema_version!r} but is missing a `min_engine_version`; refusing to "
                "assume it is compatible with this engine (fail-closed)."
            ),
        )
    ge = _semver_ge(installed_engine_version, min_engine)
    if ge is None:
        return EngineCompatResult(
            compatible=False, installed_engine_version=installed_engine_version,
            min_engine_version=min_engine,
            reason=(
                f"the target bundle {version!r} declares an unparseable "
                f"min_engine_version {min_engine!r} (fail-closed)."
            ),
        )
    if not ge:
        return EngineCompatResult(
            compatible=False, installed_engine_version=installed_engine_version,
            min_engine_version=min_engine,
            reason=(
                f"the update tool on this machine ({installed_engine_version}) is older "
                f"than the version {min_engine} the target {version!r} requires; refresh "
                "the tool first."
            ),
        )
    return EngineCompatResult(
        compatible=True, installed_engine_version=installed_engine_version,
        min_engine_version=min_engine,
    )


def _is_semver_match(from_spec: str, current_version: str) -> bool:
    """Match `migrations[*].from` value (e.g., "v0.2" / "v0.2.0" / "v0.2.x") against a current operator version.

    v0 semantics:
        - Exact-string match (e.g., from="v0.2.0" matches current="v0.2.0")
        - Major.minor prefix match (e.g., from="v0.2" matches current="v0.2.0" or "v0.2.5")
        - Wildcard patch (e.g., from="v0.2.x" matches current="v0.2.0" or "v0.2.5")
    """
    if from_spec == current_version:
        return True
    if from_spec.endswith(".x"):
        prefix = from_spec[:-2] + "."
        return current_version.startswith(prefix)
    cur = parse_semver(current_version)
    spec_tuple = parse_semver(from_spec)
    if cur is None or spec_tuple is None:
        return False
    if "." in from_spec and from_spec.count(".") == 1:
        return cur[0] == spec_tuple[0] and cur[1] == spec_tuple[1]
    return False


def load_migration_manifest(path: Path) -> Dict[str, Any]:
    """Load a target version's `migration-manifest.json` per the foundation-versioning policy migration manifest schema.

    Raises MigrationManifestError on missing path / malformed JSON / schema gap."""
    if not path.exists():
        raise MigrationManifestError(f"migration manifest not found at {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise MigrationManifestError(f"malformed JSON in migration manifest {path}: {e}") from e
    if not isinstance(data, dict):
        raise MigrationManifestError("migration manifest must be a JSON object")
    if "target_version" not in data or "migrations" not in data:
        raise MigrationManifestError(
            f"migration manifest at {path} missing required keys (target_version, migrations)"
        )
    if not isinstance(data["migrations"], list):
        raise MigrationManifestError("migration manifest `migrations` must be a list")
    return data


def find_migration_entry(manifest: Dict[str, Any], current_version: str) -> Optional[Dict[str, Any]]:
    """Find migration entry whose `from:` matches current_version. Returns None if no match.

    Per the foundation-versioning policy migration manifest schema: target-owned + directional;
    each migration declares `from:` (range/exact) + the metadata fields."""
    for m in manifest.get("migrations", []):
        if not isinstance(m, dict):
            continue
        from_spec = str(m.get("from", ""))
        if _is_semver_match(from_spec, current_version):
            return m
    return None


def migration_entry_from_dict(d: Dict[str, Any]) -> MigrationEntry:
    """Coerce a raw migration dict to a MigrationEntry dataclass."""
    return MigrationEntry(
        from_version=str(d.get("from", "")),
        migration_class=str(d.get("class", "unknown")),
        requires_operator_approval=d.get("requires_operator_approval", "not_applicable"),
        stop_condition=str(d.get("stop_condition", "")),
        breaking_changes_summary=str(d.get("breaking_changes_summary", "")),
        supported=bool(d.get("supported", False)),
        preflight=d.get("preflight", "not_applicable"),
        rollback=d.get("rollback", "not_applicable"),
        migration_steps=d.get("migration_steps", "not_applicable"),
        stabilization_exemption=str(d.get("stabilization_exemption", "")),
    )


# ===== Drift detection (non-destructive planning only at v0) =====

def _plan_action_for(status: str, merge_strategy: str) -> str:
    """Human-readable plan action per v0 merge_strategy semantics (F-1 ratified).

    NO automatic apply at v0 — every action describes a plan, not an execution."""
    if status == DRIFT_NONE:
        return "no action; file matches base_hash"
    if status == DRIFT_MISSING_FILE:
        return f"managed file missing; merge_strategy={merge_strategy}; operator must restore or accept removal (review required)"
    # status == DRIFT_DETECTED
    if merge_strategy == MERGE_STRATEGY_THREE_WAY:
        return ("drift detected; the apply path section-merges your non-overlapping edits "
                "with the new version automatically and saves any conflicting section to a "
                "review folder (your version is never overwritten)")
    if merge_strategy == MERGE_STRATEGY_OPERATOR_REVIEW:
        return "drift detected; operator review required; no automatic resolution at v0"
    if merge_strategy == MERGE_STRATEGY_WARN_ON_DRIFT:
        return "drift detected; explicit operator acknowledgement required; local content preserved unless explicitly approved"
    if merge_strategy == MERGE_STRATEGY_CONTROL_PLANE_REFRESH:
        return ("drift detected on a wizard-authored guidance file; your version is kept "
                "and the refreshed version is saved for review (never overwritten)")
    if merge_strategy == MERGE_STRATEGY_FROZEN:
        return "drift detected on frozen file; hard block — upgrade refused until drift resolved"
    return f"drift detected; unknown merge_strategy={merge_strategy}; review required"


def resolve_merge_strategy(
    target_entry: Optional[Dict[str, Any]],
    manifest_strategy: str,
    default: str = MERGE_STRATEGY_OPERATOR_REVIEW,
) -> str:
    """Resolve a managed file's merge_strategy with TARGET-CONTRACT PRECEDENCE.

    The apply trusts the target bundle's system-artifacts.json over the operator's
    (possibly stale) manifest; the PLAN must resolve identically (same function) so it
    never warns the operator that a file is at overwrite-risk when the apply will
    actually preserve it (Plan/apply consistency — plan must not lie about the apply).
    Order: the target contract entry's merge_strategy, then the manifest's recorded
    strategy, then `default`.
    """
    if target_entry:
        s = str(target_entry.get("merge_strategy", "")).strip()
        if s:
            return s
    if manifest_strategy:
        return str(manifest_strategy)
    return default


def compute_drift_report(
    operator_project_dir: Path,
    operator_manifest: Dict[str, Any],
    target_bundle_version: Optional[str] = None,
    target_contract: Optional[Dict[str, Any]] = None,
) -> DriftReport:
    """Compute drift report for an operator project against its current base_hashes.

    For each entry in operator_manifest['managed_files'] (or operator_manifest['files']):
        - Compute current hash of file in operator_project_dir
        - Compare against recorded base_hash + current_hash_last_seen
        - Classify per merge_strategy with v0 non-destructive plan action

    Returns DriftReport; raises OperatorManifestError on malformed entries.
    """
    files_block = operator_manifest.get("files") or operator_manifest.get("managed_files") or {}
    if not isinstance(files_block, dict):
        raise OperatorManifestError("manifest files/managed_files block must be a dict")

    entries: List[DriftReportEntry] = []
    for rel_path, meta in files_block.items():
        if not isinstance(meta, dict):
            raise OperatorManifestError(f"managed_files['{rel_path}'] must be a dict")
        base_hash = meta.get("base_hash", "")
        base_content_hash = meta.get("base_content_hash", "")
        # Target-contract precedence (Fork 1(c)): when a target contract is supplied, the
        # plan resolves merge_strategy exactly as the apply does, so a stale manifest value
        # cannot make the plan mislabel what the apply will do. Falls back to the manifest's
        # recorded strategy (current behavior) when no contract is passed.
        merge_strategy = resolve_merge_strategy(
            (target_contract or {}).get(rel_path), meta.get("merge_strategy", ""))
        local_mods = meta.get("local_modifications", "")
        abs_path = operator_project_dir / rel_path
        if not abs_path.exists():
            entries.append(DriftReportEntry(
                path=rel_path, base_hash=base_hash, current_hash="",
                status=DRIFT_MISSING_FILE, merge_strategy=merge_strategy,
                local_modifications=local_mods,
                plan_action=_plan_action_for(DRIFT_MISSING_FILE, merge_strategy),
            ))
            continue
        current_hash_hex = sha256_file(abs_path)
        current_hash = f"sha256:{current_hash_hex}"
        if base_content_hash.startswith("sha256:"):
            # Reconciled with apply_upgrade (which keys drift off base_content_hash):
            # compare the CONTENT-normalized hash (write-only foundation_schema_version
            # value blanked) so a pure schema-version frontmatter bump — left on the live
            # file when an upgrade advances base_hash to a content-unchanged target
            # render — is NOT reported as operator drift. Falls back to the full base_hash
            # for legacy manifests that predate base_content_hash.
            current_content_hash = "sha256:" + sha256_bytes(
                normalize_for_content_hash(abs_path.read_text(encoding="utf-8")).encode("utf-8"))
            status = DRIFT_NONE if current_content_hash == base_content_hash else DRIFT_DETECTED
        elif base_hash.startswith("sha256:") and base_hash[len("sha256:"):] == current_hash_hex:
            status = DRIFT_NONE
        elif base_hash == "" or base_hash == current_hash:
            status = DRIFT_NONE
        else:
            status = DRIFT_DETECTED
        entries.append(DriftReportEntry(
            path=rel_path, base_hash=base_hash, current_hash=current_hash,
            status=status, merge_strategy=merge_strategy, local_modifications=local_mods,
            plan_action=_plan_action_for(status, merge_strategy),
        ))

    return DriftReport(
        operator_project_path=str(operator_project_dir),
        bundle_version=operator_manifest.get("foundation_bundle_version", ""),
        target_bundle_version=target_bundle_version,
        entries=entries,
    )


# ===== Upgrade-check =====

def _lookup_target_migration(
    registry_path: Path,
    target_entry: Dict[str, Any],
    current_version: str,
    registry: Optional[Dict[str, Any]] = None,
) -> MigrationEntry:
    """Shared helper used by compute_upgrade_check + compute_upgrade_plan.

    Resolves target bundle dir + loads target migration-manifest.json + finds the matching
    `from:` entry. Fail-closed on any gap (per the foundation-versioning policy upgrade-check
    contract requiring migration metadata at upgrade-check time AND upgrade-plan time).

    Bundle-dir resolution is registry-relative + layout-agnostic (build-repo + public-clone);
    callers pass the already-loaded `registry` so the schema_version branch is honored without
    re-reading the file."""
    target_bundle_dir = _resolve_bundle_dir(registry_path, target_entry, registry=registry)
    migration_json = target_bundle_dir / MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME
    if not migration_json.exists():
        raise MigrationManifestError(
            f"target bundle directory at {target_bundle_dir} missing "
            f"{MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME} JSON sidecar"
        )
    manifest_data = load_migration_manifest(migration_json)
    raw = find_migration_entry(manifest_data, current_version)
    if raw is None:
        raise MigrationManifestError(
            f"target version {target_entry.get('foundation_bundle_version', '')!r} migration manifest "
            f"has no `from:` entry matching current version {current_version!r}"
        )
    return migration_entry_from_dict(raw)


def compute_upgrade_check(
    operator_project_dir: Path,
    operator_manifest: Dict[str, Any],
    registry: Dict[str, Any],
    registry_path: Optional[Path] = None,
) -> UpgradeCheckResult:
    """Compute `wizard upgrade-check` result per the foundation-versioning policy upgrade-check command.

    Returns UpgradeCheckResult with:
      - current_version: from operator manifest
      - available_targets: registry entries with version > current (filtered + semver-sorted +
        per-target migration metadata when registry_path provided)
      - drift_report: per-file drift status
      - standing_approval_status: always STANDING_APPROVAL_STATUS_UNAVAILABLE at v0

    Per the foundation-versioning policy § 9.1 step 4-5, when registry_path is provided this function
    also reads each newer target's migration-manifest.json + surfaces migration_class /
    requires_operator_approval / stop_condition / breaking_changes_summary / supported as fields
    on each available_targets entry. Fail-closed on missing manifest or missing matching `from:` entry.
    """
    current_version = operator_manifest.get("foundation_bundle_version", "")
    drift_report = compute_drift_report(operator_project_dir, operator_manifest)

    current_tuple = parse_semver(current_version)
    available: List[Dict[str, Any]] = []
    if current_tuple is not None:
        for entry in registry["bundles"]:
            version = entry.get("foundation_bundle_version", "")
            entry_tuple = parse_semver(version)
            if entry_tuple is None or entry_tuple <= current_tuple:
                continue
            target_record: Dict[str, Any] = {
                "foundation_bundle_version": version,
                "release_date": entry.get("release_date", ""),
                "status": entry.get("status", ""),
                "tier": classify_tier(current_version, version),
                "manifest_path": entry.get("manifest", ""),
            }
            if registry_path is not None:
                me = _lookup_target_migration(registry_path, entry, current_version, registry=registry)
                # Per the v0.4.0 release slice-level R2 advisor finding (HIGH):
                # target-owned migration manifest is authoritative when available.
                # Override semver-arithmetic tier with the migration manifest's class
                # because semver minor-bump does NOT imply minor-additive class — pre-v1
                # major-breaking changes can land on a minor-version bump.
                target_record["tier"] = me.migration_class
                target_record["semver_delta_tier"] = classify_tier(current_version, version)
                target_record["migration_class"] = me.migration_class
                target_record["requires_operator_approval"] = me.requires_operator_approval
                target_record["supported"] = me.supported
                target_record["stop_condition"] = me.stop_condition
                target_record["breaking_changes_summary"] = me.breaking_changes_summary
                target_record["stabilization_exemption"] = me.stabilization_exemption
            available.append(target_record)
        # Sort available targets semver-ascending so render order is deterministic + lowest target first.
        # load_registry guarantees every entry's version parses, so parse_semver returns a tuple (not None).
        available.sort(key=lambda e: parse_semver(e["foundation_bundle_version"]) or (0, 0, 0))

    notes: List[str] = []
    if current_tuple is None:
        notes.append(f"current_version={current_version!r} is not parseable as semver; no targets surfaced")
    if drift_report.has_drift:
        notes.append(
            f"drift detected on {drift_report.drift_count} file(s); "
            f"patch-class upgrades escalate to review-required per § 4.3 (no standing approval available)"
        )
    notes.append(
        f"standing_approval_status={STANDING_APPROVAL_STATUS_UNAVAILABLE} — "
        "every upgrade requires explicit operator approval at v0 "
        "(standing auto-approval is disabled at v0 per the foundation-versioning policy)"
    )

    return UpgradeCheckResult(
        operator_project_path=str(operator_project_dir),
        current_version=current_version,
        available_targets=available,
        drift_report=drift_report,
        standing_approval_status=STANDING_APPROVAL_STATUS_UNAVAILABLE,
        notes=notes,
    )


# ===== Upgrade plan (plan-only at v0) =====

def compute_upgrade_plan(
    operator_project_dir: Path,
    operator_manifest: Dict[str, Any],
    target_version: str,
    registry: Dict[str, Any],
    registry_path: Optional[Path] = None,
) -> UpgradePlan:
    """Compute plan-only upgrade per the foundation-versioning policy upgrade command.

    Reads the target version's migration-manifest.json + finds the matching `from:` entry
    + surfaces requires_operator_approval / stop_condition / breaking_changes_summary / supported
    in the returned UpgradePlan.migration_entry field. Fail-closed if no matching entry.

    Raises BundleNotFoundError if target_version absent from registry.
    Raises MigrationManifestError if migration manifest cannot be loaded or lacks `from:` entry
        matching operator's current version.
    """
    current_version = operator_manifest.get("foundation_bundle_version", "")
    target_entry = find_bundle_entry(registry, target_version)
    if target_entry is None:
        raise BundleNotFoundError(f"target version {target_version!r} not in registry")

    # Load the target bundle's managed-artifacts contract so the PLAN resolves
    # merge_strategy with the SAME target-contract precedence as the apply (Fork 1(c));
    # otherwise a stale operator manifest would make the plan mislabel a file the apply
    # will actually operator_review (sidecar-and-preserve). Fail-soft: a foundation-only
    # target (no contract) or an unreadable contract leaves target_contract=None, which
    # falls back to the manifest-recorded strategy (current behavior).
    target_contract = None
    if registry_path is not None and target_entry.get("path"):
        # Registry-relative, layout-agnostic (build-repo + public-clone). Was a fixed
        # `registry_path.parents[2] / entry["path"]` join that re-prepended the build-repo
        # `wizard/` prefix and broke in the prefix-stripped public clone (F-OR-4).
        _contract_path = resolve_bundle_dir(registry_path, registry, target_entry) / "system-artifacts.json"
        if _contract_path.is_file():
            try:
                _c = json.loads(_contract_path.read_text(encoding="utf-8"))
                target_contract = {
                    e["relpath"]: e for e in _c.get("artifacts", [])
                    if e.get("delivery") == "wizard" and e.get("relpath")
                }
            except (json.JSONDecodeError, OSError):
                target_contract = None
    drift_report = compute_drift_report(
        operator_project_dir, operator_manifest, target_version, target_contract=target_contract)
    semver_delta_tier = classify_tier(current_version, target_version)
    tier = semver_delta_tier  # default to semver arithmetic; overridden below if migration manifest available

    migration_entry: Optional[MigrationEntry] = None
    if registry_path is not None:
        migration_entry = _lookup_target_migration(registry_path, target_entry, current_version, registry=registry)
        # Per the v0.4.0 release slice-level R2 advisor finding (HIGH):
        # target-owned migration manifest is authoritative when available.
        # Override semver-arithmetic tier with the migration manifest's class because
        # semver minor-bump does NOT imply minor-additive class — pre-v1 major-breaking
        # changes can land on a minor-version bump (e.g., v0.3.0 → v0.4.0 = major-breaking
        # per the v0.4.0 stabilization-exempted schema refactor, NOT semver-minor-additive).
        tier = migration_entry.migration_class

    steps: List[str] = []
    steps.append(f"v0 plan-only: upgrade-from={current_version} upgrade-to={target_version} tier={tier}")
    if drift_report.has_drift:
        steps.append(
            f"drift detected on {drift_report.drift_count} file(s); "
            "patch-class upgrades escalate to review-required per § 4.3"
        )
    else:
        steps.append("no drift detected on managed files")
    if migration_entry is not None:
        steps.append(
            f"migration entry from={migration_entry.from_version} class={migration_entry.migration_class} "
            f"requires_operator_approval={migration_entry.requires_operator_approval} supported={migration_entry.supported}"
        )
        if migration_entry.breaking_changes_summary:
            steps.append(f"breaking_changes_summary: {migration_entry.breaking_changes_summary}")
        if migration_entry.stop_condition:
            steps.append(f"stop_condition: {migration_entry.stop_condition[:200]}{'...' if len(migration_entry.stop_condition) > 200 else ''}")
    else:
        steps.append("migration manifest lookup: SKIPPED (no registry_path provided to compute_upgrade_plan)")
    steps.append("preflight check: REQUIRED (operator review of every file; no standing approval at v0)")
    steps.append("post-validation: REQUIRED (operator confirmation that target version applied cleanly)")
    steps.append(
        f"TO APPLY: {UpgradePlan.__dataclass_fields__['apply_blocked_reason'].default}"
    )

    return UpgradePlan(
        operator_project_path=str(operator_project_dir),
        from_version=current_version,
        to_version=target_version,
        tier=tier,
        drift_report=drift_report,
        standing_approval_status=STANDING_APPROVAL_STATUS_UNAVAILABLE,
        migration_entry=migration_entry,
        planned_steps=steps,
        requires_review=True,
        plan_only=True,
    )


# ===== Provenance (11-field content-addressed strict-receipt schema) =====

def emit_provenance(
    bundle_dir: Path,
    source_bundle_version: str,
    bundle_file_manifest: List[Dict[str, str]],
    registry_path: Path,
    template_tree_dir: Path,
    generator_commit_sha: str,
    worktree_clean: bool,
    strict_mode: bool,
    strict_mode_source: str,
    generated_at_iso: str,
) -> Dict[str, Any]:
    """Build a foundation-bundle.provenance.json content record (11-field schema per F-4).

    Returns the dict; caller writes to disk via `json.dump` with sort_keys=True + indent=2.

    Notes:
        - `generated_at_iso` is METADATA ONLY; NOT included in any content hash
        - When this provenance file is itself emitted, it must be EXCLUDED from any
          `output_hash` computation downstream (avoids circularity per F-4)
    """
    registry_bytes = registry_path.read_bytes() if registry_path.exists() else b""
    source_registry_entry_hash = sha256_bytes(registry_bytes)

    if template_tree_dir.exists() and template_tree_dir.is_dir():
        template_tree_hash = hash_subtree(template_tree_dir)
    else:
        template_tree_hash = "absent"

    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "source_bundle_version": source_bundle_version,
        "source_registry_entry_hash": f"sha256:{source_registry_entry_hash}",
        "template_tree_hash": template_tree_hash if template_tree_hash == "absent" else f"sha256:{template_tree_hash}",
        "bundle_file_manifest": bundle_file_manifest,
        "worktree_clean": worktree_clean,
        "strict_mode": strict_mode,
        "strict_mode_source": strict_mode_source,
        "generator_version": generator_commit_sha,
        "generated_at": generated_at_iso,
    }


def hash_subtree(root: Path) -> str:
    """Hash a directory subtree (sorted by relative path; canonicalized per file).

    Returns hex digest of SHA-256 over concatenated `<relpath>\\0<filehash>\\n` entries.
    """
    if not root.exists() or not root.is_dir():
        return "absent"
    entries = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        h = sha256_file(p)
        entries.append(f"{rel}\x00{h}")
    payload = "\n".join(entries).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class BundleHashError(Exception):
    """Raised when a bundle's content hash cannot be computed: missing bundle dir / manifest,
    or a symlink in the tree. Integrity hashing fails closed rather than guessing."""


def compute_bundle_tree_sha256(bundle_dir: Path) -> str:
    """Canonical content hash of a bundle DIRECTORY for upgrade integrity (Option A+).

    Returns `sha256:` + the `hash_subtree` digest over the FULL bundle dir. The scope is the
    whole dir because the subtree publish copies it byte-identically to the operator's public
    clone (GATE-0, verified), so this EXPECTED value — recorded into the registry at build time
    and into the operator's approved UpdateResolution at check time — is reproducible when
    `self-update` re-hashes the FETCHED bundle to verify it matches what the operator approved.
    Canonicalized per file (via hash_subtree) so a Windows autocrlf git checkout still matches.

    Hashing the bundle's own `foundation-bundle.provenance.json` is NOT circular here: this
    digest lives in the REGISTRY / resolution, not inside the bundle, so it never feeds itself.

    REJECTS symlinks (F-H): a bundle is regular files only; a symlink is a fail-closed signal,
    never silently followed into content outside the bundle.
    """
    if not bundle_dir.is_dir():
        raise BundleHashError(f"bundle dir not found: {bundle_dir}")
    for p in sorted(bundle_dir.rglob("*")):
        if p.is_symlink():
            raise BundleHashError(
                f"bundle contains a symlink {p}; integrity hashing rejects symlinks (fail-closed)"
            )
    return "sha256:" + hash_subtree(bundle_dir)


def compute_bundle_manifest_sha256(bundle_dir: Path) -> str:
    """Canonical content hash of the bundle's apply-consumed migration manifest — defense in
    depth alongside the tree hash (lets self-update verify the manifest specifically). Returns
    `sha256:` + the canonicalized file digest. Fails closed if the manifest is absent."""
    manifest_path = bundle_dir / MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME
    if not manifest_path.is_file():
        raise BundleHashError(f"bundle manifest not found: {manifest_path}")
    return "sha256:" + sha256_file(manifest_path)


def hash_bundle_files(bundle_dir: Path, exclude: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Build a bundle_file_manifest list (path + canonicalized hash) for provenance.

    `exclude` defaults to [PROVENANCE_FILENAME] to avoid circular self-hashing per F-4.
    """
    if exclude is None:
        exclude = [PROVENANCE_FILENAME]
    if not bundle_dir.exists():
        return []
    result: List[Dict[str, str]] = []
    for p in sorted(bundle_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(bundle_dir).as_posix()
        if rel in exclude or any(rel.endswith(ex) for ex in exclude):
            continue
        h = sha256_file(p)
        result.append({"path": rel, "hash": f"sha256:{h}"})
    return result


# ===== Per-artifact upgrade analysis =====

def _artifact_risk_and_how(
    merge_strategy: str,
    drift_status: str,
    is_new: bool,
) -> tuple:
    """Derive (risk, how) labels from merge_strategy + drift for the analysis display.

    Returns plain-language strings the operator reads before deciding to apply.
    """
    if is_new:
        return (
            "installed as-is (new file, no existing version to conflict with)",
            "The file will be installed fresh into your system.",
        )
    if merge_strategy == MERGE_STRATEGY_THREE_WAY:
        if drift_status == DRIFT_NONE:
            return (
                "clean adopt",
                "The updated version will be installed automatically -- no edits to reconcile.",
            )
        else:
            return (
                "will merge your edits (or save for your review if they overlap)",
                "Your edits will be carried forward where possible; any overlap is saved for your review.",
            )
    if merge_strategy == MERGE_STRATEGY_OPERATOR_REVIEW:
        return (
            "saved for your review; your version kept",
            "The new version is placed in a review folder. Your existing file stays in place.",
        )
    if merge_strategy == MERGE_STRATEGY_WARN_ON_DRIFT:
        if drift_status in (DRIFT_DETECTED, DRIFT_MISSING_FILE):
            return (
                "will warn -- needs your OK (--ack) to replace",
                "You have edited this file. The upgrade will stop unless you pass --ack to confirm replacing it.",
            )
        else:
            return (
                "installed as-is",
                "The updated version will be installed automatically.",
            )
    if merge_strategy == MERGE_STRATEGY_FROZEN:
        if drift_status in (DRIFT_DETECTED, DRIFT_MISSING_FILE):
            return (
                "blocked -- drift on a frozen file must be resolved first",
                "This file must not be edited. Resolve the drift before applying the upgrade.",
            )
        else:
            return (
                "clean adopt",
                "The updated version will be installed automatically -- no edits to reconcile.",
            )
    # Unknown strategy fallback
    return (
        "review required",
        "Review this file manually before applying.",
    )


def compute_upgrade_analysis(
    change_set: List[Any],
    migration_manifest: Dict[str, Any],
) -> List["ArtifactAnalysis"]:
    """Build the per-artifact upgrade analysis from the TARGET-CHANGE SET.

    The analysis is over what the TARGET version adds/modifies versus the operator's
    current version — NOT the operator's local drift. The `change_set` is produced by
    the apply engine's read-only `compute_target_change_set` (which reuses the apply
    path's render + surface computation); this function is the presentation JOIN that
    adds the plain-language benefit (from the migration-manifest artifact_notes) and
    the at-risk / how-applied labels (from each entry's merge_strategy + the operator's
    drift state on that file). It does NOT mutate anything or touch disk.

    Args:
        change_set        -- list of change entries, each exposing the attributes
                             `relpath`, `what` ("new"|"modified"), `render_kind`
                             ("render"|"copy"), `merge_strategy`, and `drift_status`
                             (the operator's local drift on the file: DRIFT_NONE for a
                             new file). Produced by `compute_target_change_set`.
        migration_manifest -- the raw migration-manifest dict (already loaded); may
                             carry an optional top-level "artifact_notes" map keyed by
                             relpath with a plain-language `benefit`.

    Returns one ArtifactAnalysis per change-set entry, sorted by relpath, each with all
    display fields populated. Files the target does NOT change never appear (they are
    not in the change set).
    """
    artifact_notes: Dict[str, Dict[str, Any]] = {}
    if isinstance(migration_manifest, dict):
        raw_notes = migration_manifest.get("artifact_notes")
        if isinstance(raw_notes, dict):
            artifact_notes = raw_notes

    result: List[ArtifactAnalysis] = []
    for entry in sorted(change_set, key=lambda e: e.relpath):
        relpath = entry.relpath
        what = entry.what if entry.what in ("new", "modified") else "modified"
        is_new = (what == "new")

        kind = str(getattr(entry, "render_kind", "copy") or "copy")
        if kind not in ("render", "copy"):
            kind = "copy"

        merge_strategy = str(getattr(entry, "merge_strategy", "") or MERGE_STRATEGY_OPERATOR_REVIEW)
        drift_status = str(getattr(entry, "drift_status", DRIFT_NONE) or DRIFT_NONE)

        # benefit -- from migration-manifest artifact_notes, or a neutral default.
        note = artifact_notes.get(relpath)
        if isinstance(note, dict) and note.get("benefit"):
            benefit = str(note["benefit"])
        else:
            filename = relpath.split("/")[-1]
            benefit = f"Improvement to your system's {filename}."

        risk, how = _artifact_risk_and_how(merge_strategy, drift_status, is_new)

        result.append(ArtifactAnalysis(
            relpath=relpath,
            what=what,
            kind=kind,
            benefit=benefit,
            risk=risk,
            how=how,
        ))

    return result


# ===== Pretty-printing for CLI =====
# (Build-side JSON sidecar emission lives at `wizard/scripts/lib/sidecar_emit.py`;
#  this module stays pure-read engine for the operator runtime CLI.)

def render_upgrade_check(result: UpgradeCheckResult) -> str:
    """Human-readable CLI output for `wizard upgrade-check`."""
    lines = [
        "Foundation bundle upgrade check (v0 plan-only)",
        f"  operator_project_path: {result.operator_project_path}",
        f"  current_version:       {result.current_version}",
        f"  standing_approval:     {result.standing_approval_status}",
        "",
    ]
    if result.available_targets:
        lines.append("Available target versions:")
        for entry in result.available_targets:
            lines.append(
                f"  - {entry['foundation_bundle_version']} "
                f"(release_date={entry.get('release_date', 'n/a')}; "
                f"status={entry.get('status', 'n/a')}; tier={entry['tier']})"
            )
    else:
        lines.append("Available target versions: none (current_version is latest in registry)")
    lines.append("")
    if result.drift_report is not None:
        if result.drift_report.has_drift:
            lines.append(f"Drift detected ({result.drift_report.drift_count} file(s)):")
        else:
            lines.append("Drift status: none (all managed files match base_hash)")
        for e in result.drift_report.entries:
            if e.status != DRIFT_NONE:
                lines.append(f"  - {e.path}: {e.status} (merge_strategy={e.merge_strategy})")
                lines.append(f"      plan: {e.plan_action}")
    lines.append("")
    lines.append("Notes:")
    for n in result.notes:
        lines.append(f"  - {n}")
    return "\n".join(lines) + "\n"


def render_upgrade_plan(plan: UpgradePlan) -> str:
    """Human-readable CLI output for `wizard upgrade --to <version> --plan-only`."""
    lines = [
        "Foundation bundle upgrade plan (plan-only preview; run with --apply to apply)",
        f"  operator_project_path: {plan.operator_project_path}",
        f"  from_version:          {plan.from_version}",
        f"  to_version:            {plan.to_version}",
        f"  tier:                  {plan.tier}",
        f"  standing_approval:     {plan.standing_approval_status}",
        f"  requires_review:       {plan.requires_review}",
        f"  plan_only:             {plan.plan_only}",
        "",
        "Planned steps:",
    ]
    for s in plan.planned_steps:
        lines.append(f"  - {s}")
    lines.append("")
    if plan.drift_report.has_drift:
        lines.append(f"Drift report ({plan.drift_report.drift_count} file(s) drift):")
        for e in plan.drift_report.entries:
            if e.status != DRIFT_NONE:
                lines.append(f"  - {e.path}: {e.status} (merge_strategy={e.merge_strategy})")
                lines.append(f"      plan: {e.plan_action}")
    else:
        lines.append("Drift report: clean (no drift on managed files)")
    lines.append("")
    if plan.artifact_analysis:
        lines.append("Per-file upgrade analysis:")
        lines.append(
            f"  {'File':<45}  {'What':<10}  {'Kind':<8}  {'At risk':<45}  Benefit"
        )
        lines.append(f"  {'-'*45}  {'-'*10}  {'-'*8}  {'-'*45}  {'-'*30}")
        for a in plan.artifact_analysis:
            filename = a.relpath.split("/")[-1]
            lines.append(
                f"  {a.relpath:<45}  {a.what:<10}  {a.kind:<8}  {a.risk:<45}  {a.benefit}"
            )
            lines.append(f"      How applied: {a.how}")
        lines.append("")
    lines.append(f"Apply blocked reason: {plan.apply_blocked_reason}")
    return "\n".join(lines) + "\n"


def upgrade_check_to_dict(r: UpgradeCheckResult) -> Dict[str, Any]:
    """Convert UpgradeCheckResult to a JSON-emittable dict (for `--json` CLI output)."""
    return asdict(r)


def upgrade_plan_to_dict(p: UpgradePlan) -> Dict[str, Any]:
    """Convert UpgradePlan to a JSON-emittable dict (for `--json` CLI output).

    The returned dict includes an `artifact_analysis` list when the plan carries one.
    Each analysis entry has stable keys: relpath, what, kind, benefit, risk, how.
    """
    d = asdict(p)
    # asdict handles ArtifactAnalysis dataclasses in artifact_analysis automatically;
    # ensure the key is always present (empty list when no analysis attached).
    if "artifact_analysis" not in d:
        d["artifact_analysis"] = []
    return d
