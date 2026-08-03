"""Tests for the JOURNALED TRIAL EXECUTOR — `external_write.trial_executor`.

Three properties matter more than everything else in this file, and each one
names a defect this package has already shipped:

  1. THE TRIAL PATH IS REACHABLE, AND NOTHING ELSE REACHES IT. Before this
     module, the trial branch of `write_authorization.authorize_operation` and
     the whole of `trial_journal` had ZERO production callers: both existed,
     both were green, and nothing in the system invoked either. A mechanism off
     the enforced path is this package's most-repeated defect (a provisioner
     hook that was `None` in every deployment with its consuming branch never
     executed; a migration nobody called; a trust primitive that was an
     uncalled wrapper). The structural tests below assert, over this package's
     OWN source, that `trial_executor` is the ONE production caller of both.

  2. A TRIAL CANNOT EXECUTE WITHOUT JOURNALING. Not "does not, by convention" —
     cannot: there is no argument that supplies or suppresses a journal, the
     journal is opened unconditionally before any client is used to mutate
     anything, and the write-ahead assertions below are made FROM INSIDE the
     mutation callback, i.e. at the instant a crash would leave whatever is on
     disk as the only record.

  3. THE CREDENTIAL SPLIT IS REAL. `verify_one` receives a READ-ONLY facade
     built from a read-only client; `apply_one`/`undo_one` receive the
     write-capable client. That split is the entire reason a kernel-side trial
     is legitimate rather than a boundary violation. It is asserted by OBJECT
     IDENTITY, and the fixture clients are deliberately shaped so a swap cannot
     silently work: the read-only client has no mutating method and the write
     client has no read method.

What these tests do NOT claim
-----------------------------
  * They do not claim anything about the two REAL operator adapters. Those live
    in the operator's estate, are not in this repository, and are not imported
    here. The shipped-adapter tests use `adapters_gmail.GmailMessageTrashAdapter`
    — the only fully trial-eligible op_kind in the shipped adapter set — and the
    fixture adapters reproduce contract SHAPES, not any operator's code.
  * They do not claim the trial executor recovers a CRASHED trial. Resuming one
    is a separate concern with its own module; nothing here resumes anything,
    and no test below asserts a resume.
  * They do not claim `restored_verified` in the journal means the surface is
    restored on its own authority — the journal records what its caller
    established. What the caller establishes is exactly what these tests check.

Every `AuthorizedPlan` reached below is produced by the REAL
`write_authorization.authorize_operation`, through `run_trial`, never hand-built.
Uses stub clients only; no network. Every test writes into its own temp
directory, so nothing here touches the real project's `security/` or
`agents/handoffs/` trees or its ambient paused-mechanisms state.
"""

import ast
import dataclasses
import hashlib
import inspect
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import copy_run_proof as crp  # noqa: E402
from external_write import evidence as ev  # noqa: E402
from external_write import operator_acceptance as oa  # noqa: E402
from external_write import read_facades_gmail  # noqa: E402,F401 -- registers the Gmail facade
from external_write import scan, zones  # noqa: E402
from external_write import trial_eligibility as te  # noqa: E402
from external_write import trial_executor as tx  # noqa: E402
from external_write import trial_journal as tj  # noqa: E402
from external_write import write_authorization as wa  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    AdapterDispatch, get_dispatch, register_adapter, unregister_adapter,
)
from external_write.adapters_gmail import (  # noqa: E402
    OP_TRASH, OP_UNTRASH, GmailMessageTrashAdapter,
)
from external_write.contracts import (  # noqa: E402
    OPERATION_CONTRACTS, OperationContract, WRITE_AFFECTING_MODULES,
    get_contract, register_contract,
)
from external_write.lifecycle_test_fixtures import (  # noqa: E402
    hermetic_paused_mechanisms,
)
from external_write.operations import EffectUnit, Operation  # noqa: E402
from external_write.read_facade import (  # noqa: E402
    ReadFacade, get_read_facade_class, register_read_facade,
    unregister_read_facade,
)
from external_write.write_gate import InvocationLedger  # noqa: E402

# The shipped Gmail mock, reused rather than re-implemented: it is the SAME
# duck-typed discovery-API stand-in `adapters_gmail`'s own suite exercises that
# adapter against, so the end-to-end test below drives the real shipped adapter
# through the mock its own tests already trust.
from test_external_write_adapters_gmail import MockGmailService  # noqa: E402

_EXTERNAL_WRITE_DIR = _AGENTS_LIB / "external_write"
_MODULE_PATH = _EXTERNAL_WRITE_DIR / "trial_executor.py"


# ---------------------------------------------------------------------------
# Fixtures.
#
# `_Surface` stands in for the operator's live record. The two clients over it
# are deliberately DISJOINT in capability: the write client has no read method
# and the read-only client has no mutating method, so handing either one to the
# wrong side of the trial fails loudly instead of quietly working.
# ---------------------------------------------------------------------------

APPLIED_LABEL = "ARCHIVED"


class _Surface:
    def __init__(self, initial=None):
        self.state = {k: list(v) for k, v in (initial or {}).items()}

    def snapshot(self):
        return {k: sorted(v) for k, v in self.state.items()}


class _WriteClient:
    """Write-capable. No read method of any name -- if this object ever reached
    `verify_one` through the read facade, the observation would raise."""

    def __init__(self, surface):
        self.surface = surface
        self.writes = []

    def set_labels(self, unit_id, labels):
        self.surface.state[unit_id] = list(labels)
        self.writes.append((unit_id, sorted(labels)))


class _ReadOnlyClient:
    """Read-only. No mutating method of any name."""

    def __init__(self, surface):
        self.surface = surface
        self.reads = []

    def get_state(self, unit_id):
        self.reads.append(unit_id)
        return {"unit_id": unit_id,
                "labels": sorted(self.surface.state.get(unit_id, ()))}


class _FixtureReadFacade(ReadFacade):
    read_methods = ("get_state",)

    def get_state(self, unit_id):
        return self._read("get_state", unit_id)


class _FixtureAdapter:
    """The CONTRACT SHAPE of a trial-eligible adapter: an absolute-state
    `undo_one`, both evidence predicates as real callables, and the
    absolute-state declaration on the class that defines the `undo_one` it
    describes. Not a claim about any shipped or operator-authored adapter."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def __init__(self):
        # What `verify_one` was handed, recorded for the credential-split tests.
        self.observers = []

    def plan(self, params):
        return [
            EffectUnit(
                unit_id=r["unit_id"],
                target_ref={"unit_id": r["unit_id"]},
                undo_ref={"unit_id": r["unit_id"],
                          "prior_labels": list(r.get("prior_labels", ()))},
            )
            for r in (params or {}).get("records", [])
        ]

    def apply_one(self, raw_client, unit):
        raw_client.set_labels(unit.target_ref["unit_id"], [APPLIED_LABEL])

    def undo_one(self, raw_client, unit):
        raw_client.set_labels(unit.undo_ref["unit_id"],
                              unit.undo_ref["prior_labels"])

    def verify_one(self, observer, unit):
        self.observers.append(observer)
        observed = observer.get_state(unit.unit_id)["labels"]
        prior = sorted((unit.undo_ref or {}).get("prior_labels", ()))
        return {"unit_id": unit.unit_id, "observed_labels": observed,
                "applied": observed == [APPLIED_LABEL],
                "matches_prestate": observed == prior}

    def verify_apply_landed(self, evidence):
        return bool(evidence.poststate.get("applied"))

    def verify_undo_restored(self, evidence):
        return bool(evidence.poststate.get("matches_prestate"))


class _ObservingAdapter(_FixtureAdapter):
    """Runs a caller-supplied callback at the instant the external mutation
    would be issued -- which is where the write-ahead assertions live: what the
    callback can read off disk is what a crash at that instant would leave.

    Re-declares `UNDO_IS_ABSOLUTE_STATE_RESTORE` on ITSELF because it overrides
    `undo_one`; the preflight's clause is scoped to the `undo_one` it describes,
    so an inherited claim over replacement code is refused. The re-declaration
    is truthful: the override delegates to the base's absolute restore."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def __init__(self, on_apply=None, on_undo=None):
        super().__init__()
        self.on_apply = on_apply
        self.on_undo = on_undo

    def apply_one(self, raw_client, unit):
        if self.on_apply is not None:
            self.on_apply(unit)
        super().apply_one(raw_client, unit)

    def undo_one(self, raw_client, unit):
        if self.on_undo is not None:
            self.on_undo(unit)
        super().undo_one(raw_client, unit)


class _NoOpApplyAdapter(_FixtureAdapter):
    """`apply_one` returns without mutating anything -- so the observed evidence
    cannot show the apply landed. Models the false-green this package pays for:
    `apply_one` returning is NOT evidence the mutation happened."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def apply_one(self, raw_client, unit):
        return None

    def undo_one(self, raw_client, unit):
        super().undo_one(raw_client, unit)


class _NoOpUndoAdapter(_FixtureAdapter):
    """`undo_one` returns without restoring anything, so the surface stays
    mutated and `verify_undo_restored` is False over the observed state."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def undo_one(self, raw_client, unit):
        return None


class _FailsOnOneUnitAdapter(_FixtureAdapter):
    """Round-trips every unit cleanly EXCEPT one named unit, whose reversal
    silently does nothing.

    The failing unit is deliberately chosen by the test to NOT be the first.
    That is the whole point of this fixture: the `copy_run_proof-v1` schema
    carries ONE unit's observed evidence, and the producer samples the first unit
    in plan order -- so a trial whose first unit round-tripped cleanly produces a
    proof body the SHIPPED validator accepts on that unit's evidence alone.
    Nothing but the end-state post-condition over the journal on disk stands
    between that and a false green, which makes this the case that proves the
    single-unit-evidence bound is a disclosed bound rather than a hole."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def __init__(self, failing_unit_id):
        super().__init__()
        self.failing_unit_id = failing_unit_id

    def undo_one(self, raw_client, unit):
        if unit.unit_id == self.failing_unit_id:
            return None
        super().undo_one(raw_client, unit)


class _ApplyDoesNotLandOnOneUnitAdapter(_FixtureAdapter):
    """Applies every unit EXCEPT one, whose apply silently does nothing -- so
    that unit is never observed to land, yet its (unchanged) state trivially
    matches its prestate and it is honestly recorded restored.

    With the named unit LAST, every unit in the plan reaches
    `restored_verified`: nothing is outstanding on the surface and nothing is
    left at `planned`. The only thing that must still block the proof is that the
    round trip was not OBSERVED end to end for that unit."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def __init__(self, not_landing_unit_id):
        super().__init__()
        self.not_landing_unit_id = not_landing_unit_id

    def apply_one(self, raw_client, unit):
        if unit.unit_id == self.not_landing_unit_id:
            return None
        super().apply_one(raw_client, unit)

    def undo_one(self, raw_client, unit):
        super().undo_one(raw_client, unit)


class _RaisingApplyAdapter(_FixtureAdapter):
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def undo_one(self, raw_client, unit):
        super().undo_one(raw_client, unit)

    def apply_one(self, raw_client, unit):
        raise RuntimeError("the vendor call failed")


class _RaisingUndoAdapter(_FixtureAdapter):
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def undo_one(self, raw_client, unit):
        raise RuntimeError("the reversal call failed")


class _UnobservableAfterUndoAdapter(_FixtureAdapter):
    """Observation succeeds after apply and raises after undo -- the trial then
    cannot establish restoration from evidence, which must never read as
    restored."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def __init__(self):
        super().__init__()
        self.calls = 0

    def undo_one(self, raw_client, unit):
        super().undo_one(raw_client, unit)

    def verify_one(self, observer, unit):
        self.calls += 1
        if self.calls % 2 == 0:
            raise RuntimeError("the surface could not be read")
        return super().verify_one(observer, unit)


class _SelfProvisioningAdapter(_FixtureAdapter):
    """Provisions BOTH of its own clients, as an emitted adapter does. The
    caller-supplied fallbacks must then be ignored on both sides."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def __init__(self, write_client, read_only_client):
        super().__init__()
        self._write_client = write_client
        self._read_only_client = read_only_client

    def build_write_client(self, op):
        return self._write_client

    def build_read_only_client(self, op):
        return self._read_only_client


class _GmailReadOnlyClient:
    """Read-only client backing `GmailReadFacade` -- the flat method names that
    facade declares, over the shipped Gmail mock. No mutating method."""

    def __init__(self, service):
        self._service = service

    def list_messages(self, query=None, max_results=None):
        return self._service.users().messages().list(
            userId="me", q=query, maxResults=max_results).execute()

    def get_message(self, message_id):
        return self._service.users().messages().get(
            userId="me", id=message_id).execute()

    def list_labels(self):
        return {"labels": [{"id": "INBOX"}, {"id": "TRASH"}]}

    def list_filters(self):
        return self._service.users().settings().filters().list(
            userId="me").execute()

    def get_filter(self, filter_id):
        return self._service.users().settings().filters().get(
            userId="me", id=filter_id).execute()


def _receipt(op, *, digest=None):
    expires_at = (datetime.now(timezone.utc)
                  + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"approved_operation_digest":
            digest if digest is not None
            else hashlib.sha256(op.canonical_repr().encode()).hexdigest(),
            "expires_at": expires_at}


def _entry(*, id, cap=25):
    return {"id": id, "name": id, "action_class": "modify",
            "risk_class": "sensitive_data", "recovery_profile_ref": None,
            "declared_test_target": "native_undo", "blast_radius_cap": cap,
            "accepted": False}


MODULE_PATHS_FIXTURE = ("agents/capabilities/fixture_capability.py",)
CAPABILITY_ID = "fixture_capability"


class _Base(unittest.TestCase):
    """Registration hygiene + hermetic journal / proof / paused-marker trees.
    Every registry this touches is module-global, so every fixture registration
    is undone on teardown and no test writes into the real project tree."""

    OP_KIND = "fixture.trial.set_exact_labels"
    SURFACE = "fixture_surface"

    def setUp(self):
        self.surface = _Surface({"r1": ["OPEN"], "r2": ["OPEN"], "r3": ["OPEN"]})
        self.client = _WriteClient(self.surface)
        self.read_only_client = _ReadOnlyClient(self.surface)
        self.ledger = InvocationLedger()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.journal_dir = str(self.root / "security" / "trial_runs")
        self.proof_dir = str(self.root / "agents" / "handoffs")
        paused = hermetic_paused_mechanisms()
        self.paused_root = paused.__enter__()
        self.addCleanup(paused.__exit__, None, None, None)

    # -- registration --------------------------------------------------------

    def register(self, adapter=None, *, op_kind=None, binding=False,
                 read_only_scope="fixture.readonly", facade=True):
        op_kind = op_kind or self.OP_KIND
        self.adapter = adapter if adapter is not None else _FixtureAdapter()
        register_adapter(op_kind, self.adapter)
        self.addCleanup(unregister_adapter, op_kind)
        register_contract(OperationContract(
            op_kind=op_kind, writes=("labels",), produces=(),
            dependency_set=WRITE_AFFECTING_MODULES,
            verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=binding,
            risk_class="sensitive_data", requires_accepted_phase=True,
            blast_radius_cap=25, read_only_scope=read_only_scope))
        self.addCleanup(OPERATION_CONTRACTS.pop, op_kind, None)
        if facade:
            register_read_facade(op_kind, _FixtureReadFacade)
            self.addCleanup(unregister_read_facade, op_kind)
        return get_dispatch(op_kind)

    # -- operations ----------------------------------------------------------

    def op(self, *, op_kind=None, n=1, surface=None):
        return Operation(
            surface=surface or self.SURFACE, object_id="r1", field="labels",
            new_value=APPLIED_LABEL, op_kind=op_kind or self.OP_KIND,
            batch_id="b1",
            params={"records": [{"unit_id": f"r{i}", "prior_labels": ["OPEN"]}
                                for i in range(1, n + 1)]})

    def run_trial(self, op=None, **kwargs):
        op = self.op() if op is None else op
        kwargs.setdefault("capability_id", CAPABILITY_ID)
        kwargs.setdefault("capability_module_paths", MODULE_PATHS_FIXTURE)
        kwargs.setdefault("client", self.client)
        kwargs.setdefault("read_only_client", self.read_only_client)
        kwargs.setdefault("descriptor_set", [_entry(id=op.surface)])
        kwargs.setdefault("cap_ledger", self.ledger)
        kwargs.setdefault("paused_root", self.paused_root)
        kwargs.setdefault("journal_dir", self.journal_dir)
        kwargs.setdefault("proof_dir", self.proof_dir)
        return tx.run_trial(op, _receipt(op), **kwargs)

    # -- assertions ----------------------------------------------------------

    def proof_path(self, capability_id=CAPABILITY_ID):
        return Path(self.proof_dir) / f"{capability_id}.copy_run_proof.json"

    def assertNoProof(self, capability_id=CAPABILITY_ID):
        self.assertFalse(
            self.proof_path(capability_id).exists(),
            "a proof must never be written for a trial that did not reach a "
            "verified restore on every unit")

    def assertNothingMutated(self):
        self.assertEqual(self.client.writes, [],
                         "nothing may reach the external surface")

    def journal_states(self, outcome):
        return tj.load_trial_journal(
            outcome.trial_id, journal_dir=self.journal_dir).unit_states()

    # -- the refusal DISCRIMINATOR ------------------------------------------
    #
    # `ok is False` + `assertNoProof()` are not enough, and asserting a unit id
    # is in the refusal is not either: the id appears in BOTH refusal texts. The
    # two refusals mean opposite things to the person reading them, and telling
    # an operator that nothing is outstanding while a unit is durably
    # `recovery_required` on their live record is a false safety claim -- they
    # stop looking. So every refusal scenario asserts WHICH of the two it got,
    # in both directions.

    def assertRefusalSaysNotRestored(self, outcome, *unit_ids):
        self.assertIsNotNone(outcome.refusal)
        self.assertIn(
            tx.REFUSAL_MARKER_NOT_RESTORED, outcome.refusal,
            "a unit is not back at its prior state, so the refusal must SAY so")
        self.assertNotIn(
            tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, outcome.refusal,
            "the refusal must NOT tell the operator nothing is outstanding "
            "while a unit is still changed on their live record -- that is the "
            "false safety claim that makes an operator stop looking")
        self.assertIn(outcome.journal_path, outcome.refusal,
                      "the refusal must point at the durable record of what "
                      "happened to each unit")
        for unit_id in unit_ids:
            self.assertIn(unit_id, outcome.refusal)

    def assertRefusalSaysNothingOutstanding(self, outcome, *unit_ids):
        self.assertIsNotNone(outcome.refusal)
        self.assertIn(
            tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, outcome.refusal,
            "everything came back, so the refusal must say the operator's data "
            "is not left changed -- withholding that is its own dishonesty")
        self.assertNotIn(
            tx.REFUSAL_MARKER_NOT_RESTORED, outcome.refusal,
            "nothing is outstanding, so the refusal must NOT claim a unit is "
            "still changed")
        for unit_id in unit_ids:
            self.assertIn(unit_id, outcome.refusal)


# ---------------------------------------------------------------------------
# 1. THE HAPPY PATH — against the one fully trial-eligible SHIPPED op_kind
# ---------------------------------------------------------------------------

class ShippedAdapterEndToEndTests(_Base):
    """`gmail.message.trash` is the ONLY fully trial-eligible op_kind in the
    shipped adapter set: `untrash` / `modify_labels` declare no evidence
    predicates, and filter-create plans units with no reversal reference and
    has a relative-delete undo. So this is the shipped end-to-end surface --
    exactly one op_kind, driven through the real registered adapter."""

    GMAIL_SURFACE = "gmail_mailbox"

    def setUp(self):
        super().setUp()
        self.service = MockGmailService({
            "m1": {"INBOX", "IMPORTANT"},
            "m2": {"INBOX"},
            "m3": {"INBOX", "STARRED"},
        })
        self.before = {mid: sorted(labels)
                       for mid, labels in self.service.messages.items()}
        self.gmail_client = self.service
        self.gmail_read_only = _GmailReadOnlyClient(self.service)

    def gmail_op(self, n=1):
        return Operation(
            surface=self.GMAIL_SURFACE, object_id="m1", field="labels",
            new_value="TRASH", op_kind=OP_TRASH, batch_id="trial-batch",
            params={"messages": [
                {"message_id": mid, "prior_label_ids": self.before[mid]}
                for mid in sorted(self.before)[:n]]})

    def run_gmail_trial(self, n=1, **kwargs):
        op = self.gmail_op(n)
        kwargs.setdefault("client", self.gmail_client)
        kwargs.setdefault("read_only_client", self.gmail_read_only)
        return self.run_trial(op, **kwargs)

    def test_the_shipped_trial_eligible_op_kind_emits_a_proof_the_validator_accepts(self):
        """The done-condition. The proof is not merely written -- it is read
        back off disk and put through the SHIPPED validator, the same one the
        acceptance ceremony runs."""
        outcome = self.run_gmail_trial()
        self.assertTrue(outcome.ok, outcome.refusal)
        path = self.proof_path()
        self.assertTrue(path.exists(), f"no proof at {path}")
        self.assertEqual(outcome.proof_path, str(path))
        with open(path, encoding="utf-8") as f:
            proof = json.load(f)
        verdict = crp.validate_copy_run_proof(proof)
        self.assertTrue(verdict.ok, verdict.reason)

    def test_the_live_surface_is_returned_to_its_exact_prior_state(self):
        outcome = self.run_gmail_trial(n=3)
        self.assertTrue(outcome.ok, outcome.refusal)
        after = {mid: sorted(labels)
                 for mid, labels in self.service.messages.items()}
        self.assertEqual(after, self.before,
                         "a trial ALWAYS reverts -- the mailbox must be exactly "
                         "as it was before the trial ran")

    def test_every_unit_reaches_restored_verified_in_the_journal(self):
        outcome = self.run_gmail_trial(n=3)
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertEqual(self.journal_states(outcome),
                         {"m1": tj.STATE_RESTORED_VERIFIED,
                          "m2": tj.STATE_RESTORED_VERIFIED,
                          "m3": tj.STATE_RESTORED_VERIFIED})

    def test_the_proof_binds_the_capability_the_ceremony_asserts_against(self):
        outcome = self.run_gmail_trial()
        proof = json.loads(self.proof_path().read_text())
        self.assertEqual(proof["capability_id"], CAPABILITY_ID)
        self.assertEqual(proof["capability_module_paths"],
                         list(MODULE_PATHS_FIXTURE))

    def test_the_proof_declares_the_shipped_schema_and_the_real_op_kind(self):
        self.run_gmail_trial()
        proof = json.loads(self.proof_path().read_text())
        self.assertEqual(proof["schema"], crp.COPY_RUN_PROOF_SCHEMA)
        self.assertEqual(proof["op_kind"], OP_TRASH)
        self.assertIs(proof["accepted_for_live_use"], True)

    def test_the_proof_carries_no_key_outside_copy_run_proof_v1(self):
        """A new key under an existing schema tag is the hazard the capsule
        validator refuses outright: a reader cannot tell a newer version from a
        misspelling. The producer stays inside v1 -- the required fields plus
        the two the schema documents as optional-here / mandatory-at-the-trust-
        surface."""
        self.run_gmail_trial()
        proof = json.loads(self.proof_path().read_text())
        allowed = set(crp._REQUIRED_FIELDS) | {"capability_id",
                                               "capability_module_paths"}
        self.assertEqual(set(proof) - allowed, set())
        self.assertEqual(allowed - set(proof), set())

    def test_the_prestate_reference_points_at_the_trial_journal(self):
        """The per-unit prior state lives in the journal, durable before the
        first mutation. The proof's prestate reference must point at that real
        record rather than name a file nobody wrote."""
        outcome = self.run_gmail_trial()
        proof = json.loads(self.proof_path().read_text())
        self.assertEqual(proof["prestate_snapshot_ref"], outcome.journal_path)
        self.assertTrue(Path(proof["prestate_snapshot_ref"]).is_file())

    def test_the_source_reference_never_claims_a_copy_was_used(self):
        """A trial runs against the LIVE bounded target -- the copy target is
        refused at authorization. So the artifact must not carry a value that
        reads as a path to a copy."""
        outcome = self.run_gmail_trial()
        proof = json.loads(self.proof_path().read_text())
        self.assertIn(tx.LIVE_BOUNDED_TRIAL_REF_PREFIX, proof["copy_source_ref"])
        self.assertIn(wa.TRIAL_TARGET, proof["copy_source_ref"])
        self.assertIn(outcome.trial_id, proof["copy_source_ref"])

    def test_durability_checks_are_empty_for_a_non_binding_op_kind(self):
        self.run_gmail_trial()
        proof = json.loads(self.proof_path().read_text())
        self.assertEqual(proof["durability_checks"], [])

    def test_the_proof_hashes_match_a_fresh_recomputation(self):
        """The ceremony recomputes both hashes and refuses on a mismatch."""
        from external_write.proof_hash import (
            compute_contract_hash, compute_implementation_hash,
        )
        self.run_gmail_trial()
        proof = json.loads(self.proof_path().read_text())
        self.assertEqual(proof["contract_hash"], compute_contract_hash(OP_TRASH))
        self.assertEqual(proof["implementation_hash"],
                         compute_implementation_hash(OP_TRASH))

    def test_a_shipped_op_kind_with_no_evidence_predicates_is_refused_a_trial(self):
        """`gmail.message.untrash` declares no evidence predicates, so the
        preflight refuses it. The refusal must arrive with nothing applied and
        no journal -- the trial never starts."""
        op = Operation(
            surface=self.GMAIL_SURFACE, object_id="m1", field="labels",
            new_value="INBOX", op_kind=OP_UNTRASH, batch_id="trial-batch",
            params={"messages": [{"message_id": "m1",
                                  "prior_label_ids": ["TRASH"]}]})
        outcome = self.run_trial(op, client=self.gmail_client,
                                 read_only_client=self.gmail_read_only)
        self.assertFalse(outcome.ok)
        self.assertIn(te.CLAUSE_EVIDENCE_PREDICATES_DECLARED, outcome.refusal)
        self.assertIsNone(outcome.trial_id)
        self.assertNoProof()
        self.assertEqual(
            {mid: sorted(labels) for mid, labels in self.service.messages.items()},
            self.before)


# ---------------------------------------------------------------------------
# 2. THE JOURNAL IS NOT OPTIONAL
# ---------------------------------------------------------------------------

class JournalIsMandatoryTests(_Base):

    def test_a_journal_that_cannot_be_opened_applies_nothing(self):
        """The write-ahead guarantee reduced to its simplest observable form: if
        the durable record cannot be created, not one mutation is issued."""
        self.register()
        with mock.patch.object(tj, "open_trial_journal",
                               side_effect=tj.TrialJournalError("boom")):
            with self.assertRaises(tj.TrialJournalError):
                self.run_trial(self.op(n=3))
        self.assertNothingMutated()
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"])
        self.assertNoProof()

    def test_the_full_plan_and_every_capsule_are_durable_before_the_first_mutation(self):
        seen = {}

        def on_apply(unit):
            if seen:
                return
            seen["record"] = json.loads(Path(journal_path[0]).read_text())

        journal_path = [None]
        real_open = tj.open_trial_journal

        def capture(plan, **kw):
            journal = real_open(plan, **kw)
            journal_path[0] = journal.path
            return journal

        self.register(_ObservingAdapter(on_apply=on_apply))
        with mock.patch.object(tj, "open_trial_journal", side_effect=capture):
            outcome = self.run_trial(self.op(n=3))
        self.assertTrue(outcome.ok, outcome.refusal)
        units = seen["record"]["units"]
        self.assertEqual([u["unit_id"] for u in units], ["r1", "r2", "r3"])
        for u in units:
            self.assertIsNone(
                tj.validate_recovery_capsule(self.OP_KIND, u["unit_id"],
                                             u["recovery_capsule"]),
                "every unit's recovery capsule must be a conforming capsule on "
                "disk before the first mutation")

    def test_each_units_apply_intent_is_on_disk_when_its_own_mutation_is_issued(self):
        observed = []

        def on_apply(unit):
            record = json.loads(Path(journal_path[0]).read_text())
            states = {u["unit_id"]: u["state"] for u in record["units"]}
            observed.append((unit.unit_id, states[unit.unit_id]))

        journal_path = [None]
        real_open = tj.open_trial_journal

        def capture(plan, **kw):
            journal = real_open(plan, **kw)
            journal_path[0] = journal.path
            return journal

        self.register(_ObservingAdapter(on_apply=on_apply))
        with mock.patch.object(tj, "open_trial_journal", side_effect=capture):
            outcome = self.run_trial(self.op(n=2))
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertEqual(observed, [("r1", tj.STATE_APPLY_INTENT),
                                    ("r2", tj.STATE_APPLY_INTENT)])

    def test_each_units_undo_intent_is_on_disk_when_its_own_undo_is_issued(self):
        observed = []

        def on_undo(unit):
            record = json.loads(Path(journal_path[0]).read_text())
            states = {u["unit_id"]: u["state"] for u in record["units"]}
            observed.append((unit.unit_id, states[unit.unit_id]))

        journal_path = [None]
        real_open = tj.open_trial_journal

        def capture(plan, **kw):
            journal = real_open(plan, **kw)
            journal_path[0] = journal.path
            return journal

        self.register(_ObservingAdapter(on_undo=on_undo))
        with mock.patch.object(tj, "open_trial_journal", side_effect=capture):
            outcome = self.run_trial(self.op(n=2))
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertEqual(observed, [("r1", tj.STATE_UNDO_INTENT),
                                    ("r2", tj.STATE_UNDO_INTENT)])

    def test_the_journal_records_the_full_state_sequence_for_every_unit(self):
        self.register()
        outcome = self.run_trial(self.op(n=2))
        self.assertTrue(outcome.ok, outcome.refusal)
        record = tj.load_trial_journal(
            outcome.trial_id, journal_dir=self.journal_dir).read_record()
        for entry in record["units"]:
            self.assertEqual([h["state"] for h in entry["history"]],
                             [tj.STATE_PLANNED, tj.STATE_APPLY_INTENT,
                              tj.STATE_APPLY_CONFIRMED, tj.STATE_UNDO_INTENT,
                              tj.STATE_RESTORED_VERIFIED],
                             entry["unit_id"])


# ---------------------------------------------------------------------------
# 3. THE CREDENTIAL SPLIT
# ---------------------------------------------------------------------------

class CredentialSplitTests(_Base):

    def test_verify_one_receives_a_read_facade_and_never_the_write_client(self):
        """Asserted by IDENTITY, not by equality: a re-derived object could
        compare equal to the wrong thing."""
        self.register()
        outcome = self.run_trial(self.op(n=2))
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertEqual(len(self.adapter.observers), 4,
                         "verify_one is called once after apply and once after "
                         "undo, for each of the two units")
        for observer in self.adapter.observers:
            self.assertIsInstance(observer, ReadFacade)
            self.assertIsNot(observer, self.client)
            self.assertIsNot(observer, self.read_only_client)

    def test_the_facade_is_built_over_the_read_only_client_never_the_write_one(self):
        recorded = []
        real_build = tx.build_read_facade

        def capture(op_kind, client, *args, **kwargs):
            recorded.append(client)
            return real_build(op_kind, client, *args, **kwargs)

        self.register()
        with mock.patch.object(tx, "build_read_facade", side_effect=capture):
            outcome = self.run_trial()
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertEqual(len(recorded), 1)
        self.assertIs(recorded[0], self.read_only_client)
        self.assertIsNot(recorded[0], self.client)

    def test_apply_and_undo_receive_the_write_client(self):
        received = []

        class _Recording(_FixtureAdapter):
            UNDO_IS_ABSOLUTE_STATE_RESTORE = True

            def apply_one(self, raw_client, unit):
                received.append(("apply", raw_client))
                super().apply_one(raw_client, unit)

            def undo_one(self, raw_client, unit):
                received.append(("undo", raw_client))
                super().undo_one(raw_client, unit)

        self.register(_Recording())
        outcome = self.run_trial()
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertEqual([phase for phase, _ in received], ["apply", "undo"])
        for _, client in received:
            self.assertIs(client, self.client)

    def test_the_write_client_is_never_reachable_through_the_facade(self):
        """The fixture clients are disjoint in capability, so this is a real
        tripwire: the read-only client has no mutating method, and the write
        client has no read method. A swap in either direction fails."""
        self.register()
        outcome = self.run_trial()
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertFalse(hasattr(self.read_only_client, "set_labels"))
        self.assertFalse(hasattr(self.client, "get_state"))
        self.assertGreater(len(self.read_only_client.reads), 0,
                           "the observation must actually have gone through "
                           "the read-only client")

    def test_a_self_provisioning_adapter_supplies_both_clients_itself(self):
        """An emitted adapter provisions its own clients. The caller-supplied
        fallbacks must then be ignored on BOTH sides -- the write side is the
        credential-isolation keystone, and the read side mirrors it."""
        own_surface = _Surface({"r1": ["OPEN"]})
        own_write = _WriteClient(own_surface)
        own_read = _ReadOnlyClient(own_surface)
        adapter = _SelfProvisioningAdapter(own_write, own_read)
        self.register(adapter)
        outcome = self.run_trial(self.op(n=1))
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertEqual(self.client.writes, [],
                         "the caller-supplied write client must be ignored when "
                         "the adapter provisions its own")
        self.assertEqual(self.read_only_client.reads, [],
                         "the caller-supplied read-only client must be ignored "
                         "when the adapter provisions its own")
        self.assertGreater(len(own_write.writes), 0)
        self.assertGreater(len(own_read.reads), 0)

    def test_the_clients_are_resolved_through_the_shared_registry_helpers(self):
        """Structural: the trial executor must not carry its OWN copy of the
        provisioner-else-fallback rule. Two resolutions that have to agree is
        how a trial could end up writing through a different credential than
        production does."""
        tree = ast.parse(_MODULE_PATH.read_text())
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("resolve_write_client", called)
        self.assertIn("resolve_read_only_client", called)
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertNotIn("provision_write_client", attrs)
        self.assertNotIn("provision_read_only_client", attrs)

    def test_the_split_holds_at_the_source_level_not_only_at_run_time(self):
        """The behavioural tests above prove the split for the paths they drive.
        This one proves it for EVERY path, by reading the only three call sites
        that could violate it: the observer is handed `facade`, the two mutating
        calls are handed `write_client`, and no call site mixes them."""
        tree = ast.parse(_MODULE_PATH.read_text())
        seen = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("verify_one", "apply_one", "undo_one")):
                continue
            seen.setdefault(node.func.attr, []).append(
                [ast.unparse(a) for a in node.args])
        self.assertEqual(sorted(seen), ["apply_one", "undo_one", "verify_one"])
        for name, calls in seen.items():
            self.assertEqual(len(calls), 1, f"{name} must have one call site")
            args = calls[0]
            self.assertEqual(args[0], "dispatch.instance",
                             f"{name} must be called through the FROZEN dispatch "
                             "record captured at registration, with the instance "
                             "passed explicitly -- never off the mutable instance")
            expected = "facade" if name == "verify_one" else "write_client"
            self.assertEqual(
                args[1], expected,
                f"{name} must receive {expected!r}: the read-only observer and "
                "the write-capable client are never interchangeable, and that "
                "split is the whole reason a kernel-side trial is legitimate")

    def test_the_two_clients_cannot_be_transposed_at_the_call_site(self):
        """The source-level test above pins argument names as written INSIDE
        `_drive_unit`, so a transposition at its call site would satisfy it while
        handing the observer the write-capable client. Keyword-only parameters
        make that unexpressible — asserted here so a future revert to positional
        parameters, which would quietly reopen the route, fails."""
        tree = ast.parse(_MODULE_PATH.read_text())
        drive = next(n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "_drive_unit")
        kwonly = {a.arg for a in drive.args.kwonlyargs}
        positional = {a.arg for a in drive.args.args}
        for name in ("write_client", "facade"):
            self.assertIn(name, kwonly, f"{name} must be keyword-only")
            self.assertNotIn(name, positional)
        # And the interpreter genuinely refuses the positional form.
        with self.assertRaises(TypeError):
            tx._drive_unit(None, None, None, None, None, None, None)

    def test_the_ordinary_write_path_resolves_through_the_same_helpers(self):
        """The other half of the single-source claim: `adapters.py` -- the
        ordinary executor -- must call the SAME two functions, so there is one
        implementation with two callers rather than two implementations."""
        adapters_src = ast.parse((_EXTERNAL_WRITE_DIR / "adapters.py").read_text())
        called = {n.func.id for n in ast.walk(adapters_src)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("resolve_write_client", called)
        self.assertIn("resolve_read_only_client", called)
        attrs = {n.attr for n in ast.walk(adapters_src)
                 if isinstance(n, ast.Attribute)}
        self.assertNotIn("provision_write_client", attrs)
        self.assertNotIn("provision_read_only_client", attrs)


# ---------------------------------------------------------------------------
# 4. A SINGLE FAILED UNIT BLOCKS THE PROOF — AND THE JOURNAL STAYS TRUTHFUL
# ---------------------------------------------------------------------------

class FailedUnitBlocksProofTests(_Base):

    def test_an_unrestored_unit_blocks_the_proof_and_is_recorded_as_needing_recovery(self):
        self.register(_NoOpUndoAdapter())
        outcome = self.run_trial(self.op(n=1))
        self.assertFalse(outcome.ok)
        self.assertNoProof()
        self.assertEqual(self.journal_states(outcome),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        self.assertEqual(outcome.recovery_required_unit_ids, ("r1",))
        self.assertTrue(outcome.units[0].reason.strip())
        self.assertIs(outcome.units[0].undo_restored, False)
        self.assertRefusalSaysNotRestored(outcome, "r1")

    def test_the_recovery_required_record_states_a_cause(self):
        """A durable blocking record with no stated cause cannot be acted on."""
        self.register(_NoOpUndoAdapter())
        outcome = self.run_trial(self.op(n=1))
        record = tj.load_trial_journal(
            outcome.trial_id, journal_dir=self.journal_dir).read_record()
        history = record["units"][0]["history"][-1]
        self.assertEqual(history["state"], tj.STATE_RECOVERY_REQUIRED)
        self.assertTrue(history.get("reason", "").strip())

    def test_an_apply_that_did_not_land_blocks_the_proof_but_is_still_reverted(self):
        """`apply_one` returning is not evidence the mutation landed. The unit
        is still reversed -- an absolute-state restore converges whether or not
        the apply happened -- so the journal truthfully says restored_verified
        while the proof is still refused."""
        self.register(_NoOpApplyAdapter())
        outcome = self.run_trial(self.op(n=1))
        self.assertFalse(outcome.ok)
        self.assertNoProof()
        self.assertEqual(self.journal_states(outcome),
                         {"r1": tj.STATE_RESTORED_VERIFIED})
        self.assertIs(outcome.units[0].apply_landed, False)
        self.assertRefusalSaysNothingOutstanding(outcome, "r1")
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"])

    def test_an_apply_that_raises_is_still_reverted_and_blocks_the_proof(self):
        self.register(_RaisingApplyAdapter())
        outcome = self.run_trial(self.op(n=1))
        self.assertFalse(outcome.ok)
        self.assertNoProof()
        self.assertIn("r1", outcome.units[0].unit_id)
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"])
        self.assertIn(self.journal_states(outcome)["r1"],
                      (tj.STATE_RESTORED_VERIFIED, tj.STATE_RECOVERY_REQUIRED))

    def test_an_undo_that_raises_records_recovery_required(self):
        self.register(_RaisingUndoAdapter())
        outcome = self.run_trial(self.op(n=1))
        self.assertFalse(outcome.ok)
        self.assertNoProof()
        self.assertEqual(self.journal_states(outcome),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        self.assertRefusalSaysNotRestored(outcome, "r1")

    def test_a_surface_that_cannot_be_observed_after_undo_is_never_read_as_restored(self):
        self.register(_UnobservableAfterUndoAdapter())
        outcome = self.run_trial(self.op(n=1))
        self.assertFalse(outcome.ok)
        self.assertNoProof()
        self.assertEqual(self.journal_states(outcome),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        self.assertRefusalSaysNotRestored(outcome, "r1")

    def test_no_later_unit_is_applied_once_an_earlier_unit_has_failed(self):
        """A trial exists to earn a proof. Once it cannot, issuing further live
        mutations is pure cost."""
        self.register(_RaisingUndoAdapter())
        outcome = self.run_trial(self.op(n=3))
        self.assertFalse(outcome.ok)
        states = self.journal_states(outcome)
        self.assertEqual(states["r1"], tj.STATE_RECOVERY_REQUIRED)
        self.assertEqual(states["r2"], tj.STATE_PLANNED)
        self.assertEqual(states["r3"], tj.STATE_PLANNED)
        self.assertEqual([unit_id for unit_id, _ in self.client.writes], ["r1"])
        self.assertRefusalSaysNotRestored(outcome, "r1", "r2", "r3")

    def test_a_LATER_units_failure_blocks_the_proof_the_sampled_unit_would_have_passed(self):
        """The case the rest of this class cannot reach, and the one that keeps
        the schema's single-unit-evidence bound honest.

        Unit r1 round-trips cleanly and IS the unit whose evidence the proof body
        would carry -- so the shipped validator, given that body, would accept
        it. Unit r2 does not come back. The proof must still be refused, and it is
        refused by the END-STATE post-condition read off the journal, not by the
        validator: this asserts the post-condition independently of the check
        that happens to agree with it in every other scenario."""
        self.register(_FailsOnOneUnitAdapter("r2"))
        outcome = self.run_trial(self.op(n=3))
        self.assertFalse(outcome.ok)
        self.assertNoProof()
        self.assertEqual(self.journal_states(outcome),
                         {"r1": tj.STATE_RESTORED_VERIFIED,
                          "r2": tj.STATE_RECOVERY_REQUIRED,
                          "r3": tj.STATE_PLANNED})
        self.assertEqual(outcome.recovery_required_unit_ids, ("r2",))
        # THE assertion the first version of this test was missing. `"r2"` alone
        # appears in BOTH refusal texts, so asserting it proved nothing: with the
        # end-state check deleted this same scenario reported "every unit came
        # back to its prior state... Nothing external is outstanding" about a unit
        # that is durably recovery_required on the operator's live record.
        self.assertRefusalSaysNotRestored(outcome, "r2", "r3")
        # The sampled unit really would have passed on its own evidence -- so the
        # refusal above is the post-condition doing work, not a coincidence.
        self.assertIs(outcome.units[0].apply_landed, True)
        self.assertIs(outcome.units[0].undo_restored, True)

    def test_a_LAST_unit_whose_apply_was_not_observed_blocks_the_proof(self):
        """Every unit is recorded back at its prior state and none is left at
        `planned`, so the restored-state post-condition is satisfied. The proof
        must STILL be refused, because the apply of the last unit was never
        observed to land -- a proof asserts an observed round trip, not merely
        that nothing is outstanding."""
        self.register(_ApplyDoesNotLandOnOneUnitAdapter("r2"))
        outcome = self.run_trial(self.op(n=2))
        self.assertFalse(outcome.ok)
        self.assertNoProof()
        self.assertEqual(self.journal_states(outcome),
                         {"r1": tj.STATE_RESTORED_VERIFIED,
                          "r2": tj.STATE_RESTORED_VERIFIED})
        self.assertEqual(outcome.recovery_required_unit_ids, ())
        self.assertIs(outcome.units[0].apply_landed, True)
        self.assertIs(outcome.units[1].apply_landed, False)
        self.assertRefusalSaysNothingOutstanding(outcome, "r2")
        self.assertEqual(self.surface.snapshot()["r2"], ["OPEN"])

    def test_the_end_state_read_answers_from_the_journal_in_both_directions(self):
        """The end-state read's LOGIC, tested directly — alongside (not instead
        of) the call-site assertions above, which are what catch its deletion.

        Both directions of disagreement, and absent is never read as restored."""
        self.register(_FailsOnOneUnitAdapter("r2"))
        outcome = self.run_trial(self.op(n=3))
        journal = tj.load_trial_journal(outcome.trial_id,
                                        journal_dir=self.journal_dir)
        self.assertEqual(
            tx._units_not_restored_on_disk(journal, ("r1", "r2", "r3")),
            ["r2", "r3"],
            "a unit at recovery_required and a unit still at planned are both "
            "'not back at its prior state'")
        self.assertEqual(
            tx._units_not_restored_on_disk(journal, ("r1", "r4")),
            ["r2", "r3", "r4"],
            "a planned unit the journal does not cover establishes nothing, so it "
            "counts as not restored; and a unit the journal covers that the plan "
            "does not contain means this is not this plan's journal")

    def test_a_failed_trial_reports_every_unit_it_touched(self):
        self.register(_NoOpUndoAdapter())
        outcome = self.run_trial(self.op(n=3))
        self.assertFalse(outcome.ok)
        self.assertEqual([u.unit_id for u in outcome.units], ["r1"])
        self.assertEqual(outcome.recovery_required_unit_ids, ("r1",))


# ---------------------------------------------------------------------------
# 5. THE PRODUCER REFUSES TO EMIT ANYTHING THE SHIPPED VALIDATOR WOULD REJECT
# ---------------------------------------------------------------------------

class ProofSelfCheckTests(_Base):

    def test_a_proof_the_validator_rejects_is_never_written(self):
        self.register()
        with mock.patch.object(
                tx, "validate_copy_run_proof",
                return_value=crp.ProofResult(ok=False, reason="synthetic")):
            outcome = self.run_trial()
        self.assertFalse(outcome.ok)
        self.assertIn("synthetic", outcome.refusal)
        self.assertNoProof()

    def test_every_field_the_producer_writes_is_load_bearing(self):
        """Mutation proof: delete each emitted key in turn and the SHIPPED
        validator must reject. A field nothing checks is padding; a field the
        validator needs and the producer omits is the F-38 class."""
        self.register()
        outcome = self.run_trial()
        self.assertTrue(outcome.ok, outcome.refusal)
        proof = json.loads(Path(outcome.proof_path).read_text())
        for key in crp._REQUIRED_FIELDS:
            mutated = {k: v for k, v in proof.items() if k != key}
            self.assertFalse(crp.validate_copy_run_proof(mutated).ok,
                             f"dropping {key!r} must fail the validator")

    def test_each_nested_evidence_block_is_load_bearing(self):
        self.register()
        outcome = self.run_trial()
        proof = json.loads(Path(outcome.proof_path).read_text())
        for parent, child in (("copy_apply_proof", "apply_receipt_ref"),
                              ("copy_apply_proof", "apply_verification"),
                              ("copy_apply_proof", "apply_evidence"),
                              ("copy_undo_proof", "undo_receipt_ref"),
                              ("copy_undo_proof", "undo_verification"),
                              ("copy_undo_proof", "undo_evidence")):
            mutated = json.loads(json.dumps(proof))
            del mutated[parent][child]
            self.assertFalse(crp.validate_copy_run_proof(mutated).ok,
                             f"dropping {parent}.{child} must fail the validator")

    def test_the_evidence_lineage_the_producer_declares_is_what_the_validator_rederives(self):
        """The producer evaluates the adapter's predicates over evidence it
        builds itself; the validator rebuilds evidence from the RECORD in the
        proof. If those two lineages differ, a lineage-sensitive predicate
        would reach a different verdict at proof time than at run time."""
        self.register()
        outcome = self.run_trial()
        proof = json.loads(Path(outcome.proof_path).read_text())
        for half, block in (("copy_apply_proof", "apply_verification"),
                            ("copy_undo_proof", "undo_verification")):
            rederived = crp._lineage_from_verification_record(
                proof[half][block])
            self.assertEqual(rederived, tx.trial_source_lineage(self.OP_KIND),
                             half)

    def test_the_apply_and_undo_evidence_name_the_unit_they_observed(self):
        self.register()
        outcome = self.run_trial()
        proof = json.loads(Path(outcome.proof_path).read_text())
        self.assertEqual(proof["copy_apply_proof"]["apply_evidence"]["unit_id"],
                         "r1")
        self.assertEqual(proof["copy_undo_proof"]["undo_evidence"]["unit_id"],
                         "r1")

    def test_the_receipt_references_point_into_the_real_journal_record(self):
        self.register()
        outcome = self.run_trial()
        proof = json.loads(Path(outcome.proof_path).read_text())
        for ref in (proof["copy_apply_proof"]["apply_receipt_ref"],
                    proof["copy_undo_proof"]["undo_receipt_ref"]):
            self.assertTrue(ref.startswith(outcome.journal_path), ref)
            self.assertTrue(Path(outcome.journal_path).is_file())

    def test_the_proof_is_written_atomically_and_leaves_no_temp_file(self):
        self.register()
        outcome = self.run_trial()
        self.assertTrue(outcome.ok, outcome.refusal)
        leftovers = [p.name for p in Path(self.proof_dir).iterdir()
                     if p.name != f"{CAPABILITY_ID}.copy_run_proof.json"]
        self.assertEqual(leftovers, [])

    def test_the_emitted_proof_is_canonical_json(self):
        self.register()
        outcome = self.run_trial()
        raw = Path(outcome.proof_path).read_text()
        self.assertEqual(raw, tj.serialize_journal_payload(json.loads(raw)))


# ---------------------------------------------------------------------------
# 6. FAIL-CLOSED REFUSALS — NOTHING WRITTEN, NOTHING APPLIED
# ---------------------------------------------------------------------------

class RefusalTests(_Base):

    def test_a_blank_capability_id_refuses(self):
        self.register()
        for bad in (None, "", "   ", 7):
            with self.subTest(capability_id=bad):
                with self.assertRaises(tx.TrialExecutorError):
                    self.run_trial(capability_id=bad)
        self.assertNothingMutated()

    def test_absent_capability_module_paths_refuse(self):
        self.register()
        for bad in (None, (), [], "a.py", ["", "b.py"], [None]):
            with self.subTest(paths=bad):
                with self.assertRaises(tx.TrialExecutorError):
                    self.run_trial(capability_module_paths=bad)
        self.assertNothingMutated()

    def test_an_op_kind_with_no_registered_adapter_refuses(self):
        register_contract(OperationContract(
            op_kind="fixture.no.adapter", writes=("labels",), produces=(),
            dependency_set=WRITE_AFFECTING_MODULES,
            verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False, risk_class="sensitive_data",
            requires_accepted_phase=True, blast_radius_cap=25,
            read_only_scope="fixture.readonly"))
        self.addCleanup(OPERATION_CONTRACTS.pop, "fixture.no.adapter", None)
        with self.assertRaises(tx.TrialExecutorError):
            self.run_trial(self.op(op_kind="fixture.no.adapter"))
        self.assertNothingMutated()

    def test_an_op_kind_with_no_registered_contract_refuses(self):
        register_adapter("fixture.no.contract", _FixtureAdapter())
        self.addCleanup(unregister_adapter, "fixture.no.contract")
        with self.assertRaises(tx.TrialExecutorError):
            self.run_trial(self.op(op_kind="fixture.no.contract"))
        self.assertNothingMutated()

    def test_a_persistent_binding_op_kind_is_refused_before_any_mutation(self):
        """A binding op_kind's proof requires durability checks -- tested
        operator actions against the new structure. This trial protocol does not
        perform them, and a machine may not write an affirmative it did not
        earn. So the trial refuses UP FRONT rather than running live mutations
        for a proof that could never be emitted."""
        self.register(binding=True)
        with self.assertRaises(tx.TrialExecutorError) as ctx:
            self.run_trial(self.op(n=1))
        self.assertIn("durability", str(ctx.exception).lower())
        self.assertNothingMutated()
        self.assertNoProof()

    def test_an_op_kind_with_no_read_only_scope_refuses_before_any_mutation(self):
        """A trial that cannot observe the real surface cannot earn a proof. It
        refuses rather than degrading to an unverified claim -- the ordinary
        write path's honest `applied_not_verified` is the right answer there and
        the wrong answer here."""
        self.register(read_only_scope=None, facade=False)
        with self.assertRaises(tx.TrialExecutorError):
            self.run_trial(self.op(n=1))
        self.assertNothingMutated()

    def test_no_registered_read_facade_refuses_before_any_mutation(self):
        self.register(facade=False)
        with self.assertRaises(tx.TrialExecutorError):
            self.run_trial(self.op(n=1))
        self.assertNothingMutated()

    def test_no_read_only_client_refuses_before_any_mutation(self):
        self.register()
        with self.assertRaises(tx.TrialExecutorError):
            self.run_trial(self.op(n=1), read_only_client=None)
        self.assertNothingMutated()

    def test_no_write_client_refuses_before_any_mutation(self):
        self.register()
        with self.assertRaises(tx.TrialExecutorError):
            self.run_trial(self.op(n=1), client=None)
        self.assertNothingMutated()

    def test_an_empty_plan_refuses(self):
        self.register()
        op = Operation(surface=self.SURFACE, object_id="r1", field="labels",
                       new_value=APPLIED_LABEL, op_kind=self.OP_KIND,
                       batch_id="b1", params={"records": []})
        outcome = self.run_trial(op)
        self.assertFalse(outcome.ok)
        self.assertNothingMutated()

    def test_a_bad_receipt_refuses_without_applying_anything(self):
        self.register()
        op = self.op()
        outcome = tx.run_trial(
            op, _receipt(op, digest="0" * 64), capability_id=CAPABILITY_ID,
            capability_module_paths=MODULE_PATHS_FIXTURE, client=self.client,
            read_only_client=self.read_only_client,
            descriptor_set=[_entry(id=op.surface)], cap_ledger=self.ledger,
            paused_root=self.paused_root, journal_dir=self.journal_dir,
            proof_dir=self.proof_dir)
        self.assertFalse(outcome.ok)
        self.assertIn("receipt", outcome.refusal.lower())
        self.assertNothingMutated()
        self.assertNoProof()

    def test_an_undeclared_surface_refuses_at_the_gate(self):
        self.register()
        outcome = self.run_trial(self.op(), descriptor_set=[])
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.refusal.strip())
        self.assertNothingMutated()
        self.assertNoProof()

    def test_a_plan_larger_than_the_declared_cap_refuses_before_any_mutation(self):
        self.register()
        op = self.op(n=3)
        outcome = self.run_trial(op, descriptor_set=[_entry(id=op.surface, cap=2)])
        self.assertFalse(outcome.ok)
        self.assertNothingMutated()
        self.assertNoProof()

    def test_a_refusal_never_opens_a_journal(self):
        self.register()
        outcome = self.run_trial(self.op(), descriptor_set=[])
        self.assertFalse(outcome.ok)
        self.assertIsNone(outcome.trial_id)
        self.assertFalse(Path(self.journal_dir).exists()
                         and any(Path(self.journal_dir).iterdir()))


# ---------------------------------------------------------------------------
# 7. ANTI-ZERO-CALLER — STRUCTURAL, OVER THIS PACKAGE'S OWN SOURCE
# ---------------------------------------------------------------------------

def _production_modules():
    """Every non-test module in the emitted lib, as (relpath, ast)."""
    out = {}
    for path in sorted(_EXTERNAL_WRITE_DIR.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        out[path.name] = ast.parse(path.read_text())
    return out


def _modules_calling(func_name):
    return {name for name, tree in _production_modules().items()
            if any(isinstance(n, ast.Call)
                   and ((isinstance(n.func, ast.Name) and n.func.id == func_name)
                        or (isinstance(n.func, ast.Attribute)
                            and n.func.attr == func_name))
                   for n in ast.walk(tree))}


class AntiZeroCallerTests(unittest.TestCase):
    """Both mechanisms this task consumes shipped with no production caller.
    These assertions are over the package's OWN source, so they keep holding as
    it grows -- and they fail if the executor is ever bypassed or orphaned."""

    def test_the_trial_executor_is_the_only_production_caller_of_the_journal(self):
        callers = _modules_calling("open_trial_journal")
        self.assertEqual(callers - {"trial_journal.py"}, {"trial_executor.py"},
                         "the journal must have exactly one production caller "
                         "-- the trial executor -- besides its own module")

    def test_the_trial_executor_is_the_only_production_caller_of_the_trial_intent(self):
        """`authorize_operation`'s TRIAL branch: exactly one production module
        may pass the trial intent to it."""
        callers = set()
        for name, tree in _production_modules().items():
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and ((isinstance(node.func, ast.Name)
                              and node.func.id == "authorize_operation")
                             or (isinstance(node.func, ast.Attribute)
                                 and node.func.attr == "authorize_operation"))):
                    continue
                for kw in node.keywords:
                    if kw.arg == "intent" and "TRIAL" in ast.unparse(kw.value):
                        callers.add(name)
        self.assertEqual(callers, {"trial_executor.py"})

    def test_run_trial_opens_the_journal_unconditionally(self):
        """Not inside an `if`, a `try`, or a loop: there is no branch through
        `run_trial` that mutates anything without a journal on disk first."""
        tree = ast.parse(_MODULE_PATH.read_text())
        run_trial = next(n for n in tree.body
                         if isinstance(n, ast.FunctionDef) and n.name == "run_trial")
        found = []

        def walk(node, guarded):
            for child in ast.iter_child_nodes(node):
                is_guard = isinstance(child, (ast.If, ast.Try, ast.While,
                                              ast.For, ast.With))
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "open_trial_journal"):
                    found.append(guarded)
                walk(child, guarded or is_guard)

        walk(run_trial, False)
        self.assertEqual(found, [False],
                         "run_trial must open the journal exactly once, on an "
                         "unguarded statement")

    def test_the_module_has_exactly_one_apply_and_one_undo_call_site(self):
        tree = ast.parse(_MODULE_PATH.read_text())
        counts = {"apply_one": 0, "undo_one": 0}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in counts:
                    counts[node.func.attr] += 1
        self.assertEqual(counts, {"apply_one": 1, "undo_one": 1},
                         "one mutation call site each -- a second one is a "
                         "second ordering to keep right")

    def test_the_mutation_call_sites_live_in_a_function_that_takes_the_journal(self):
        tree = ast.parse(_MODULE_PATH.read_text())
        for func in [n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef)]:
            mutates = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("apply_one", "undo_one")
                for n in ast.walk(func))
            if not mutates:
                continue
            args = {a.arg for a in func.args.args} | {
                a.arg for a in func.args.kwonlyargs}
            self.assertIn("journal", args,
                          f"{func.name} issues an external mutation, so it must "
                          "be handed the journal that authorizes it")

    def test_the_write_driver_is_not_in_the_read_only_capability_runner(self):
        """`capability_runner.py`'s shipped docstring states that nothing there
        authorizes a write. Putting the driver there would have falsified it."""
        runner = _EXTERNAL_WRITE_DIR / "capability_runner.py"
        src = runner.read_text()
        self.assertIn("Nothing here authorizes a write", src)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr,
                                 ("apply_one", "undo_one", "open_trial_journal",
                                  "authorize_operation"))


# ---------------------------------------------------------------------------
# 8. THE PROOF LANDS WHERE THE ACCEPTANCE COMMAND LOOKS FOR IT
# ---------------------------------------------------------------------------

class ProofPathSingleSourceTests(_Base):

    def test_the_producer_and_the_acceptance_default_share_one_path_builder(self):
        """A producer that writes where the consumer does not look is the
        two-paths-that-must-agree defect at its most expensive: the proof exists
        and acceptance still refuses."""
        self.assertIs(oa.DEFAULT_COPY_RUN_PROOF_DIR, crp.COPY_RUN_PROOF_DIR)
        self.assertEqual(crp.copy_run_proof_path("acme_crm_sync"),
                         os.path.join(oa.DEFAULT_COPY_RUN_PROOF_DIR,
                                      "acme_crm_sync.copy_run_proof.json"))

    def test_the_emitted_path_is_the_documented_per_capability_convention(self):
        self.register()
        outcome = self.run_trial()
        self.assertEqual(
            outcome.proof_path,
            crp.copy_run_proof_path(CAPABILITY_ID, proof_dir=self.proof_dir))

    def test_a_capability_id_with_a_separator_cannot_escape_the_proof_directory(self):
        self.assertEqual(
            Path(crp.copy_run_proof_path("a/b", proof_dir="handoffs")).parent,
            Path("handoffs"))


# ---------------------------------------------------------------------------
# 9. ENROLMENT, ZONE, AND SCAN HYGIENE
# ---------------------------------------------------------------------------

class EnrolmentTests(unittest.TestCase):

    def test_the_trial_executor_is_enrolled_in_the_emitted_lib_file_set(self):
        """A trial runs in the OPERATOR's project. An unenrolled executor means
        the module that produces the proof acceptance requires never physically
        reaches the project that needs it."""
        import agent_emitter
        self.assertIn("trial_executor.py",
                      agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_the_trial_executor_is_enrolled_as_sealed_kernel(self):
        self.assertIn("trial_executor.py", zones.SEALED_KERNEL_MODULE_PATHS)

    def test_capability_zone_code_may_not_import_the_trial_executor(self):
        """SEALED_KERNEL membership is not an invitation: the trial protocol is
        kernel-driven, and capability code has no business driving the writes it
        proposes."""
        self.assertNotIn("trial_executor",
                         scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES)

    def test_the_module_scans_clean_under_the_bypass_scanner(self):
        violations = scan.scan_paths([str(_MODULE_PATH)])
        self.assertEqual(violations, [], [str(v) for v in violations])

    def test_the_facade_observation_lineage_token_has_exactly_one_spelling(self):
        """A re-spelled string literal is a defect. Both the ordinary run-time
        verification path and the trial path declare the same lineage token, so
        it lives in one constant."""
        self.assertTrue(ev.LIVE_READ_ONLY_FACADE_OBSERVATION)
        for name in ("adapters.py", "trial_executor.py"):
            src = (_EXTERNAL_WRITE_DIR / name).read_text()
            literals = {n.value for n in ast.walk(ast.parse(src))
                        if isinstance(n, ast.Constant)
                        and n.value == ev.LIVE_READ_ONLY_FACADE_OBSERVATION}
            self.assertEqual(literals, set(),
                             f"{name} must import the constant, not re-spell it")

    def test_the_invariant_names_are_the_canonical_predicate_names(self):
        for name in (tx.APPLY_PREDICATE_NAME, tx.UNDO_PREDICATE_NAME):
            self.assertIn(name, ev.REQUIRED_EVIDENCE_PREDICATES)

    def test_the_predicate_names_are_fields_the_dispatch_record_actually_has(self):
        """The pin above joins the CONTRACT set (which names the adapter must
        declare). `_evaluate` reads these names off the `AdapterDispatch` RECORD
        with `getattr`, which is a DIFFERENT set that merely happens to agree.

        Without this assertion, renaming an `AdapterDispatch` field leaves the
        pin above green while `getattr` returns None for every adapter, every
        evidence predicate reads as undeclared, and EVERY trial refuses forever
        -- blaming the adapter author. That is permanently-unreachable acceptance
        rebuilt inside the cut whose entire purpose is removing it, so the name
        is pinned to what the code actually reads, not to a name that matches."""
        fields = {f.name for f in dataclasses.fields(AdapterDispatch)}
        for name in (tx.APPLY_PREDICATE_NAME, tx.UNDO_PREDICATE_NAME):
            self.assertIn(name, fields)


# ---------------------------------------------------------------------------
# 10. THE OPERATOR-INVOCABLE ENTRYPOINT — the way IN to the protocol
#
# Until this existed, `run_trial` had zero production callers, no `__main__`, and
# no manifest entry: the proof acceptance requires had a zone-legal producer that
# no operator could start. A producer nobody can invoke is the same shape as a
# repair nobody can find, which is the defect this whole cut exists to close.
# ---------------------------------------------------------------------------

class _SelfProvisioningGmailAdapter(GmailMessageTrashAdapter):
    """The shipped trial-eligible adapter, provisioning BOTH of its own clients
    the way an emitted adapter does -- which is what the entrypoint requires,
    because an operator invocation supplies no client and must not.

    Deliberately does NOT override `undo_one`: the absolute-state restore
    declaration is scoped to the class that defines the `undo_one` it describes,
    so inheriting the real one keeps the declaration truthful."""

    def __init__(self, write_client, read_only_client):
        super().__init__()
        self._write_client = write_client
        self._read_only_client = read_only_client

    def build_write_client(self, op):
        return self._write_client

    def build_read_only_client(self, op):
        return self._read_only_client


_CAPABILITY_SRC = '''"""Fixture capability -- proposes ONE trial-eligible operation."""
from external_write.operations import Operation

OP_KIND = "{op_kind}"


def describe():
    return "fixture trial capability"


def propose_operations(facade, batch_id):
    return [Operation(surface="{surface}", object_id="{first}", field="labels",
                      new_value="TRASH", op_kind=OP_KIND, batch_id=batch_id,
                      params={{"messages": [{messages}]}})]
'''


class _EntrypointBase(_Base):
    """A project on disk carrying a capability that proposes a trial-eligible
    operation, with the SHIPPED adapter registered self-provisioning.

    The shipped `gmail.message.trash` op_kind is used rather than a fixture
    op_kind, and that is forced rather than preferred: the proposal step resolves
    a read facade through the declaration topology over the KERNEL's own lib
    directory, so an op_kind no shipped module declares a reader for cannot reach
    a proposal at all in this process. The end-to-end operator path is therefore
    exercised on the one fully trial-eligible shipped op_kind."""

    GMAIL_SURFACE = "gmail_mailbox"
    CAP_ID = "fixture_trial"

    def setUp(self):
        super().setUp()
        self.service = MockGmailService({"m1": {"INBOX", "IMPORTANT"},
                                         "m2": {"INBOX"}})
        self.before = {mid: sorted(labels)
                       for mid, labels in self.service.messages.items()}
        self.adapter = _SelfProvisioningGmailAdapter(
            self.service, _GmailReadOnlyClient(self.service))
        register_adapter(OP_TRASH, self.adapter)
        self.addCleanup(unregister_adapter, OP_TRASH)
        self.write_capability(self.CAP_ID)

    def write_capability(self, capability_id, op_kind=OP_TRASH):
        messages = ", ".join(
            '{"message_id": "%s", "prior_label_ids": %r}' % (mid, self.before[mid])
            for mid in sorted(self.before))
        path = self.root / "agents" / "capabilities" / f"{capability_id}_capability.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_CAPABILITY_SRC.format(
            op_kind=op_kind, surface=self.GMAIL_SURFACE,
            first=sorted(self.before)[0], messages=messages), encoding="utf-8")
        # The capabilities directory goes on sys.path inside the runner and the
        # module is imported by stem, so a same-named module from another test's
        # temp tree would be served from the import cache.
        self.addCleanup(sys.modules.pop, f"{capability_id}_capability", None)
        return path

    def start(self, capability_id=None, **kwargs):
        kwargs.setdefault("operator_approval", APPROVAL)
        kwargs.setdefault("descriptor_set", [_entry(id=self.GMAIL_SURFACE)])
        kwargs.setdefault("cap_ledger", self.ledger)
        kwargs.setdefault("paused_root", self.paused_root)
        kwargs.setdefault("journal_dir", self.journal_dir)
        kwargs.setdefault("proof_dir", self.proof_dir)
        kwargs.setdefault("review_dir", str(self.root / "review"))
        Path(kwargs["review_dir"]).mkdir(parents=True, exist_ok=True)
        return tx.run_trial_for_capability(
            capability_id or self.CAP_ID, project_root=str(self.root), **kwargs)


APPROVAL = "Yes -- run a bounded trial on my real record and put it back."


class TheRenderedTrialCommandTests(unittest.TestCase):
    """The command is spelled in ONE place, and it is paste-ready. Every other
    surface that has to name it renders it from here."""

    def test_the_module_declares_its_own_entrypoint_path_once(self):
        self.assertEqual(tx.TRIAL_ENTRYPOINT_REL,
                         "agents/lib/external_write/trial_executor.py")
        self.assertTrue((_AGENTS_LIB.parent.parent / tx.TRIAL_ENTRYPOINT_REL).is_file(),
                        "the declared entrypoint path names a file this project "
                        "does not ship")

    def test_the_rendered_command_is_one_physical_line_naming_the_entrypoint(self):
        command = tx.trial_command("acme_crm_sync")
        self.assertEqual(len(command.splitlines()), 1,
                         "a command that wraps is a paste hazard")
        self.assertIn(tx.TRIAL_ENTRYPOINT_REL, command)
        self.assertTrue(command.startswith("python3 "))
        self.assertIn("acme_crm_sync", command)

    def test_the_operators_words_are_a_PLACEHOLDER_when_nobody_has_said_them(self):
        """A surface rendering this as guidance does not know what the operator
        will say and must never invent it -- a machine-filled approval is forged
        consent, not a convenience."""
        self.assertIn(tx.APPROVAL_PLACEHOLDER, tx.trial_command("acme_crm_sync"))
        self.assertNotIn(tx.APPROVAL_PLACEHOLDER,
                         tx.trial_command("acme_crm_sync",
                                          operator_approval=APPROVAL))

    def test_the_operators_own_words_are_carried_verbatim_and_quoted(self):
        command = tx.trial_command("acme_crm_sync", operator_approval=APPROVAL)
        self.assertIn(APPROVAL, shlex.split(command))
        self.assertEqual(len(command.splitlines()), 1)

    def test_a_multi_line_approval_is_REFUSED_rather_than_wrapped(self):
        with self.assertRaises(ValueError):
            tx.trial_command("acme_crm_sync", operator_approval="yes\ngo ahead")

    def test_a_multi_line_CAPABILITY_ID_is_refused_too(self):
        """The same guarantee on the sibling field. `shlex.quote` escapes shell
        metacharacters and PRESERVES a newline, so an id carrying one would render
        a wrapped command from the one surface an operator reads -- and the
        acceptance CLI passes `--capability-id` straight from argv, so the value is
        not this module's to trust."""
        for bad in ("acme\nsync", "acme\rsync"):
            with self.subTest(capability_id=bad):
                with self.assertRaises(ValueError):
                    tx.trial_command(bad)
                with self.assertRaises(ValueError):
                    tx.trial_command(bad, operator_approval=APPROVAL)

    def test_every_rendered_command_is_ONE_line_for_every_interpolated_part(self):
        """Quantified over the parts rather than asserted for one of them: the
        guarantee is about the rendered line, and a check on a single field is how
        the sibling field was missed."""
        for capability_id, approval in (("c", APPROVAL), ("c", None),
                                        ("with space", APPROVAL)):
            with self.subTest(capability_id=capability_id):
                command = tx.trial_command(capability_id,
                                          operator_approval=approval)
                self.assertEqual(len(command.splitlines()), 1)

    def test_the_rendered_command_parses_back_through_the_arg_parser(self):
        """The renderer and the parser are two halves of one contract; a command
        the parser refuses is not paste-ready however it reads."""
        options, error = tx.parse_trial_args(
            shlex.split(tx.trial_command(
                "acme_crm_sync", operator_approval=APPROVAL))[2:])
        self.assertIsNone(error, error)
        self.assertEqual(options[tx.FLAG_CAPABILITY], "acme_crm_sync")
        self.assertEqual(options[tx.FLAG_APPROVAL], APPROVAL)


class TheTrialArgParserRefusesByDefaultTests(unittest.TestCase):
    """DENY BY DEFAULT. This package has already shipped the other shape: an
    unrecognized probe flag was silently dropped and the wrapper ran the live job
    regardless. Here the payload is a live write to the operator's own record."""

    def test_an_unrecognized_argument_refuses(self):
        options, error = tx.parse_trial_args(
            [tx.FLAG_CAPABILITY, "c", tx.FLAG_APPROVAL, APPROVAL, "--checkonly"])
        self.assertIsNone(options)
        self.assertIn("--checkonly", error)

    def test_a_flag_with_no_value_refuses(self):
        options, error = tx.parse_trial_args([tx.FLAG_CAPABILITY])
        self.assertIsNone(options)
        self.assertIn(tx.FLAG_CAPABILITY, error)

    def test_a_missing_capability_refuses(self):
        options, error = tx.parse_trial_args([tx.FLAG_APPROVAL, APPROVAL])
        self.assertIsNone(options)
        self.assertIn(tx.FLAG_CAPABILITY, error)

    def test_a_missing_or_blank_approval_refuses(self):
        for argv in ([tx.FLAG_CAPABILITY, "c"],
                     [tx.FLAG_CAPABILITY, "c", tx.FLAG_APPROVAL, "   "]):
            with self.subTest(argv=argv):
                options, error = tx.parse_trial_args(argv)
                self.assertIsNone(options)
                self.assertIn(tx.FLAG_APPROVAL, error)

    def test_every_refusal_carries_the_usage_line(self):
        for argv in ([], ["--nope", "x"], [tx.FLAG_CAPABILITY, "c"]):
            with self.subTest(argv=argv):
                _options, error = tx.parse_trial_args(argv)
                self.assertIn(tx.TRIAL_ENTRYPOINT_REL, error)


class TheEntrypointDrivesARealTrialTests(_EntrypointBase):
    """The done-condition of the whole task: an operator-invocable call drives a
    trial-eligible operation to a proof the SHIPPED validator accepts, at the
    path the acceptance command reads."""

    def test_it_produces_a_validated_proof_where_acceptance_looks_for_it(self):
        outcome = self.start()
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertEqual(outcome.proof_path,
                         crp.copy_run_proof_path(self.CAP_ID,
                                                 proof_dir=self.proof_dir))
        with open(outcome.proof_path, encoding="utf-8") as f:
            proof = json.load(f)
        verdict = crp.validate_copy_run_proof(proof)
        self.assertTrue(verdict.ok, verdict.reason)
        self.assertEqual(proof["capability_id"], self.CAP_ID)

    def test_the_operators_real_record_is_returned_to_its_prior_state(self):
        self.assertTrue(self.start().ok)
        self.assertEqual({mid: sorted(labels)
                          for mid, labels in self.service.messages.items()},
                         self.before,
                         "a trial ALWAYS reverts")

    def test_every_unit_is_recorded_restored_verified_in_the_durable_record(self):
        outcome = self.start()
        states = set(tj.load_trial_journal(
            outcome.trial_id, journal_dir=self.journal_dir).unit_states().values())
        self.assertEqual(states, {tj.STATE_RESTORED_VERIFIED})

    def test_the_proof_names_the_capability_module_the_runner_actually_LOADED(self):
        """The acceptance ceremony scans these files to establish that this
        capability's write path is gated. A path this entrypoint invented would
        send the ceremony to scan a file that is not the one that ran."""
        outcome = self.start()
        with open(outcome.proof_path, encoding="utf-8") as f:
            proof = json.load(f)
        self.assertEqual(list(proof["capability_module_paths"]),
                         [f"agents/capabilities/{self.CAP_ID}_capability.py"])

    def test_a_capability_that_proposes_NOTHING_is_refused_before_anything_runs(self):
        path = self.write_capability("empty_trial")
        path.write_text('OP_KIND = "%s"\n\n\ndef propose_operations(f, b):\n'
                        "    return []\n" % OP_TRASH, encoding="utf-8")
        with self.assertRaises(tx.TrialExecutorError) as raised:
            self.start("empty_trial")
        self.assertIn("nothing", str(raised.exception).lower())
        self.assertEqual({mid: sorted(labels)
                          for mid, labels in self.service.messages.items()},
                         self.before)

    def test_an_UNKNOWN_capability_is_refused_in_plain_language(self):
        with self.assertRaises(Exception) as raised:
            self.start("no_such_capability")
        message = str(raised.exception)
        self.assertIn("no_such_capability", message)
        self.assertNotIn("Traceback", message)

    def test_a_capability_proposing_a_DIFFERENT_op_kind_than_it_declares_is_refused(self):
        """Read isolation. The facade the proposal step built was resolved from
        the capability's OWN declared op_kind; trialling an operation that names
        another one would trial a surface this capability never declared."""
        path = self.write_capability("mismatched")
        path.write_text(path.read_text(encoding="utf-8").replace(
            "op_kind=OP_KIND", 'op_kind="gmail.message.untrash"'),
            encoding="utf-8")
        with self.assertRaises(tx.TrialExecutorError) as raised:
            self.start("mismatched")
        message = str(raised.exception)
        # BOTH op_kinds and the guard's own reason. Asserting only the proposed
        # op_kind passed with the guard REMOVED -- a later refusal (the proposed
        # op_kind has no read-only reader declared) raises the same exception type
        # and names the same op_kind, so the test did not bind the thing it was
        # written for. Measured, not assumed: the mutation survived.
        self.assertIn("gmail.message.untrash", message)
        self.assertIn(OP_TRASH, message,
                      "the refusal must say what the capability DECLARES as well "
                      "as what it proposed; without both it is not this check")
        self.assertIn("never said it works on", message)
        self.assertEqual({mid: sorted(labels)
                          for mid, labels in self.service.messages.items()},
                         self.before)


class TheEntrypointWorksInAFRESHProcessTests(_EntrypointBase):
    """A freshly-invoked operator command has imported no read-facade module.
    Nothing in production imports one at module scope, and the registry
    `build_read_facade` resolves from is populated only by such an import -- so an
    entrypoint that assumed a warm registry would refuse on EVERY real
    invocation, which is what the recovery command already had to solve."""

    def test_a_COLD_read_facade_registry_is_warmed_and_the_trial_still_proves(self):
        registered = get_read_facade_class(OP_TRASH)
        self.assertIsNotNone(registered, "fixture precondition")
        unregister_read_facade(OP_TRASH)
        self.addCleanup(register_read_facade, OP_TRASH, registered)
        # THE FRESH-PROCESS CONDITION TAKES TWO STEPS, not one. Emptying the
        # registry alone is not a fresh process: the declaring module is still in
        # `sys.modules`, so re-importing it is a no-op and its module-scope
        # registration never re-runs -- the resolver then reports "loaded, but
        # registered nothing" and the test reads as a product defect when it is an
        # unfaithful fixture. A real fresh interpreter has neither.
        cached = sys.modules.pop("external_write.read_facades_gmail", None)
        self.assertIsNotNone(cached, "fixture precondition: it was imported")
        self.addCleanup(sys.modules.setdefault,
                        "external_write.read_facades_gmail", cached)
        self.assertIsNone(get_read_facade_class(OP_TRASH),
                          "the registry must actually be cold for this to mean "
                          "anything")

        outcome = self.start()
        self.assertTrue(outcome.ok, outcome.refusal)
        self.assertIsNotNone(get_read_facade_class(OP_TRASH),
                             "the entrypoint left the registry cold, so the "
                             "observation it recorded came from somewhere else")

    def test_the_warming_step_POPULATES_a_cold_registry_and_short_circuits_a_warm_one(self):
        """The mechanism itself, driven in both directions.

        Asserted here as well as end to end because of a MEASURED fact rather than
        a suspected one: removing the warming call from the runtime path leaves the
        end-to-end trial green, because the proposal step this entrypoint runs
        first resolves through the SAME shared function. So the end-to-end test
        cannot bind the call site, and the honest thing is to bind the mechanism
        and say so rather than to claim a falsifiability that is not there."""
        registered = get_read_facade_class(OP_TRASH)
        self.assertIsNotNone(registered, "fixture precondition")
        unregister_read_facade(OP_TRASH)
        self.addCleanup(register_read_facade, OP_TRASH, registered)
        cached = sys.modules.pop("external_write.read_facades_gmail", None)
        self.assertIsNotNone(cached, "fixture precondition: it was imported")
        self.addCleanup(sys.modules.setdefault,
                        "external_write.read_facades_gmail", cached)
        self.assertIsNone(get_read_facade_class(OP_TRASH))

        tx._warmed_read_facade_registry(OP_TRASH)
        self.assertIsNotNone(get_read_facade_class(OP_TRASH),
                             "a cold registry was left cold")

        # Warm: the declaring module is not imported again. Proven by removing it
        # from the module cache and asserting the registry entry is untouched --
        # an unconditional import would repopulate it from the module, so this
        # distinguishes "short-circuited" from "did the work twice".
        again = sys.modules.pop("external_write.read_facades_gmail", None)
        tx._warmed_read_facade_registry(OP_TRASH)
        self.assertNotIn("external_write.read_facades_gmail", sys.modules,
                         "the declaring module was imported again for an op_kind "
                         "whose reader is already registered")
        if again is not None:
            sys.modules.setdefault("external_write.read_facades_gmail", again)

    def test_an_op_kind_with_no_declared_reader_is_REFUSED_not_silently_skipped(self):
        with self.assertRaises(Exception) as raised:
            tx._warmed_read_facade_registry("nothing.declares.this")
        self.assertNotIsInstance(raised.exception, AssertionError)

    def test_the_resolution_goes_through_the_ONE_shared_resolver(self):
        """Not a second copy of "which module provides read-only access for this
        op_kind" -- that is a classification, and two implementations of one
        classification is this package's most expensive recurring defect."""
        tree = ast.parse(_MODULE_PATH.read_text())
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertIn("import_declared_read_facade", called)
        self.assertNotIn("build_topology", called,
                         "the topology lookup belongs to the one shared "
                         "implementation")

    def test_the_registry_is_NOT_warmed_at_module_scope(self):
        """`trial_executor` is imported on every project that touches the health
        surface (capability_health -> state_actions -> trial_recovery -> here, all
        at module scope). Warming at module scope would fire read-facade module
        imports on every health check in every project."""
        tree = ast.parse(_MODULE_PATH.read_text())
        for node in tree.body:
            # Definitions do not RUN at import; every other module-level
            # statement does, including the script bootstrap and the constants.
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    name = getattr(inner.func, "id",
                                   getattr(inner.func, "attr", ""))
                    self.assertNotIn(name, ("import_declared_read_facade",
                                            "get_read_facade_class",
                                            "run_capability_proposal"))


class TheEntrypointIsAnENROLLEDOperatorCommandTests(unittest.TestCase):
    """A live-write command an operator runs. Enrolled, never allowlist-eligible
    -- and the agreement between the manifest's hand-spelled prefix and this
    module's own declared path is pinned, not hoped for."""

    def test_it_is_enrolled_as_a_live_write_that_is_never_auto_approved(self):
        from external_write import command_manifest as cm
        entry = cm.find_command("trial-run")
        self.assertIsNotNone(
            entry, "the trial command performs a real external write to the "
                   "operator's record; it must be classified")
        self.assertEqual(entry.command_class, cm.LIVE_WRITE)
        self.assertTrue(entry.writes_external)
        self.assertFalse(cm.is_allowlist_eligible(entry))

    def test_the_enrolled_prefix_agrees_with_this_modules_own_constant(self):
        from external_write import command_manifest as cm
        self.assertEqual(cm.find_command("trial-run").command_prefix,
                         f"python3 {tx.TRIAL_ENTRYPOINT_REL}")

    def test_the_module_declares_a_command_line_entrypoint(self):
        tree = ast.parse(_MODULE_PATH.read_text())
        self.assertTrue(
            any(isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__" for node in tree.body),
            "the producer ships no operator-invocable entrypoint")


class TheOperatorsOwnWordsAreTheApprovalTests(_EntrypointBase):
    """A trial is a real live write to a bounded subset of the operator's own
    record. Its approval is the operator's own words, minted through the
    sanctioned broker path -- never a receipt this module invents for itself."""

    def test_a_blank_approval_is_refused_and_nothing_is_written(self):
        for approval in ("", "   ", None):
            with self.subTest(approval=approval):
                with self.assertRaises(tx.TrialExecutorError):
                    self.start(operator_approval=approval)
                self.assertEqual({mid: sorted(labels)
                                  for mid, labels in self.service.messages.items()},
                                 self.before)

    def test_the_approval_is_minted_through_the_brokers_own_path(self):
        tree = ast.parse(_MODULE_PATH.read_text())
        names = {getattr(n.func, "id", getattr(n.func, "attr", ""))
                 for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertIn("confirm", names,
                      "the operator's approval must go through the broker that "
                      "records their verbatim words, not a self-minted receipt")

    def test_the_receipt_is_bound_to_the_EXACT_operation_that_is_trialled(self):
        """A receipt for a different operation is not an approval of this one."""
        outcome = self.start()
        self.assertTrue(outcome.ok, outcome.refusal)


class WhatTheOperatorIsTOLDAboutTheOutcomeTests(_EntrypointBase):
    """`trial_summary` is the only sentence an operator reads about a completed
    trial, so every claim in it has to be true when written and every branch of it
    has to be reachable from the operator's own path."""

    def test_the_proposal_COUNT_travels_with_the_outcome(self):
        """The disclosed bound says a capability proposing several is not silently
        narrowed. That is only deliverable if the count reaches the sentence, and
        the only thing that crosses from the producer to the CLI is the outcome."""
        outcome = self.start()
        self.assertEqual(outcome.proposed_operation_count, 1)
        self.assertEqual(
            tj.load_trial_journal(
                outcome.trial_id, journal_dir=self.journal_dir).unit_states(),
            {"m1": tj.STATE_RESTORED_VERIFIED, "m2": tj.STATE_RESTORED_VERIFIED})

    def test_the_summary_NAMES_the_count_when_more_was_proposed_than_tried(self):
        outcome = dataclasses.replace(self.start(), proposed_operation_count=3)
        message = tx.trial_summary(outcome, capability_id=self.CAP_ID)
        self.assertIn("proposed 3", message)
        self.assertIn(str(outcome.proof_path), message)

    def test_the_summary_says_nothing_about_a_count_for_a_single_proposal(self):
        message = tx.trial_summary(self.start(), capability_id=self.CAP_ID)
        self.assertNotIn("proposed", message)

    def test_the_summary_takes_the_count_from_the_OUTCOME_not_a_parameter(self):
        """A count the caller has to remember to pass is a count the caller
        forgets: the first version of this sentence had a `proposed` parameter and
        the only caller -- the CLI -- never passed it, so the branch was
        unreachable from the operator's path and the bound was a claim with no
        code behind it."""
        parameters = inspect.signature(tx.trial_summary).parameters
        self.assertEqual(sorted(parameters), ["capability_id", "outcome"])

    def test_a_refusal_with_NO_recorded_REASON_never_prints_the_word_None(self):
        """`str(None)` is "None", and "None" is not a reason. An operator-facing
        sentence must be true when written, and this branch must not claim the
        thing that would make someone stop looking either: it says nothing can be
        established about whether a change is still live, and routes to a person."""
        message = tx.trial_summary(
            tx.TrialOutcome(ok=False, trial_id="t-1", journal_path="p.json"),
            capability_id="acme_crm_sync")
        self.assertNotIn("None", message)
        self.assertIn("p.json", message)
        self.assertIn("ask your assistant", message.lower())
        self.assertNotIn(tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, message,
                         "a run that recorded no reason cannot establish that "
                         "nothing is outstanding")

    def test_a_refusal_WITH_a_reason_is_surfaced_verbatim(self):
        outcome = tx.TrialOutcome(ok=False, refusal="the gate said no, plainly")
        self.assertEqual(tx.trial_summary(outcome, capability_id="c"),
                         "the gate said no, plainly")


class TheEntrypointNeverShowsAnOperatorATracebackTests(unittest.TestCase):
    """The `__main__` block promises it, and the promise is only as good as the
    exception types it names."""

    def _main_handlers(self):
        tree = ast.parse(_MODULE_PATH.read_text())
        main = next(node for node in tree.body
                    if isinstance(node, ast.If)
                    and isinstance(node.test, ast.Compare)
                    and getattr(node.test.left, "id", "") == "__name__")
        names = set()
        for node in ast.walk(main):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            for element in (node.type.elts if isinstance(node.type, ast.Tuple)
                            else [node.type]):
                found = getattr(element, "id", getattr(element, "attr", None))
                if found:
                    names.add(found)
        return names

    def test_every_refusal_the_runtime_path_can_raise_is_CAUGHT(self):
        """`_warmed_read_facade_registry` calls the shared resolver directly, so it
        raises that resolver's OWN types -- `TopologyError` and
        `ReadFacadeDeclarationError` -- rather than the capability-flavoured
        translation the capability-facing wrapper provides.

        `ReadFacadeDeclarationError` being unreachable TODAY is a coupling, not a
        guarantee: it is shadowed only because the proposal step resolves the same
        op_kind first, which is the identical coupling that let the warming-call
        mutation survive. The recovery entrypoint's own facade step already catches
        it; this follows that precedent rather than relying on the shadow."""
        handlers = self._main_handlers()
        for required in ("TrialExecutorError", "TrialJournalError",
                         "CapabilityRunnerError", "TopologyError",
                         "ReadFacadeDeclarationError"):
            with self.subTest(exception=required):
                self.assertIn(
                    required, handlers,
                    "the entrypoint promises it never prints a traceback, and "
                    "this is a refusal its own runtime path can raise")

    def test_the_shared_resolver_still_declares_the_types_this_pins(self):
        """Joined on what the resolver DOCUMENTS raising, so a rename upstream
        fails here rather than leaving the tuple naming a type nothing raises."""
        from external_write import capability_runner as cr
        self.assertTrue(hasattr(cr, "ReadFacadeDeclarationError"))
        self.assertIn("TopologyError",
                      inspect.getdoc(cr.import_declared_read_facade))
        self.assertIn("ReadFacadeDeclarationError",
                      inspect.getdoc(cr.import_declared_read_facade))


class TheACCEPTANCERefusalNamesTheProducerTests(unittest.TestCase):
    """The other half of reachability: a command nothing names is only reachable
    by someone who already knows it exists.

    Acceptance requires a validated copy-run proof, and the operator-facing
    refusal for a missing one said what was wrong and nothing about what to do --
    which is exactly the dead-end shape this cut exists to close, at the surface
    where a capability that has been made fully compliant still cannot be
    accepted. The refusal now names the producer, rendered by the module that owns
    the entrypoint rather than spelled a second time."""

    def _project(self, capability_id="acme_crm_sync"):
        """A project with ONE pending descriptor entry -- enough that the CLI
        reaches the ceremony rather than refusing earlier for want of a phase."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        descriptors = root / "security" / "capability_descriptors.json"
        descriptors.parent.mkdir(parents=True, exist_ok=True)
        descriptors.write_text(json.dumps([{
            "id": capability_id, "name": capability_id, "phase_id": "phase_1",
            "action_class": "modify", "risk_class": "sensitive_data",
            "recovery_profile_ref": None, "declared_test_target": "native_undo",
            "blast_radius_cap": 25, "accepted": False}]), encoding="utf-8")
        return root, descriptors, capability_id

    def _run_acceptance(self, descriptors, capability_id, proof_path=None):
        """The acceptance CLI as a real process, from the repo's own emitted tree
        -- which is where its `__main__` lives and the only way to observe what an
        operator reads."""
        argv = [sys.executable, "agents/lib/external_write/operator_acceptance.py",
                "--capability-id", capability_id,
                "--operator-confirmation", "yes go ahead",
                "--descriptor-set", str(descriptors)]
        if proof_path is not None:
            argv += ["--copy-run-proof", str(proof_path)]
        result = subprocess.run(
            argv, capture_output=True, text=True,
            cwd=str(_AGENTS_LIB.parent.parent),
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                     PYTHONPATH=str(_AGENTS_LIB)),
            timeout=300)
        return result, result.stdout + result.stderr

    def test_a_missing_proof_refusal_hands_over_the_producers_own_command(self):
        _root, descriptors, capability_id = self._project()
        result, message = self._run_acceptance(descriptors, capability_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REFUSED", message)
        self.assertIn(tx.trial_command(capability_id), message,
                      "the acceptance refusal names no way to produce the "
                      "evidence it requires: %r" % message)
        self.assertIn(tx.APPROVAL_PLACEHOLDER, message,
                      "the operator's own words must be left as a blank for them "
                      "to fill in, never invented")
        self.assertNotIn("Traceback", message)

    def test_the_hint_is_absent_when_a_proof_IS_present(self):
        """Keyed on the FILE, not on the refusal wording -- so a refusal for some
        other reason does not tell the operator to produce evidence they have."""
        root, descriptors, capability_id = self._project()
        proof = root / crp.copy_run_proof_path(capability_id)
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("{}", encoding="utf-8")
        result, message = self._run_acceptance(descriptors, capability_id,
                                              proof_path=proof)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REFUSED", message)
        self.assertNotIn(tx.TRIAL_ENTRYPOINT_REL, message)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
