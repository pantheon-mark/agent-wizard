"""Legitimate fixture (Task R1 / BL-1 residual): a concrete adapter module that
DEFINES ``build_write_client`` — the ONE legal place the write-capable client is
provisioned. This lives in the ADAPTER_PROFILE trust zone (exempt from every
scan check). The scanner must NOT flag the adapter's own method definition; only
a *reference* to that method from a non-adapter zone is a violation.
"""

from typing import Any, List, Optional

from external_write.operations import EffectUnit


class AcmeSyncAdapter:
    def plan(self, params: Optional[dict]) -> List[EffectUnit]:
        return []

    def apply_one(self, raw_client: Any, unit: EffectUnit) -> None:
        raw_client.apply(unit)

    def undo_one(self, raw_client: Any, unit: EffectUnit) -> None:
        ...

    def verify_one(self, raw_client: Any, unit: EffectUnit) -> Any:
        ...

    def build_write_client(self, op: Any) -> Any:
        # The ONE legal provisioning point, inside the ADAPTER_PROFILE zone.
        return _make_write_client(op)


def _make_write_client(op: Any) -> Any:
    return object()
