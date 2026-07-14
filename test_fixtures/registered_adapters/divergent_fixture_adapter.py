"""Test-only DIVERGENT (non-Gmail) adapter fixture — Task 7 (A4 / F-37),
v0.13.0 Slice 2.

Every shipped ADAPTER_PROFILE module today (`adapters_gmail.py`) happens to be
Gmail-shaped. Task 7's turnkey-acceptance mechanism (`registered_adapters.py`
+ its `get_contract`/`get_dispatch`-resolution pre-check in
`operator_acceptance.record_operator_acceptance`) must not be accidentally
proven only against Gmail — the mandatory anti-overfit constraint. This
module is a real, standalone, IMPORTABLE adapter module (not a hand-called
helper) that registers its own `OperationContract` + `Adapter` at MODULE
SCOPE, at import time, exactly like `adapters_gmail.py`'s own convention
(mirrors `_FieldStyleAdapter` in `test_external_write_evidence_predicate.py`
and `_StubAdapter` in `test_external_write_adapter_registry.py`, but as a
real file so importing it is a genuine "at import" registration, not a
manual `register_adapter(...)` call inside a test body).

Field/prestate-diff shaped (a spreadsheet-style value write), deliberately
NOT label-diff shaped like every Gmail op_kind — a different evaluation
shape, proving the mechanism this module exercises is generic.

Loaded via `importlib.util.spec_from_file_location` under a test-chosen
module name (see `test_external_write_registered_adapters.py` and the e2e
test in `test_external_write_operator_acceptance.py`) — never itself part of
the shipped `external_write` package, and never imported by
`registered_adapters.py`.

Stdlib only — no third-party dependencies.
"""

from typing import Any, List, Optional

from external_write.adapter_registry import register_adapter
from external_write.contracts import (
    OperationContract,
    WRITE_AFFECTING_MODULES,
    register_contract,
)
from external_write.operations import EffectUnit


# Deliberately namespaced away from any real vendor/capability op_kind so this
# fixture can never collide with a real registration.
OP_KIND = "fixture_divergent.record.set_status"


register_contract(OperationContract(
    op_kind=OP_KIND,
    writes=("Status",),
    produces=(),
    dependency_set=WRITE_AFFECTING_MODULES,
    verifier_set=("operator_attested_v1",),
    introduces_persistent_binding=False,
    risk_class="sensitive_data",
    requires_accepted_phase=True,
    blast_radius_cap=10,
    read_only_scope="fixture_divergent.readonly",
))


class DivergentFixtureAdapter:
    """Field/spreadsheet-shaped adapter (prestate-diff evaluation) — the
    divergent counterpart to every Gmail op_kind's label-diff shape."""

    def plan(self, params: Optional[dict]) -> List[EffectUnit]:
        params = params or {}
        units: List[EffectUnit] = []
        for row in params.get("rows", []):
            row_id = row["row_id"]
            units.append(EffectUnit(
                unit_id=row_id,
                target_ref={"row_id": row_id, "value": row.get("value")},
                undo_ref={"row_id": row_id, "prior_value": row.get("prior_value")},
            ))
        return units

    def apply_one(self, raw_client: Any, unit: EffectUnit) -> None:
        raw_client.write(unit.target_ref["row_id"], "Status", unit.target_ref["value"])

    def undo_one(self, raw_client: Any, unit: EffectUnit) -> None:
        if unit.undo_ref is None:
            raise ValueError(f"{OP_KIND}: unit {unit.unit_id!r} has no undo_ref")
        raw_client.write(unit.undo_ref["row_id"], "Status", unit.undo_ref["prior_value"])

    def verify_one(self, observer: Any, unit: EffectUnit) -> Any:
        return {"row_id": unit.target_ref["row_id"], "value": unit.target_ref.get("value")}


register_adapter(OP_KIND, DivergentFixtureAdapter())
