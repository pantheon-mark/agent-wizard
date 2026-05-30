"""Maintained tier->model resolution loader (stdlib-only).

The wizard resolves the three logical model tiers (high / standard / fast) to REAL
current Claude model IDs so an emitted operator system's start-session.sh and
project_instructions.md carry a real --model, never a manually-selected one (the
programmatic-model rule). The scaffold-plan keeps shape-correct PLACEHOLDERS
(model-high/standard/fast) so the distributed data stays shape-valid without pinning
a model string in the scaffold structure; this registry is the separate, maintained
generation-time resolution, fed to the assembler through its model_tiers override seam.

Budget-conditioned tiering (a values flag that would downgrade tiers under a spend
ceiling) is intentionally OUT of v0 scope: one fixed family map, default OFF.

Fail-closed: an unknown shape, a contract/version/shape mismatch, a missing tier, or a
placeholder/empty value is a hard error (a placeholder leaking into a generated system
would break the operator's --model). Stdlib-only, pip-install-free.
"""

import json
from pathlib import Path
from typing import Dict, Optional

EXPECTED_CONTRACT_ID = "model-tiers"
EXPECTED_CONTRACT_VERSIONS = {"model-tiers-v1"}
REQUIRED_TIERS = ("high", "standard", "fast")
_PLACEHOLDER_PREFIX = "model-"  # the scaffold-plan's shape-correct, non-real placeholder family


class ModelTiersError(Exception):
    """Raised on model-tiers registry load/validation failure (fail-closed)."""


def _require(cond: bool, invariant: str, detail: str) -> None:
    if not cond:
        raise ModelTiersError(f"{invariant} FAIL: {detail}")


def default_registry_dir() -> Path:
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent
    return wizard_root / "foundation-bundles" / "v0" / "model-tiers"


def load_model_tiers(system_shape: str, registry_dir: Optional[Path] = None) -> Dict[str, str]:
    """Load + validate the maintained tier->model map for `system_shape`.

    Returns a dict with exactly the keys high/standard/fast mapped to real, non-placeholder
    model-id strings. Fail-closed throughout."""
    rdir = registry_dir or default_registry_dir()
    path = Path(rdir) / f"{system_shape}.json"
    if not path.exists():
        raise ModelTiersError(f"model-tiers registry not found for shape {system_shape!r}: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ModelTiersError(f"model-tiers registry is not valid JSON: {path}: {e}") from e

    _require(isinstance(data, dict), "contract", "top-level value must be an object")
    _require(data.get("contract_id") == EXPECTED_CONTRACT_ID, "contract_id",
             f"expected {EXPECTED_CONTRACT_ID!r}, got {data.get('contract_id')!r}")
    cv = data.get("contract_version")
    _require(isinstance(cv, str) and cv in EXPECTED_CONTRACT_VERSIONS, "contract_version",
             f"must be one of {sorted(EXPECTED_CONTRACT_VERSIONS)}; got {cv!r}")
    _require(data.get("system_shape") == system_shape, "system_shape_match",
             f"file declares {data.get('system_shape')!r} but asked for {system_shape!r}")

    tiers = data.get("model_tiers")
    _require(isinstance(tiers, dict), "model_tiers", "model_tiers must be an object")
    _require(set(tiers.keys()) == set(REQUIRED_TIERS), "model_tiers_keys",
             f"must have exactly tiers {sorted(REQUIRED_TIERS)}; got {sorted(tiers.keys())}")
    resolved: Dict[str, str] = {}
    for tier in REQUIRED_TIERS:
        v = tiers[tier]
        _require(isinstance(v, str) and v.strip(), "tier_value", f"{tier}: must be a non-empty string")
        _require(not v.startswith(_PLACEHOLDER_PREFIX), "tier_not_placeholder",
                 f"{tier}={v!r} is a placeholder; the maintained registry must hold a real model id")
        resolved[tier] = v
    return resolved


def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: model_tiers.py <system-shape> [registry-dir]", file=sys.stderr)
        return 2
    rdir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        mt = load_model_tiers(sys.argv[1], rdir)
    except ModelTiersError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"OK: {sys.argv[1]} -> {mt}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
