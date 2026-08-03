"""Tests for the AUTHORIZE/EXECUTE SPLIT — `external_write.write_authorization`.

The seam under test:

    plan -> preflight -> authorize through the EXISTING live-bounded funnel
         -> AuthorizedPlan -> ordinary executor OR journaled trial executor

Three properties matter more than the rest, and each has its own class below.

1. THE PREFLIGHT IS UNAVOIDABLE, not merely present. A gate that exists off the
   enforced path is worth nothing, and that is the failure this package has
   shipped repeatedly: a provisioner hook that was None in every deployment, a
   migration function with no callers, a trust primitive that was a wrapper
   nobody called — each green because a test proved the FUNCTION worked. So the
   tests here do not merely check that the preflight answers correctly when
   called. They check, structurally, that the real flow cannot reach an executor
   without it: exactly one construction site for the authorization carrier, one
   caller of the preflight, a private construction token, and fail-closed
   post-conditions re-validated on the carrier at consumption time.

2. THERE IS EXACTLY ONE AUTHORIZATION IMPLEMENTATION. Any second copy IS the
   defect class — "two paths that must agree" has caused four of the last five
   defects in this family. Proven by AST over the real package source (a text
   search cannot answer a question about code structure), not by reading.

3. NOTHING IS RELAXED FOR A TRIAL. No cap is duplicated, no ledger is
   duplicated, no flag relaxes enforcement. A trial traverses the gate's
   existing live-bounded branch and is still refused without a declaration,
   without a ledger, over the cap, while paused, and without a valid receipt.
   The one relaxation is the one that branch already grants to every caller:
   `accepted: true` is not required pre-acceptance, but a DECLARATION is.

The journaled trial executor itself is a separate concern and does not exist
yet. `_TrialExecutorDouble` below is a TEST DOUBLE — it lives in this file only,
proves the carrier is consumable by a second executor, and asserts the shape the
real one will consume. Nothing in the package's production code refers to it.

Uses stub clients only; no network, and no test here touches the real project's
ambient `.wizard/paused-mechanisms` state.
"""

import ast
import copy
import dataclasses
import pickle
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import adapters as adapters_mod  # noqa: E402
from external_write import scan, zones  # noqa: E402
from external_write import trial_eligibility as te  # noqa: E402
from external_write import write_authorization as wa  # noqa: E402
from external_write import write_gate  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    get_dispatch, register_adapter, unregister_adapter,
)
from external_write.contracts import (  # noqa: E402
    OPERATION_CONTRACTS, OperationContract, WRITE_AFFECTING_MODULES,
    register_contract,
)
from external_write.lifecycle_test_fixtures import (  # noqa: E402
    hermetic_paused_mechanisms,
)
from external_write.operations import EffectUnit, Operation  # noqa: E402
from external_write.write_gate import (  # noqa: E402
    COPY_SURFACE, LIVE_BOUNDED_TEST_TARGETS, InvocationLedger,
)

_EXTERNAL_WRITE_DIR = _AGENTS_LIB / "external_write"
# The module under test, spelled as the guards below report paths: relative to
# the `wizard/` distribution root, so a same-named file elsewhere is distinct.
_WA_REL = "agents/lib/external_write/write_authorization.py"


# ---------------------------------------------------------------------------
# Fixtures: a trial-eligible adapter shape, and the surfaces around it.
#
# The fixture reproduces the CONTRACT SHAPE of a compliant adapter (absolute
# prior-state restore, both evidence predicates, an undo_ref per unit). It is
# not a claim about any real operator-authored adapter: only ONE shipped
# op_kind is fully trial-eligible today, and this file never asserts otherwise.
# ---------------------------------------------------------------------------

class _RecordingClient:
    """Write-capable stand-in. Records every mutation so a test can assert that
    a refusal really did write NOTHING, rather than trusting that it didn't."""

    def __init__(self):
        self.applied = []
        self.undone = []

    def set_exact_labels(self, message_id, label_ids):
        self.applied.append((message_id, list(label_ids)))

    def restore_exact_labels(self, message_id, label_ids):
        self.undone.append((message_id, list(label_ids)))


class _CompliantAdapter:
    """Trial-eligible against every preflight clause: an undo_ref per unit, both
    evidence predicates as real callables, and an absolute prior-state restore
    declared on the same class that defines the `undo_one` it describes."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

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
        raw_client.restore_exact_labels(unit.undo_ref["message_id"],
                                        unit.undo_ref["prior_label_ids"])

    def verify_one(self, observer, unit):
        return {"current_label_ids": list(observer.get_message(unit.unit_id))}

    def verify_apply_landed(self, evidence):
        return bool(evidence.poststate.get("is_trashed"))

    def verify_undo_restored(self, evidence):
        return bool(evidence.poststate.get("matches_prestate"))


class _UnreversibleAdapter(_CompliantAdapter):
    """Identical in every respect EXCEPT that its plan carries no undo_ref, so
    exactly ONE preflight clause refuses it. Used to prove a refusal comes from
    the preflight and not from some other part of the flow."""

    def plan(self, params):
        return [EffectUnit(unit_id=m["message_id"],
                           target_ref={"message_id": m["message_id"]},
                           undo_ref=None)
                for m in (params or {}).get("messages", [])]


class _TrialExecutorDouble:
    """TEST DOUBLE for the journaled trial executor that does not exist yet.

    Its only purpose is to prove the seam: a second executor can consume the
    SAME `AuthorizedPlan` the ordinary executor consumes, and it has no other
    source of units, dispatch or authority. It deliberately reads everything off
    the plan — it never re-plans, never re-resolves the dispatch, and never
    consults the gate itself.

    It also asserts what the real executor will be built to assert: it refuses
    anything that is not a trial-intent plan. That check lives HERE, in a
    double, rather than as a zero-caller guard in production code.
    """

    def __init__(self):
        self.journal = []

    def execute(self, plan, raw_client):
        if not isinstance(plan, wa.AuthorizedPlan):
            raise AssertionError("a trial executor takes an AuthorizedPlan")
        if plan.intent != wa.EXECUTION_INTENT_TRIAL:
            raise AssertionError("not a trial-intent plan")
        for unit in plan.units:
            # A real executor writes this entry to disk BEFORE the mutation.
            self.journal.append({"unit_id": unit.unit_id,
                                 "capsule": plan.recovery_capsules[unit.unit_id],
                                 "state": "apply_intended"})
            plan.dispatch.apply_one(plan.dispatch.instance, raw_client, unit)
            self.journal[-1]["state"] = "apply_attempted"
        return self.journal


def _receipt(op, *, valid=True):
    import hashlib
    digest = hashlib.sha256(op.canonical_repr().encode()).hexdigest()
    delta = timedelta(seconds=900) if valid else timedelta(seconds=-900)
    expires_at = (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"approved_operation_digest": digest, "expires_at": expires_at}


def _entry(*, id="fixture_surface", risk_class="sensitive_data",
           blast_radius_cap=25, declared_test_target="native_undo",
           recovery_profile_ref=None, accepted=False):
    return {"id": id, "name": id, "action_class": "modify",
            "risk_class": risk_class, "recovery_profile_ref": recovery_profile_ref,
            "declared_test_target": declared_test_target,
            "blast_radius_cap": blast_radius_cap, "accepted": accepted}


_UNSET = object()


class _Base(unittest.TestCase):
    """Registration hygiene: the adapter + contract registries are module-global,
    so every fixture registration is undone on teardown."""

    OP_KIND = "fixture.authorization.set_exact_labels"
    SURFACE = "fixture_surface"

    def setUp(self):
        self.client = _RecordingClient()
        self.ledger = InvocationLedger()

    def register(self, adapter=None, *, op_kind=None, risk_class="sensitive_data",
                 blast_radius_cap=25):
        op_kind = op_kind or self.OP_KIND
        register_adapter(op_kind, adapter if adapter is not None else _CompliantAdapter())
        self.addCleanup(unregister_adapter, op_kind)
        register_contract(OperationContract(
            op_kind=op_kind, writes=("labels",), produces=(),
            dependency_set=WRITE_AFFECTING_MODULES,
            verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False,
            risk_class=risk_class, requires_accepted_phase=True,
            blast_radius_cap=blast_radius_cap))
        self.addCleanup(OPERATION_CONTRACTS.pop, op_kind, None)
        return get_dispatch(op_kind)

    def op(self, *, op_kind=None, surface=None, n=1):
        return Operation(
            surface=surface if surface is not None else self.SURFACE,
            object_id="m1", field="labels", new_value="TRASH",
            op_kind=op_kind or self.OP_KIND, batch_id="b1",
            params={"messages": [{"message_id": f"m{i}",
                                  "prior_label_ids": ["INBOX"]}
                                 for i in range(1, n + 1)]})

    def capsules(self, op):
        dispatch = get_dispatch(op.op_kind)
        return {u.unit_id: {"unit_id": u.unit_id, "undo_ref": u.undo_ref}
                for u in dispatch.plan(dispatch.instance, op.params)}

    def authorize_trial(self, op, *, descriptor_set=_UNSET, cap_ledger=_UNSET,
                        receipt=_UNSET, capsules=_UNSET, target="native_undo",
                        paused_root=None):
        # `_UNSET` (not None) marks "use the working default", so a test can pass
        # an explicit None to exercise an ABSENT ledger / receipt — the fail-safe
        # branch a None-means-default helper would have quietly filled in.
        return wa.authorize_operation(
            op, _receipt(op) if receipt is _UNSET else receipt,
            intent=wa.EXECUTION_INTENT_TRIAL, target=target,
            descriptor_set=[_entry()] if descriptor_set is _UNSET else descriptor_set,
            cap_ledger=self.ledger if cap_ledger is _UNSET else cap_ledger,
            recovery_capsules=(self.capsules(op) if capsules is _UNSET
                               else capsules),
            paused_root=paused_root)

    def assertRefused(self, authorization, *, contains=None):
        self.assertFalse(authorization.authorized,
                         "expected a refusal; the operation was AUTHORIZED")
        self.assertIsNone(authorization.plan)
        self.assertEqual(authorization.refusal.status, "refused")
        if contains is not None:
            self.assertIn(contains, authorization.refusal.detail["reason"])
        return authorization.refusal


# ---------------------------------------------------------------------------
# 1. THE PREFLIGHT IS UNAVOIDABLE — structural, not behavioural
# ---------------------------------------------------------------------------

_WIZARD_ROOT = _AGENTS_LIB.parents[1]
_PARSED_PRODUCTION_MODULES = None


def _production_modules():
    """Every production Python module under `wizard/` — the WHOLE distribution
    subtree, recursively, not just the emitted package directory.

    Two exclusions, both deliberate and both narrow:
      * `foundation-bundles/` — released bundle templates are FROZEN copies of a
        past cut. They legitimately still contain the pre-split
        `adapters._validate_receipt` and their own gate call, and rewriting a
        released bundle is exactly what must never happen.
      * `test_*.py` — a test may legitimately construct or call anything.

    Everything else is in scope, including build-side scripts and scan fixtures:
    the single-implementation property is a claim about the whole subtree, and a
    guard scoped to one directory would not notice a second gate call, preflight
    call or carrier construction placed anywhere else. Returns `(relpath, tree)`
    pairs, parsed once and reused.
    """
    global _PARSED_PRODUCTION_MODULES
    if _PARSED_PRODUCTION_MODULES is None:
        parsed = []
        for path in sorted(_WIZARD_ROOT.rglob("*.py")):
            rel = path.relative_to(_WIZARD_ROOT).as_posix()
            if rel.startswith("foundation-bundles/") or path.name.startswith("test_"):
                continue
            # A file that cannot be parsed is a FAILURE of the guard, never a
            # silently skipped module: skipping is how a scanner goes blind.
            parsed.append((rel, ast.parse(path.read_text(encoding="utf-8"))))
        _PARSED_PRODUCTION_MODULES = parsed
    return _PARSED_PRODUCTION_MODULES


def _called_names(tree):
    """Every simple/attribute call NAME in `tree` (`f(...)` -> "f";
    `m.f(...)` -> "f"), by AST — never a text search."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _modules_calling(name):
    return [rel for rel, tree in _production_modules()
            if name in _called_names(tree)]


def _modules_naming(identifier):
    """Every production module whose AST contains `identifier` as a Name or
    Attribute node — i.e. actually references the symbol, not merely mentions it
    in a docstring or comment."""
    hits = []
    for rel, tree in _production_modules():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Name) and node.id == identifier) or \
                    (isinstance(node, ast.Attribute) and node.attr == identifier):
                hits.append(rel)
                break
    return hits


def _modules_constructing(identifier):
    """Every production module that CONSTRUCTS `identifier` — i.e. names it in a
    call position (`AuthorizedPlan(...)`), by AST.

    Distinct from `_modules_naming` on purpose. Referencing the carrier (an
    `isinstance` fail-closed check, a type annotation) is what a consumer of an
    authorization does; CONSTRUCTING it is what only the authorizer may do.
    """
    hits = []
    for rel, tree in _production_modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Name) and func.id == identifier) or \
                    (isinstance(func, ast.Attribute) and func.attr == identifier):
                hits.append(rel)
                break
    return hits


def _modules_subclassing(identifier):
    """Every production module that names `identifier` in a `ClassDef.bases`
    position — i.e. SUBCLASSES it, by AST.

    A subclass is an ORDINARY route into existence, alongside a direct call and
    the reconstruction protocols, and it is the worst-behaved of those: an
    overriding `__post_init__` never runs the token check at all, so the resulting
    object carries none of the carrier's invariants while still satisfying
    `isinstance(plan, AuthorizedPlan)` in every consumer. It is invisible to
    `_modules_constructing` (a class base is not a call) and invisible to the
    construction-token test (the token is never named). Hence its own probe.

    Anti-drift over this package's own source, not a completeness claim: see
    `write_authorization`'s DISCLOSED BOUND for why in-process reflection routes
    cannot be enumerated, and why nothing here should try.
    """
    hits = []
    for rel, tree in _production_modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                if (isinstance(base, ast.Name) and base.id == identifier) or \
                        (isinstance(base, ast.Attribute) and base.attr == identifier):
                    hits.append(rel)
                    break
            if hits and hits[-1] == rel:
                break
    return hits


class SingleAuthorizationImplementationTests(unittest.TestCase):
    """Review focus: is there exactly ONE authorization implementation? Every
    assertion here is made by parsing the real package source."""

    def test_the_write_gate_is_called_from_exactly_one_production_module(self):
        # The gate call is the heart of authorization. Two callers would be two
        # authorization implementations that must agree, however similar they
        # looked on the day they were written.
        self.assertEqual(_modules_calling("evaluate_write_gate"),
                         [_WA_REL])

    def test_the_trial_preflight_has_exactly_one_production_caller(self):
        # The anti-zero-caller assertion: the preflight shipped with NO
        # production caller at all, which is this codebase's most-repeated
        # defect shape. This asserts both directions — it is called, and it is
        # called from exactly one place.
        self.assertEqual(_modules_calling("check_trial_eligibility"),
                         [_WA_REL])

    def test_receipt_validation_has_exactly_one_implementation(self):
        # It used to live in adapters.py, where only run_operation could reach
        # it; a trial executor would have needed its own copy.
        defs = []
        for rel, tree in _production_modules():
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and "receipt" in node.name \
                        and "valid" in node.name:
                    defs.append(f"{rel}:{node.name}")
        self.assertEqual(defs, [f"{_WA_REL}:validate_receipt"])

    def test_the_authorization_carrier_is_constructed_in_exactly_one_place(self):
        tree = ast.parse((_EXTERNAL_WRITE_DIR / "write_authorization.py")
                         .read_text(encoding="utf-8"))
        authorize = next(n for n in ast.walk(tree)
                         if isinstance(n, ast.FunctionDef)
                         and n.name == "authorize_operation")
        inside = sum(1 for n in ast.walk(authorize)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "AuthorizedPlan")
        whole_module = sum(1 for n in ast.walk(tree)
                           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                           and n.func.id == "AuthorizedPlan")
        self.assertEqual(inside, 1)
        self.assertEqual(whole_module, 1,
                         "AuthorizedPlan is constructed somewhere other than "
                         "inside authorize_operation")
        # And brought into existence nowhere else in the package at all, by
        # EITHER route.
        #
        # RETARGETED (Cut 1.9 Task 3), and the retarget then CORRECTED after
        # review. This was `_modules_naming("AuthorizedPlan") == [_WA_REL]` -- "no
        # other module NAMES the carrier" -- which was a workable proxy for "no
        # other module brings one into existence" only while nothing consumed the
        # carrier. The carrier exists precisely to be consumed, and a consumer
        # handed one must be able to refuse anything else: the trial write-ahead
        # journal opens only from an `isinstance(plan, AuthorizedPlan)` that
        # passes. That reference is a fail-closed check, not a construction site,
        # and forbidding it would push consumers toward duck-typing whatever they
        # are handed -- the opposite of what this guard is for.
        #
        # The first retarget replaced the naming check with the CALL check alone,
        # which lost a shape the naming check had covered: a production module
        # could subclass the carrier and override `__post_init__`, and a class
        # base is not a call. Both of THOSE routes are asserted now, separately,
        # because they fail differently -- see `_modules_subclassing`.
        #
        # Neither assertion is a completeness claim, and this pair must never be
        # read as one. They are build-time ANTI-DRIFT checks over this package's
        # own source: they catch a carrier brought into existence off the
        # sanctioned path by a future author in good faith. In-process reflection
        # defeats them by construction and is disclosed as a within-ceiling bound
        # in `write_authorization`'s DISCLOSED BOUND -- which is also why no test
        # here counts remaining routes.
        self.assertEqual(_modules_constructing("AuthorizedPlan"), [_WA_REL])
        self.assertEqual(
            _modules_subclassing("AuthorizedPlan"), [],
            "a production module subclasses the authorization carrier. An "
            "overriding __post_init__ never runs the token check, so the "
            "subclass instance carries NONE of the carrier's invariants while "
            "still satisfying isinstance() in every consumer")

    def test_the_carrier_refuses_to_be_subclassed_at_all(self):
        """The structural half of the subclass route: `__init_subclass__` removes
        it rather than watching for it.

        The AST assertion above is a detective control over this package's own
        source. This one is the preventive control, and it holds for a subclass
        defined anywhere -- including in code this repo never parses. Both are
        kept: if a future author deletes `__init_subclass__`, the AST assertion
        still trips on any in-package use of the reopened route.
        """
        with self.assertRaises(wa.AuthorizationRequiredError) as ctx:
            class _ForgedPlan(wa.AuthorizedPlan):
                def __post_init__(self, issued_by):
                    return
        self.assertIn("subclass", str(ctx.exception).lower())

    def test_subclassing_is_refused_even_without_overriding_post_init(self):
        """Refused at class-creation time, so it cannot depend on what the
        subclass happens to override -- a subclass that merely adds a field would
        also reach `__post_init__` with a token it does not hold, but a subclass
        that overrides it would not, and the guard must not have to tell them
        apart."""
        with self.assertRaises(wa.AuthorizationRequiredError):
            class _Extended(wa.AuthorizedPlan):
                pass

    def test_the_construction_token_is_named_in_exactly_one_module(self):
        self.assertEqual(_modules_naming("_ISSUED_BY_AUTHORIZE"), [_WA_REL])

    def test_authorization_re_implements_no_cap_and_no_ledger(self):
        tree = ast.parse((_EXTERNAL_WRITE_DIR / "write_authorization.py")
                         .read_text(encoding="utf-8"))
        called = _called_names(tree)
        for forbidden in ("reserve", "record", "InvocationLedger",
                          "PersistentInvocationLedger", "resolve_effective_cap",
                          "_effective_cap", "_enforce_live_funnel"):
            self.assertNotIn(forbidden, called,
                             f"{forbidden} is called here; the cap and the "
                             "ledger belong to the shared funnel alone")
        defined = {n.name for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for forbidden in ("reserve", "record", "count", "InvocationLedger"):
            self.assertNotIn(forbidden, defined)

    def test_no_trial_mode_flag_exists_on_the_authorization_surface(self):
        import inspect
        params = inspect.signature(wa.authorize_operation).parameters
        for banned in ("trial", "is_trial", "trial_mode", "skip_preflight",
                       "force", "bypass"):
            self.assertNotIn(banned, params)
        # Intent is a two-valued vocabulary, not a boolean, and neither value
        # relaxes anything (see the enforcement-parity tests below).
        self.assertEqual(set(wa.EXECUTION_INTENTS),
                         {wa.EXECUTION_INTENT_ORDINARY, wa.EXECUTION_INTENT_TRIAL})

    def test_authorization_cannot_even_name_a_write_capable_client(self):
        # Credential isolation: the write client is resolved inside the adapter
        # EXECUTION path, keyed by the registered adapter's captured
        # provisioner. An authorization surface that accepted one would be a
        # place a caller could inject it.
        import inspect
        params = set(inspect.signature(wa.authorize_operation).parameters)
        self.assertEqual(params & {"client", "raw_client", "write_client"}, set())
        tree = ast.parse((_EXTERNAL_WRITE_DIR / "write_authorization.py")
                         .read_text(encoding="utf-8"))
        called = _called_names(tree)
        self.assertNotIn("provision_write_client", called)

    def test_run_operation_authorizes_through_that_one_implementation(self):
        # Not an inspection: the real ordinary path is driven and the single
        # implementation is observed being called with the ordinary intent. A
        # run_operation that kept its own inline gate call would still pass
        # every behavioural test in this file, and fail this one.
        with mock.patch.object(adapters_mod, "authorize_operation",
                               wraps=wa.authorize_operation) as spy:
            op = Operation(surface="google_sheets", object_id="obj:1",
                           field="Status", new_value="Complete",
                           op_kind="set_status", batch_id="b1")

            class _Client:
                def write(self, object_id, field, value):
                    self.v = value

                def read(self, object_id, field):
                    return getattr(self, "v", None)

            result = adapters_mod.run_operation(op, _receipt(op), _Client())
        self.assertEqual(result.status, "written")
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(spy.call_args.kwargs["intent"],
                         wa.EXECUTION_INTENT_ORDINARY)


class CarrierCannotBeForgedTests(_Base):
    """The carrier's own fail-closed post-conditions. Each case reaches for the
    module-private token deliberately — that is the ONLY way to exercise these
    branches, and reaching a private name is precisely the disclosed ceiling
    (build-time enforcement plus operator-as-approver, never a runtime sandbox).
    """

    def _plan_kwargs(self, op, **overrides):
        verdict = te.check_trial_eligibility(
            op.op_kind,
            get_dispatch(op.op_kind).plan(get_dispatch(op.op_kind).instance,
                                          op.params),
            self.capsules(op))
        kwargs = dict(op=op, intent=wa.EXECUTION_INTENT_TRIAL,
                      target="native_undo", resolved_target="native_undo",
                      dispatch=get_dispatch(op.op_kind),
                      units=tuple(verdict.units), gate_audit=None,
                      trial_verdict=verdict,
                      recovery_capsules=self.capsules(op),
                      issued_by=wa._ISSUED_BY_AUTHORIZE)
        kwargs.update(overrides)
        return kwargs

    def test_a_plan_built_without_the_token_cannot_exist(self):
        self.register()
        op = self.op()
        with self.assertRaises(wa.AuthorizationRequiredError) as ctx:
            wa.AuthorizedPlan(**self._plan_kwargs(op, issued_by=None))
        self.assertIn("authorize_operation", str(ctx.exception))
        # Not even with a plausible-looking stand-in token.
        with self.assertRaises(wa.AuthorizationRequiredError):
            wa.AuthorizedPlan(**self._plan_kwargs(op, issued_by=object()))

    def test_a_trial_plan_with_no_verdict_cannot_exist(self):
        self.register()
        with self.assertRaises(wa.AuthorizationRequiredError):
            wa.AuthorizedPlan(**self._plan_kwargs(self.op(), trial_verdict=None))

    def test_a_trial_plan_carrying_an_INELIGIBLE_verdict_cannot_exist(self):
        self.register(_UnreversibleAdapter())
        op = self.op()
        dispatch = get_dispatch(op.op_kind)
        units = dispatch.plan(dispatch.instance, op.params)
        ineligible = te.check_trial_eligibility(op.op_kind, units, {})
        self.assertFalse(ineligible.eligible)
        with self.assertRaises(wa.AuthorizationRequiredError) as ctx:
            wa.AuthorizedPlan(
                op=op, intent=wa.EXECUTION_INTENT_TRIAL, target="native_undo",
                resolved_target="native_undo", dispatch=dispatch,
                units=tuple(units), gate_audit=None, trial_verdict=ineligible,
                recovery_capsules={}, issued_by=wa._ISSUED_BY_AUTHORIZE)
        self.assertIn("ELIGIBLE", str(ctx.exception))

    def test_units_cannot_be_swapped_after_the_preflight_blessed_them(self):
        """The check-then-swap. Holding the token is not enough: the plan's units
        must be exactly the units the verdict carries."""
        self.register()
        op = self.op(n=2)
        swapped = (EffectUnit(unit_id="not-reviewed", target_ref={}, undo_ref={}),)
        with self.assertRaises(wa.AuthorizationRequiredError) as ctx:
            wa.AuthorizedPlan(**self._plan_kwargs(op, units=swapped))
        self.assertIn("EXACTLY the units", str(ctx.exception))
        with self.assertRaises(wa.AuthorizationRequiredError):
            wa.AuthorizedPlan(**self._plan_kwargs(op, units=()))

    def test_a_verdict_earned_by_another_op_kind_does_not_authorize_this_one(self):
        self.register()
        other = "fixture.authorization.other_kind"
        self.register(op_kind=other)
        op = self.op()
        borrowed = te.check_trial_eligibility(
            other,
            get_dispatch(other).plan(get_dispatch(other).instance, op.params),
            self.capsules(op))
        self.assertTrue(borrowed.eligible, borrowed.reason_text())
        with self.assertRaises(wa.AuthorizationRequiredError) as ctx:
            wa.AuthorizedPlan(**self._plan_kwargs(op, trial_verdict=borrowed,
                                                  units=tuple(borrowed.units)))
        self.assertIn("never authorizes another", str(ctx.exception))

    def test_a_trial_plan_on_a_non_live_bounded_target_cannot_exist(self):
        self.register()
        op = self.op()
        for bad in ("live", "copy", "dry_run", "bounded_sample", None,
                    "native_undo "):
            with self.subTest(resolved_target=bad):
                with self.assertRaises(wa.AuthorizationRequiredError):
                    wa.AuthorizedPlan(**self._plan_kwargs(op, resolved_target=bad))

    def test_a_trial_plan_without_a_dispatch_or_capsules_cannot_exist(self):
        self.register()
        op = self.op()
        with self.assertRaises(wa.AuthorizationRequiredError):
            wa.AuthorizedPlan(**self._plan_kwargs(op, dispatch=None))
        for bad in (None, [], "capsules"):
            with self.subTest(recovery_capsules=bad):
                with self.assertRaises(wa.AuthorizationRequiredError):
                    wa.AuthorizedPlan(**self._plan_kwargs(op,
                                                          recovery_capsules=bad))

    def test_an_ordinary_plan_may_not_carry_a_trial_verdict(self):
        self.register()
        op = self.op()
        with self.assertRaises(wa.AuthorizationRequiredError):
            wa.AuthorizedPlan(**self._plan_kwargs(
                op, intent=wa.EXECUTION_INTENT_ORDINARY))

    def test_an_unrecognized_intent_cannot_be_carried(self):
        self.register()
        op = self.op()
        for bad in ("TRIAL", "trial_mode", "", None, True):
            with self.subTest(intent=bad):
                with self.assertRaises(wa.AuthorizationRequiredError):
                    wa.AuthorizedPlan(**self._plan_kwargs(op, intent=bad,
                                                          trial_verdict=None))


class CarrierCannotBeRECONSTRUCTEDTests(_Base):
    """A construction guard that only covers `Cls(...)` is not a construction
    guard. Python offers several other ways to bring a dataclass instance into
    existence from one that already exists, and a legitimately-authorized plan
    WILL be handed to a trial executor — so every one of those routes has to
    refuse rather than silently yield an unblessed carrier.

    Each test here corresponds to a route that worked before this round.
    """

    def _authorized_ordinary_plan(self, *, n=1):
        self.register()
        op = self.op(n=n)
        authorization = wa.authorize_operation(
            op, _receipt(op), target="native_undo", descriptor_set=[_entry()],
            cap_ledger=self.ledger)
        self.assertTrue(authorization.authorized)
        return op, authorization.plan

    def test_a_plan_never_exposes_the_construction_token(self):
        """The most direct route of all: read the token off a plan you were
        legitimately handed, then construct anything. A holder of a plan must
        not be able to recover the token from it."""
        _op, plan = self._authorized_ordinary_plan()
        self.assertIsNot(getattr(plan, "issued_by", None), wa._ISSUED_BY_AUTHORIZE)
        self.assertNotIn(wa._ISSUED_BY_AUTHORIZE, vars(plan).values())
        # It is not a retained FIELD either, which is what stops
        # `dataclasses.replace` carrying it forward (see the next test).
        self.assertNotIn("issued_by", [f.name for f in dataclasses.fields(plan)])

    def test_dataclasses_replace_cannot_swap_a_plans_contents(self):
        """`replace` builds a NEW instance from an existing one's fields. While
        the token was an ordinary field it was carried forward automatically, so
        the identity check passed for a caller holding no token at all."""
        _op, plan = self._authorized_ordinary_plan(n=2)
        forged = EffectUnit(unit_id="not-reviewed", target_ref={}, undo_ref={})
        for label, changes in (
            ("units", {"units": (forged,)}),
            ("dispatch", {"dispatch": object()}),
            ("resolved_target", {"resolved_target": "live"}),
            ("op", {"op": self.op(op_kind="fixture.authorization.other_kind")}),
        ):
            with self.subTest(swapped=label):
                with self.assertRaises(wa.AuthorizationRequiredError):
                    dataclasses.replace(plan, **changes)

    def test_dataclasses_replace_cannot_escalate_an_ordinary_plan_to_a_trial(self):
        """The worst of the routes: an ordinary authorization — which never runs
        the preflight — turned into a trial authorization, with a hand-built
        verdict and no token held."""
        op, plan = self._authorized_ordinary_plan()
        dispatch = get_dispatch(op.op_kind)
        units = tuple(dispatch.plan(dispatch.instance, op.params))
        hand_built = te.TrialEligibility(op_kind=op.op_kind, eligible=True,
                                        refusals=(), units=units)
        with self.assertRaises(wa.AuthorizationRequiredError):
            dataclasses.replace(
                plan, intent=wa.EXECUTION_INTENT_TRIAL, trial_verdict=hand_built,
                units=units, resolved_target="native_undo",
                recovery_capsules=self.capsules(op))

    def test_copy_and_deepcopy_cannot_produce_a_plan(self):
        """`copy` reconstructs without running `__post_init__` at all, so it
        produced a carrier that had never been validated — and, combined with
        `object.__setattr__`, one that could then be rewritten freely."""
        _op, plan = self._authorized_ordinary_plan()
        with self.assertRaises(wa.AuthorizationRequiredError):
            copy.copy(plan)
        with self.assertRaises(wa.AuthorizationRequiredError):
            copy.deepcopy(plan)

    def test_pickling_cannot_produce_a_plan(self):
        """An authorization is not a portable document. Serializing one would
        let it be revived in another process, at another time, with the
        registry in another state — none of which the gate ever saw."""
        _op, plan = self._authorized_ordinary_plan()
        with self.assertRaises(wa.AuthorizationRequiredError):
            pickle.dumps(plan)

    def test_a_plans_dispatch_must_be_the_one_the_registry_holds(self):
        """`dispatch is None` was not enough: a plan carrying a DIFFERENT
        adapter's dispatch would apply the preflight-blessed units through
        someone else's `apply_one`."""
        self.register()
        other = "fixture.authorization.other_kind"
        self.register(op_kind=other)
        op = self.op()
        verdict = te.check_trial_eligibility(
            op.op_kind,
            get_dispatch(op.op_kind).plan(get_dispatch(op.op_kind).instance,
                                          op.params),
            self.capsules(op))
        self.assertTrue(verdict.eligible, verdict.reason_text())
        for label, bad in (("another adapter's dispatch", get_dispatch(other)),
                           ("an arbitrary object", object())):
            with self.subTest(dispatch=label):
                with self.assertRaises(wa.AuthorizationRequiredError):
                    wa.AuthorizedPlan(
                        op=op, intent=wa.EXECUTION_INTENT_TRIAL,
                        target="native_undo", resolved_target="native_undo",
                        dispatch=bad, units=tuple(verdict.units),
                        gate_audit=None, trial_verdict=verdict,
                        recovery_capsules=self.capsules(op),
                        issued_by=wa._ISSUED_BY_AUTHORIZE)

    def test_a_trial_plan_for_an_op_kind_with_no_adapter_at_all_cannot_exist(self):
        # The reachable shape of the dispatch-absent branch: nothing registered,
        # so the registry and the plan agree on None, and the trial is still
        # refused because there is no undo_one to reverse it with.
        op = self.op(op_kind="fixture.authorization.never_registered")
        verdict = te.TrialEligibility(
            op_kind=op.op_kind, eligible=True, refusals=(),
            units=(EffectUnit(unit_id="m1", target_ref={}, undo_ref={}),))
        with self.assertRaises(wa.AuthorizationRequiredError) as ctx:
            wa.AuthorizedPlan(
                op=op, intent=wa.EXECUTION_INTENT_TRIAL, target="native_undo",
                resolved_target="native_undo", dispatch=None,
                units=verdict.units, gate_audit=None, trial_verdict=verdict,
                recovery_capsules={"m1": {}},
                issued_by=wa._ISSUED_BY_AUTHORIZE)
        self.assertIn("no registered adapter", str(ctx.exception))


class PreflightIsOnTheEnforcedPathTests(_Base):
    """Behavioural half of property 1: the real flow calls the preflight, and a
    refusal from it stops the flow BEFORE anything is reserved or written."""

    def test_the_real_trial_flow_calls_the_preflight_with_the_planned_units(self):
        self.register()
        op = self.op(n=2)
        capsules = self.capsules(op)
        with mock.patch.object(wa.trial_eligibility, "check_trial_eligibility",
                               wraps=te.check_trial_eligibility) as spy:
            authorization = self.authorize_trial(op, capsules=capsules)
        self.assertTrue(authorization.authorized,
                        authorization.refusal.detail if authorization.refusal else "")
        self.assertEqual(spy.call_count, 1)
        called_op_kind, called_units, called_capsules = spy.call_args.args
        self.assertEqual(called_op_kind, op.op_kind)
        self.assertEqual([u.unit_id for u in called_units], ["m1", "m2"])
        self.assertIs(called_capsules, capsules)

    def test_the_authorized_plan_carries_the_VERY_units_the_preflight_blessed(self):
        """Identity, not equality — and the difference is the whole point.

        `plan()` is contractually PURE, but that purity is an adapter-author
        invariant nothing machine-enforces (every `plan()` implementation lives
        in a scanner-exempt zone). So if authorization re-derived the plan after
        the preflight blessed one, an impure `plan()` would hand the executor
        units the preflight never saw — a check-then-swap. An equality assertion
        would not notice, because a deterministic fixture re-derives units that
        compare equal; binding to the verdict's own objects is what closes it.
        """
        self.register()
        op = self.op(n=2)
        captured = {}
        real = te.check_trial_eligibility

        def _capture(*args, **kwargs):
            verdict = real(*args, **kwargs)
            captured["verdict"] = verdict
            return verdict

        with mock.patch.object(wa.trial_eligibility, "check_trial_eligibility",
                               _capture):
            authorization = self.authorize_trial(op)
        self.assertTrue(authorization.authorized)
        blessed = captured["verdict"].units
        self.assertEqual(len(authorization.plan.units), len(blessed))
        for got, want in zip(authorization.plan.units, blessed):
            self.assertIs(got, want,
                          "the authorized plan carries a RE-DERIVED unit, not "
                          "the one the preflight blessed")

    def test_an_ordinary_write_does_not_run_the_trial_preflight(self):
        # The preflight governs trials. Running it on the ordinary path would
        # make every existing accepted capability newly refusable.
        self.register()
        op = self.op()
        with mock.patch.object(wa.trial_eligibility, "check_trial_eligibility",
                               wraps=te.check_trial_eligibility) as spy:
            authorization = wa.authorize_operation(
                op, _receipt(op), intent=wa.EXECUTION_INTENT_ORDINARY,
                target="native_undo", descriptor_set=[_entry()],
                cap_ledger=self.ledger)
        self.assertTrue(authorization.authorized)
        self.assertEqual(spy.call_count, 0)

    def test_one_broken_clause_refuses_the_trial_and_writes_nothing(self):
        """Everything is valid except a single preflight clause: the plan carries
        no undo_ref. The refusal must name that clause, and nothing may be
        applied."""
        self.register(_UnreversibleAdapter())
        op = self.op(n=2)
        refusal = self.assertRefused(self.authorize_trial(op),
                                     contains="not eligible for a trial")
        self.assertEqual(refusal.detail["trial_ineligible_clauses"],
                         [te.CLAUSE_UNDO_REF_PRESENT])
        self.assertIn("undo_ref=None", refusal.detail["reason"])
        self.assertEqual(self.client.applied, [])

    def test_a_preflight_refusal_consumes_no_blast_radius_slot(self):
        """Ordering, not just outcome: the preflight runs BEFORE the funnel's
        atomic reserve, so an ineligible operation cannot burn a slot it was
        never entitled to."""
        self.register(_UnreversibleAdapter())
        op = self.op(n=2)
        key = f"{op.surface}::{op.op_kind}"
        self.assertRefused(self.authorize_trial(op))
        self.assertEqual(self.ledger.count(key), 0)
        # Contrast: an ELIGIBLE trial does reach the funnel and does consume.
        unregister_adapter(op.op_kind)
        register_adapter(op.op_kind, _CompliantAdapter())
        self.assertTrue(self.authorize_trial(op).authorized)
        self.assertEqual(self.ledger.count(key), 2)

    def test_an_op_kind_with_no_registered_adapter_is_refused_a_trial(self):
        op = self.op(op_kind="fixture.authorization.unregistered")
        refusal = self.assertRefused(self.authorize_trial(op, capsules={}))
        self.assertIn(te.CLAUSE_EVIDENCE_PREDICATES_DECLARED,
                      refusal.detail["trial_ineligible_clauses"])

    def test_a_preflight_that_raises_is_not_swallowed_into_an_authorization(self):
        """If the preflight itself breaks, authorization must not proceed. A
        `try/except: pass` around it would be a silent bypass, so the failure
        propagates rather than degrading to an authorized plan."""
        self.register()
        op = self.op()
        with mock.patch.object(wa.trial_eligibility, "check_trial_eligibility",
                               side_effect=RuntimeError("preflight broke")):
            with self.assertRaises(RuntimeError):
                self.authorize_trial(op)

    def test_an_unrecognized_intent_refuses_rather_than_defaulting(self):
        self.register()
        op = self.op()
        for bad in ("TRIAL", "trial_mode", "", None, "ordinary "):
            with self.subTest(intent=bad):
                authorization = wa.authorize_operation(
                    op, _receipt(op), intent=bad, target="native_undo",
                    descriptor_set=[_entry()], cap_ledger=self.ledger,
                    recovery_capsules=self.capsules(op))
                self.assertRefused(authorization,
                                   contains="unrecognized execution intent")


class TrialTargetMustBeLiveBoundedTests(_Base):
    """A trial's proof depends on traversing the live-bounded funnel. Every other
    target is refused, each for its own reason."""

    def test_a_dry_run_can_never_be_trialled(self):
        # dry_run permits UNCONDITIONALLY at the gate — no surface, cap, ledger
        # or acceptance requirement — because the adapter guarantees it never
        # writes. A "restoration proof" from it would be evidence of nothing.
        self.register()
        self.assertRefused(self.authorize_trial(self.op(), target="dry_run"),
                           contains="bounded subset of the live resource")

    def test_a_copy_target_can_never_be_trialled(self):
        self.register()
        self.assertRefused(self.authorize_trial(self.op(), target="copy"))

    def test_an_affirmative_live_target_can_never_be_trialled(self):
        self.register()
        self.assertRefused(self.authorize_trial(self.op(), target="live"))

    def test_an_absent_target_can_never_be_trialled(self):
        self.register()
        self.assertRefused(self.authorize_trial(self.op(), target=None))

    def test_a_live_bounded_request_on_a_copy_SURFACE_is_refused(self):
        """The hole a naive check on the requested string would leave open: an
        operation on the copy-surface convention RESOLVES to 'copy' however it
        was asked for, so it would take the gate's isolated branch — no cap, no
        ledger — while the caller still believed a live-bounded funnel had run."""
        self.register()
        op = self.op(surface=COPY_SURFACE)
        self.assertEqual(write_gate.resolve_effective_target(op, "native_undo"),
                         "copy")
        refusal = self.assertRefused(self.authorize_trial(op))
        self.assertEqual(refusal.detail["requested_target"], "native_undo")
        self.assertEqual(refusal.detail["resolved_target"], "copy")
        self.assertEqual(self.ledger.count(f"{COPY_SURFACE}::{op.op_kind}"), 0)

    def test_native_undo_is_the_ONLY_target_a_trial_accepts(self):
        self.register()
        op = self.op()
        authorization = self.authorize_trial(
            op, target=wa.TRIAL_TARGET,
            descriptor_set=[_entry(declared_test_target=wa.TRIAL_TARGET)],
            cap_ledger=InvocationLedger())
        self.assertTrue(authorization.authorized,
                        authorization.refusal.detail if authorization.refusal else "")
        self.assertEqual(authorization.plan.resolved_target, wa.TRIAL_TARGET)
        self.assertEqual(wa.TRIAL_TARGET, "native_undo")

    def test_a_bounded_sample_DECLARATION_is_refused_a_trial_specifically(self):
        """The declaration-fidelity property, and the reason the trial accepts one
        target rather than both live-bounded ones.

        The two live-bounded targets are not interchangeable: the gate's own
        branch distinguishes them as perform-then-revert (`native_undo`) versus a
        bounded live sample (`bounded_sample`). A trial ALWAYS reverts. So running
        a trial under a capability whose operator-declared test target says "a
        bounded sample that persists" would be the system doing something other
        than what the declaration describes — which is the failure family this
        work exists to close, not to add an instance of.

        Both halves are asserted: refused for a TRIAL, and still perfectly legal
        for its own non-trial purpose.
        """
        self.register()
        op = self.op()
        declared_sample = [_entry(declared_test_target="bounded_sample")]

        refusal = self.assertRefused(
            self.authorize_trial(op, target="bounded_sample",
                                 descriptor_set=declared_sample))
        self.assertEqual(refusal.detail["resolved_target"], "bounded_sample")
        self.assertEqual(refusal.detail["trial_target"], "native_undo")
        # The reason must say WHY the other live-bounded target is not
        # interchangeable, not merely that it was rejected.
        self.assertIn("REVERTS", refusal.detail["reason"])
        self.assertIn("PERSISTS", refusal.detail["reason"])
        # Nothing was reserved: the refusal is ahead of the funnel.
        self.assertEqual(self.ledger.count(f"{op.surface}::{op.op_kind}"), 0)

        # ... and the SAME operation, SAME declaration, ordinary intent: legal.
        authorization = wa.authorize_operation(
            op, _receipt(op), intent=wa.EXECUTION_INTENT_ORDINARY,
            target="bounded_sample", descriptor_set=declared_sample,
            cap_ledger=self.ledger)
        self.assertTrue(authorization.authorized,
                        authorization.refusal.detail if authorization.refusal else "")
        self.assertEqual(authorization.plan.resolved_target, "bounded_sample")
        self.assertEqual(self.ledger.count(f"{op.surface}::{op.op_kind}"), 1)

    def test_the_live_bounded_VOCABULARY_itself_is_not_narrowed(self):
        """Only what a TRIAL accepts was tightened. The gate's own live-bounded
        vocabulary is untouched, and `TRIAL_TARGET` is a member of it — so this
        is a narrowing of one consumer, never a redefinition of the shared
        vocabulary (widening it later stays a one-line, reviewable change)."""
        self.assertEqual(LIVE_BOUNDED_TEST_TARGETS,
                         frozenset({"bounded_sample", "native_undo"}))
        self.assertIn(wa.TRIAL_TARGET, LIVE_BOUNDED_TEST_TARGETS)
        self.assertEqual(LIVE_BOUNDED_TEST_TARGETS - {wa.TRIAL_TARGET},
                         frozenset({"bounded_sample"}))


class TrialTraversesTheSharedLiveFunnelTests(_Base):
    """Property 3: a trial runs the SAME live-enforcement funnel as an accepted
    live write, and the ONLY relaxation is the one that branch already grants."""

    def test_a_declared_but_UNACCEPTED_capability_is_authorized_for_a_trial(self):
        self.register()
        op = self.op(n=2)
        entry = _entry(accepted=False)
        self.assertIsNot(entry["accepted"], True)
        authorization = self.authorize_trial(op, descriptor_set=[entry])
        self.assertTrue(authorization.authorized,
                        authorization.refusal.detail if authorization.refusal else "")
        # The funnel really ran: the shared ledger, keyed exactly as the live
        # path keys it, is charged in UNITS.
        self.assertEqual(self.ledger.count(f"{op.surface}::{op.op_kind}"), 2)

    def test_the_ONE_relaxation_is_acceptance_and_nothing_else(self):
        self.register()
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                authorization = self.authorize_trial(
                    self.op(), descriptor_set=[_entry(accepted=accepted)],
                    cap_ledger=InvocationLedger())
                self.assertTrue(authorization.authorized)

    def test_a_trial_is_refused_without_a_DECLARATION(self):
        self.register()
        self.assertRefused(self.authorize_trial(self.op(), descriptor_set=[]),
                           contains="capability not DECLARED for test target")

    def test_a_declaration_for_a_different_test_target_does_not_cover(self):
        self.register()
        self.assertRefused(
            self.authorize_trial(self.op(),
                                 descriptor_set=[_entry(declared_test_target="copy")]),
            contains="capability not DECLARED for test target")

    def test_a_trial_is_still_refused_with_no_invocation_ledger(self):
        self.register()
        self.assertRefused(self.authorize_trial(self.op(), cap_ledger=None),
                           contains="no invocation ledger supplied")

    def test_a_trial_is_still_refused_with_no_determinable_cap(self):
        self.register(blast_radius_cap=None)
        self.assertRefused(
            self.authorize_trial(self.op(),
                                 descriptor_set=[_entry(blast_radius_cap=None)]),
            contains="no blast-radius cap could be determined")

    def test_a_trial_is_still_refused_over_the_cap(self):
        self.register(blast_radius_cap=1)
        self.assertRefused(
            self.authorize_trial(self.op(n=2),
                                 descriptor_set=[_entry(blast_radius_cap=1)]),
            contains="blast-radius cap of 1 reached")

    def test_a_trial_is_still_bound_by_the_non_graduating_recovery_floor(self):
        self.register(risk_class="standing_automation")
        self.assertRefused(
            self.authorize_trial(
                self.op(),
                descriptor_set=[_entry(risk_class="standing_automation",
                                       recovery_profile_ref=None)]),
            contains="non-graduating recovery floor is not satisfied")

    def test_a_trial_is_still_refused_for_a_paused_op_kind(self):
        self.register()
        op = self.op()
        with hermetic_paused_mechanisms([op.op_kind]) as paused_root:
            self.assertRefused(self.authorize_trial(op, paused_root=paused_root),
                               contains="paused pending migration")

    def test_a_trial_still_requires_a_valid_unexpired_receipt(self):
        self.register()
        op = self.op()
        self.assertRefused(self.authorize_trial(op, receipt={}),
                           contains="receipt is missing or empty")
        self.assertRefused(
            self.authorize_trial(op, receipt=_receipt(op, valid=False),
                                 cap_ledger=InvocationLedger()),
            contains="receipt has expired")

    def test_an_irreversible_trial_still_writes_the_irreversibility_audit(self):
        self.register(risk_class="irreversible_external")
        authorization = self.authorize_trial(
            self.op(), descriptor_set=[_entry(risk_class="irreversible_external")])
        self.assertTrue(authorization.authorized)
        ack = authorization.plan.gate_audit["irreversibility_acknowledgement"]
        self.assertIs(ack["reversible"], False)
        self.assertEqual(ack["units_consumed_in_window"], 1)


class BothExecutorsConsumeTheSamePlanTests(_Base):
    """The seam itself: one carrier, two consumers."""

    def test_a_trial_executor_double_consumes_the_authorized_plan(self):
        self.register()
        op = self.op(n=2)
        authorization = self.authorize_trial(op)
        self.assertTrue(authorization.authorized)
        plan = authorization.plan
        journal = _TrialExecutorDouble().execute(plan, self.client)
        self.assertEqual([e["unit_id"] for e in journal], ["m1", "m2"])
        self.assertEqual([e["state"] for e in journal],
                         ["apply_attempted", "apply_attempted"])
        self.assertEqual(self.client.applied,
                         [("m1", ["TRASH"]), ("m2", ["TRASH"])])
        # Everything the executor needed came off the plan — it never re-planned
        # and never re-resolved the dispatch.
        self.assertIs(plan.dispatch, get_dispatch(op.op_kind))
        self.assertEqual([u.unit_id for u in plan.units], ["m1", "m2"])
        self.assertEqual(sorted(plan.recovery_capsules), ["m1", "m2"])

    def test_the_ordinary_executor_consumes_the_same_carrier_shape(self):
        self.register()
        op = self.op(n=2)
        authorization = wa.authorize_operation(
            op, _receipt(op), target="native_undo",
            descriptor_set=[_entry()], cap_ledger=self.ledger)
        self.assertTrue(authorization.authorized)
        plan = authorization.plan
        self.assertEqual(plan.intent, wa.EXECUTION_INTENT_ORDINARY)
        self.assertIsNone(plan.trial_verdict)
        self.assertIsNone(plan.recovery_capsules)
        # Same fields the trial executor reads, from the same carrier type.
        self.assertIsInstance(plan, wa.AuthorizedPlan)
        self.assertEqual([u.unit_id for u in plan.units], ["m1", "m2"])
        self.assertIs(plan.dispatch, get_dispatch(op.op_kind))

    def test_a_trial_executor_double_rejects_an_ordinary_plan(self):
        self.register()
        op = self.op()
        authorization = wa.authorize_operation(
            op, _receipt(op), target="native_undo", descriptor_set=[_entry()],
            cap_ledger=self.ledger)
        with self.assertRaises(AssertionError):
            _TrialExecutorDouble().execute(authorization.plan, self.client)


class OrdinaryPathIsUnchangedTests(unittest.TestCase):
    """The refactor must not move the ordinary path by a single behaviour."""

    def setUp(self):
        self.ledger = InvocationLedger()

    def _sheets_op(self, op_kind="delete_record", surface="google_sheets"):
        return Operation(surface=surface, object_id="obj:1", field="__record__",
                         new_value="<x>", op_kind=op_kind, batch_id="b1")

    def test_a_pre_acceptance_LIVE_write_is_still_refused(self):
        # The property this cut must not weaken while making the trial
        # reachable: a declared-but-unaccepted capability may run a bounded live
        # trial, and still may NOT run an ordinary live write.
        op = self._sheets_op()

        class _Client:
            def write(self, *a):
                raise AssertionError("a refused op must not reach the surface")

        result = adapters_mod.run_operation(
            op, _receipt(op), _Client(), target="live",
            descriptor_set=[_entry(id="google_sheets",
                                   risk_class="irreversible_external",
                                   accepted=False)],
            cap_ledger=self.ledger)
        self.assertEqual(result.status, "refused")
        self.assertIn("no covering ACCEPTED descriptor phase",
                      result.detail["reason"])

    def test_an_absent_target_on_a_gated_op_is_still_refused(self):
        op = self._sheets_op()
        result = adapters_mod.run_operation(op, _receipt(op), None,
                                           descriptor_set=[], cap_ledger=self.ledger)
        self.assertEqual(result.status, "refused")
        self.assertIn("no target signal", result.detail["reason"])

    def test_a_bad_receipt_is_still_refused_after_the_gate(self):
        op = self._sheets_op(op_kind="set_status")
        result = adapters_mod.run_operation(op, {}, None)
        self.assertEqual(result.status, "refused")
        self.assertEqual(result.detail["reason"], "receipt is missing or empty")

    def test_a_dry_run_still_previews_without_writing(self):
        op = self._sheets_op()

        class _Client:
            def write(self, *a):
                raise AssertionError("dry_run must never reach client.write")

        result = adapters_mod.run_operation(op, _receipt(op), _Client(),
                                            target="dry_run")
        self.assertEqual(result.status, "written")
        self.assertTrue(result.detail["dry_run"])

    def test_an_unplannable_operation_is_still_a_clean_refusal(self):
        class _Exploding:
            UNDO_IS_ABSOLUTE_STATE_RESTORE = True

            def plan(self, params):
                raise KeyError("message_id")

            def apply_one(self, raw_client, unit):
                raise AssertionError

            def undo_one(self, raw_client, unit):
                raise AssertionError

            def verify_one(self, observer, unit):
                raise AssertionError

        register_adapter("fixture.authorization.exploding", _Exploding())
        self.addCleanup(unregister_adapter, "fixture.authorization.exploding")
        op = self._sheets_op(op_kind="fixture.authorization.exploding")
        result = adapters_mod.run_operation(op, _receipt(op), None, target="live")
        self.assertEqual(result.status, "refused")
        self.assertIn("could not plan effect units", result.detail["reason"])


class ZoneMembershipTests(unittest.TestCase):
    """SEALED_KERNEL membership, asserted in BOTH directions so the entry cannot
    quietly become decorative."""

    MODULE = "write_authorization.py"
    _PATH = _EXTERNAL_WRITE_DIR / "write_authorization.py"

    def test_module_is_enumerated_in_the_sealed_kernel_allowlist(self):
        self.assertIn(self.MODULE, zones.SEALED_KERNEL_MODULE_PATHS)
        self.assertEqual(zones.classify_zone(self._PATH, _EXTERNAL_WRITE_DIR),
                         zones.Zone.SEALED_KERNEL)

    def test_module_scans_clean_as_sealed_kernel(self):
        self.assertEqual(
            scan.scan_paths([self._PATH], allowed_root=_EXTERNAL_WRITE_DIR), [])

    def test_without_the_entry_the_scan_would_flag_kernel_wiring(self):
        # The counterfactual: membership is load-bearing, not decorative. The
        # KIND SET is the durable fact; no violation COUNT is recorded here,
        # because a count tracks how many times the module happens to name a
        # kernel symbol and goes stale on an added annotation.
        without = frozenset(zones.SEALED_KERNEL_MODULE_PATHS) - {self.MODULE}
        kinds = {v.kind for v in scan.scan_paths(
            [self._PATH], allowed_root=_EXTERNAL_WRITE_DIR,
            sealed_kernel_paths=without)}
        self.assertEqual(
            kinds,
            {"adapter_module_import", "adapter_registry_reference",
             "sealed_kernel_import"})

    def test_membership_does_not_let_capability_code_import_it(self):
        # A capability has no business authorizing its own write.
        self.assertNotIn("write_authorization",
                         scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES)


class CeilingHonestyTests(unittest.TestCase):
    """The carrier's stated bound must be the CEILING, never a count of routes.

    This is a trust-surface prose guard, and it exists because the prose was wrong
    twice in two review rounds: first it omitted a route (subclassing), then it
    asserted a closed COUNT of remaining forgeries, which a plain
    allocate-then-assign reflection forgery falsifies. No enumeration of
    in-process reflection paths can be complete, so the honest statement is the
    enforcement ceiling this project already states for its sibling AST bypass
    scanner: a build-time anti-drift check backed by operator-as-approver, never a
    runtime sandbox, with the reflection paths it cannot close disclosed as
    within-ceiling bounds rather than left as silent gaps.

    Cheap by design — it reads the real docstrings, asserts no
    completeness-claiming vocabulary appears in them, and asserts the ceiling and
    the illustrative-not-exhaustive marker DO. That is enough to stop a third
    attempt at a count without pinning any wording this guard would then own.
    """

    # Vocabulary that can only be doing one job in a bound like this: claiming
    # completeness. Substring-matched, lowercased.
    _COMPLETENESS_CLAIMING = (
        "impossible", "exhaustive", "every route python offers",
        "cannot be forged", "unforgeable", "tamper-proof", "tamperproof",
    )

    # The NEGATED forms are the opposite of a completeness claim -- they are the
    # marker the bound is required to carry -- so they are removed before the ban
    # is applied, rather than dropped from the ban. A bare "is exhaustive" still
    # trips; "not exhaustive" is what the second test below insists on.
    _NEGATED_FORMS = ("not exhaustive", "non-exhaustive", "nonexhaustive")

    def setUp(self):
        # Under `python -OO` docstrings are stripped, so there is no prose to
        # check and every assertion below would be a confusing false red. Skipped
        # explicitly rather than silently passing on an empty string: the guard is
        # VACUOUS in that mode, not satisfied by it.
        if wa.__doc__ is None or wa.AuthorizedPlan.__doc__ is None:
            self.skipTest("docstrings stripped (-OO); there is no prose to check")

    def _trust_prose(self):
        """The module docstring plus the carrier's own class docstring — the two
        places a reader looks to learn what the carrier guarantees."""
        return "\n".join([wa.__doc__, wa.AuthorizedPlan.__doc__]).lower()

    def _prose_without_negations(self):
        prose = self._trust_prose()
        for negated in self._NEGATED_FORMS:
            prose = prose.replace(negated, "")
        return prose

    def test_the_bound_claims_no_completeness(self):
        prose = self._prose_without_negations()
        for phrase in self._COMPLETENESS_CLAIMING:
            self.assertNotIn(
                phrase, prose,
                f"the carrier's stated bound uses {phrase!r}. In-process "
                "reflection defeats every construction guard here by "
                "construction, so a completeness claim is false however it is "
                "phrased. State the ceiling instead")

    def test_the_bound_states_the_ceiling_and_marks_its_examples_illustrative(self):
        prose = self._trust_prose()
        self.assertIn("not a runtime sandbox", prose,
                      "the bound must name the enforcement ceiling explicitly")
        self.assertIn("anti-drift", prose,
                      "the bound must say what the guards ARE -- a build-time "
                      "anti-drift control -- not only what they are not")
        self.assertIn("not exhaustive", prose,
                      "any reflection examples the bound gives must be marked "
                      "illustrative, or the next reader will read them as the set")

    def test_no_forgery_count_is_asserted(self):
        """A bare count is the specific shape that was wrong. Catch it as a
        count, not as a particular sentence, so a rephrased count trips too."""
        prose = self._trust_prose()
        for count in ("one forgery", "two forgeries", "three forgeries",
                      "two remaining", "three remaining"):
            self.assertNotIn(
                count, prose,
                f"the bound counts remaining forgeries ({count!r}). Any count is "
                "a completeness claim about in-process reflection, which cannot "
                "be enumerated -- this has already been wrong twice")


if __name__ == "__main__":
    unittest.main()
