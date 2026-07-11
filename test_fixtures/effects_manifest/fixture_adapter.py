"""Throwaway fixture adapter — Task 3 (external-write-gate-generalization slice).

NOT a real vendor adapter and never registered at import time (no
`register_adapter` call at module scope — contrast with a real adapter module).
This exists solely so `test_external_write_effects_manifest.py` can prove the
GENERIC hash-binding mechanism: a registered op_kind's `implementation_hash`
must change when the op_kind's OWN registered adapter module's bytes change.

The real Gmail verb adapter is Task 7 and does not exist yet (T3/T7 boundary
per the Task 3 brief's ambiguity resolution). This fixture stands in for "some
capability's registered adapter module" without hard-coding any vendor
specifics — the test loads a COPY of this file from a temp directory and
mutates the copy; this checked-in original is never mutated by the test.

Stdlib only — no third-party dependencies.
"""

from typing import Any, List, Optional

from external_write.operations import EffectUnit


class FixtureAdapter:
    """Minimal Adapter-protocol-conforming stub (plan / apply_one / undo_one /
    verify_one — see external_write.adapter_registry.Adapter). Never invoked
    against a real surface in these tests: the object under test is this
    module's OWN SOURCE BYTES (via effects_manifest.resolve_dependency_files
    and proof_hash.compute_implementation_hash), not this class's runtime
    behavior.
    """

    def plan(self, params: Optional[dict]) -> List[EffectUnit]:
        return [EffectUnit(unit_id="fixture-unit", target_ref=params)]

    def apply_one(self, raw_client: Any, unit: EffectUnit) -> None:
        pass

    def undo_one(self, raw_client: Any, unit: EffectUnit) -> None:
        pass

    def verify_one(self, raw_client: Any, unit: EffectUnit) -> Any:
        return True
