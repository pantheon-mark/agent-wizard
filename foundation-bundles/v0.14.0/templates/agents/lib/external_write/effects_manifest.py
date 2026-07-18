"""Per-`op_kind` effects manifest — the hash-bound authority.

Previously, `proof_hash.compute_implementation_hash` hashed only a FIXED module
tuple (`contracts._WRITE_AFFECTING_MODULES` — `adapters.py`, `broker.py`,
`operations.py`, `verifiers.py`). That tuple is the shared plumbing every
op_kind runs through, but it structurally EXCLUDES a capability's own
registered adapter module (`adapter_registry.get_adapter(op_kind)`).
An adapter could be edited in place and the accepted-write identity would not
change: exactly the in-place-edit hole the whole proof-hash mechanism exists to
close.

This module is the fix: it builds, per op_kind, an `EffectsManifest` — a
single declarative record of everything that determines the op's behavior and
identity — and `dependency_files` is computed as the contract's declared
`dependency_set` **UNION** the op_kind's registered adapter module (if any).
`proof_hash.compute_implementation_hash` now hashes THIS list, not the bare
contract-declared set, so a byte changed in a capability's own adapter module
changes that capability's `implementation_hash` and drops it off the accepted
list.

Scope note: this module and its tests are generic — proven against a
throwaway fixture adapter (`wizard/test_fixtures/effects_manifest/
fixture_adapter.py`), never against Gmail specifics; the real Gmail verb
adapter lives elsewhere.

Enforcement ceiling: build-time + operator-as-approver, NOT a runtime/OS
guarantee (same ceiling as proof_hash.py and contracts.py).

Stdlib only — no third-party dependencies.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from external_write.adapter_registry import get_adapter
from external_write.contracts import get_contract, get_verifier


class ManifestBuildError(Exception):
    """Raised when a manifest cannot be built or does not pass structural
    validation (fail-closed — mirrors proof_hash.ProofHashError)."""


def _adapter_module_file(adapter: Any) -> Optional[str]:
    """Resolve the absolute source-file path of `adapter`'s defining module.

    Returns None if the module or its `__file__` cannot be resolved (e.g. a
    hand-built test stub with no real backing file). That is treated as "this
    adapter contributes no additional dependency file", not a build failure —
    `adapter_registry.Adapter` is a structural Protocol and does not require a
    real on-disk module (see e.g. `_StubAdapter` in
    test_external_write_adapter_registry.py).
    """
    module_name = type(adapter).__module__
    module = sys.modules.get(module_name)
    if module is None:
        return None
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return None
    return str(Path(module_file).resolve())


def _adapter_effect_unit_path(adapter: Any) -> Optional[str]:
    """A dotted `module.QualName` reference to the registered adapter class —
    i.e. where this op_kind's EffectUnits are actually planned/applied. None
    when no adapter is registered (the op_kind uses the legacy field-write
    path, which has no EffectUnit-producing adapter)."""
    module_name = type(adapter).__module__
    qualname = type(adapter).__qualname__
    if not module_name:
        return None
    return f"{module_name}.{qualname}"


def resolve_dependency_files(op_kind: str) -> Tuple[str, ...]:
    """Return the sorted tuple of write-affecting files for `op_kind`: the
    contract's declared `dependency_set` (bare filenames, resolved against a
    `lib_dir` root at hash time — unchanged, backward-compatible behavior)
    UNION the absolute path of `op_kind`'s registered adapter module, if any
    (closing the in-place-edit hole above). Fail-closed on an unregistered op_kind.
    """
    c = get_contract(op_kind)
    if c is None:
        raise ManifestBuildError(
            f"operation kind {op_kind!r} has no registered contract"
        )
    files = set(c.dependency_set)
    adapter = get_adapter(op_kind)
    if adapter is not None:
        module_file = _adapter_module_file(adapter)
        if module_file is not None:
            files.add(module_file)
    return tuple(sorted(files))


def unresolvable_adapter_seal_gap(op_kind: str) -> Optional[str]:
    """Fail-closed guard for a caller (the acceptance ceremony) that
    must REFUSE rather than mint a trust seal it knows does not cover the
    real writer.

    `_adapter_module_file` can fail to resolve a registered adapter's
    defining module (e.g. a dynamically-loaded or hand-stubbed adapter whose
    `__module__` names nothing in `sys.modules`, or a module with no
    `__file__`) -- in that case `resolve_dependency_files` /
    `proof_hash.compute_implementation_hash` silently EXCLUDE the adapter
    from the hashed dependency set (see `_adapter_module_file`'s own
    docstring: "treated as this adapter contributes no additional
    dependency file, not a build failure"). That is the correct call for a
    structural Protocol stub used in a unit test, but it is exactly the
    hole at the TRUST surface: a proof's stored `implementation_hash` and the
    ceremony's own freshly recomputed one would AGREE with each other while
    both are blind to the adapter's bytes, so hash-equality checking alone
    can never detect this -- the two hashes were never covering the real
    writer in the first place.

    Returns a human-readable reason string IFF op_kind has a registered
    adapter whose module file cannot be resolved. Returns None when there is
    no registered adapter at all (nothing to seal -- the legacy field-write
    path is unaffected) or when the registered adapter's module resolves
    normally (the seal is complete).
    """
    adapter = get_adapter(op_kind)
    if adapter is None:
        return None
    if _adapter_module_file(adapter) is not None:
        return None
    return (
        f"operation kind {op_kind!r} has a registered adapter "
        f"({type(adapter).__module__}.{type(adapter).__qualname__}) whose "
        "defining module's source file could not be resolved -- "
        "implementation_hash would silently EXCLUDE this adapter from the "
        "tamper-seal; refusing rather than accepting a seal that "
        "does not cover the real writer"
    )


@dataclass(frozen=True)
class EffectsManifest:
    """The per-op_kind hash-bound authority record.

    Attributes
    ----------
    op_kind:           The operation kind this manifest describes.
    params_schema:     Optional declared schema for the op's runtime params.
                       None until a verb-shaped adapter declares one (a hook
                       for a later task; no adapter declares this yet).
    effect_unit_path:  Dotted `module.QualName` of the registered adapter
                       class that plans/applies this op_kind's EffectUnits, or
                       None if no adapter is registered (legacy field-write
                       path).
    cap_default:       The op_kind's default blast-radius cap
                       (`contract.blast_radius_cap`), or None for no inherent
                       cap.
    allowed_mutations: The field(s)/range(s) this op is allowed to change
                       (`contract.writes`).
    undo:              Optional undo descriptor. None until a verb-shaped
                       adapter declares one (a hook for a later task).
    verifiers:         The verifier_ids this op accepts (`contract.verifier_set`).
    dependency_files:  The resolved write-affecting files for this op_kind —
                       see `resolve_dependency_files`. Mixed shape by design:
                       bare filenames (resolved against a `lib_dir` root at
                       hash time, for the static declared dependency_set) and
                       absolute paths (for a registered adapter module, which
                       must hash correctly regardless of `lib_dir`).
    implementation_hash: sha256 over `dependency_files` + the resolved
                       contract canon + runtime params — identical to
                       `proof_hash.compute_implementation_hash(op_kind)`; see
                       that function's docstring for the exact algorithm. This
                       manifest does not reinvent that hashing (DRY).
    """

    op_kind: str
    params_schema: Optional[Mapping[str, Any]]
    effect_unit_path: Optional[str]
    cap_default: Optional[int]
    allowed_mutations: Tuple[str, ...]
    undo: Optional[Mapping[str, Any]]
    verifiers: Tuple[str, ...]
    dependency_files: Tuple[str, ...]
    implementation_hash: str


def build_manifest(op_kind: str, *, lib_dir: Optional[Path] = None,
                    runtime_params: Optional[dict] = None) -> EffectsManifest:
    """Build the EffectsManifest for `op_kind`. Fail-closed on an unregistered
    op_kind. Validates the built manifest before returning it (see
    `validate_manifest`)."""
    c = get_contract(op_kind)
    if c is None:
        raise ManifestBuildError(
            f"operation kind {op_kind!r} has no registered contract"
        )

    # Local import: proof_hash imports resolve_dependency_files from this
    # module at its own module scope, so importing proof_hash back at THIS
    # module's top level would be circular. Deferred to call time, by which
    # point both modules are fully loaded. Reuses proof_hash's existing
    # hashing machinery rather than reinventing it here (DRY).
    from external_write.proof_hash import compute_implementation_hash

    dependency_files = resolve_dependency_files(op_kind)
    implementation_hash = compute_implementation_hash(
        op_kind, lib_dir=lib_dir, runtime_params=runtime_params
    )

    adapter = get_adapter(op_kind)
    effect_unit_path = (
        _adapter_effect_unit_path(adapter) if adapter is not None else None
    )

    manifest = EffectsManifest(
        op_kind=op_kind,
        params_schema=None,
        effect_unit_path=effect_unit_path,
        cap_default=c.blast_radius_cap,
        allowed_mutations=tuple(c.writes),
        undo=None,
        verifiers=tuple(c.verifier_set),
        dependency_files=dependency_files,
        implementation_hash=implementation_hash,
    )
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: EffectsManifest) -> None:
    """Pure structural validation of an EffectsManifest. Fail-closed: raises
    ManifestBuildError on the first violation found. No network, no disk I/O
    beyond what the caller already resolved into `manifest`.
    """
    if not manifest.op_kind:
        raise ManifestBuildError("manifest.op_kind must be a non-empty string")

    if not manifest.dependency_files:
        raise ManifestBuildError(
            f"manifest for {manifest.op_kind!r} has no dependency_files — "
            "refusing a coverage-incomplete implementation hash"
        )

    for vid in manifest.verifiers:
        if get_verifier(vid) is None:
            raise ManifestBuildError(
                f"manifest for {manifest.op_kind!r} references unregistered "
                f"verifier {vid!r}"
            )

    h = manifest.implementation_hash
    if not (isinstance(h, str) and len(h) == 64):
        raise ManifestBuildError(
            f"manifest for {manifest.op_kind!r} has a malformed "
            f"implementation_hash: {h!r}"
        )
    try:
        int(h, 16)
    except ValueError:
        raise ManifestBuildError(
            f"manifest for {manifest.op_kind!r} implementation_hash is not "
            f"valid hex: {h!r}"
        )
