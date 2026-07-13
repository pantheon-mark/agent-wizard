"""Tests for `evidence.AdapterEvidence` — the kernel-supplied, lineage-typed
evidence record a per-op_kind evidence predicate (Task 1, B4/T1 — v0.12.0
Slice 1) evaluates.

Scope note: this task builds ONLY the type + the adapter-dispatch capture
mechanism (see test_external_write_adapter_registry.py's
TestAdapterDispatchEvidencePredicateCapture) + proves the predicate signature
is shape-neutral on two divergent op_kinds (see
test_external_write_evidence_predicate.py). Constructing a real
AdapterEvidence from a live read-only observer or a captured evidence file is
a KERNEL responsibility wired in a later task (proof-time / run-time
verification) — not built here.
"""

import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.evidence import AdapterEvidence  # noqa: E402
from external_write.contracts import SourceLineage  # noqa: E402


def _lineage():
    return SourceLineage(
        pre_write_sources=("prewrite_csv_backup",),
        post_write_sources=("live_surface_read",),
        forbidden_verification_inputs=("writer_generated_id_map",),
    )


class TestAdapterEvidenceShape(unittest.TestCase):

    def test_minimal_construction_with_required_fields(self):
        ev = AdapterEvidence(
            op_kind="gmail.message.trash",
            unit_id="m1",
            poststate={"is_trashed": True},
            source_lineage=_lineage(),
        )
        self.assertEqual(ev.op_kind, "gmail.message.trash")
        self.assertEqual(ev.unit_id, "m1")
        self.assertEqual(ev.poststate, {"is_trashed": True})
        self.assertIsInstance(ev.source_lineage, SourceLineage)

    def test_prestate_defaults_to_none(self):
        ev = AdapterEvidence(
            op_kind="set_status", unit_id="row1",
            poststate={"value": "Complete"}, source_lineage=_lineage(),
        )
        self.assertIsNone(ev.prestate)

    def test_prestate_may_be_supplied(self):
        ev = AdapterEvidence(
            op_kind="set_status", unit_id="row1",
            poststate={"value": "Complete"},
            prestate={"value": "Open"},
            source_lineage=_lineage(),
        )
        self.assertEqual(ev.prestate, {"value": "Open"})

    def test_poststate_defaults_to_empty_mapping(self):
        ev = AdapterEvidence(op_kind="k", unit_id="u", source_lineage=_lineage())
        self.assertEqual(ev.poststate, {})

    def test_is_frozen_immutable(self):
        ev = AdapterEvidence(
            op_kind="k", unit_id="u",
            poststate={"a": 1}, source_lineage=_lineage(),
        )
        with self.assertRaises(FrozenInstanceError):
            ev.poststate = {"a": 2}

    def test_no_path_or_ref_field_exists_on_the_dataclass(self):
        """Anti-tautology structural proof at the TYPE level: AdapterEvidence
        carries no field shaped like a filesystem path or an opaque ref
        string a predicate could dereference itself -- only already-
        materialized state mappings + declared lineage. This is a coarse
        but meaningful guard: any future field literally named to look like
        a path/ref must be a deliberate, reviewed decision, not an
        accidental erosion of the anti-tautology property."""
        field_names = {f for f in AdapterEvidence.__dataclass_fields__}
        for suspicious in ("path", "ref", "file", "evidence_ref"):
            for name in field_names:
                self.assertNotIn(
                    suspicious, name.lower(),
                    f"AdapterEvidence field {name!r} looks path/ref-shaped — "
                    "the predicate must only ever see already-materialized "
                    "state, never something it could open itself")


if __name__ == "__main__":
    unittest.main()
