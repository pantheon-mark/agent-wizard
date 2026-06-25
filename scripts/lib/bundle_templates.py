"""Bundle-resident template resolution (the single frozen template home).

The system bundle's `system-artifacts.json` declares, per emitted operator-project
file (`relpath`), the bundle-resident template it is produced from (`template_path`,
relative to the bundle directory). This module is the ONE place that resolves a
file's `relpath` to its frozen bundle template, so that emit (and a future
upgrade-render) read wizard-authored templates from exactly ONE source — the
versioned bundle — instead of the live `wizard/templates/`, `wizard/agents/`,
`wizard/scripts/` working trees.

Fail-closed: bundle-sourced means there is NO live fallback. A missing
contract, a `relpath` absent from the contract, or a `template_path` that does not
resolve inside the bundle RAISES — the emitter must not silently fall back to a live
template (that would defeat the frozen-home / replay-conformance guarantee).

Only the operating-layer + scaffold templates resolve through here. Foundation-doc
templates were already bundle-sourced (generator.render_foundation_docs reads them
from `<bundle>/templates/<doc>.md` via the registry path); this module does not
change that path.

Stdlib-only, pip-install-free.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple


class BundleTemplateError(Exception):
    """Raised when a bundle template cannot be resolved (missing contract, unknown
    relpath, or a template_path that escapes / does not exist in the bundle).
    Fail-closed: no live-tree fallback."""


CONTRACT_BASENAME = "system-artifacts.json"


def wizard_subroot(build_repo_root: Path) -> Path:
    """Resolve the toolkit subroot that directly contains `foundation-bundles/`.

    Layout-agnostic (operator-reach C1'): the toolkit ships two ways and the bundle
    directories live at different depths relative to the value callers pass as
    ``build_repo_root``:

      * BUILD-REPO  : the value IS the repo root and bundles are under `wizard/` ->
        the subroot is `<build_repo_root>/wizard`.
      * PUBLIC-CLONE / toolkit-root: the value IS already the toolkit root (the dir
        that holds `registry/` + `foundation-bundles/`, e.g. resolve_toolkit_root(...))
        -> the subroot is the value itself (no `wizard/` segment exists in the split).

    The PRIMARY canonical bundle-directory resolution is registry-relative
    (`upgrade.resolve_bundle_dir`); this helper is the transitional bridge for the
    render engine, which receives only a root path (no registry). It keys on the
    structural invariant "the subroot is the dir that holds `foundation-bundles/`" —
    not on string-matching a path — and falls back to the legacy `wizard/`-prefixed
    subroot when the value is a build-repo root.
    """
    if (build_repo_root / "foundation-bundles").is_dir():
        return build_repo_root
    return build_repo_root / "wizard"


def _bundle_dir(version: str, build_repo_root: Path) -> Path:
    return wizard_subroot(build_repo_root) / "foundation-bundles" / version


def bundle_has_operating_layer(version: str, build_repo_root: Path) -> bool:
    """Return True iff the named bundle carries a system-artifacts.json contract
    (i.e. it declares the operating-layer template home). Foundation-only bundles
    (v0.3.0/v0.4.0/v0.5.0 and earlier) return False; the emitters skip the
    operating-layer files gracefully when this returns False."""
    return (_bundle_dir(version, build_repo_root) / CONTRACT_BASENAME).is_file()


@lru_cache(maxsize=None)
def operating_layer_source_version(build_repo_root_str: str) -> str:
    """DEPRECATED — used only by the ``_verify_template_dependencies`` prewrite
    guard in operator_system_emitter (which still needs to locate the
    contract-bearing bundle for legacy callers).  Emit paths now call
    ``bundle_has_operating_layer`` + ``read_bundle_template`` with the explicit
    ``bundle_version`` from the plan instead of discovering the "latest" bundle.

    Resolved as the lexically-greatest bundle version directory that contains a
    `system-artifacts.json`. Fail-closed if none exists."""
    build_repo_root = Path(build_repo_root_str)
    bundles_root = wizard_subroot(build_repo_root) / "foundation-bundles"
    candidates = []
    if bundles_root.is_dir():
        for child in bundles_root.iterdir():
            if child.is_dir() and (child / CONTRACT_BASENAME).is_file():
                candidates.append(child.name)
    if not candidates:
        raise BundleTemplateError(
            f"no bundle carries a {CONTRACT_BASENAME} under {bundles_root}; cannot locate "
            f"the operating-layer template home (fail-closed, no live fallback)"
        )
    # Version strings are vMAJOR.MINOR[.PATCH]; sort by parsed tuple for correctness.
    def _key(v: str):
        core = v.lstrip("v")
        parts = []
        for p in core.split("."):
            parts.append(int(p) if p.isdigit() else -1)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    return max(candidates, key=_key)


@lru_cache(maxsize=None)
def _contract_template_paths(version: str, build_repo_root_str: str) -> Tuple[Tuple[str, str], ...]:
    """Load the version's managed-artifacts contract; return an immutable tuple of
    (relpath, template_path) pairs. Cached per (version, repo-root) — the contract is
    a frozen build-time artifact."""
    build_repo_root = Path(build_repo_root_str)
    contract_path = _bundle_dir(version, build_repo_root) / CONTRACT_BASENAME
    if not contract_path.is_file():
        raise BundleTemplateError(
            f"system-artifacts contract not found for bundle {version!r} at {contract_path}; "
            f"bundle-sourced templates require the contract (no live fallback)"
        )
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BundleTemplateError(
            f"system-artifacts contract for bundle {version!r} is not valid JSON: {exc}"
        ) from exc
    pairs = []
    for entry in contract.get("artifacts", []):
        rel = entry.get("relpath")
        if rel is None:
            raise BundleTemplateError(
                f"contract entry missing relpath in bundle {version!r}: {entry!r}"
            )
        # Control-plane-emitted entries (source=control_plane) are produced by a Python
        # emitter, not a bundle template — they carry no template_path and are not
        # resolvable here (the emitter never asks for them).
        tp = entry.get("template_path")
        if tp is None:
            continue
        pairs.append((rel, tp))
    return tuple(pairs)


def _template_map(version: str, build_repo_root: Path) -> Dict[str, str]:
    return dict(_contract_template_paths(version, str(build_repo_root)))


def bundle_template_path(version: str, relpath: str, build_repo_root: Path) -> Path:
    """Resolve an operator-project `relpath` to its frozen bundle template path.

    Fail-closed: raises BundleTemplateError if the relpath is not declared in the
    contract, or the declared template_path does not resolve to a file inside the
    bundle (no traversal, no live-tree fallback)."""
    tmap = _template_map(version, build_repo_root)
    if relpath not in tmap:
        raise BundleTemplateError(
            f"no managed-artifacts contract entry for {relpath!r} in bundle {version!r}; "
            f"cannot bundle-source its template (fail-closed, no live fallback)"
        )
    bundle_dir = _bundle_dir(version, build_repo_root)
    tpl = (bundle_dir / tmap[relpath]).resolve()
    # Guard against path traversal outside the bundle.
    if not str(tpl).startswith(str(bundle_dir.resolve()) + "/"):
        raise BundleTemplateError(
            f"template_path for {relpath!r} escapes bundle {version!r}: {tmap[relpath]!r}"
        )
    if not tpl.is_file():
        raise BundleTemplateError(
            f"bundle template for {relpath!r} not found at {tpl} (bundle {version!r})"
        )
    return tpl


def read_bundle_template(version: str, relpath: str, build_repo_root: Path) -> str:
    """Read a bundle template's text by operator-project relpath. Fail-closed."""
    return bundle_template_path(version, relpath, build_repo_root).read_text(encoding="utf-8")


class _DerivationShim:
    """A minimal stand-in for an EmissionPlan, carrying ONLY the fields the
    scaffold/corpus derivation helpers read (`system_shape`, `foundation_doc_inputs`,
    `foundation_only_mode`). At upgrade time there is no live EmissionPlan — the capsule
    plus the manifest carry everything the derivation needs, and the corpus/scaffold
    helpers reach only these three attributes."""

    def __init__(self, system_shape: str, foundation_doc_inputs: Dict[str, str]):
        self.system_shape = system_shape
        self.foundation_doc_inputs = foundation_doc_inputs
        self.foundation_only_mode = False


def derive_scaffold_render_inputs(
    *,
    system_shape: str,
    foundation_doc_inputs: Dict[str, str],
    project_name: str,
    target_version: str,
    build_repo_root: Path,
) -> Dict[str, str]:
    """Re-derive the FULL substitution map for the TARGET bundle's scaffold/root
    `render_kind:render` operating-layer files, reproducing exactly what the emitter
    fed `_substitute_placeholders` at setup time.

    The replay capsule deliberately stores only the PERSISTED inputs (foundation_doc_inputs
    + operating.resolved_scaffold_inputs); the DERIVED inputs (the deterministic scaffold
    defaults, the corpus-rendered inherited-principles block, the autonomy-derived
    autonomous-actions body, the resolved model-tier strings, and the corpus rules-library
    body) are NOT stored — they are re-derived from the TARGET bundle/corpus/registry here.
    This is what closes the operating-layer-upgrade delivery gap: persisted-only substitution
    leaves derived placeholders unresolved and the apply refuses.

    Merge precedence mirrors scaffold_emitter.build_scaffold_inputs exactly:
        defaults < foundation_doc_inputs < derived-extra < structural overrides
    where the structural overrides (PROJECT_NAME from the manifest, MODEL_* from the
    maintained tier registry) win LAST — `_plan_derived_inputs` is applied last at emit,
    so PROJECT_NAME is the project's directory-derived name, NOT a foundation_doc_inputs
    value.

    The caller overlays the capsule's persisted `resolved_scaffold_inputs` on top of this
    map (they are persisted, not derived) and runs the bundle's deterministic target-hook
    injection post-pass, reproducing the emitted bytes. Stdlib-only / pip-free.
    """
    # Imports are deferred so importing this module stays light and circular-free; all of
    # these are pip-free (verified on the operator/runtime path).
    from scaffold_emitter import _default_scaffold_inputs  # type: ignore
    from corpus_emitter import (  # type: ignore
        render_claude_md_block,
        render_rules_library_entries,
        _resolved_records,
        INSTALLED_DATE_KEY,
        DEFAULT_INSTALLED_MARKER,
    )
    from corpus_loader import load_corpus_pack  # type: ignore
    from authority_profile import autonomous_actions_summary  # type: ignore
    from model_tiers import load_model_tiers  # type: ignore
    from voice_settings import voice_settings_inputs  # type: ignore

    shim = _DerivationShim(system_shape, dict(foundation_doc_inputs))
    records = load_corpus_pack()
    tiers = load_model_tiers(system_shape)
    created = str(foundation_doc_inputs.get(INSTALLED_DATE_KEY, DEFAULT_INSTALLED_MARKER))

    inputs: Dict[str, str] = dict(_default_scaffold_inputs())
    # foundation_doc_inputs override defaults (build_scaffold_inputs precedence).
    for k, v in (foundation_doc_inputs or {}).items():
        inputs[k] = str(v)
    # Derived-extra: the emitter's scaffold_extra (corpus block + autonomy body + purpose).
    inputs["INHERITED_OPERATING_PRINCIPLES"] = render_claude_md_block(shim, records)
    inputs["AUTONOMOUS_ACTIONS"] = autonomous_actions_summary(
        foundation_doc_inputs.get("AUTONOMY_LEVEL", "1")
    )
    inputs.update(voice_settings_inputs(foundation_doc_inputs))
    core_purpose = str(foundation_doc_inputs.get("CORE_PURPOSE", "")).strip()
    if core_purpose:
        inputs["PROJECT_PURPOSE"] = core_purpose
    # The corpus single-home body (quality/rules_library.md's only derived key).
    inputs["RULES_LIBRARY_ENTRIES"] = render_rules_library_entries(
        _resolved_records(shim, records), created
    )
    # Structural overrides win LAST (mirror scaffold_emitter._plan_derived_inputs).
    inputs["PROJECT_NAME"] = project_name
    inputs["MODEL_HIGH"] = tiers["high"]
    inputs["MODEL_STANDARD"] = tiers["standard"]
    inputs["MODEL_FAST"] = tiers["fast"]
    return inputs
