"""The trust-zone taxonomy — SINGLE canonical place both ``scan.py`` (the AST
bypass scanner) and ``coverage_gate.py`` (the descriptor-coverage gate) read
to decide which trust zone a module belongs to (Task 5 —
external-write-gate-generalization slice).

------------------------------------------------------------------------------
Why a three-zone split (replaces the old "whole external_write/ tree is
exempt" rule)
------------------------------------------------------------------------------
Prior to this task, ``scan.py`` exempted every file inside the installed
``agents/lib/external_write/`` directory from every bypass check — one
binary distinction (inside the package == trusted; outside == scanned in
full). That was fine while the package held only the surface-agnostic gate
machinery, but it does not survive the package growing concrete, per-vendor
adapter modules: those modules MUST legitimately import a vendor SDK, obtain
a write-capable credential, and perform raw vendor mutation, while every
OTHER module in the package must NOT be able to do any of those three
things. A single "inside the package" exemption cannot express that split.

So the trust boundary is split into three zones:

  SEALED_KERNEL    -- the gate machinery itself: ``run_operation`` (in
                      adapters.py), the write gate + invocation ledger (in
                      write_gate.py), the broker, receipt validation, the
                      operation/contract/proof-hash/effects-manifest layers,
                      the adapter registry, the read facade, the AST scanner
                      and coverage gate, and the acceptance/verification
                      support modules. This code is surface-agnostic by
                      design (see contracts.py, operations.py) and must
                      NEVER need a vendor SDK import or a write-capable
                      credential. It is therefore held to the SAME bypass
                      checks as ordinary capability code (forbidden_import,
                      direct_api_call, dynamic_import, subprocess_network,
                      credential_construction) -- it is not a free pass, it
                      simply never trips them because it never needs to.

  ADAPTER_PROFILE   -- registered, per-vendor adapter modules (e.g. the
                      eventual Gmail/Sheets/etc. adapter modules -- Task 7+).
                      This is the ONLY zone allowed to import a vendor SDK,
                      construct/obtain a write-capable credential, and
                      perform raw vendor mutation. It is exempt from every
                      check scan.py enforces.

  CAPABILITY        -- everything else: operator capability/proposal/read
                      scripts, and -- critically -- any module that is not
                      EXPLICITLY enumerated in either allowlist below, even
                      if it physically lives inside the installed package
                      directory. This is the fail-closed default: an
                      unclassifiable module is always treated as the most
                      restrictive zone, never silently granted a pass.

------------------------------------------------------------------------------
Zone membership is EXPLICIT, never "anything under this path"
------------------------------------------------------------------------------
A prior review of this gate's history flagged exactly this failure mode
once already (see scan.py's "Allowed-module identity" section: exemption
used to be keyed on a directory NAME appearing anywhere in the path, which
was spoofable). This task removes a SECOND, more subtle version of the same
failure mode: if adapter-profile membership were decided by "any file under
external_write/adapters/", a newly created adapter directory would be
blanket-exempted from every check the moment it exists, before a human ever
looked at what is inside it -- the exact bug class this taxonomy exists to
prevent, one level down.

Both allowlists below are therefore enumerated by RELATIVE PATH (from the
kernel anchor), not by directory membership. A file is SEALED_KERNEL or
ADAPTER_PROFILE iff (a) it resolves to a location under the anchor AND (b)
its path relative to the anchor is literally listed in the corresponding
frozenset. Adding a new file under the package directory does not exempt it
from anything until its relative path is deliberately added to one of these
sets -- and doing that is a reviewable, textual, one-line diff.

Stdlib only -- no third-party dependencies.
"""

import json
from enum import Enum
from pathlib import Path
from typing import FrozenSet, Optional, Union


class Zone(Enum):
    """The three trust zones. See module docstring."""

    SEALED_KERNEL = "sealed_kernel"
    ADAPTER_PROFILE = "adapter_profile"
    CAPABILITY = "capability"


# ---------------------------------------------------------------------------
# SEALED_KERNEL -- the gate machinery. Enumerated explicitly (relative path
# from the package anchor), not "everything in this directory". Every file
# that currently exists in agents/lib/external_write/ is gate machinery (no
# concrete adapter module has landed yet -- that is Task 7+), so this list is,
# for now, the complete file listing of the installed package; it does NOT
# grow automatically when a new file is added (see module docstring).
# ---------------------------------------------------------------------------
SEALED_KERNEL_MODULE_PATHS: FrozenSet[str] = frozenset(
    {
        "__init__.py",
        "acceptance_ceremony.py",
        "adapter_registry.py",
        "adapters.py",
        "boundary.py",
        "broker.py",
        "capability_registration.py",
        "contracts.py",
        "copy_run_proof.py",
        "coverage_gate.py",
        "effects_manifest.py",
        "operations.py",
        "operator_acceptance.py",
        "proof_hash.py",
        "read_facade.py",
        # registered_adapters.py (Task 7 / F-37 — v0.13.0 Slice 2): the
        # build-emitted static adapter registry `operator_acceptance.py`
        # imports at module scope so the operator-acceptance CLI is turnkey.
        # It exists SOLELY to import adapter modules (adapters_gmail.py, and
        # any capability-added adapters_<id>.py) at module scope -- exactly
        # the "registry's own intended kernel-side consumer" rationale
        # already given for adapters.py/effects_manifest.py above, so it is
        # exempt from the CAPABILITY-zone-ONLY adapter_module_import rule the
        # same way they are.
        "registered_adapters.py",
        # run_envelope.py — the v0.12.0 RunEnvelope trust core. It legitimately
        # wraps the raw kernel primitive run_operation (the ONE place the
        # run-level envelope — disk-authoritative spendability, consent-receipt
        # binding, APPLY-BY-ID against the frozen reviewed_set, and the
        # AGGREGATE CEILING — is enforced around it). It is kernel machinery,
        # exactly like adapters.py / write_gate.py, so it belongs in
        # SEALED_KERNEL and is exempt from the CAPABILITY-zone-ONLY
        # raw_run_operation_reference rule scan.py enforces (a capability
        # module reaching run_operation directly would bypass that envelope).
        "run_envelope.py",
        "scan.py",
        "verification_modes.py",
        "verifiers.py",
        "write_gate.py",
        "zones.py",
        # standing_automation.py (Task 9 / B2 / F-42 — v0.13.0 Slice 2): the safe
        # standing-automation entrypoint primitive. Its --check/--dry-run path
        # legitimately calls raw `run_operation(..., target="dry_run")` — reusing
        # the SAME code path a live run eventually uses rather than a separate
        # fake check surface (the operator-originated-enhancement flow's
        # pre-acceptance test-surface amendment) — so it needs the
        # same SEALED_KERNEL exemption from the CAPABILITY-zone-ONLY
        # raw_run_operation_reference rule that run_envelope.py already carries
        # (see that entry's rationale above). It never authorizes or performs a
        # LIVE write itself (the live branch calls the caller-supplied
        # `run_live`, never `run_operation`), so it does not need — and does not
        # get — the ADAPTER_PROFILE exemption.
        "standing_automation.py",
    }
)

# ---------------------------------------------------------------------------
# ADAPTER_PROFILE -- registered per-vendor adapter modules. Deliberately NOT
# a directory rule: a build or test wiring that needs a DIFFERENT set (e.g.
# an isolated test fixture tree) passes its own frozenset explicitly via the
# `adapter_profile_paths` parameter of `classify_zone` / `scan_paths` /
# `run_coverage_gate` rather than mutating this module-level default.
#
# "adapters_gmail.py" (Task 7 — external-write-gate-generalization slice) is
# the first real entry: the reference Gmail verb-shaped adapter, proving the
# generalized gate against a real vendor API shape. This is the ONE-LINE,
# reviewable diff the module docstring above describes -- the file is exempt
# from every check scan.py enforces ONLY because its relative path is
# deliberately listed here, never merely because of where it lives on disk.
# ---------------------------------------------------------------------------
_BASE_ADAPTER_PROFILE_MODULE_PATHS: FrozenSet[str] = frozenset({"adapters_gmail.py"})

# ---------------------------------------------------------------------------
# Capability-added ADAPTER_PROFILE entries (Task 10 — external-write-gate-
# generalization slice; "gate-wired by construction"). A capability added
# AFTER the initial build (through the add-capability skill, long after this
# module was already installed into an operator's project) cannot practically
# hand-edit this frozenset literal the way Task 7 did for adapters_gmail.py --
# there is no human maintainer available to make that one-line diff at
# add-capability time; the operator is non-technical and the skill must land
# it BY CONSTRUCTION with zero manual wiring.
#
# So the effective ADAPTER_PROFILE allowlist is the hardcoded base set above
# UNION whatever is declared in a sibling, deliberately-reviewable JSON file:
# <this module's own directory>/adapter_profile_registry.json -- a plain JSON
# array of relative filenames. wizard/scripts/lib/capability_code_scaffold.py
# (the deterministic emitter add-capability's build cascade invokes for a
# writes-back capability) appends the new adapter module's filename there
# when it emits it; it never edits THIS file's source. This is still the same
# "explicit, reviewable, one-line diff" shape the module docstring above
# describes -- a git diff of the registry file shows exactly the one line
# added -- it is simply written by the deterministic emitter instead of by
# hand.
#
# Fail-closed: a missing, unreadable, malformed, non-list, or non-string-
# entry registry file resolves to NO additional paths (never an exception,
# never a silent grant of something unintended) -- the same disclosed-bound
# spirit as every other fail-closed default in this package. A file that is
# not listed here (and not in SEALED_KERNEL_MODULE_PATHS) is CAPABILITY, the
# most restrictive zone, exactly as before.
# ---------------------------------------------------------------------------
_ADAPTER_PROFILE_REGISTRY_FILENAME = "adapter_profile_registry.json"


def _load_extra_adapter_profile_paths(lib_dir: Path) -> FrozenSet[str]:
    """Fail-closed loader for capability-added ADAPTER_PROFILE entries.

    Reads ``<lib_dir>/adapter_profile_registry.json`` -- a plain JSON array of
    relative filenames. Returns an empty frozenset (never raises) when the
    file is absent, unreadable, not valid JSON, not a JSON array, or contains
    a non-string / empty entry (that one entry is simply skipped, not fatal
    to the rest -- fail-closed per-entry, not fail-open on the whole file).
    """
    registry_path = Path(lib_dir) / _ADAPTER_PROFILE_REGISTRY_FILENAME
    if not registry_path.is_file():
        return frozenset()
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return frozenset()
    if not isinstance(data, list):
        return frozenset()
    return frozenset(p for p in data if isinstance(p, str) and p)


def effective_adapter_profile_paths(lib_dir: Optional[Path] = None) -> FrozenSet[str]:
    """The full ADAPTER_PROFILE allowlist for the ``external_write`` package
    rooted at `lib_dir`: the hardcoded base set (``adapters_gmail.py``) UNION
    any capability-added entries declared in
    ``<lib_dir>/adapter_profile_registry.json`` (see the module-level
    docstring block above this function for the full rationale).

    `lib_dir` defaults to THIS module's own installed directory (the real
    package anchor -- mirrors ``scan.py``'s ``_default_kernel_anchor``) when
    omitted, so production callers that read the ``ADAPTER_PROFILE_MODULE_PATHS``
    module constant below (computed by calling this function with no
    argument, once, at import time) get the fully merged set with zero code
    changes -- a capability the emitter adds after this module was first
    imported in a given process is picked up on the process's next start,
    the same "read once, not per-call" cadence this module already had.

    A caller building/testing against an arbitrary directory (e.g. a golden-
    emit test writing into a temporary project) passes its own `lib_dir`
    explicitly instead of relying on the process-wide default.
    """
    anchor = Path(lib_dir) if lib_dir is not None else Path(__file__).resolve().parent
    return _BASE_ADAPTER_PROFILE_MODULE_PATHS | _load_extra_adapter_profile_paths(anchor)


ADAPTER_PROFILE_MODULE_PATHS: FrozenSet[str] = effective_adapter_profile_paths()


def _resolve_relative(file_path: Path, anchor: Path) -> Union[str, None]:
    """Return file_path's POSIX path relative to anchor, or None if file_path
    does not resolve to a location under anchor at all."""
    resolved = file_path.resolve()
    try:
        is_under = resolved.is_relative_to(anchor)
    except AttributeError:  # pragma: no cover - py<3.9 fallback
        try:
            resolved.relative_to(anchor)
            is_under = True
        except ValueError:
            is_under = False
    if not is_under:
        return None
    return resolved.relative_to(anchor).as_posix()


def classify_zone(
    file_path: Union[str, Path],
    kernel_anchor: Path,
    *,
    sealed_kernel_paths: FrozenSet[str] = SEALED_KERNEL_MODULE_PATHS,
    adapter_profile_paths: FrozenSet[str] = ADAPTER_PROFILE_MODULE_PATHS,
) -> Zone:
    """Classify ``file_path`` into one of the three trust zones.

    Fail-closed (acceptance criterion: "unknown/unclassifiable module =>
    fail-closed, treated as capability"): a file that is not explicitly
    listed in ``sealed_kernel_paths`` or ``adapter_profile_paths`` is
    CAPABILITY -- the most restrictive zone -- regardless of whether it
    physically lives under ``kernel_anchor``. Physical location under the
    anchor is NECESSARY but never SUFFICIENT for SEALED_KERNEL or
    ADAPTER_PROFILE membership; the relative path must also be explicitly
    enumerated. This is what stops a new file (or a whole new adapter
    directory) from being silently exempted the moment it is created under
    the package -- see module docstring.
    """
    rel = _resolve_relative(Path(file_path), kernel_anchor)
    if rel is None:
        return Zone.CAPABILITY
    if rel in sealed_kernel_paths:
        return Zone.SEALED_KERNEL
    if rel in adapter_profile_paths:
        return Zone.ADAPTER_PROFILE
    return Zone.CAPABILITY
