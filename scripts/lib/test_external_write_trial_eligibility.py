"""Tests for the TRIAL-ELIGIBILITY PREFLIGHT (Cut 1.9 Task 1, Phase A1' —
v0.23.0): the fail-closed gate that decides which operations may LEGALLY
undergo a journaled `apply -> verify -> undo -> verify-restored` TRIAL. It runs
BEFORE any external write, and everything downstream (the write-ahead journal,
the trial executor, the recovery path) trusts its verdict.

Four clauses, ALL of which must pass, plus the plan-integrity precondition that
makes clause (a)'s "every unit" quantifier mean something:

  (a) every planned unit carries a non-None `undo_ref`
  (b) the adapter declares BOTH names in `evidence.REQUIRED_EVIDENCE_PREDICATES`
  (c) the adapter declares `undo_one` as an ABSOLUTE-STATE idempotent restore
  (d) every unit's recovery capsule is JSON-serializable

------------------------------------------------------------------------------
IMPORTANT -- what NO test in this file claims
------------------------------------------------------------------------------
The two live estate op_kinds (`adapters_inbox`, `adapters_estate_upkeep`) are
OPERATOR-authored modules living in a separate operator project. They are NOT
in this repo, are NOT imported here, and NOTHING here asserts that the REAL
estate adapters pass this gate. The two eligible fixtures below reproduce their
CONTRACT SHAPE only -- absolute-state restore (`_set_exact_labels` to the exact
prior label set / `_write_cell` of the prior value), verified by the controller
against the real files. The claim "the real estate adapters are trial-eligible"
belongs to the empirical replay against a real operator-project copy (Cut 1.9
Task 19). Naming a fixture-based test as if it proved the real thing is the
exact false-green pattern this cut exists to end.

The ONE real, shipped adapter exercised here is `adapters_gmail.py`'s
`gmail.filter.create` -- used unstubbed, as the REFUSAL fixture, because it
plans `undo_ref=None` (adapters_gmail.py:439) and holds the only reversal id in
an in-memory dict (`:427-428`), so it must be refused on clause (a) AND,
independently, on clause (c). Both grounds are asserted SEPARATELY: two
independent bans agreeing on the same op is the property the design wants, and
a single combined assertion would still pass if either ban were lost.

Fixture construction convention: every negative fixture ADDS exactly what it
declares to a bare protocol base (`_InboxPlanBase`). Deliberately never
subclass-and-delete -- deleting an attribute from a subclass reveals the
PARENT's, so such a fixture would silently claim the very thing it is supposed
to be missing.
"""

import json
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import evidence as evidence_mod  # noqa: E402
from external_write import scan, zones  # noqa: E402
from external_write import trial_eligibility as te  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    UNDO_IDEMPOTENCY_DECLARATION_ATTR, get_dispatch, register_adapter,
    unregister_adapter,
)
from external_write.operations import EffectUnit  # noqa: E402
from external_write.adapters_gmail import (  # noqa: E402
    OP_FILTER_CREATE, GmailFilterCreateAdapter,
)


# ---------------------------------------------------------------------------
# Fixture adapters. Each reproduces a CONTRACT SHAPE (see the header) -- never
# a real operator-project module.
# ---------------------------------------------------------------------------

class _FakeLabelClient:
    """Duck-typed stand-in for the write-capable raw_client the fixture
    adapters mutate. Never invoked by the preflight (which performs no write at
    all) -- present so the fixtures are honest, runnable adapters rather than
    raise-only shells."""

    def __init__(self):
        self.labels = {}

    def set_exact_labels(self, message_id, label_ids):
        self.labels[message_id] = list(label_ids)


class _FakeCellClient:
    def __init__(self):
        self.cells = {}

    def write_cell(self, ref):
        self.cells[ref["cell"]] = ref["value"]


def _label_apply_landed(self, evidence):
    """Absolute post-condition: True iff the OBSERVED live state shows the
    mutation, never a blind pass."""
    return bool(evidence.poststate.get("is_trashed"))


def _label_undo_restored(self, evidence):
    """Absolute post-condition: True iff the OBSERVED live state equals the
    prestate snapshot."""
    return bool(evidence.poststate.get("matches_prestate"))


class _InboxPlanBase:
    """`adapter_registry.Adapter` protocol and NOTHING else: plan / apply_one /
    undo_one / verify_one. No evidence predicates, silent about idempotency.
    Doubles as the "does any clause pass by default?" probe.

    Reproduces the plan/undo SHAPE of the operator project's `adapters_inbox`:
    `undo_one` sets the EXACT prior label set (absolute-state restore,
    therefore idempotent). The DECLARATION of that property is added only by
    the subclasses that declare it -- this base deliberately does not, so a
    fixture can be silent about it."""

    def plan(self, params):
        units = []
        for m in (params or {}).get("messages", []):
            mid = m["message_id"]
            units.append(EffectUnit(
                unit_id=mid,
                target_ref={"message_id": mid},
                undo_ref={"message_id": mid,
                          "prior_label_ids": list(m.get("prior_label_ids", ()))},
            ))
        return units

    def apply_one(self, raw_client, unit):
        raw_client.set_exact_labels(unit.target_ref["message_id"], ["TRASH"])

    def undo_one(self, raw_client, unit):
        raw_client.set_exact_labels(unit.undo_ref["message_id"],
                                    unit.undo_ref["prior_label_ids"])

    def verify_one(self, observer, unit):
        return {"current_label_ids": list(observer.get_message(unit.unit_id))}


class InboxShapedAdapter(_InboxPlanBase):
    """Fully compliant against all four clauses."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True
    verify_apply_landed = _label_apply_landed
    verify_undo_restored = _label_undo_restored


class _NoUndoRestoredPredicate(_InboxPlanBase):
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True
    verify_apply_landed = _label_apply_landed


class _NoApplyLandedPredicate(_InboxPlanBase):
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True
    verify_undo_restored = _label_undo_restored


class _LyingNonCallablePredicate(_InboxPlanBase):
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True
    verify_apply_landed = _label_apply_landed
    verify_undo_restored = True  # not a method -- a lie


class _SilentAboutIdempotency(_InboxPlanBase):
    verify_apply_landed = _label_apply_landed
    verify_undo_restored = _label_undo_restored


class _DeclaresNotAbsolute(_SilentAboutIdempotency):
    UNDO_IS_ABSOLUTE_STATE_RESTORE = False


class UpkeepShapedAdapter:
    """Reproduces the contract shape of the operator project's
    `adapters_estate_upkeep`: `undo_one` writes the PRIOR value back into the
    cell (absolute-state restore, therefore idempotent). A deliberately
    DIVERGENT shape from the label-set fixtures above (a field/cell value, not
    a label set), so nothing here is overfitted to one vendor's shape."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def plan(self, params):
        units = []
        for c in (params or {}).get("cells", []):
            units.append(EffectUnit(
                unit_id=c["cell"],
                target_ref={"cell": c["cell"], "value": c["new_value"]},
                undo_ref={"cell": c["cell"], "value": c["prior_value"]},
            ))
        return units

    def apply_one(self, raw_client, unit):
        raw_client.write_cell(unit.target_ref)

    def undo_one(self, raw_client, unit):
        raw_client.write_cell(unit.undo_ref)

    def verify_one(self, observer, unit):
        return {"value": observer.read_cell(unit.unit_id)}

    def verify_apply_landed(self, evidence):
        return evidence.poststate.get("value") == evidence.poststate.get("expected")

    def verify_undo_restored(self, evidence):
        return (evidence.prestate or {}).get("value") == evidence.poststate.get("value")


class _Base(unittest.TestCase):
    """Registration hygiene: the adapter registry is module-global, so every
    fixture registration is unregistered on teardown -- otherwise a fixture
    op_kind leaks into every later test in the process."""

    def register(self, op_kind, adapter):
        register_adapter(op_kind, adapter)
        self.addCleanup(unregister_adapter, op_kind)
        return adapter

    def capsules(self, op_kind, units):
        """One recovery capsule per planned unit. Clause (d) deliberately does
        NOT constrain the capsule's SHAPE (a later task owns the format) -- it
        checks only that what it is handed survives a real JSON round trip."""
        return {u.unit_id: {"op_kind": op_kind, "unit_id": u.unit_id,
                            "undo_ref": u.undo_ref}
                for u in units}

    def inbox_units(self, adapter):
        return adapter.plan({"messages": [{"message_id": "m1",
                                           "prior_label_ids": ["INBOX"]}]})

    def verdict_for(self, op_kind, adapter):
        units = self.inbox_units(adapter)
        return te.check_trial_eligibility(op_kind, units,
                                          self.capsules(op_kind, units))

    def assertRefusedOn(self, verdict, clause):
        self.assertFalse(verdict.eligible,
                         f"expected a refusal on {clause}; got an ELIGIBLE verdict")
        self.assertIn(clause, verdict.failed_clauses,
                      f"expected clause {clause!r} to refuse; refusals were "
                      f"{verdict.failed_clauses!r}: {verdict.reason_text()}")

    def assertNotRefusedOn(self, verdict, clause):
        self.assertNotIn(clause, verdict.failed_clauses,
                         f"clause {clause!r} should NOT have refused; "
                         f"{verdict.reason_text()}")


# ---------------------------------------------------------------------------
# The four clauses all pass -- on FIXTURES reproducing two divergent contract
# shapes (never a claim about the real estate adapters; see the header).
# ---------------------------------------------------------------------------

class EligibleContractShapeTests(_Base):

    def test_inbox_shaped_fixture_passes_all_four_clauses(self):
        op = "fixture.inbox_shaped.set_exact_labels"
        adapter = self.register(op, InboxShapedAdapter())
        units = adapter.plan({"messages": [
            {"message_id": "m1", "prior_label_ids": ["INBOX", "UNREAD"]},
            {"message_id": "m2", "prior_label_ids": ["INBOX"]},
        ]})
        verdict = te.check_trial_eligibility(op, units, self.capsules(op, units))
        self.assertTrue(verdict.eligible, verdict.reason_text())
        self.assertEqual(verdict.failed_clauses, ())
        self.assertEqual(verdict.reason_text(), "")

    def test_upkeep_shaped_fixture_passes_all_four_clauses(self):
        op = "fixture.upkeep_shaped.write_cell"
        adapter = self.register(op, UpkeepShapedAdapter())
        units = adapter.plan({"cells": [
            {"cell": "B7", "new_value": "done", "prior_value": "in progress"},
        ]})
        verdict = te.check_trial_eligibility(op, units, self.capsules(op, units))
        self.assertTrue(verdict.eligible, verdict.reason_text())

    def test_eligible_verdict_echoes_back_exactly_the_units_it_blessed(self):
        """Task 2 binds its AuthorizedPlan to the units the preflight actually
        checked rather than re-deriving them -- a check-then-swap would
        otherwise execute units this gate never saw."""
        op = "fixture.inbox_shaped.echo"
        adapter = self.register(op, InboxShapedAdapter())
        units = self.inbox_units(adapter)
        verdict = te.check_trial_eligibility(op, units, self.capsules(op, units))
        self.assertEqual(verdict.units, tuple(units))
        self.assertEqual(verdict.op_kind, op)


# ---------------------------------------------------------------------------
# Review focus: does any clause pass by DEFAULT? Every clause must require an
# explicit POSITIVE declaration.
# ---------------------------------------------------------------------------

class NoClausePassesByDefaultTests(_Base):

    def test_bare_protocol_adapter_is_refused_on_both_adapter_clauses(self):
        """An adapter that satisfies the Adapter protocol and says nothing else
        -- well-formed units, real capsules -- must still be refused. Silence is
        never consent."""
        op = "fixture.bare.protocol_only"
        adapter = self.register(op, _InboxPlanBase())
        verdict = self.verdict_for(op, adapter)
        self.assertRefusedOn(verdict, te.CLAUSE_EVIDENCE_PREDICATES_DECLARED)
        self.assertRefusedOn(verdict, te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)
        # The plan-side clauses genuinely pass here -- this fixture's units are
        # well-formed and its capsules serialize -- which keeps this test a
        # statement about the ADAPTER clauses specifically.
        self.assertNotRefusedOn(verdict, te.CLAUSE_PLAN_INTEGRITY)
        self.assertNotRefusedOn(verdict, te.CLAUSE_UNDO_REF_PRESENT)
        self.assertNotRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)

    def test_an_op_kind_with_no_registered_adapter_is_refused(self):
        """Fail-closed: with no adapter there is nothing that could have
        declared clause (b) or (c), so neither may pass. The six seeded field
        op_kinds have no registered adapter by permanent design and are
        correctly ineligible for an adapter trial."""
        units = [EffectUnit(unit_id="u1", target_ref={"a": 1}, undo_ref={"a": 0})]
        verdict = te.check_trial_eligibility(
            "fixture.never.registered", units, {"u1": {"undo_ref": {"a": 0}}})
        self.assertRefusedOn(verdict, te.CLAUSE_EVIDENCE_PREDICATES_DECLARED)
        self.assertRefusedOn(verdict, te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)
        self.assertIn("no registered adapter", verdict.reason_text())

    def test_every_clause_can_refuse_independently_in_one_verdict(self):
        """All five refusal grounds reported at once -- the gate never
        short-circuits, so fixing one clause cannot mask another still being
        broken."""
        op = "fixture.everything.wrong"

        class _Worst(_InboxPlanBase):
            def plan(self, params):
                return [EffectUnit(unit_id="dup", target_ref={}, undo_ref=None),
                        EffectUnit(unit_id="dup", target_ref={}, undo_ref=None)]

        adapter = self.register(op, _Worst())
        verdict = te.check_trial_eligibility(op, adapter.plan(None),
                                             {"dup": {"bad": {1, 2}}})
        self.assertEqual(set(verdict.failed_clauses),
                         set(te.TRIAL_ELIGIBILITY_CLAUSES),
                         verdict.reason_text())

    def test_clause_ids_are_reported_in_canonical_order(self):
        op = "fixture.everything.wrong.ordered"

        class _Worst(_InboxPlanBase):
            def plan(self, params):
                return [EffectUnit(unit_id="dup", target_ref={}, undo_ref=None),
                        EffectUnit(unit_id="dup", target_ref={}, undo_ref=None)]

        adapter = self.register(op, _Worst())
        verdict = te.check_trial_eligibility(op, adapter.plan(None),
                                             {"dup": {"bad": {1, 2}}})
        self.assertEqual(verdict.failed_clauses, te.TRIAL_ELIGIBILITY_CLAUSES)


# ---------------------------------------------------------------------------
# Clause (b) -- the two REQUIRED evidence predicates
# ---------------------------------------------------------------------------

class EvidencePredicateClauseTests(_Base):

    def test_absent_undo_restored_predicate_refuses_and_names_it(self):
        op = "fixture.missing.verify_undo_restored"
        adapter = self.register(op, _NoUndoRestoredPredicate())
        verdict = self.verdict_for(op, adapter)
        self.assertRefusedOn(verdict, te.CLAUSE_EVIDENCE_PREDICATES_DECLARED)
        self.assertIn("verify_undo_restored", verdict.reason_text())
        self.assertNotIn("verify_apply_landed", verdict.reason_text())

    def test_absent_apply_landed_predicate_refuses_and_names_it(self):
        op = "fixture.missing.verify_apply_landed"
        adapter = self.register(op, _NoApplyLandedPredicate())
        verdict = self.verdict_for(op, adapter)
        self.assertRefusedOn(verdict, te.CLAUSE_EVIDENCE_PREDICATES_DECLARED)
        self.assertIn("verify_apply_landed", verdict.reason_text())
        self.assertNotIn("verify_undo_restored", verdict.reason_text())

    def test_a_lying_non_callable_predicate_declaration_refuses(self):
        """The defect a bare `is not None` check lets through: an adapter that
        declares the required NAME as a truthy class ATTRIBUTE rather than a
        method. It satisfies "declared", is captured off the class, and can
        never be called as a predicate."""
        op = "fixture.lying.non_callable_predicate"
        adapter = self.register(op, _LyingNonCallablePredicate())
        self.assertIsNotNone(get_dispatch(op).verify_undo_restored,
                             "precondition: the registry DID capture something, so "
                             "a bare is-not-None check would pass this fixture")
        verdict = self.verdict_for(op, adapter)
        self.assertRefusedOn(verdict, te.CLAUSE_EVIDENCE_PREDICATES_DECLARED)
        self.assertIn("verify_undo_restored", verdict.reason_text())

    def test_the_required_set_is_read_from_the_canonical_constant(self):
        """The clause must CONSUME `evidence.REQUIRED_EVIDENCE_PREDICATES`, not
        re-list the two names (the defect class this codebase has shipped five
        times). Patching the canonical tuple must immediately bind this gate --
        the same coupling `capability_invariants` / `copy_run_proof` are already
        pinned to."""
        op = "fixture.coupling.canonical_required_set"
        adapter = self.register(op, InboxShapedAdapter())
        self.assertTrue(self.verdict_for(op, adapter).eligible)

        grown = evidence_mod.REQUIRED_EVIDENCE_PREDICATES + ("verify_cut19_probe",)
        with mock.patch.object(evidence_mod, "REQUIRED_EVIDENCE_PREDICATES", grown):
            verdict = self.verdict_for(op, adapter)
        self.assertRefusedOn(verdict, te.CLAUSE_EVIDENCE_PREDICATES_DECLARED)
        self.assertIn("verify_cut19_probe", verdict.reason_text())


# ---------------------------------------------------------------------------
# Clause (c) -- the NEW absolute-state idempotent-restore declaration
# ---------------------------------------------------------------------------

class AbsoluteStateRestoreClauseTests(_Base):

    def test_silence_about_idempotency_refuses(self):
        op = "fixture.silent.about_idempotency"
        adapter = self.register(op, _SilentAboutIdempotency())
        verdict = self.verdict_for(op, adapter)
        self.assertRefusedOn(verdict, te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)
        self.assertIn(UNDO_IDEMPOTENCY_DECLARATION_ATTR, verdict.reason_text())

    def test_an_explicit_negative_declaration_refuses(self):
        op = "fixture.declares.not_absolute"
        adapter = self.register(op, _DeclaresNotAbsolute())
        self.assertRefusedOn(self.verdict_for(op, adapter),
                             te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)

    def test_a_truthy_non_boolean_declaration_refuses(self):
        """Deny-by-default at a trust-critical surface: the declaration must be
        the boolean True, not merely something truthy. `"yes"` / `1` /
        `["absolute"]` is a MALFORMED declaration, and a malformed declaration
        is not consent."""
        for i, bad in enumerate(("yes", 1, ["absolute"], {"absolute": True})):
            op = f"fixture.truthy.declaration.{i}"

            class _Truthy(_SilentAboutIdempotency):
                UNDO_IS_ABSOLUTE_STATE_RESTORE = bad

            adapter = self.register(op, _Truthy())
            with self.subTest(declared=bad):
                self.assertRefusedOn(self.verdict_for(op, adapter),
                                     te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)

    def test_declaration_is_captured_at_registration_not_read_at_call_time(self):
        """The declaration is frozen off the CLASS at registration time, before
        any capability code runs. Mutating the instance -- or even the class --
        afterwards must not flip an ineligible adapter to eligible: the same
        monkey-patch-inert property `AdapterDispatch` exists to give
        apply_one / build_write_client."""
        op = "fixture.late.declaration"

        class _Silent(_SilentAboutIdempotency):
            pass

        adapter = self.register(op, _Silent())
        self.assertRefusedOn(self.verdict_for(op, adapter),
                             te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)

        setattr(adapter, UNDO_IDEMPOTENCY_DECLARATION_ATTR, True)
        self.assertRefusedOn(self.verdict_for(op, adapter),
                             te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)

        setattr(_Silent, UNDO_IDEMPOTENCY_DECLARATION_ATTR, True)
        self.assertRefusedOn(self.verdict_for(op, adapter),
                             te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)

    def test_a_subclass_that_overrides_undo_one_without_redeclaring_refuses(self):
        """THE inheritance hole. An ordinary MRO lookup hands a subclass its
        parent's consent: declare nothing, replace undo_one with a RELATIVE
        delete, and the parent's `True` is captured for code the parent never
        saw. The declaration is a claim about a specific undo_one, so it does not
        survive that undo_one being replaced."""
        op = "fixture.subclass.overrides_undo_one"

        class _RelativeSubclass(InboxShapedAdapter):
            # Declares NOTHING itself; inherits UNDO_IS_ABSOLUTE_STATE_RESTORE
            # = True from InboxShapedAdapter while replacing undo_one with a
            # compensating delete.
            def undo_one(self, raw_client, unit):
                raw_client.delete(unit.undo_ref["message_id"])

        self.assertNotIn(UNDO_IDEMPOTENCY_DECLARATION_ATTR,
                         vars(_RelativeSubclass))
        self.assertIs(getattr(_RelativeSubclass,
                              UNDO_IDEMPOTENCY_DECLARATION_ATTR), True,
                      "precondition: a plain MRO getattr DOES see the parent's "
                      "True, which is exactly why the capture must be scoped")

        adapter = self.register(op, _RelativeSubclass())
        verdict = self.verdict_for(op, adapter)
        self.assertRefusedOn(verdict, te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)
        self.assertIn("OVERRIDES undo_one", verdict.reason_text())

    def test_a_subclass_that_overrides_undo_one_and_redeclares_is_eligible(self):
        op = "fixture.subclass.overrides_and_redeclares"

        class _RedeclaringSubclass(InboxShapedAdapter):
            UNDO_IS_ABSOLUTE_STATE_RESTORE = True

            def undo_one(self, raw_client, unit):
                raw_client.set_exact_labels(unit.undo_ref["message_id"],
                                            unit.undo_ref["prior_label_ids"])

        adapter = self.register(op, _RedeclaringSubclass())
        self.assertTrue(self.verdict_for(op, adapter).eligible)

    def test_a_base_declaring_and_defining_both_is_inherited_legitimately(self):
        """A family base that defines undo_one AND declares it, subclassed by a
        child that overrides neither, stays eligible: the claim still describes
        the code that will run."""
        op = "fixture.base.declares_and_defines"

        class _AbsoluteFamilyBase(_InboxPlanBase):
            UNDO_IS_ABSOLUTE_STATE_RESTORE = True
            verify_apply_landed = _label_apply_landed
            verify_undo_restored = _label_undo_restored

            def undo_one(self, raw_client, unit):
                raw_client.set_exact_labels(unit.undo_ref["message_id"],
                                            unit.undo_ref["prior_label_ids"])

        class _InheritsEverything(_AbsoluteFamilyBase):
            pass

        adapter = self.register(op, _InheritsEverything())
        self.assertTrue(self.verdict_for(op, adapter).eligible,
                        self.verdict_for(op, adapter).reason_text())

    def test_declaring_for_an_undo_one_inherited_unchanged_is_eligible(self):
        """The fourth shape, and the reason the scoping rule is an MRO-ORDER
        comparison rather than a strict same-class test: a subclass may declare
        for an undo_one it inherits UNCHANGED, because the declaring author can
        see the implementation being vouched for. `InboxShapedAdapter` itself is
        this shape, so a strict same-class rule would refuse the compliant
        fixture the whole suite is built on."""
        op = "fixture.declares.for_inherited_undo_one"
        self.assertNotIn("undo_one", vars(InboxShapedAdapter))
        self.assertIn(UNDO_IDEMPOTENCY_DECLARATION_ATTR,
                      vars(InboxShapedAdapter))
        adapter = self.register(op, InboxShapedAdapter())
        self.assertTrue(self.verdict_for(op, adapter).eligible)

    def test_a_non_callable_undo_one_refuses(self):
        """`register_adapter` captures `cls.undo_one` unchecked, so a plain class
        ATTRIBUTE named undo_one registers successfully. The trial would apply to
        the live surface and then raise calling it — the exact "mutated with no
        way back" outcome this gate exists to prevent. Same hole clause (b)
        closes for the evidence predicates, on the one symbol the whole protocol
        depends on."""
        op = "fixture.undo_one.not_callable"

        class _NonCallableUndo(InboxShapedAdapter):
            UNDO_IS_ABSOLUTE_STATE_RESTORE = True
            undo_one = True  # not a method

        adapter = self.register(op, _NonCallableUndo())
        self.assertIs(get_dispatch(op).undo_one, True,
                      "precondition: the registry captured a non-callable, so "
                      "every other clause would pass")
        verdict = self.verdict_for(op, adapter)
        self.assertRefusedOn(verdict, te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)
        self.assertIn("callable", verdict.reason_text())

    def test_reason_states_why_a_relative_undo_is_unsafe_for_a_trial(self):
        """The refusal must be actionable in plain language: the recovery path
        may run undo_one when apply was merely INTENDED, and may run it more
        than once -- which is exactly why a compensating action is refused."""
        op = "fixture.reason.text"
        adapter = self.register(op, _SilentAboutIdempotency())
        text = self.verdict_for(op, adapter).reason_text().lower()
        self.assertIn("more than once", text)
        self.assertIn("fix step", text)


# ---------------------------------------------------------------------------
# Clause (a) + the plan-integrity precondition
# ---------------------------------------------------------------------------

class PlanClauseTests(_Base):

    def test_a_single_unreversible_unit_refuses_the_whole_plan(self):
        op = "fixture.one.unreversible_unit"
        self.register(op, InboxShapedAdapter())
        units = [
            EffectUnit(unit_id="m1", target_ref={"message_id": "m1"},
                       undo_ref={"message_id": "m1", "prior_label_ids": []}),
            EffectUnit(unit_id="m2", target_ref={"message_id": "m2"},
                       undo_ref=None),
        ]
        verdict = te.check_trial_eligibility(op, units, self.capsules(op, units))
        self.assertRefusedOn(verdict, te.CLAUSE_UNDO_REF_PRESENT)
        self.assertIn("m2", verdict.reason_text())

    def test_an_empty_plan_refuses_rather_than_passing_vacuously(self):
        """"Every planned unit has an undo_ref" is vacuously TRUE over an empty
        plan -- the textbook pass-by-default. A trial that applies nothing
        cannot produce restoration evidence, so an empty plan is refused."""
        op = "fixture.empty.plan"
        self.register(op, InboxShapedAdapter())
        verdict = te.check_trial_eligibility(op, [], {})
        self.assertRefusedOn(verdict, te.CLAUSE_PLAN_INTEGRITY)

    def test_duplicate_unit_ids_refuse(self):
        """The journal and the capsule set both key on unit_id, so a duplicate
        silently collapses two mutations into one entry -- and one of them would
        never be undone."""
        op = "fixture.duplicate.unit_ids"
        self.register(op, InboxShapedAdapter())
        units = [
            EffectUnit(unit_id="m1", target_ref={}, undo_ref={"prior": 1}),
            EffectUnit(unit_id="m1", target_ref={}, undo_ref={"prior": 2}),
        ]
        verdict = te.check_trial_eligibility(op, units, self.capsules(op, units))
        self.assertRefusedOn(verdict, te.CLAUSE_PLAN_INTEGRITY)
        self.assertIn("m1", verdict.reason_text())

    def test_an_unusable_unit_id_refuses(self):
        op = "fixture.unusable.unit_id"
        self.register(op, InboxShapedAdapter())
        for bad_id in ("", "   ", None, 7):
            with self.subTest(unit_id=bad_id):
                units = [EffectUnit(unit_id=bad_id, target_ref={},
                                    undo_ref={"prior": 1})]
                verdict = te.check_trial_eligibility(op, units,
                                                     {bad_id: {"prior": 1}})
                self.assertRefusedOn(verdict, te.CLAUSE_PLAN_INTEGRITY)

    def test_a_non_effectunit_planned_entry_refuses(self):
        op = "fixture.non.effectunit"
        self.register(op, InboxShapedAdapter())
        verdict = te.check_trial_eligibility(
            op, [{"unit_id": "m1", "undo_ref": {"prior": 1}}], {"m1": {"p": 1}})
        self.assertRefusedOn(verdict, te.CLAUSE_PLAN_INTEGRITY)


# ---------------------------------------------------------------------------
# Clause (d) -- recovery-capsule serializability
# ---------------------------------------------------------------------------

class RecoveryCapsuleClauseTests(_Base):

    def test_a_capsule_that_json_cannot_serialize_refuses(self):
        op = "fixture.capsule.unserializable"
        adapter = self.register(op, InboxShapedAdapter())
        verdict = te.check_trial_eligibility(
            op, self.inbox_units(adapter),
            {"m1": {"undo_ref": {"prior_label_ids": {"INBOX"}}}})
        self.assertRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)
        self.assertIn("m1", verdict.reason_text())

    def test_a_capsule_carrying_nan_refuses(self):
        """`json.dumps` accepts NaN/Infinity BY DEFAULT and emits a bare `NaN`
        -- not valid JSON, and rejected by a strict reader. A journal entry that
        cannot be read back after a crash is worthless, so it is refused."""
        op = "fixture.capsule.nan"
        adapter = self.register(op, InboxShapedAdapter())
        self.assertEqual(json.dumps({"x": math.nan}), '{"x": NaN}',
                         "precondition: the stdlib default really does emit NaN")
        verdict = te.check_trial_eligibility(
            op, self.inbox_units(adapter), {"m1": {"undo_ref": {"x": math.nan}}})
        self.assertRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)

    def test_a_capsule_with_a_non_string_mapping_key_refuses(self):
        """`json.dumps({1: "a"})` SUCCEEDS and silently coerces the key to
        `"1"`, so a resumed executor's `capsule[1]` lookup raises KeyError after
        a crash. Serializable is not the same as faithful."""
        op = "fixture.capsule.int_key"
        adapter = self.register(op, InboxShapedAdapter())
        self.assertEqual(json.dumps({1: "a"}), '{"1": "a"}',
                         "precondition: the stdlib really does coerce the key")
        verdict = te.check_trial_eligibility(
            op, self.inbox_units(adapter),
            {"m1": {"undo_ref": {"by_index": {1: "INBOX"}}}})
        self.assertRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)

    def test_a_capsule_keyed_by_none_refuses(self):
        """`None` is itself a legal mapping key that json coerces to the string
        `"null"`. The key-fidelity check must not use None as its own
        "nothing found" signal, or this exact capsule becomes a false negative
        in a fail-closed check."""
        op = "fixture.capsule.none_key"
        adapter = self.register(op, InboxShapedAdapter())
        self.assertEqual(json.dumps({None: "a"}), '{"null": "a"}',
                         "precondition: the stdlib really does coerce a None key")
        verdict = te.check_trial_eligibility(
            op, self.inbox_units(adapter),
            {"m1": {"undo_ref": {"by_key": {None: "INBOX"}}}})
        self.assertRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)

    def test_a_capsule_keyed_by_a_falsy_non_string_refuses(self):
        """The companion foot-gun: a `0` / `False` key is falsy, so a truthiness
        test on the found key would also let it through."""
        op = "fixture.capsule.zero_key"
        adapter = self.register(op, InboxShapedAdapter())
        verdict = te.check_trial_eligibility(
            op, self.inbox_units(adapter),
            {"m1": {"undo_ref": {"rows": [{0: "INBOX"}]}}})
        self.assertRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)

    def test_a_missing_capsule_refuses(self):
        op = "fixture.capsule.missing"
        adapter = self.register(op, InboxShapedAdapter())
        verdict = te.check_trial_eligibility(op, self.inbox_units(adapter), {})
        self.assertRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)
        self.assertIn("m1", verdict.reason_text())

    def test_a_none_capsule_is_treated_as_missing(self):
        op = "fixture.capsule.none"
        adapter = self.register(op, InboxShapedAdapter())
        verdict = te.check_trial_eligibility(op, self.inbox_units(adapter),
                                             {"m1": None})
        self.assertRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)

    def test_capsules_supplied_as_a_non_mapping_refuse(self):
        op = "fixture.capsule.non_mapping"
        adapter = self.register(op, InboxShapedAdapter())
        verdict = te.check_trial_eligibility(op, self.inbox_units(adapter),
                                             [{"undo_ref": {}}])
        self.assertRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)

    def test_a_self_referential_capsule_refuses_rather_than_raising(self):
        """A preflight that raises is indistinguishable, to its caller, from a
        preflight that failed to run -- so even a pathological capsule must come
        back as a plain refusal."""
        op = "fixture.capsule.circular"
        adapter = self.register(op, InboxShapedAdapter())
        capsule = {"undo_ref": {}}
        capsule["self"] = capsule
        verdict = te.check_trial_eligibility(op, self.inbox_units(adapter),
                                             {"m1": capsule})
        self.assertRefusedOn(verdict, te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE)

    def test_a_degenerate_capsule_is_ACCEPTED_and_that_is_the_documented_bound(self):
        """Locks the exactly-limited guarantee clause (d) gives. The capsule
        FORMAT belongs to the journal task, so this gate does not judge content:
        `{}` / `""` / `0` / `False` / `[]` all pass. Recorded as a test, not just
        prose, so a downstream consumer cannot infer a non-emptiness guarantee
        this clause never made — and so that tightening it later is a visible,
        deliberate change to a pinned expectation."""
        op = "fixture.capsule.degenerate"
        adapter = self.register(op, InboxShapedAdapter())
        for degenerate in ({}, "", 0, False, []):
            with self.subTest(capsule=degenerate):
                verdict = te.check_trial_eligibility(
                    op, self.inbox_units(adapter), {"m1": degenerate})
                self.assertTrue(verdict.eligible, verdict.reason_text())

    def test_a_tuple_valued_capsule_is_accepted(self):
        """JSON's type lattice is narrower than Python's: a tuple comes back as
        a list. That is still a faithful, restorable capsule -- refusing it
        would refuse the shipped Gmail adapters' own `prior_label_ids` tuples --
        so clause (d) checks a real round trip, not type identity."""
        op = "fixture.capsule.tuple_valued"
        adapter = self.register(op, InboxShapedAdapter())
        verdict = te.check_trial_eligibility(
            op, self.inbox_units(adapter),
            {"m1": {"undo_ref": {"prior_label_ids": ("INBOX", "UNREAD")}}})
        self.assertTrue(verdict.eligible, verdict.reason_text())


# ---------------------------------------------------------------------------
# The one REAL shipped adapter: gmail.filter.create must be refused on clause
# (a) AND, independently, on clause (c).
# ---------------------------------------------------------------------------

class RealGmailFilterCreateRefusalTests(_Base):
    """`adapters_gmail.GmailFilterCreateAdapter`, unstubbed. Its
    UNDO_DESCRIPTOR records `"reverse_op_kind": None  # no native "un-create";
    delete is the reverse` (adapters_gmail.py:424) and `"recovery":
    "delete_created_filter"`: deleting a created filter is a RELATIVE,
    non-idempotent compensating action, and the only reversal id lives in an
    in-memory dict on the adapter instance (`:427-428`) that no crash
    survives."""

    def setUp(self):
        # The adapter is registered at adapters_gmail import scope. Assert that
        # rather than re-register: if some earlier test in the process
        # unregistered it, this must fail loudly here rather than silently turn
        # the two refusals below into "no registered adapter" refusals that
        # would pass for the wrong reason.
        self.assertIsNotNone(
            get_dispatch(OP_FILTER_CREATE),
            "precondition: adapters_gmail registers gmail.filter.create at "
            "module scope; these tests exercise that REAL registration")

    def _plan_and_capsules(self):
        adapter = GmailFilterCreateAdapter()
        units = adapter.plan({"filters": [
            {"client_ref": "f1", "criteria": {"from": "a@b.c"},
             "action": {"addLabelIds": ["Label_1"]}},
        ]})
        return units, {u.unit_id: {"op_kind": OP_FILTER_CREATE,
                                   "unit_id": u.unit_id,
                                   "undo_ref": u.undo_ref} for u in units}

    def test_the_shipped_adapter_really_plans_no_undo_ref(self):
        """Ground truth for the two refusals below, read off the real module
        rather than assumed."""
        units, _ = self._plan_and_capsules()
        self.assertEqual(len(units), 1)
        self.assertIsNone(units[0].undo_ref)
        self.assertIsNone(
            GmailFilterCreateAdapter.UNDO_DESCRIPTOR["reverse_op_kind"])
        self.assertEqual(
            GmailFilterCreateAdapter.UNDO_DESCRIPTOR["recovery"],
            "delete_created_filter")

    def test_filter_create_is_refused_on_clause_a_undo_ref(self):
        units, capsules = self._plan_and_capsules()
        verdict = te.check_trial_eligibility(OP_FILTER_CREATE, units, capsules)
        self.assertRefusedOn(verdict, te.CLAUSE_UNDO_REF_PRESENT)
        self.assertIn("f1", verdict.reason_text())

    def test_filter_create_is_refused_on_clause_c_independently(self):
        """Asserted SEPARATELY from clause (a) on purpose: two independent bans
        agreeing on the same op is the property the design wants. A combined
        assertion would still pass if either ban were lost."""
        units, capsules = self._plan_and_capsules()
        verdict = te.check_trial_eligibility(OP_FILTER_CREATE, units, capsules)
        self.assertRefusedOn(verdict, te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)

    def test_clause_c_refuses_filter_create_even_with_an_undo_ref_supplied(self):
        """Proves clause (c) is not merely echoing clause (a): hand the gate a
        plan whose unit DOES carry an undo_ref and clause (c) still refuses,
        because the shipped adapter declares nothing about absolute-state
        restore."""
        units = [EffectUnit(unit_id="f1", target_ref={"criteria": {}, "action": {}},
                            undo_ref={"filter_id": "hand-supplied"})]
        verdict = te.check_trial_eligibility(
            OP_FILTER_CREATE, units,
            {"f1": {"undo_ref": {"filter_id": "hand-supplied"}}})
        self.assertNotRefusedOn(verdict, te.CLAUSE_UNDO_REF_PRESENT)
        self.assertRefusedOn(verdict, te.CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE)

    def test_filter_create_declares_both_evidence_predicates_so_clause_b_passes(self):
        """Scope honesty: the shipped filter-create adapter DOES declare both
        required evidence predicates, so clause (b) is not one of its refusal
        grounds. Recording that keeps the two real grounds -- (a) and (c) --
        exact."""
        units, capsules = self._plan_and_capsules()
        verdict = te.check_trial_eligibility(OP_FILTER_CREATE, units, capsules)
        self.assertNotRefusedOn(verdict, te.CLAUSE_EVIDENCE_PREDICATES_DECLARED)


# ---------------------------------------------------------------------------
# Zone membership -- asserted in BOTH directions, so the entry in zones.py is
# provably load-bearing rather than decorative.
# ---------------------------------------------------------------------------

class SealedKernelZoneMembershipTests(unittest.TestCase):

    _LIB = _AGENTS_LIB / "external_write"
    _MODULE = _LIB / "trial_eligibility.py"

    def test_the_preflight_is_enrolled_as_sealed_kernel(self):
        self.assertIn("trial_eligibility.py", zones.SEALED_KERNEL_MODULE_PATHS)
        self.assertEqual(zones.classify_zone(self._MODULE, self._LIB),
                         zones.Zone.SEALED_KERNEL)

    def test_the_preflight_scans_clean_as_sealed_kernel(self):
        self.assertEqual(scan.scan_paths([self._MODULE], allowed_root=self._LIB), [])

    def test_without_that_membership_the_preflight_would_be_flagged(self):
        """The counterfactual. Scanned as CAPABILITY the module trips the
        CAPABILITY-zone-ONLY module-boundary rules, because it legitimately
        reaches the sibling kernel adapter registry -- which is exactly why the
        zones.py entry exists. If a future change made these violations
        disappear, the SEALED_KERNEL entry would have become decorative and
        should be reviewed rather than kept out of habit."""
        without = frozenset(
            p for p in zones.SEALED_KERNEL_MODULE_PATHS if p != "trial_eligibility.py")
        kinds = {v.kind for v in scan.scan_paths(
            [self._MODULE], allowed_root=self._LIB, sealed_kernel_paths=without)}
        self.assertEqual(
            kinds,
            {"adapter_module_import", "adapter_registry_reference",
             "sealed_kernel_import"})

    def test_sealed_kernel_membership_does_not_let_a_capability_import_it(self):
        """Membership exempts THIS module from the CAPABILITY-zone-only rules;
        it does not add the module to the narrow set a capability may import.
        The trial protocol is kernel-driven -- capability code has no business
        deciding its own trial eligibility."""
        self.assertNotIn("trial_eligibility",
                         scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES)


if __name__ == "__main__":
    unittest.main()
