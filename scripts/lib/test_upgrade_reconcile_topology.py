"""Attribution must come from the declaration join, not from a filename
convention. Run:
  python3 -m unittest discover -s wizard/scripts/lib -p test_upgrade_reconcile_topology.py
"""
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

import upgrade_reconcile


class AdapterAttributionByDeclarationTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.lib = self.root / "agents" / "lib" / "external_write"
        self.lib.mkdir(parents=True)
        caps = self.root / "agents" / "capabilities"
        caps.mkdir(parents=True)
        (caps / "inbox_management_capability.py").write_text(
            'OP_KIND = "inbox.labels.modify"\n', encoding="utf-8")
        # Filename deliberately does NOT match the canonical id.
        (self.lib / "adapters_inbox.py").write_text(
            'OP_KIND = "inbox.labels.modify"\n'
            'class InboxLabelsAdapter: pass\n'
            'register_adapter(OP_KIND, InboxLabelsAdapter())\n',
            encoding="utf-8")

    def test_capability_scoped_attribution_uses_the_CAPABILITY_id(self):
        attribution = upgrade_reconcile.attribute_adapter_to_capability(
            self.root, "agents/lib/external_write/adapters_inbox.py")
        self.assertEqual(attribution, "inbox_management",
                         "attribution must join on op_kind, not on the filename")

    def test_canonical_by_relpath_no_longer_exists(self):
        src = Path(upgrade_reconcile.__file__).read_text(encoding="utf-8")
        self.assertNotIn("canonical_by_relpath", src)

    def test_no_matching_capability_returns_none_not_a_guess(self):
        # An adapter that registers an op_kind no capability declares serves
        # no capability -- None is the honest answer, never a fallback guess
        # dressed up as a capability id.
        (self.lib / "adapters_orphan.py").write_text(
            'OP_KIND = "orphan.op.nothing_declares_this"\n'
            'class OrphanAdapter: pass\n'
            'register_adapter(OP_KIND, OrphanAdapter())\n',
            encoding="utf-8")
        attribution = upgrade_reconcile.attribute_adapter_to_capability(
            self.root, "agents/lib/external_write/adapters_orphan.py")
        self.assertIsNone(attribution)

    def test_resolvable_adapter_op_kind_does_not_false_match_an_unreadable_capability(self):
        # Genuinely exercises the CAPABILITY-side filter (not the adapter-side
        # early return): the adapter's own op_kind resolves cleanly, so this
        # reaches the capability scan loop. The only capability present has
        # an OP_KIND this checker cannot read (nested inside a function --
        # _extract_op_kind_literal is module-level-only by design and reports
        # no literal at all, never guesses at the nested one). A resolvable
        # op_kind on one side must not spuriously "match" an unreadable
        # declaration on the other just because neither is a normal miss.
        (self.root / "agents" / "capabilities" / "unreadable_capability.py").write_text(
            "def f():\n    OP_KIND = 'some.op'\n", encoding="utf-8")
        (self.lib / "adapters_resolvable.py").write_text(
            'OP_KIND = "some.op"\n'
            'class ResolvableAdapter: pass\n'
            'register_adapter(OP_KIND, ResolvableAdapter())\n',
            encoding="utf-8")
        attribution = upgrade_reconcile.attribute_adapter_to_capability(
            self.root, "agents/lib/external_write/adapters_resolvable.py")
        self.assertIsNone(attribution)


class AdapterAttributionUnresolvedRaisesTests(unittest.TestCase):
    """"We do not know what this adapter provides" must never collapse into
    the same ``None`` as "it provides nothing a capability needs" -- the two
    are different facts, and treating them the same is how a wrong id gets
    keyed in place of an honest report."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.lib = self.root / "agents" / "lib" / "external_write"
        self.lib.mkdir(parents=True)
        (self.root / "agents" / "capabilities").mkdir(parents=True)

    def test_nested_registration_raises_naming_the_file_and_line(self):
        # A hand-authored shape ordinary operator code actually uses: the
        # registration call sits inside a function body, one structural
        # level away from the module top -- exactly the shape topology.py
        # reports rather than drops.
        (self.lib / "adapters_nested.py").write_text(
            "class NestedAdapter: pass\n"
            "def setup():\n"
            "    register_adapter('some.op', NestedAdapter())\n",
            encoding="utf-8")
        with self.assertRaises(upgrade_reconcile.AdapterAttributionUnresolvedError) as ctx:
            upgrade_reconcile.attribute_adapter_to_capability(
                self.root, "agents/lib/external_write/adapters_nested.py")
        self.assertEqual(len(ctx.exception.reasons), 1)
        self.assertIn("adapters_nested.py", ctx.exception.reasons[0])
        self.assertIn("line", ctx.exception.reasons[0])

    def test_function_call_op_kind_raises_rather_than_matching_nothing(self):
        # A second ordinary hand-authored shape: the op_kind argument is a
        # function call's return value, not a literal or a module-level
        # constant -- topology cannot fold it, so it reports the call site
        # rather than guessing.
        (self.lib / "adapters_dynamic.py").write_text(
            "def _op_kind():\n    return 'crm.contacts.update'\n\n"
            "class DynamicAdapter: pass\n\n"
            "register_adapter(_op_kind(), DynamicAdapter())\n",
            encoding="utf-8")
        with self.assertRaises(upgrade_reconcile.AdapterAttributionUnresolvedError):
            upgrade_reconcile.attribute_adapter_to_capability(
                self.root, "agents/lib/external_write/adapters_dynamic.py")

    def test_inaccessible_capabilities_directory_raises_not_none(self):
        # Fail-closed filesystem check, distinguishing ABSENT (a clean,
        # trustworthy empty scan) from INACCESSIBLE (a permission problem --
        # Path.glob silently swallows this, which is exactly the bug this
        # check must not reproduce).
        (self.lib / "adapters_clean.py").write_text(
            'OP_KIND = "clean.op"\n'
            'class CleanAdapter: pass\n'
            'register_adapter(OP_KIND, CleanAdapter())\n',
            encoding="utf-8")
        caps_dir = self.root / "agents" / "capabilities"
        os.chmod(caps_dir, 0)
        self.addCleanup(os.chmod, caps_dir, stat.S_IRWXU)
        with self.assertRaises(upgrade_reconcile.AdapterAttributionUnresolvedError) as ctx:
            upgrade_reconcile.attribute_adapter_to_capability(
                self.root, "agents/lib/external_write/adapters_clean.py")
        self.assertIn("capabilities", ctx.exception.reasons[0])

    def test_absent_capabilities_directory_is_a_clean_none_not_an_error(self):
        # The companion case to the previous test: ABSENT is not
        # INACCESSIBLE. Most projects have no capabilities yet -- that must
        # stay a legitimate, quiet None, never an error.
        shutil.rmtree(self.root / "agents" / "capabilities")
        (self.lib / "adapters_clean.py").write_text(
            'OP_KIND = "clean.op"\n'
            'class CleanAdapter: pass\n'
            'register_adapter(OP_KIND, CleanAdapter())\n',
            encoding="utf-8")
        attribution = upgrade_reconcile.attribute_adapter_to_capability(
            self.root, "agents/lib/external_write/adapters_clean.py")
        self.assertIsNone(attribution)

    def test_unreadable_capability_file_raises_not_a_silent_miss(self):
        (self.lib / "adapters_clean.py").write_text(
            'OP_KIND = "clean.op"\n'
            'class CleanAdapter: pass\n'
            'register_adapter(OP_KIND, CleanAdapter())\n',
            encoding="utf-8")
        cap_path = self.root / "agents" / "capabilities" / "locked_capability.py"
        cap_path.write_text('OP_KIND = "clean.op"\n', encoding="utf-8")
        os.chmod(cap_path, 0)
        self.addCleanup(os.chmod, cap_path, stat.S_IRUSR | stat.S_IWUSR)
        with self.assertRaises(upgrade_reconcile.AdapterAttributionUnresolvedError) as ctx:
            upgrade_reconcile.attribute_adapter_to_capability(
                self.root, "agents/lib/external_write/adapters_clean.py")
        self.assertIn("locked_capability.py", ctx.exception.reasons[0])


class ReconcileReportsAndContainsUnresolvedAttributionTests(unittest.TestCase):
    """End-to-end proof through the real ``reconcile_adapter_migrations``:
    a filename-CONFORMANT adapter whose registration is statically
    unreadable must land a durable, operator-visible repair record naming
    the file -- and must NEVER key a capability-scoped queue entry on its
    own filename stem, the exact regression this guards."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.build_repo_root = Path(__file__).resolve().parents[3]

    def test_unreadable_registration_files_a_repair_record_not_a_wrong_id(self):
        caps = self.root / "agents" / "capabilities"
        caps.mkdir(parents=True)
        (caps / "crm_contact_sync_capability.py").write_text(
            'OP_KIND = "crm.contacts.update"\n', encoding="utf-8")

        ext_dir = self.root / "agents" / "lib" / "external_write"
        ext_dir.mkdir(parents=True)
        # Filename IS conformant with the capability id -- this is the exact
        # shape where the old filename convention would have gotten the
        # right answer for the wrong reason. The registration itself is
        # unreadable (op_kind built by string formatting), which must be
        # reported honestly rather than papered over by the filename.
        (ext_dir / "adapters_crm_contact_sync.py").write_text(
            "SURFACE = 'crm'\n"
            "class CrmContactSyncAdapter: pass\n\n"
            "register_adapter(f\"{SURFACE}.contacts.update\", CrmContactSyncAdapter())\n",
            encoding="utf-8")
        (ext_dir / "operator_adapters.json").write_text(
            json.dumps(["adapters_crm_contact_sync"]), encoding="utf-8")

        remediated, outcomes, blocking = upgrade_reconcile.reconcile_adapter_migrations(
            self.root, self.build_repo_root, from_version="1.0.0", to_version="1.1.0")

        self.assertIsNone(blocking)
        # Contained: no capability-scoped remediation was attempted against
        # an unresolved identity.
        self.assertEqual(remediated, [])

        queue_path = self.root / upgrade_reconcile.MIGRATION_QUEUE_REL
        queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
        kinds = {e.get("kind") for e in queue}
        self.assertNotIn("missing_evidence_predicates", kinds)
        self.assertNotIn("ambiguous_adapter_registration", kinds)

        entry = next(e for e in queue if e.get("kind") == "adapter_registration_unresolved")
        self.assertEqual(entry["writer_relpath"],
                         "agents/lib/external_write/adapters_crm_contact_sync.py")
        self.assertNotEqual(entry["mechanism_id"], "crm_contact_sync",
                            "must never be presented as if it were a resolved capability id")
        self.assertIn("adapters_crm_contact_sync.py", entry["reason"])
        self.assertNotIn("Traceback", entry["reason"])
        self.assertEqual(entry["status"], "pending")


if __name__ == "__main__":
    unittest.main()
