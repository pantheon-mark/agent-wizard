"""Capability third-party dependency enrollment (Cut 1.4, Task 5 / F-9).

The problem this closes
------------------------
An emitted operator project's ``requirements.txt`` was a STATIC comment-only
template declaring "stdlib only", and the ``.venv`` bootstrap
(``start_session_template.sh``'s "Python venv bootstrap" section) installs
only what that file declares — nothing. But a capability's adapter module
(the one ``capability_code_scaffold.py`` scaffolds, or a hand-completed one)
can need a real third-party vendor SDK — for example, ``import
googleapiclient`` for a Google integration. Before this module existed there
was NO mechanism anywhere that recorded a third-party package a capability
needed: not ``CapabilityCodeSpec``, not the ``add-capability`` flow, not the
F-76 operator-adapter manifest (module stems only), not an ADR. The result:
a clean-session resume's ``.venv`` could not import the SDK the capability's
own code required, and the build agent had no prescribed way to fix that —
this was a next-phase TODO with no package placeholder.

The fix (mirrors F-76's segregation pattern)
---------------------------------------------
This module is invoked by the build agent — from ``add-capability.md`` /
``next-phase.md`` — at the MOMENT it writes a vendor ``import`` into a
capability's adapter code, on an EXISTING project (not just at fresh-emit
time, so it reaches an already-built estate via the normal build/next-phase
re-flow). It:

  1. Resolves the vendor **import name** to its real pip **package name**
     (see `IMPORT_TO_PACKAGE` — import name is not always package name:
     ``googleapiclient`` -> ``google-api-python-client``).
  2. Resolves an exact **pinned version** for that package (`resolve_
     dependency_version` — a real network call by default; tests inject
     their own resolver).
  3. Records the pin in a SEGREGATED per-project manifest,
     ``operator_requirements.json`` — a plain JSON array of `{import_name,
     package_name, version, capability_id}` objects, living beside
     `registered_adapters.py`'s own `operator_adapters.json` (same
     directory, same rationale): NEVER part of `agent_emitter.py`'s
     `_EXTERNAL_WRITE_LIB_FILES` bundle-copy set, so a contract-changing
     upgrade's wholesale re-copy of the lib files can never drop an
     operator's enrolled dependency.
  4. Re-renders `requirements.txt` from the manifest — MERGING, never
     clobbering: any package line an operator (or an earlier, non-enrollment
     path) already added directly to `requirements.txt` survives the
     re-render untouched (see `render_requirements_txt`).
  5. Installs every enrolled package's exact pin into the project's own
     `.venv/` immediately (`install_dependencies`) — BEFORE any proof/test
     run — and, on success, snapshots the FULL transitive closure actually
     installed to `operator_requirements.lock` (top-level pins alone allow
     transitive drift; see Locked design #6).
  6. Records a plain-language, append-only audit line (what was installed,
     when) to `operator_requirements_audit.log` — honesty, not a gate (#8).

Idempotent, fail-isolated failure state (Locked design #7)
------------------------------------------------------------
The manifest write (steps 1-4 above) and the install (step 5) are
DELIBERATELY separable. If the manifest update succeeds but `pip install`
fails (no network, a yanked version, a transient registry outage, ...), the
enrollment is NOT lost and NOT left in a silent half-state: the caller gets
back `environment_satisfied=False` and a `detail` message meant to be
relayed VERBATIM as "dependency enrolled, environment unsatisfied: <detail>"
-- and a clean retry (calling `install_dependencies` again, or `enroll_and_
install` again with the same import) picks up exactly where it left off
-- the manifest entry is never duplicated (re-enrolling the same
`import_name` overwrites its own entry, not appends a sibling one).

Build-time stdlib lint (Locked design #9) -- reliability flag, NOT a gate
----------------------------------------------------------------------------
`lint_adapter_imports` flags a top-level import in an adapter module that is
NEITHER a standard-library module (`sys.stdlib_module_names`, a 3.10+
attribute — this project's `.venv` floor is 3.11, well above it) NOR already
enrolled in the manifest. This is an anti-drift reliability signal the build
agent can act on (per `feedback_match_enforcement_to_risk_class_not_guard_
theater`) — it is never wired as a trust/safety gate, and it never blocks a
write gate or an acceptance path.

Rejected alternative: pyproject.toml + `uv`/`poetry`
-------------------------------------------------------
Adds a toolchain dependency against the stdlib-only ethos this whole
`external_write` lib holds to, and against the non-technical operator bar (a
`uv`/`poetry` install is one more tool for a non-technical operator to have
installed and to reason about when something goes wrong). A controlled,
segregated JSON manifest plus a generated, fully-pinned lock snapshot is the
v0 answer instead.

Stdlib only — no third-party dependencies (this module itself never imports
anything it might be asked to enroll for someone else).

Trust zone: SEALED_KERNEL, by deliberate decision (Cut 1.4 Task 5 review fix)
------------------------------------------------------------------------------
This module shells out to pip (`pip index versions`, `pip install`, `pip
freeze` via `subprocess`) — a real network reach. That is registered as
SEALED_KERNEL in `zones.SEALED_KERNEL_MODULE_PATHS` (see that registry
entry's own comment for the full rationale), not left CAPABILITY (scan.py's
fail-closed default for an unregistered module) and not ADAPTER_PROFILE (the
zone reserved for per-vendor adapters that mutate the OPERATOR'S external
surface). The distinction: this module is TRUSTED build/maintenance
infrastructure that manages the project's OWN `.venv`/`requirements.txt` —
never a customer/vendor write. A capability's actual vendor mutation still
goes through the ordinary adapter/broker/write_gate path this zone protects;
this module never touches that path at all.

Before this registration, the module scanned clean under scan.py's rules by
ACCIDENT, not by decision: the subprocess_network check only flags a
shell-out that names a KNOWN network CLI tool (`curl`/`wget`/`scp`/... —
`scan._NETWORK_CLI_TOOLS`), and "pip" was never added to that list, so this
module passed regardless of its zone. Broadening that denylist to include
pip is a deliberate, separate follow-up (flagged, not done here, to avoid
introducing an FP-risk class-level tightening inside this task) — this
registration is what makes the zone an explicit, reviewed, tested decision
either way, not a scanner gap nobody looked at.

SEALED_KERNEL membership does NOT grant a capability the right to import this
module: the CAPABILITY-zone import allowlist
(`scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES`) is the independent,
narrow `{capability_api, operations, read_facade}` set — a capability
importing `external_write.dependency_enrollment` directly is already a
`sealed_kernel_import` violation under the existing A' module-boundary rule
(same as `capability_health.py`). This module is invoked ONLY via its own
CLI entrypoint (`__main__` block below), by the build agent from
`add-capability.md` / `next-phase.md` — never imported by emitted capability
code.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Filenames -- all segregated, sibling to F-76's operator_adapters.json, in
# the same external_write directory. NEVER part of agent_emitter.py's
# _EXTERNAL_WRITE_LIB_FILES bundle-copy set (see this module's own docstring).
# ---------------------------------------------------------------------------
MANIFEST_BASENAME = "operator_requirements.json"
LOCK_BASENAME = "operator_requirements.lock"
AUDIT_LOG_BASENAME = "operator_requirements_audit.log"
REQUIREMENTS_BASENAME = "requirements.txt"

DEFAULT_EXTERNAL_WRITE_REL = Path("agents/lib/external_write")
_VENV_REL = Path(".venv")

# The .venv floor this whole external_write lib already holds to
# (start_session_template.sh's PYTHON_FLOOR_MAJOR/MINOR) -- sys.stdlib_
# module_names requires 3.10+; this project's floor (3.11) clears it with
# room to spare, so no fallback/heuristic stdlib detection is needed.
PYTHON_FLOOR = (3, 11)

# Seed import-name -> PyPI package-name map (Locked design: import name is
# not always package name). A name absent here defaults to identity (import
# name == package name), which is the common case. Extend this table as new
# mismatches are discovered in the field -- it is plain data, not logic.
IMPORT_TO_PACKAGE: Dict[str, str] = {
    "googleapiclient": "google-api-python-client",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "google_auth_httplib2": "google-auth-httplib2",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "PIL": "Pillow",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "jwt": "PyJWT",
    "slugify": "python-slugify",
    "docx": "python-docx",
    "OpenSSL": "pyOpenSSL",
    "cv2": "opencv-python",
    "Crypto": "pycryptodome",
    "requests_oauthlib": "requests-oauthlib",
    "dns": "dnspython",
}

# The static preamble every emitted requirements.txt starts from -- MUST stay
# byte-identical to wizard/templates/root/requirements_template's own
# preamble (agent_emitter.py's own duplicate-content discipline; see that
# template file's header comment, and test_agent_emitter.py's pinning test
# for the enforced invariant). Duplicated here (not imported) because this
# module is EMITTED (ships inside the operator project's own tree) while the
# template lives in the wizard TOOLKIT's source tree -- the two are never on
# the same sys.path at runtime, so a literal copy, pinned by a byte-equality
# test, is the correct discipline (mirrors capability_code_scaffold.py's own
# _REGISTERED_ADAPTERS_BASELINE convention).
DEFAULT_PREAMBLE = (
    "# Python dependencies for this system's write-back components\n"
    "# (agents/lib/external_write/ and any capability code built on top of it).\n"
    "#\n"
    "# Installed automatically into this project's own .venv/ the first time you run\n"
    "# ./start-session.sh — see the \"Python venv bootstrap\" section of that script.\n"
    "# You never need to run pip yourself.\n"
    "#\n"
    "# Third-party packages a capability actually needs are declared below this\n"
    "# preamble, one per line, pinned to an exact version (e.g. requests==2.32.3).\n"
    "# None by default: a system where no capability has needed one leaves this\n"
    "# file exactly as you see it. When a capability's code needs a package, it is\n"
    "# added here automatically -- resolved, pinned, and installed before any code\n"
    "# that imports it ever runs -- never by hand-editing this file yourself. See\n"
    "# agents/lib/external_write/dependency_enrollment.py and its sibling manifest,\n"
    "# agents/lib/external_write/operator_requirements.json.\n"
    "#\n"
    "# This file's mere presence is what tells the wizard this system has a Python\n"
    "# component at all: a system with none does not carry this file, and its\n"
    "# session startup script skips the whole venv/interpreter-pin sequence.\n"
)


def resolve_package_name(import_name: str) -> str:
    """Vendor import name -> pip package name (Locked design: these are not
    always the same string). Unknown import names default to identity."""
    return IMPORT_TO_PACKAGE.get(import_name, import_name)


class DependencyEnrollmentError(Exception):
    """Raised when resolving a package/version fails BEFORE anything is
    written -- a plain-language, fixable problem, never a raw traceback."""


class DependencyInstallError(Exception):
    """The manifest was updated (enrollment succeeded) but `.venv` pip
    install failed. Carries `detail` -- the caller relays exactly "dependency
    enrolled, environment unsatisfied: <detail>", never a silent half-state.
    A clean retry (re-running install, or `enroll_and_install` again) is
    always safe once the underlying problem is fixed -- the manifest entry
    this failure is attached to is never lost or duplicated by a retry."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"dependency enrolled, environment unsatisfied: {detail}")


# ---------------------------------------------------------------------------
# The manifest: operator_requirements.json
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DependencyEntry:
    import_name: str
    package_name: str
    version: str
    capability_id: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "import_name": self.import_name,
            "package_name": self.package_name,
            "version": self.version,
            "capability_id": self.capability_id,
        }

    @staticmethod
    def from_dict(d: dict) -> "DependencyEntry":
        return DependencyEntry(
            import_name=str(d["import_name"]),
            package_name=str(d["package_name"]),
            version=str(d["version"]),
            capability_id=str(d.get("capability_id", "")),
        )


def _warn(message: str) -> None:
    """Plain-language stderr warning -- never a raw traceback (mirrors
    registered_adapters.py's own `_warn_operator_manifest_problem`)."""
    print(f"WARNING: {message}", file=sys.stderr)


def load_manifest(external_write_dir: Path) -> List[DependencyEntry]:
    """Fail-isolated loader (mirrors `registered_adapters._load_operator_
    adapter_module_stems`): a MISSING manifest is a clean, silent empty list
    (most systems have none); a PRESENT but corrupt/unreadable/malformed one
    is surfaced with a named-file warning and degrades to whatever entries
    CAN be salvaged, never a crash and never a silent full loss with zero
    breadcrumb."""
    manifest_path = Path(external_write_dir) / MANIFEST_BASENAME
    if not manifest_path.is_file():
        return []
    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        _warn(f"dependency manifest {manifest_path} could not be read ({e}) -- "
              "treating as empty; any package enrolled only in this file will not "
              "install until the file is fixed.")
        return []
    try:
        data = json.loads(raw_text)
    except ValueError as e:
        _warn(f"dependency manifest {manifest_path} is not valid JSON ({e}) -- "
              "treating as empty.")
        return []
    if not isinstance(data, list):
        _warn(f"dependency manifest {manifest_path} is not a JSON array -- "
              "treating as empty.")
        return []
    entries: List[DependencyEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            entries.append(DependencyEntry.from_dict(item))
        except (KeyError, TypeError, ValueError) as e:
            _warn(f"dependency manifest {manifest_path} has one unreadable entry "
                  f"({e}) -- skipping it; every other entry is unaffected.")
    return entries


def _atomic_write_text(out_path: Path, text: str) -> None:
    """Write ``text`` to ``out_path`` atomically: a temp file in the SAME
    directory (so the final rename is same-filesystem, hence atomic), then
    ``os.replace``. A crash or interruption between the temp-file write and
    the rename leaves the ORIGINAL file (or its prior absence) completely
    untouched -- never a truncated/partial write. Stdlib-only and
    self-contained on purpose: this module is EMITTED (ships inside the
    operator project's own tree) and must not depend on the toolkit's own
    ``upgrade_reconcile.py::_atomic_write`` (same pattern, deliberately
    duplicated rather than imported -- see ``DEFAULT_PREAMBLE``'s own
    duplicate-content discipline note above for why an emitted module never
    imports across the toolkit/emitted boundary)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{MANIFEST_BASENAME}.", suffix=".tmp", dir=str(out_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(out_path))
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass
        raise


def save_manifest(external_write_dir: Path, entries: Sequence[DependencyEntry]) -> Path:
    """Idempotent, deterministic write: sorted by import_name so a re-write of
    an unchanged manifest is byte-identical (clean diffs, no spurious churn).
    Written atomically -- see ``_atomic_write_text`` -- so a crash mid-write
    can never truncate the operator's durable dependency record."""
    out_dir = Path(external_write_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / MANIFEST_BASENAME
    ordered = sorted(entries, key=lambda e: e.import_name)
    _atomic_write_text(
        out_path,
        json.dumps([e.to_dict() for e in ordered], indent=2, ensure_ascii=False) + "\n",
    )
    return out_path


def _upsert_entry(entries: Sequence[DependencyEntry], new_entry: DependencyEntry) -> List[DependencyEntry]:
    """Idempotent union: re-enrolling the same import_name REPLACES its own
    entry in place -- never appends a duplicate sibling."""
    return [e for e in entries if e.import_name != new_entry.import_name] + [new_entry]


# ---------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------

VersionResolver = Callable[[str], str]


_PIP_AVAILABLE_VERSIONS_RE = re.compile(r"Available versions:\s*([^\n]*)")


def default_version_resolver(package_name: str) -> str:
    """Live resolver: ask pip itself for the package's newest available
    version via ``pip index versions`` (a real pip subcommand) — a real
    network round trip, exactly like the install step already makes, but
    through `subprocess` rather than a direct HTTP-client import. Deliberate:
    this module lives under `agents/lib/external_write/`, where the build-time
    bypass scanner (`scan.py`) forbids importing a network-client library
    (`urllib`, `requests`, ...) directly — for the SAME reason a capability
    adapter is forbidden from doing so — so this default resolver reaches the
    network only through pip's own CLI, never through a raw HTTP import in
    this module's own source. Raises `DependencyEnrollmentError` with a
    plain-language, fixable message on any failure — callers that need
    determinism (tests; an offline build) inject their own `version_resolver`
    instead of using this default."""
    try:
        result = subprocess.run(  # noqa: S603 -- fixed argv, no shell, package_name only
            [sys.executable, "-m", "pip", "index", "versions", package_name],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise DependencyEnrollmentError(
            f"could not resolve a version for package {package_name!r}: pip could "
            f"not be run ({e}) -- fix step: check network access, or pin the exact "
            "version by hand and retry") from e

    combined = f"{result.stdout}\n{result.stderr}"
    match = _PIP_AVAILABLE_VERSIONS_RE.search(combined)
    if result.returncode != 0 or not match:
        detail = (result.stderr or result.stdout or "no output from pip").strip()
        raise DependencyEnrollmentError(
            f"could not resolve a version for package {package_name!r} via pip "
            f"({detail}) -- fix step: check network access, confirm the package "
            "name is correct, or pin the exact version by hand and retry")
    first_version = match.group(1).split(",")[0].strip()
    if not first_version:
        raise DependencyEnrollmentError(
            f"pip reported no available versions for package {package_name!r}")
    return first_version


# ---------------------------------------------------------------------------
# requirements.txt derivation (merge, never clobber -- Locked design #4)
# ---------------------------------------------------------------------------

_SPEC_SPLIT_RE = re.compile(r"[=<>!~\[; ]")


def _package_root(line: str) -> str:
    """The bare, PEP-503-normalized package name at the start of a
    requirements.txt line (before any ==/>=/[extra] specifier), for merge
    de-duplication. Case/dash/underscore/dot-insensitive, matching PyPI's own
    name normalization -- so `Google-API-Python-Client` and
    `google_api_python_client` are recognized as the same package."""
    stripped = line.strip()
    m = _SPEC_SPLIT_RE.search(stripped)
    if m:
        stripped = stripped[: m.start()]
    return re.sub(r"[-_.]+", "-", stripped).strip().lower()


def render_requirements_txt(preamble_text: str, entries: Sequence[DependencyEntry],
                            existing_text: Optional[str] = None) -> str:
    """Derive the full requirements.txt content: `preamble_text` verbatim,
    plus a generated enrolled-packages block from `entries`, plus any line
    already present in `existing_text` that is NOT already covered by an
    enrolled package (an operator-added, or otherwise pre-existing, package
    line -- preserved verbatim, never clobbered; the manifest wins only when
    the SAME package is named in both places, so it is never duplicated).

    Byte-identical to `preamble_text` alone when `entries` is empty AND
    `existing_text` carries no extra (non-comment, non-blank) lines --
    the back-compat invariant Step 2 of this task pins."""
    enrolled_roots = {_package_root(e.package_name) for e in entries}

    preserved_lines: List[str] = []
    if existing_text:
        for line in existing_text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if _package_root(s) in enrolled_roots:
                continue  # the manifest's own pin wins; do not duplicate
            preserved_lines.append(line.rstrip())

    if not entries and not preserved_lines:
        return preamble_text

    out = preamble_text if preamble_text.endswith("\n") else preamble_text + "\n"
    if entries:
        out += ("\n# Enrolled by capability code (see agents/lib/external_write/"
                "operator_requirements.json) -- do not hand-edit these lines; they are "
                "regenerated on the next enrollment.\n")
        for e in sorted(entries, key=lambda e: e.package_name.lower()):
            out += f"{e.package_name}=={e.version}\n"
    if preserved_lines:
        out += "\n# Added outside dependency enrollment -- preserved as-is.\n"
        for line in preserved_lines:
            out += f"{line}\n"
    return out


def _rewrite_requirements_txt(project_root: Path, entries: Sequence[DependencyEntry],
                              requirements_rel: Path, preamble_text: str) -> Path:
    requirements_path = Path(project_root) / requirements_rel
    existing_text = (requirements_path.read_text(encoding="utf-8")
                     if requirements_path.is_file() else None)
    rendered = render_requirements_txt(preamble_text, entries, existing_text)
    requirements_path.parent.mkdir(parents=True, exist_ok=True)
    requirements_path.write_text(rendered, encoding="utf-8")
    return requirements_path


# ---------------------------------------------------------------------------
# Enrollment (resolve + pin + manifest write + re-render) -- NEVER installs.
# ---------------------------------------------------------------------------

@dataclass
class EnrollmentResult:
    entries: List[DependencyEntry]
    manifest_path: Path
    requirements_path: Path
    package_name: str
    version: str


def enroll_dependency(project_root: Path, import_name: str, capability_id: str, *,
                      package_name: Optional[str] = None,
                      version_resolver: Optional[VersionResolver] = None,
                      preamble_text: str = DEFAULT_PREAMBLE,
                      external_write_rel: Path = DEFAULT_EXTERNAL_WRITE_REL,
                      requirements_rel: Path = Path(REQUIREMENTS_BASENAME)) -> EnrollmentResult:
    """Resolve `import_name` to a pip package + an exact pinned version,
    idempotently record it in `operator_requirements.json`, and re-render
    `requirements.txt` (merge, never clobber) -- WITHOUT installing anything
    (see `install_dependencies` / `enroll_and_install` for that half). Safe to
    call again for the same `import_name`: the manifest entry is replaced in
    place, never duplicated."""
    project_root = Path(project_root)
    external_write_dir = project_root / external_write_rel
    resolver = version_resolver or default_version_resolver
    resolved_package = package_name or resolve_package_name(import_name)
    version = resolver(resolved_package)

    entries = _upsert_entry(load_manifest(external_write_dir),
                            DependencyEntry(import_name=import_name,
                                            package_name=resolved_package,
                                            version=version,
                                            capability_id=capability_id))
    manifest_path = save_manifest(external_write_dir, entries)
    requirements_path = _rewrite_requirements_txt(project_root, entries, requirements_rel,
                                                  preamble_text)
    return EnrollmentResult(entries=entries, manifest_path=manifest_path,
                            requirements_path=requirements_path,
                            package_name=resolved_package, version=version)


# ---------------------------------------------------------------------------
# Install (.venv pip install) + the frozen transitive lock snapshot
# ---------------------------------------------------------------------------

InstallerFn = Callable[[Sequence[str]], "subprocess.CompletedProcess"]


def _venv_python(project_root: Path) -> Path:
    return Path(project_root) / _VENV_REL / "bin" / "python"


def _default_installer(args: Sequence[str]) -> "subprocess.CompletedProcess":
    return subprocess.run(list(args), capture_output=True, text=True)  # noqa: S603


@dataclass
class InstallResult:
    satisfied: bool
    detail: str
    lock_path: Optional[Path] = None


def install_dependencies(project_root: Path, entries: Sequence[DependencyEntry], *,
                         installer: Optional[InstallerFn] = None,
                         external_write_rel: Path = DEFAULT_EXTERNAL_WRITE_REL) -> InstallResult:
    """Install every enrolled entry's EXACT pin into `<project_root>/.venv`.
    Never raises for an ordinary pip failure (Locked design #7) -- that is a
    reportable, cleanly-retryable state, returned as `InstallResult(
    satisfied=False, detail=...)`, never a crash and never a silent
    half-state. On success, also snapshots the full transitive closure
    actually installed to `operator_requirements.lock` (Locked design #6) --
    a best-effort step that never turns a successful top-level install into a
    reported failure if the freeze step itself has trouble."""
    if not entries:
        return InstallResult(satisfied=True, detail="no third-party dependencies enrolled")

    installer = installer or _default_installer
    python_exe = _venv_python(project_root)
    if not python_exe.is_file():
        return InstallResult(
            satisfied=False,
            detail=f".venv not found at {python_exe} -- run ./start-session.sh first "
                   "to create it, then retry")

    pins = [f"{e.package_name}=={e.version}" for e in entries]
    result = installer([str(python_exe), "-m", "pip", "install", "--quiet",
                        "--disable-pip-version-check", *pins])
    if result.returncode != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "")
                 or "pip exited non-zero").strip()
        return InstallResult(satisfied=False, detail=detail)

    lock_path = _write_lock_file(project_root, installer, python_exe, external_write_rel)
    return InstallResult(satisfied=True, detail="installed", lock_path=lock_path)


def _write_lock_file(project_root: Path, installer: InstallerFn, python_exe: Path,
                     external_write_rel: Path) -> Optional[Path]:
    """Best-effort: `pip freeze`'s own output IS the frozen, fully-pinned
    transitive set (Locked design #6) -- a top-level pin alone allows
    transitive drift; this snapshot is what the operator's project actually
    has installed, byte for byte. A failure here never turns a successful
    top-level install into a reported failure -- the top-level pins in
    requirements.txt remain authoritative either way."""
    result = installer([str(python_exe), "-m", "pip", "freeze"])
    if result.returncode != 0:
        return None
    lock_path = Path(project_root) / external_write_rel / LOCK_BASENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(getattr(result, "stdout", "") or "", encoding="utf-8")
    return lock_path


# ---------------------------------------------------------------------------
# Audit note (Locked design #8 -- honesty, not a gate)
# ---------------------------------------------------------------------------

def record_audit_note(project_root: Path, message: str, *,
                      external_write_rel: Path = DEFAULT_EXTERNAL_WRITE_REL) -> Path:
    """Append one plain, human-readable, timestamped line to the
    operator-visible dependency audit log -- auto-install runs third-party
    code, so what was installed and when is recorded honestly. Best-effort:
    a failure to write the log never blocks or unwinds an enrollment that
    already succeeded."""
    log_path = Path(project_root) / external_write_rel / AUDIT_LOG_BASENAME
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {message}\n")
    except OSError as e:  # pragma: no cover -- best-effort, never fatal
        _warn(f"could not write dependency audit note to {log_path} ({e})")
    return log_path


# ---------------------------------------------------------------------------
# Orchestration: the one call the build agent makes
# ---------------------------------------------------------------------------

@dataclass
class EnrollAndInstallStatus:
    enrolled: bool
    environment_satisfied: bool
    message: str
    package_name: str
    version: str
    manifest_path: Path
    requirements_path: Path
    lock_path: Optional[Path] = None


def enroll_and_install(project_root: Path, import_name: str, capability_id: str, *,
                       package_name: Optional[str] = None,
                       version_resolver: Optional[VersionResolver] = None,
                       installer: Optional[InstallerFn] = None,
                       preamble_text: str = DEFAULT_PREAMBLE,
                       external_write_rel: Path = DEFAULT_EXTERNAL_WRITE_REL,
                       requirements_rel: Path = Path(REQUIREMENTS_BASENAME)) -> EnrollAndInstallStatus:
    """The single call `add-capability.md` / `next-phase.md` make the moment
    the build agent writes a vendor `import`: resolve, pin, enroll, re-render,
    then install immediately (Locked design #5) -- before any proof/test run.

    Enrollment (the manifest write + requirements.txt re-render) and install
    are separable and BOTH always attempted in this order: if install fails,
    the enrollment is NOT rolled back and NOT lost -- the returned status
    reports `enrolled=True, environment_satisfied=False` with a `message`
    that is exactly the idempotent-failure text this task requires:
    "dependency enrolled, environment unsatisfied: <detail>". Calling this
    again (a clean retry) never duplicates the manifest entry and, once
    whatever blocked pip is fixed, resolves cleanly to
    `environment_satisfied=True`."""
    result = enroll_dependency(project_root, import_name, capability_id,
                              package_name=package_name, version_resolver=version_resolver,
                              preamble_text=preamble_text, external_write_rel=external_write_rel,
                              requirements_rel=requirements_rel)

    install = install_dependencies(project_root, result.entries, installer=installer,
                                   external_write_rel=external_write_rel)

    if install.satisfied:
        message = f"dependency enrolled and installed: {result.package_name}=={result.version}"
    else:
        message = (f"dependency enrolled, environment unsatisfied: {install.detail}")

    record_audit_note(
        project_root,
        f"enroll {result.package_name}=={result.version} (import {import_name!r}, "
        f"capability {capability_id!r}) -- {'installed' if install.satisfied else 'install FAILED: ' + install.detail}",
        external_write_rel=external_write_rel,
    )

    return EnrollAndInstallStatus(
        enrolled=True,
        environment_satisfied=install.satisfied,
        message=message,
        package_name=result.package_name,
        version=result.version,
        manifest_path=result.manifest_path,
        requirements_path=result.requirements_path,
        lock_path=install.lock_path,
    )


# ---------------------------------------------------------------------------
# Build-time stdlib lint (Locked design #9 -- reliability flag, NOT a gate)
# ---------------------------------------------------------------------------

def _top_level_import_names(source: str) -> List[str]:
    """Every root module name a `import`/`from ... import` statement in
    `source` names, anywhere in the file (not scope-restricted -- an adapter
    that imports inside a function still needs the package installed).
    ``import googleapiclient.discovery`` and ``from googleapiclient.discovery
    import build`` both yield the root name ``googleapiclient``. A syntax
    error in `source` is surfaced as an empty result (nothing to lint) rather
    than a raised exception -- this is a reliability lint, never a gate that
    could itself crash the build on malformed input."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # a relative import names no top-level module at all
            if node.module:
                names.append(node.module.split(".")[0])
    return names


def _stdlib_module_names() -> frozenset:
    """`sys.stdlib_module_names` (3.10+; this project's `.venv` floor is
    3.11, well above it -- see this module's own docstring)."""
    return sys.stdlib_module_names  # type: ignore[attr-defined]


# Local, first-party package roots that exist inside every emitted operator
# project's own tree (see capability_code_scaffold.py's own DEFAULT_EXTERNAL_
# WRITE_REL) -- an adapter's `from external_write.X import Y` names a sibling
# project module, never a vendor dependency, so it is never lint-flagged as
# one regardless of the manifest's contents.
LOCAL_FIRST_PARTY_ROOTS = frozenset({"external_write"})


def lint_adapter_imports(source: str, enrolled_import_names: Iterable[str],
                         *, also_known_local: Iterable[str] = LOCAL_FIRST_PARTY_ROOTS) -> List[str]:
    """Flag every top-level import name in `source` that is NEITHER a
    standard-library module, NOR a known local first-party project package
    (`also_known_local`), NOR already present in `enrolled_import_names`
    (typically every `DependencyEntry.import_name` in the current manifest).
    Sorted, de-duplicated. A reliability/anti-drift signal ONLY -- see this
    module's docstring; never wired as a trust gate."""
    stdlib = _stdlib_module_names()
    enrolled = set(enrolled_import_names) | set(also_known_local)
    flagged = {
        name for name in _top_level_import_names(source)
        if name not in stdlib and name not in enrolled and name not in sys.builtin_module_names
    }
    return sorted(flagged)


def lint_adapter_file(adapter_path: Path, external_write_dir: Path) -> List[str]:
    """Convenience wrapper: lint the adapter module at `adapter_path` against
    the manifest already recorded at `external_write_dir`."""
    source = Path(adapter_path).read_text(encoding="utf-8")
    enrolled_import_names = [e.import_name for e in load_manifest(external_write_dir)]
    return lint_adapter_imports(source, enrolled_import_names)


# ---------------------------------------------------------------------------
# CLI wrapper -- add-capability's / next-phase's build cascade invokes this
# the moment the build agent writes a vendor `import`. Exits 0 when enrolled
# AND installed, 1 when enrolled but the environment is unsatisfied (a clean
# retry is always safe), 2 on a usage/resolve problem (nothing was written).
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _args = _sys.argv[1:]
    _opts = {"--import-name": None, "--capability-id": None, "--project-root": ".",
             "--package-name": None, "--lint": None}
    _usage = ("Usage: dependency_enrollment.py --import-name <name> --capability-id <id> "
              "--project-root <path> [--package-name <pip-name>]\n"
              "   or: dependency_enrollment.py --lint <adapter.py> --project-root <path>")
    _i = 0
    while _i < len(_args):
        _a = _args[_i]
        if _a in _opts:
            if _i + 1 >= len(_args):
                print(_usage, file=_sys.stderr)
                _sys.exit(2)
            _opts[_a] = _args[_i + 1]
            _i += 2
        else:
            print(f"unknown argument {_a!r}\n{_usage}", file=_sys.stderr)
            _sys.exit(2)

    _project_root = Path(_opts["--project-root"] or ".")

    if _opts["--lint"]:
        _flagged = lint_adapter_file(
            Path(_opts["--lint"]), _project_root / DEFAULT_EXTERNAL_WRITE_REL)
        if _flagged:
            print("FLAGGED (not stdlib, not enrolled -- reliability check, not a gate):")
            for _name in _flagged:
                print(f"  {_name}")
        else:
            print("No unenrolled non-stdlib imports found.")
        _sys.exit(0)

    if not _opts["--import-name"] or not _opts["--capability-id"]:
        print(_usage, file=_sys.stderr)
        _sys.exit(2)

    try:
        _status = enroll_and_install(
            _project_root, _opts["--import-name"], _opts["--capability-id"],
            package_name=_opts["--package-name"])
    except DependencyEnrollmentError as _e:
        print(f"REFUSED: {_e}", file=_sys.stderr)
        _sys.exit(2)

    print(_status.message)
    print(f"  manifest:     {_status.manifest_path}")
    print(f"  requirements: {_status.requirements_path}")
    if _status.lock_path is not None:
        print(f"  lock:         {_status.lock_path}")
    _sys.exit(0 if _status.environment_satisfied else 1)
