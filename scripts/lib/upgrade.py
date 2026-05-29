"""Foundation-bundle upgrade engine — plan-only at v0.

Library module for `wizard upgrade-check` + `wizard upgrade --to <version> --plan-only`.
Engine functions + data records; argparse shim lives in `wizard/scripts/wizard_upgrade.py`.

Stdlib-only — no PyYAML, no third-party deps. JSON sidecars are the runtime contract
surface; YAML manifests are human-facing companions. Operator-side CLI consumes
`.wizard/manifest.json` only at v0 (YAML+JSON sync emitted by generator-side
`wizard/scripts/generate_bundle.py`; emit-side `.wizard/` sidecar emission into
operator projects lands at the next foundation-bundle emission release).

v0 scope:
    - Plan-only at v0; no apply path; the next emission release lands apply.
    - Non-destructive drift planning; no merge-apply at v0.
    - Standing approval fully disabled at v0; CLI reports
      `unavailable_idq_050_open` regardless of `excluded_when:` content.
    - Library-first split: engine here + argparse shim in wizard_upgrade.py.

Authority: the foundation-versioning policy (canonical implementation reference).
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
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

STANDING_APPROVAL_STATUS_UNAVAILABLE = "unavailable_idq_050_open"
"""v0 sentinel: CLI reports this regardless of `excluded_when:` content.
Full normative § 6.2 eligibility evaluation activates when operator-authority-profile generation resolves."""

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

# Operator-project manifest schema versions.
#   manifest-v1: legacy / foundation-docs-only manifests (no manifest_schema_version field).
#   manifest-v2: full-tree-ownership manifests emitted by the operator-system pipeline.
MANIFEST_SCHEMA_V1 = "manifest-v1"
MANIFEST_SCHEMA_V2 = "manifest-v2"

_MERGE_STRATEGIES = {
    MERGE_STRATEGY_THREE_WAY, MERGE_STRATEGY_OPERATOR_REVIEW,
    MERGE_STRATEGY_WARN_ON_DRIFT, MERGE_STRATEGY_FROZEN,
}
_LOCAL_MODIFICATIONS = {"expected", "allowed", "not_recommended"}

# Drift status
DRIFT_NONE = "no_drift"
DRIFT_DETECTED = "drift_detected"
DRIFT_MISSING_FILE = "managed_file_missing"

# Semver regex (vMAJOR.MINOR.PATCH; pre-v1 vN.M[.P] tolerated)
SEMVER_PATTERN = re.compile(r"^v(\d+)\.(\d+)(?:\.(\d+))?(?:-[a-zA-Z0-9.-]+)?$")


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
    """Raised when `wizard upgrade --to <version>` invoked without `--plan-only` flag at v0.

    At v0: plan-only; apply path lands at the next foundation-bundle emission release.
    """


class MigrationManifestError(UpgradeError):
    """Raised when target version's migration manifest cannot be loaded or lacks required `from:` entry."""


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
class UpgradePlan:
    """Plan-only upgrade record. No apply path at v0."""
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
        "v0: apply path lands at the next foundation-bundle emission release; "
        "--plan-only required at v0"
    )


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


def _resolve_bundle_dir(registry_path: Path, entry: Dict[str, Any]) -> Path:
    """Resolve the bundle directory path from a registry entry.

    Entry's `path` is repo-relative. Anchor strategy (in priority order):
      1. Walk up from registry_path looking for a `.git` directory → use that as repo root.
      2. Otherwise fall back to registry_path's parent (best-effort; test fixture path).
    """
    start = registry_path.resolve().parent
    for candidate in [start] + list(start.parents):
        if (candidate / ".git").exists():
            repo_root = candidate
            break
    else:
        repo_root = start
    rel = entry.get("path", "")
    return repo_root / rel if rel else repo_root


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
        return "drift detected; v0 reports candidate diff; refuses automatic apply (full three_way merge semantics deferred to follow-on slice)"
    if merge_strategy == MERGE_STRATEGY_OPERATOR_REVIEW:
        return "drift detected; operator review required; no automatic resolution at v0"
    if merge_strategy == MERGE_STRATEGY_WARN_ON_DRIFT:
        return "drift detected; explicit operator acknowledgement required; local content preserved unless explicitly approved"
    if merge_strategy == MERGE_STRATEGY_FROZEN:
        return "drift detected on frozen file; hard block — upgrade refused until drift resolved"
    return f"drift detected; unknown merge_strategy={merge_strategy}; review required"


def compute_drift_report(
    operator_project_dir: Path,
    operator_manifest: Dict[str, Any],
    target_bundle_version: Optional[str] = None,
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
        merge_strategy = meta.get("merge_strategy", MERGE_STRATEGY_OPERATOR_REVIEW)
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
        if base_hash.startswith("sha256:") and base_hash[len("sha256:"):] == current_hash_hex:
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
) -> MigrationEntry:
    """Shared helper used by compute_upgrade_check + compute_upgrade_plan.

    Resolves target bundle dir + loads target migration-manifest.json + finds the matching
    `from:` entry. Fail-closed on any gap (per the foundation-versioning policy upgrade-check
    contract requiring migration metadata at upgrade-check time AND upgrade-plan time)."""
    target_bundle_dir = _resolve_bundle_dir(registry_path, target_entry)
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
                me = _lookup_target_migration(registry_path, entry, current_version)
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
        "all upgrades require explicit operator approval at v0 "
        "(operator-authority-profile generation unresolved)"
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

    drift_report = compute_drift_report(operator_project_dir, operator_manifest, target_version)
    semver_delta_tier = classify_tier(current_version, target_version)
    tier = semver_delta_tier  # default to semver arithmetic; overridden below if migration manifest available

    migration_entry: Optional[MigrationEntry] = None
    if registry_path is not None:
        migration_entry = _lookup_target_migration(registry_path, target_entry, current_version)
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
        f"APPLY PATH NOT AVAILABLE AT v0: {UpgradePlan.__dataclass_fields__['apply_blocked_reason'].default}"
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
        "Foundation bundle upgrade plan (v0 plan-only; no apply path)",
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
    lines.append(f"Apply blocked reason: {plan.apply_blocked_reason}")
    return "\n".join(lines) + "\n"


def upgrade_check_to_dict(r: UpgradeCheckResult) -> Dict[str, Any]:
    """Convert UpgradeCheckResult to a JSON-emittable dict (for `--json` CLI output)."""
    return asdict(r)


def upgrade_plan_to_dict(p: UpgradePlan) -> Dict[str, Any]:
    """Convert UpgradePlan to a JSON-emittable dict (for `--json` CLI output)."""
    return asdict(p)
