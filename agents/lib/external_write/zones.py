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

from enum import Enum
from pathlib import Path
from typing import FrozenSet, Union


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
        "scan.py",
        "verification_modes.py",
        "verifiers.py",
        "write_gate.py",
        "zones.py",
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
ADAPTER_PROFILE_MODULE_PATHS: FrozenSet[str] = frozenset({"adapters_gmail.py"})


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
