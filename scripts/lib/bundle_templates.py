"""Bundle-resident template resolution (the single frozen template home).

The system bundle's `system-artifacts.json` declares, per emitted operator-project
file (`relpath`), the bundle-resident template it is produced from (`template_path`,
relative to the bundle directory). This module is the ONE place that resolves a
file's `relpath` to its frozen bundle template, so that emit (and a future
upgrade-render) read wizard-authored templates from exactly ONE source — the
versioned bundle — instead of the live `wizard/templates/`, `wizard/agents/`,
`wizard/scripts/` working trees.

Fail-closed (REV-2 C1d): bundle-sourced means there is NO live fallback. A missing
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


def _bundle_dir(version: str, build_repo_root: Path) -> Path:
    return build_repo_root / "wizard" / "foundation-bundles" / version


@lru_cache(maxsize=None)
def operating_layer_source_version(build_repo_root_str: str) -> str:
    """The bundle version that is the single frozen home for the wizard-authored
    operating-layer + scaffold templates — i.e. the version that carries a
    `system-artifacts.json` managed-artifacts contract + the relocated operating-layer
    `templates/` tree.

    Emit's `plan.bundle_version` selects the FOUNDATION-doc + manifest version (the
    operator-install version, e.g. the current production bundle). The operating-layer
    templates were relocated into ONE frozen home (the contract-bearing bundle); emit
    sources every `delivery:"wizard"` operating-layer template from there so emit and a
    future upgrade-render share that one source. The two are decoupled on purpose: a
    foundation-only bundle bump must not require re-relocating the operating layer.

    Resolved (not hardcoded) as the lexically-greatest bundle version directory that
    contains a `system-artifacts.json`. Fail-closed if none exists."""
    build_repo_root = Path(build_repo_root_str)
    bundles_root = build_repo_root / "wizard" / "foundation-bundles"
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
