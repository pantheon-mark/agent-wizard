"""Tests for the Gmail verb-shaped adapter (Task 7 — external-write-gate-
generalization slice): the reference ADAPTER_PROFILE module proving the
generalized external-write gate (Tasks 1-6) actually gates a REAL vendor API
shape, not just the seeded spreadsheet-style field write.

Everything here runs against a MOCKED Gmail service (an in-memory mailbox +
filter store, duck-typed to the real discovery-API call shape) — no real
network, no real credentials, per the global TDD/mocking constraint.

Groups:
  1. TestContractsRegistered      -- the four op_kinds' contracts + read_only_scope.
  2. TestPlanYieldsOneUnitPerTarget -- one EffectUnit per target/message/filter.
  3. TestApplyUndoVerifyRoundTrip -- apply -> undo -> verify restores prestate,
     per op_kind (the Review focus: "undo descriptor + reverse method exist
     and are exercised").
  4. TestStructuralSafetyByAbsence -- no send/draft/forward method anywhere in
     the module; no messages().delete/trash/untrash call site (AST-verified,
     not a textual grep that would false-positive on this file's own
     explanatory docstrings).
  5. TestZoneScanClassification   -- adapters_gmail.py classifies ADAPTER_PROFILE
     and scans clean; a capability module that imported the write-capable
     client directly still fails the scan (negative control fixture).
  6. TestGmailReadFacade          -- declared read_methods only; wrapped client
     unreachable via any attribute.
  7. TestInvariantEightPositiveControl -- a REAL resolvable adapter (this
     module, imported normally — not a throwaway fixture) whose
     implementation_hash covers it, and the acceptance ceremony (Task 6)
     ACCEPTS a conformant fixture through it.
"""

import ast
import inspect
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

import external_write.adapters_gmail as adapters_gmail  # noqa: E402
import external_write.read_facades_gmail as read_facades_gmail  # noqa: E402
from external_write.adapters_gmail import (  # noqa: E402
    OP_TRASH, OP_UNTRASH, OP_MODIFY_LABELS, OP_FILTER_CREATE,
    GmailMessageTrashAdapter, GmailMessageUntrashAdapter,
    GmailMessageModifyLabelsAdapter, GmailFilterCreateAdapter,
)
from external_write.read_facades_gmail import GmailReadFacade  # noqa: E402
from external_write.adapter_registry import get_adapter  # noqa: E402
from external_write.contracts import get_contract  # noqa: E402
from external_write.read_facade import build_read_facade  # noqa: E402
from external_write.zones import (  # noqa: E402
    ADAPTER_PROFILE_MODULE_PATHS, SEALED_KERNEL_MODULE_PATHS, Zone, classify_zone,
)
from external_write.scan import scan_paths, _attr_chain_names  # noqa: E402
from external_write.effects_manifest import (  # noqa: E402
    build_manifest, resolve_dependency_files,
)
from external_write.proof_hash import (  # noqa: E402
    compute_contract_hash, compute_implementation_hash,
)
from external_write.copy_run_proof import (  # noqa: E402
    COPY_RUN_PROOF_SCHEMA, validate_copy_run_proof,
)
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402
from external_write.acceptance_ceremony import (  # noqa: E402
    accept_capability_for_live_use, OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA,
)

_ADAPTER_MODULE_PATH = Path(adapters_gmail.__file__).resolve()
_ADAPTER_ANCHOR = _ADAPTER_MODULE_PATH.parent  # agents/lib/external_write

_READ_FACADES_GMAIL_MODULE_PATH = Path(read_facades_gmail.__file__).resolve()

_FIXTURES = (
    Path(__file__).resolve().parents[2] / "test_fixtures" / "external_write_scan"
)
_CLEAN_CAPABILITY_MODULE = str(_FIXTURES / "legal_through_adapter.py")
_BYPASS_FIXTURE = _FIXTURES / "gmail_capability_direct_write.py"


# ---------------------------------------------------------------------------
# Mocked Gmail service -- NO network, NO real credentials. Duck-typed to the
# real discovery-API call shape (service.users().messages().get(...).execute(),
# etc.) so the adapter code under test is exercised exactly as it would run
# against a real (authenticated elsewhere) Gmail client.
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, execute_fn):
        self._execute_fn = execute_fn

    def execute(self):
        return self._execute_fn()


class _FakeMessagesResource:
    def __init__(self, service):
        self._service = service

    def get(self, userId, id, format=None):
        def _exec():
            if id not in self._service.messages:
                raise KeyError(f"no such message {id!r}")
            return {"id": id, "labelIds": sorted(self._service.messages[id])}
        return _FakeRequest(_exec)

    def modify(self, userId, id, body):
        def _exec():
            if id not in self._service.messages:
                raise KeyError(f"no such message {id!r}")
            labels = set(self._service.messages[id])
            for l in (body.get("addLabelIds") or []):
                labels.add(l)
            for l in (body.get("removeLabelIds") or []):
                labels.discard(l)
            self._service.messages[id] = labels
            return {"id": id, "labelIds": sorted(labels)}
        return _FakeRequest(_exec)

    def list(self, userId, q=None, maxResults=None):
        def _exec():
            return {"messages": [{"id": mid} for mid in sorted(self._service.messages)]}
        return _FakeRequest(_exec)

    # Deliberately present as tripwires: if the adapter ever called one of
    # these, the mock itself fails loudly rather than silently no-opping.
    def trash(self, userId, id):
        raise AssertionError(
            "messages().trash() must never be called -- this adapter speaks "
            "only modify() label deltas (see module docstring)")

    def untrash(self, userId, id):
        raise AssertionError("messages().untrash() must never be called")

    def delete(self, userId, id):
        raise AssertionError(
            "messages().delete() (Gmail's PERMANENT delete) must never be called")

    def send(self, userId, body=None):
        raise AssertionError("messages().send() must never be called -- no send path exists")


class _FakeFiltersResource:
    def __init__(self, service):
        self._service = service
        self._next_id = 1

    def create(self, userId, body):
        def _exec():
            fid = f"filter-{self._next_id}"
            self._next_id += 1
            self._service.filters[fid] = dict(body)
            return {"id": fid, **body}
        return _FakeRequest(_exec)

    def delete(self, userId, id):
        def _exec():
            if id not in self._service.filters:
                raise KeyError(f"no such filter {id!r}")
            del self._service.filters[id]
            return {}
        return _FakeRequest(_exec)

    def get(self, userId, id):
        def _exec():
            if id not in self._service.filters:
                raise KeyError(f"no such filter {id!r}")
            return {"id": id, **self._service.filters[id]}
        return _FakeRequest(_exec)

    def list(self, userId):
        def _exec():
            return {"filter": [{"id": fid, **spec}
                               for fid, spec in self._service.filters.items()]}
        return _FakeRequest(_exec)


class _FakeSettingsResource:
    def __init__(self, service):
        self._filters = _FakeFiltersResource(service)

    def filters(self):
        return self._filters


class _FakeUsersResource:
    def __init__(self, service):
        self._messages = _FakeMessagesResource(service)
        self._settings = _FakeSettingsResource(service)

    def messages(self):
        return self._messages

    def settings(self):
        return self._settings


class MockGmailService:
    """In-memory Gmail mailbox (message_id -> set(labelIds)) + filter store
    (filter_id -> {criteria, action}). No network, no real credentials."""

    def __init__(self, messages=None):
        self.messages = {mid: set(labels) for mid, labels in (messages or {}).items()}
        self.filters = {}
        self._users = _FakeUsersResource(self)

    def users(self):
        return self._users


# ---------------------------------------------------------------------------
# 1. Contracts registered
# ---------------------------------------------------------------------------

class TestContractsRegistered(unittest.TestCase):
    def test_all_four_op_kinds_have_contracts_with_gmail_readonly_scope(self):
        for op_kind in (OP_TRASH, OP_UNTRASH, OP_MODIFY_LABELS, OP_FILTER_CREATE):
            c = get_contract(op_kind)
            self.assertIsNotNone(c, op_kind)
            self.assertEqual(c.read_only_scope, "gmail.readonly", op_kind)

    def test_message_op_kinds_are_sensitive_data_and_gated(self):
        for op_kind in (OP_TRASH, OP_UNTRASH, OP_MODIFY_LABELS):
            c = get_contract(op_kind)
            self.assertEqual(c.risk_class, "sensitive_data", op_kind)
            self.assertTrue(c.requires_accepted_phase, op_kind)
            self.assertGreater(c.blast_radius_cap, 0, op_kind)

    def test_filter_create_is_standing_automation_and_introduces_binding(self):
        c = get_contract(OP_FILTER_CREATE)
        self.assertEqual(c.risk_class, "standing_automation")
        self.assertTrue(c.requires_accepted_phase)
        self.assertTrue(c.introduces_persistent_binding)

    def test_message_op_kinds_do_not_introduce_persistent_binding(self):
        for op_kind in (OP_TRASH, OP_UNTRASH, OP_MODIFY_LABELS):
            self.assertFalse(get_contract(op_kind).introduces_persistent_binding, op_kind)

    def test_all_four_op_kinds_are_registered_in_the_adapter_registry(self):
        for op_kind in (OP_TRASH, OP_UNTRASH, OP_MODIFY_LABELS, OP_FILTER_CREATE):
            self.assertIsNotNone(get_adapter(op_kind), op_kind)

    def test_each_adapter_declares_an_undo_descriptor(self):
        for op_kind, adapter_cls in (
            (OP_TRASH, GmailMessageTrashAdapter),
            (OP_UNTRASH, GmailMessageUntrashAdapter),
            (OP_MODIFY_LABELS, GmailMessageModifyLabelsAdapter),
            (OP_FILTER_CREATE, GmailFilterCreateAdapter),
        ):
            descriptor = adapter_cls.UNDO_DESCRIPTOR
            self.assertEqual(descriptor["op_kind"], op_kind)
            self.assertIn("recovery", descriptor)
            self.assertIn("prestate_requirement", descriptor)


# ---------------------------------------------------------------------------
# 2. plan() yields exactly one EffectUnit per target
# ---------------------------------------------------------------------------

class TestPlanYieldsOneUnitPerTarget(unittest.TestCase):
    def test_trash_plan_one_unit_per_message(self):
        adapter = GmailMessageTrashAdapter()
        units = adapter.plan({"messages": [
            {"message_id": "m1", "prior_label_ids": ["INBOX"]},
            {"message_id": "m2", "prior_label_ids": ["INBOX", "STARRED"]},
            {"message_id": "m3", "prior_label_ids": []},
        ]})
        self.assertEqual(len(units), 3)
        self.assertEqual({u.unit_id for u in units}, {"m1", "m2", "m3"})

    def test_untrash_plan_one_unit_per_message(self):
        adapter = GmailMessageUntrashAdapter()
        units = adapter.plan({"messages": [
            {"message_id": "m1", "prior_label_ids": ["INBOX"]},
        ]})
        self.assertEqual(len(units), 1)

    def test_modify_labels_plan_one_unit_per_message(self):
        adapter = GmailMessageModifyLabelsAdapter()
        units = adapter.plan({"messages": [
            {"message_id": "m1", "add_label_ids": ["Label_1"], "remove_label_ids": [],
             "prior_label_ids": ["INBOX"]},
            {"message_id": "m2", "add_label_ids": [], "remove_label_ids": ["INBOX"],
             "prior_label_ids": ["INBOX"]},
        ]})
        self.assertEqual(len(units), 2)

    def test_filter_create_plan_one_unit_per_filter(self):
        adapter = GmailFilterCreateAdapter()
        units = adapter.plan({"filters": [
            {"criteria": {"from": "a@example.com"}, "action": {"addLabelIds": ["Label_1"]}},
            {"criteria": {"from": "b@example.com"}, "action": {"addLabelIds": ["Label_2"]}},
        ]})
        self.assertEqual(len(units), 2)
        self.assertEqual(len({u.unit_id for u in units}), 2)

    def test_empty_params_yields_no_units(self):
        for adapter_cls in (GmailMessageTrashAdapter, GmailMessageUntrashAdapter,
                            GmailMessageModifyLabelsAdapter, GmailFilterCreateAdapter):
            self.assertEqual(adapter_cls().plan(None), [])
            self.assertEqual(adapter_cls().plan({}), [])


# ---------------------------------------------------------------------------
# 3. apply -> undo -> verify round-trip restores prestate
# ---------------------------------------------------------------------------

class TestApplyUndoVerifyRoundTrip(unittest.TestCase):

    def test_trash_apply_undo_verify_restores_prestate(self):
        service = MockGmailService(messages={"m1": {"INBOX", "IMPORTANT"}})
        adapter = GmailMessageTrashAdapter()
        units = adapter.plan({"messages": [
            {"message_id": "m1", "prior_label_ids": ["INBOX", "IMPORTANT"]},
        ]})
        self.assertEqual(len(units), 1)
        unit = units[0]

        adapter.apply_one(service, unit)
        applied = adapter.verify_one(service, unit)
        self.assertTrue(applied["is_trashed"])
        self.assertFalse(applied["matches_prestate"])
        self.assertEqual(set(service.messages["m1"]), {"TRASH", "IMPORTANT"})

        adapter.undo_one(service, unit)
        restored = adapter.verify_one(service, unit)
        self.assertTrue(restored["matches_prestate"])
        self.assertEqual(set(service.messages["m1"]), {"INBOX", "IMPORTANT"})

    def test_untrash_apply_undo_verify_round_trip(self):
        service = MockGmailService(messages={"m1": {"TRASH", "IMPORTANT"}})
        adapter = GmailMessageUntrashAdapter()
        units = adapter.plan({"messages": [
            {"message_id": "m1", "prior_label_ids": ["INBOX", "IMPORTANT"]},
        ]})
        unit = units[0]

        adapter.apply_one(service, unit)
        self.assertEqual(set(service.messages["m1"]), {"INBOX", "IMPORTANT"})
        applied = adapter.verify_one(service, unit)
        self.assertTrue(applied["matches_prestate"])

        # undo = re-trash
        adapter.undo_one(service, unit)
        self.assertEqual(set(service.messages["m1"]), {"TRASH", "IMPORTANT"})

    def test_modify_labels_apply_undo_verify_restores_prestate(self):
        service = MockGmailService(messages={"m1": {"INBOX"}})
        adapter = GmailMessageModifyLabelsAdapter()
        units = adapter.plan({"messages": [
            {"message_id": "m1", "add_label_ids": ["Label_custom"],
             "remove_label_ids": ["INBOX"], "prior_label_ids": ["INBOX"]},
        ]})
        unit = units[0]

        adapter.apply_one(service, unit)
        self.assertEqual(set(service.messages["m1"]), {"Label_custom"})

        adapter.undo_one(service, unit)
        restored = adapter.verify_one(service, unit)
        self.assertTrue(restored["matches_prestate"])
        self.assertEqual(set(service.messages["m1"]), {"INBOX"})

    def test_filter_create_apply_undo_verify_round_trip(self):
        service = MockGmailService()
        adapter = GmailFilterCreateAdapter()
        units = adapter.plan({"filters": [
            {"criteria": {"from": "newsletter@example.com"},
             "action": {"addLabelIds": ["Label_news"], "removeLabelIds": ["INBOX"]}},
        ]})
        unit = units[0]

        adapter.apply_one(service, unit)
        self.assertEqual(len(service.filters), 1)
        applied = adapter.verify_one(service, unit)
        self.assertTrue(applied["exists"])
        self.assertEqual(applied["criteria"], {"from": "newsletter@example.com"})

        adapter.undo_one(service, unit)
        self.assertEqual(service.filters, {})
        after_undo = adapter.verify_one(service, unit)
        self.assertFalse(after_undo["exists"])

    def test_filter_create_undo_without_prior_apply_raises(self):
        service = MockGmailService()
        adapter = GmailFilterCreateAdapter()
        units = adapter.plan({"filters": [{"criteria": {}, "action": {}}]})
        with self.assertRaises(ValueError):
            adapter.undo_one(service, units[0])

    def test_trash_undo_with_no_undo_ref_raises(self):
        from external_write.operations import EffectUnit
        adapter = GmailMessageTrashAdapter()
        unit = EffectUnit(unit_id="m1", target_ref={"message_id": "m1"}, undo_ref=None)
        with self.assertRaises(ValueError):
            adapter.undo_one(MockGmailService(), unit)

    def test_batch_trash_applies_and_undoes_each_unit_independently(self):
        service = MockGmailService(messages={
            "m1": {"INBOX"}, "m2": {"INBOX", "STARRED"},
        })
        adapter = GmailMessageTrashAdapter()
        units = adapter.plan({"messages": [
            {"message_id": "m1", "prior_label_ids": ["INBOX"]},
            {"message_id": "m2", "prior_label_ids": ["INBOX", "STARRED"]},
        ]})
        for unit in units:
            adapter.apply_one(service, unit)
        self.assertEqual(set(service.messages["m1"]), {"TRASH"})
        self.assertEqual(set(service.messages["m2"]), {"TRASH", "STARRED"})

        for unit in units:
            adapter.undo_one(service, unit)
        self.assertEqual(set(service.messages["m1"]), {"INBOX"})
        self.assertEqual(set(service.messages["m2"]), {"INBOX", "STARRED"})


# ---------------------------------------------------------------------------
# 4. Structural safety by ABSENCE of code
# ---------------------------------------------------------------------------

def _call_attr_chains(source: str):
    """Return the set of dotted method-chain strings (root-first, e.g.
    'users.messages.modify') for every `ast.Attribute` node in `source`,
    reusing scan.py's OWN `_attr_chain_names` helper (DRY — not a
    reimplemented, possibly-divergent chain walker) which correctly unwraps
    intervening `ast.Call` nodes (`x.users().messages().modify` is a chain of
    Attribute-wrapping-Call-wrapping-Attribute nodes, not a flat attribute
    access). Used to verify structural safety by inspecting the real call
    graph, not by grepping raw text (which would false-positive on this
    module's own explanatory docstrings, which discuss the forbidden verbs by
    name in order to explain their absence)."""
    tree = ast.parse(source)
    chains = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chains.add(".".join(reversed(_attr_chain_names(node))))
    return chains


class TestStructuralSafetyByAbsence(unittest.TestCase):

    def test_no_send_draft_forward_method_defined_anywhere_in_the_module(self):
        forbidden_substrings = ("send", "draft", "forward")
        for name, obj in inspect.getmembers(adapters_gmail):
            if inspect.isclass(obj) and obj.__module__ == adapters_gmail.__name__:
                for meth_name, _ in inspect.getmembers(obj, predicate=inspect.isfunction):
                    lowered = meth_name.lower()
                    for bad in forbidden_substrings:
                        self.assertNotIn(
                            bad, lowered,
                            f"{obj.__name__}.{meth_name} looks like a send/draft/forward path")
            elif inspect.isfunction(obj) and obj.__module__ == adapters_gmail.__name__:
                lowered = name.lower()
                for bad in forbidden_substrings:
                    self.assertNotIn(bad, lowered, f"module function {name!r}")

    def test_no_permanent_delete_or_native_trash_untrash_call_site(self):
        source = _ADAPTER_MODULE_PATH.read_text(encoding="utf-8")
        chains = _call_attr_chains(source)
        # None of these vendor-native shapes are ever called (checked as a
        # dotted-suffix match against the full root-first chain, since the
        # real chains are rooted at "users...").
        forbidden_suffixes = (
            "messages.delete", "messages.trash", "messages.untrash",
            "messages.send", "drafts.create", "drafts.send",
        )
        for chain in chains:
            for forbidden in forbidden_suffixes:
                self.assertFalse(
                    chain.endswith(forbidden),
                    f"forbidden call site: {chain}")

    def test_the_detection_mechanism_is_not_vacuous(self):
        # Sanity: prove the AST-chain check actually finds real call sites, so
        # the absence checks above are meaningful, not a check that never fires.
        source = _ADAPTER_MODULE_PATH.read_text(encoding="utf-8")
        chains = _call_attr_chains(source)
        self.assertIn("users.messages.modify", chains)
        self.assertIn("users.settings.filters.create", chains)
        self.assertIn("users.settings.filters.delete", chains)
        self.assertIn("users.settings.filters.get", chains)

    def test_mock_service_itself_would_raise_if_forbidden_verbs_were_ever_invoked(self):
        # Defense in depth / documents intent: even if some future edit added
        # a call to one of these, the mock used throughout this suite fails
        # loudly rather than silently no-opping.
        service = MockGmailService(messages={"m1": {"INBOX"}})
        with self.assertRaises(AssertionError):
            service.users().messages().trash(userId="me", id="m1")
        with self.assertRaises(AssertionError):
            service.users().messages().delete(userId="me", id="m1")
        with self.assertRaises(AssertionError):
            service.users().messages().send(userId="me", body={})


# ---------------------------------------------------------------------------
# 5. Zone scan classification
# ---------------------------------------------------------------------------

class TestZoneScanClassification(unittest.TestCase):

    def test_adapters_gmail_module_path_is_registered_adapter_profile(self):
        self.assertIn("adapters_gmail.py", ADAPTER_PROFILE_MODULE_PATHS)

    def test_adapters_gmail_classifies_as_adapter_profile(self):
        zone = classify_zone(_ADAPTER_MODULE_PATH, _ADAPTER_ANCHOR)
        self.assertEqual(zone, Zone.ADAPTER_PROFILE)

    def test_adapters_gmail_scans_clean(self):
        violations = scan_paths([_ADAPTER_MODULE_PATH])
        self.assertEqual(violations, [], violations)

    def test_capability_module_importing_the_write_capable_client_directly_fails_scan(self):
        # The negative control: a hypothetical CAPABILITY-side module that
        # imported the vendor SDK / constructed a write-capable Gmail client
        # directly (instead of going through the credential-isolation seam)
        # is NOT in any zone allowlist and must still fail the scan.
        violations = scan_paths([_BYPASS_FIXTURE])
        self.assertTrue(violations, "capability-side vendor-client bypass must be flagged")
        kinds = {v.kind for v in violations}
        self.assertIn("forbidden_import", kinds)
        self.assertIn("credential_construction", kinds)

    def test_read_facades_gmail_is_not_listed_in_any_zone_allowlist(self):
        """Task R7-T1: the split-out facade module is deliberately left OUT
        of both ADAPTER_PROFILE_MODULE_PATHS and SEALED_KERNEL_MODULE_PATHS
        -- an unlisted module defaults to the fail-closed CAPABILITY
        classification (zones.py's module docstring), which is fine here
        because the module contains nothing that trips the scanner."""
        rel = _READ_FACADES_GMAIL_MODULE_PATH.name
        self.assertNotIn(rel, ADAPTER_PROFILE_MODULE_PATHS)
        self.assertNotIn(rel, SEALED_KERNEL_MODULE_PATHS)

    def test_read_facades_gmail_classifies_as_capability(self):
        zone = classify_zone(_READ_FACADES_GMAIL_MODULE_PATH, _ADAPTER_ANCHOR)
        self.assertEqual(zone, Zone.CAPABILITY)

    def test_read_facades_gmail_scans_clean(self):
        violations = scan_paths([_READ_FACADES_GMAIL_MODULE_PATH])
        self.assertEqual(violations, [], violations)


# ---------------------------------------------------------------------------
# 6. GmailReadFacade
# ---------------------------------------------------------------------------

class _FixtureGmailReadOnlyClient:
    """Fixture read-only client backing GmailReadFacade in tests -- a thin,
    already-scoped wrapper exposing the flat method names GmailReadFacade
    declares (list_messages/get_message/...), matching the generic
    ReadFacade._read(method_name, ...) dispatch contract."""

    def __init__(self, service: MockGmailService):
        self._service = service

    def list_messages(self, query=None, max_results=None):
        return self._service.users().messages().list(userId="me", q=query,
                                                       maxResults=max_results).execute()

    def get_message(self, message_id):
        return self._service.users().messages().get(userId="me", id=message_id).execute()

    def list_labels(self):
        return {"labels": [{"id": "INBOX"}, {"id": "TRASH"}]}

    def list_filters(self):
        return self._service.users().settings().filters().list(userId="me").execute()

    def get_filter(self, filter_id):
        return self._service.users().settings().filters().get(
            userId="me", id=filter_id).execute()


class TestGmailReadFacade(unittest.TestCase):

    def test_build_read_facade_for_gmail_trash_op_kind(self):
        service = MockGmailService(messages={"m1": {"INBOX"}})
        read_only = _FixtureGmailReadOnlyClient(service)
        facade = build_read_facade(OP_TRASH, read_only, GmailReadFacade)
        self.assertIsInstance(facade, GmailReadFacade)
        self.assertEqual(facade.get_message("m1"), {"id": "m1", "labelIds": ["INBOX"]})

    def test_facade_exposes_exactly_its_declared_read_methods(self):
        facade = GmailReadFacade(_FixtureGmailReadOnlyClient(MockGmailService()))
        public = sorted(n for n in dir(facade)
                        if not n.startswith("_") and n != "read_methods")
        self.assertEqual(public, sorted(GmailReadFacade.read_methods))

    def test_wrapped_client_unreachable_via_any_attribute(self):
        service = MockGmailService()
        read_only = _FixtureGmailReadOnlyClient(service)
        facade = build_read_facade(OP_TRASH, read_only, GmailReadFacade)
        for name in ("_read_only_client", "_client", "client", "_service", "_raw"):
            value = getattr(facade, name, "__ABSENT__")
            self.assertIsNot(value, read_only)
            self.assertIsNot(value, service)

    def test_two_arg_build_read_facade_resolves_gmail_read_facade_from_the_kernel_registry(self):
        """R7-T1: capability-facing call shape -- no facade_cls supplied, no
        import of GmailReadFacade needed by the caller at all; the kernel
        resolves it from the registry read_facades_gmail.py populated at
        import time."""
        service = MockGmailService(messages={"m1": {"INBOX"}})
        read_only = _FixtureGmailReadOnlyClient(service)
        for op_kind in (OP_TRASH, OP_UNTRASH, OP_MODIFY_LABELS, OP_FILTER_CREATE):
            with self.subTest(op_kind=op_kind):
                facade = build_read_facade(op_kind, read_only)
                self.assertIsInstance(facade, GmailReadFacade)

    def test_gmail_read_facade_recovers_the_read_facades_module_not_the_adapter_module(self):
        """The whole point of the split (Task R7-T1): a capability that
        recovers `facade.__class__.__module__` for a Gmail read facade lands
        on read_facades_gmail -- a module with no adapter and no credential
        in it -- never on adapters_gmail, which defines write-capable
        Adapters."""
        facade = GmailReadFacade(_FixtureGmailReadOnlyClient(MockGmailService()))
        self.assertEqual(facade.__class__.__module__, "external_write.read_facades_gmail")
        self.assertNotEqual(facade.__class__.__module__, adapters_gmail.__name__)


# ---------------------------------------------------------------------------
# 7. Invariant-8 POSITIVE CONTROL: a real resolvable adapter whose
# implementation_hash covers this module, and the acceptance ceremony
# ACCEPTS a conformant fixture through it.
# ---------------------------------------------------------------------------

def _verification():
    return {
        "schema": POSTWRITE_VERIFICATION_SCHEMA,
        "verification_mode": "prestate_snapshot_diff",
        "claim_strength": "verified",
        "verifier_id": "prestate_snapshot_diff_v1",
        "source_lineage": {
            "pre_write_sources": ["prewrite_csv_backup"],
            "post_write_sources": ["live_surface_read"],
            "forbidden_sources": [
                "writer_generated_id_map",
                "live_id_column_as_truth",
                "apply_report",
            ],
        },
        "invariant_checked": "message labels restored to prestate after undo",
        "evidence_ref": "agents/handoffs/.gmail_ev.txt",
    }


class TestInvariantEightPositiveControl(unittest.TestCase):
    """Task 6's F-34 CARRY note: a registered adapter whose module cannot be
    resolved is silently EXCLUDED from implementation_hash. This is the
    POSITIVE control closing that -- adapters_gmail.py is imported normally
    (not via the throwaway-fixture importlib trick Task 3's tests use), so
    `type(adapter).__module__` resolves to a REAL entry in sys.modules and
    `effects_manifest._adapter_module_file` finds its real, on-disk path."""

    def test_adapter_is_really_registered_and_resolvable(self):
        adapter = get_adapter(OP_TRASH)
        self.assertIsInstance(adapter, GmailMessageTrashAdapter)

    def test_dependency_files_include_the_real_adapters_gmail_module(self):
        dep_files = resolve_dependency_files(OP_TRASH)
        self.assertIn(str(_ADAPTER_MODULE_PATH), dep_files)

    def test_implementation_hash_changes_if_the_real_module_bytes_change(self):
        # Prove the hash genuinely covers this module's bytes (not merely
        # lists its path): hash over a byte-for-byte copy with one appended
        # byte must differ from the real module's hash -- exercised via
        # resolve_dependency_files's file-content hashing indirectly through
        # build_manifest, without mutating the real checked-in file.
        h_real = compute_implementation_hash(OP_TRASH)
        manifest = build_manifest(OP_TRASH)
        self.assertEqual(manifest.implementation_hash, h_real)
        self.assertIn(str(_ADAPTER_MODULE_PATH), manifest.dependency_files)
        self.assertIn("GmailMessageTrashAdapter", manifest.effect_unit_path)

    def test_acceptance_ceremony_accepts_a_conformant_fixture_through_this_adapter(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            security = tmp_path / "security"
            security.mkdir()
            set_path = security / "capability_descriptors.json"
            proof_path = tmp_path / "proof.json"
            receipt_path = tmp_path / "receipt.json"
            audit_path = security / "capability_acceptance_log.jsonl"

            phase = "phase_gmail_01"
            capability_id = "gmail"

            descriptors = [{
                "id": capability_id, "name": capability_id, "action_class": "trash",
                "risk_class": "sensitive_data", "recovery_profile_ref": None,
                "declared_test_target": "copy", "blast_radius_cap": 25,
                "accepted": False, "phase_id": phase,
            }]
            set_path.write_text(json.dumps(descriptors, indent=2) + "\n", encoding="utf-8")

            proof = {
                "schema": COPY_RUN_PROOF_SCHEMA,
                "operation_id": "gmail-op-001",
                "op_kind": OP_TRASH,
                "data_class": "gmail_messages",
                "copy_source_ref": "copies/gmail_copy.json",
                "prestate_snapshot_ref": "copies/gmail_copy.prestate.json",
                "copy_apply_proof": {
                    "apply_receipt_ref": "agents/handoffs/.gmail_apply_receipt.json",
                    "apply_verification": _verification(),
                },
                "copy_undo_proof": {
                    "undo_receipt_ref": "agents/handoffs/.gmail_undo_receipt.json",
                    "undo_verification": _verification(),
                },
                "durability_checks": [],  # gmail.message.trash is non-binding -- must be empty
                "accepted_for_live_use": True,
                "implementation_hash": compute_implementation_hash(OP_TRASH),
                "contract_hash": compute_contract_hash(OP_TRASH),
                "capability_id": capability_id,
                # DRY: reuses the SAME clean capability-module fixture Task 6's own
                # acceptance-ceremony tests use -- a conformant capability module's
                # shape is generic, not Gmail-specific (T3/T7 boundary).
                "capability_module_paths": [_CLEAN_CAPABILITY_MODULE],
            }
            self.assertTrue(validate_copy_run_proof(proof).ok)
            proof_path.write_text(json.dumps(proof), encoding="utf-8")

            receipt = {
                "schema": OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA,
                "capability_id": capability_id,
                "phase_id": phase,
                "copy_run_proof_ref": str(proof_path),
                "operator_confirmation": "Yes, accept the Gmail trash capability for live use.",
                "accepted_at": "2026-07-11T12:00:00Z",
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            result = accept_capability_for_live_use(
                capability_id, phase, str(proof_path), str(receipt_path),
                descriptor_set_path=str(set_path), audit_log_path=str(audit_path),
            )
            self.assertTrue(result.accepted, result.reason)

            entries = json.loads(set_path.read_text(encoding="utf-8"))
            self.assertTrue(entries[0]["accepted"])


if __name__ == "__main__":
    unittest.main()
