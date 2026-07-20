"""Tests for the Task C1 (Cut 1.1 Cluster C / F-78) command manifest --
`agents/lib/external_write/command_manifest.py`.

Covers:
  * CommandEntry construction validates command_class and the
    live_write<->writes_external agreement.
  * is_allowlist_eligible is the by-construction predicate: a live_write
    command is NEVER eligible, regardless of what writes_external says on a
    duck-typed entry that bypasses CommandEntry's own guard; a
    writes_external=True command is never eligible regardless of class.
  * The baseline manifest classifies bulk-review / capability_invariants /
    bulk-verify as read_only + allowlist-eligible, and
    "bulk-apply --target live" as live_write + NOT eligible.
  * allowlist_eligible_prefixes / manifest_as_dicts derive from the same
    entries and the same predicate -- never a second, independently
    -maintained eligibility list.
"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import command_manifest as cm  # noqa: E402
from external_write.command_manifest import (  # noqa: E402
    BASELINE_COMMANDS,
    CommandEntry,
    CommandManifestError,
    LIVE_WRITE,
    READ_ONLY,
    READ_ONLY_PII,
    allowlist_eligible_prefixes,
    find_command,
    is_allowlist_eligible,
    manifest_as_dicts,
)


class TestCommandEntryConstruction(unittest.TestCase):
    def test_valid_read_only_entry_constructs(self):
        entry = CommandEntry(
            name="x", command_prefix="python3 x.py", command_class=READ_ONLY,
            writes_external=False,
        )
        self.assertEqual(entry.command_class, READ_ONLY)

    def test_valid_read_only_pii_entry_constructs(self):
        entry = CommandEntry(
            name="x", command_prefix="python3 x.py", command_class=READ_ONLY_PII,
            writes_external=False,
        )
        self.assertEqual(entry.command_class, READ_ONLY_PII)

    def test_valid_live_write_entry_constructs(self):
        entry = CommandEntry(
            name="x", command_prefix="python3 x.py", command_class=LIVE_WRITE,
            writes_external=True,
        )
        self.assertEqual(entry.command_class, LIVE_WRITE)

    def test_unrecognized_class_raises(self):
        with self.assertRaises(CommandManifestError):
            CommandEntry(
                name="x", command_prefix="python3 x.py", command_class="not_a_real_class",
                writes_external=False,
            )

    def test_live_write_with_writes_external_false_raises(self):
        # The two fields must agree at construction time -- a live_write entry
        # that does not also declare writes_external=True is an authoring bug,
        # caught here rather than shipped silently.
        with self.assertRaises(CommandManifestError):
            CommandEntry(
                name="x", command_prefix="python3 x.py", command_class=LIVE_WRITE,
                writes_external=False,
            )

    def test_read_only_with_writes_external_true_is_not_rejected_at_construction(self):
        # Deliberately NOT guarded at construction (only the live_write<->True
        # direction is) -- is_allowlist_eligible below is what must still deny
        # eligibility for this shape; see TestIsAllowlistEligibleByConstruction.
        entry = CommandEntry(
            name="x", command_prefix="python3 x.py", command_class=READ_ONLY,
            writes_external=True,
        )
        self.assertTrue(entry.writes_external)


class TestIsAllowlistEligibleByConstruction(unittest.TestCase):
    """The eligibility predicate itself must deny a live-write command no
    matter how the entry got constructed -- proves "you cannot mark a
    live-write command allowlist-eligible" is a property of the PREDICATE,
    not merely of well-behaved manifest authoring."""

    def test_read_only_not_writing_external_is_eligible(self):
        entry = CommandEntry(
            name="x", command_prefix="p", command_class=READ_ONLY, writes_external=False,
        )
        self.assertTrue(is_allowlist_eligible(entry))

    def test_read_only_pii_not_writing_external_is_eligible(self):
        entry = CommandEntry(
            name="x", command_prefix="p", command_class=READ_ONLY_PII, writes_external=False,
        )
        self.assertTrue(is_allowlist_eligible(entry))

    def test_live_write_is_never_eligible(self):
        entry = CommandEntry(
            name="x", command_prefix="p", command_class=LIVE_WRITE, writes_external=True,
        )
        self.assertFalse(is_allowlist_eligible(entry))

    def test_duck_typed_live_write_with_false_writes_external_is_still_ineligible(self):
        # This exact combination cannot be constructed as a real CommandEntry
        # (see test_live_write_with_writes_external_false_raises above) -- but
        # the predicate must independently deny it too, for any object that
        # merely LOOKS like an entry (e.g. one built by a future consumer that
        # does not route through CommandEntry at all). class alone is enough
        # to deny eligibility here, regardless of writes_external's value.
        fake_entry = SimpleNamespace(command_class=LIVE_WRITE, writes_external=False)
        self.assertFalse(is_allowlist_eligible(fake_entry))

    def test_duck_typed_mislabeled_read_only_that_writes_external_is_ineligible(self):
        # The reverse mislabeling: command_class says read_only but
        # writes_external is honestly True. writes_external alone is enough to
        # deny eligibility here, regardless of the (wrong) class.
        fake_entry = SimpleNamespace(command_class=READ_ONLY, writes_external=True)
        self.assertFalse(is_allowlist_eligible(fake_entry))

    def test_duck_typed_unknown_class_is_ineligible(self):
        fake_entry = SimpleNamespace(command_class="something_else", writes_external=False)
        self.assertFalse(is_allowlist_eligible(fake_entry))


class TestBaselineManifestClassification(unittest.TestCase):
    """The plan's own test intent: bulk-review / capability_invariants /
    bulk-verify classify read-only + allowlist-eligible; bulk-apply --target
    live classifies live_write + NOT eligible."""

    def test_capability_invariants_is_read_only_and_eligible(self):
        entry = find_command("capability_invariants")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.command_class, READ_ONLY)
        self.assertFalse(entry.writes_external)
        self.assertTrue(is_allowlist_eligible(entry))

    def test_bulk_review_is_read_only_and_eligible(self):
        entry = find_command("bulk-review")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.command_class, READ_ONLY)
        self.assertFalse(entry.writes_external)
        self.assertTrue(is_allowlist_eligible(entry))

    def test_bulk_verify_is_read_only_and_eligible(self):
        entry = find_command("bulk-verify")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.command_class, READ_ONLY)
        self.assertFalse(entry.writes_external)
        self.assertTrue(is_allowlist_eligible(entry))

    def test_bulk_apply_target_live_is_live_write_and_not_eligible(self):
        entry = find_command("bulk-apply --target live")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.command_class, LIVE_WRITE)
        self.assertTrue(entry.writes_external)
        self.assertFalse(is_allowlist_eligible(entry))

    def test_capability_health_is_read_only_and_eligible(self):
        entry = find_command("capability_health")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.command_class, READ_ONLY)
        self.assertTrue(is_allowlist_eligible(entry))

    def test_unknown_command_name_returns_none(self):
        self.assertIsNone(find_command("this-command-does-not-exist"))

    def test_no_duplicate_names_in_baseline(self):
        names = [entry.name for entry in BASELINE_COMMANDS]
        self.assertEqual(len(names), len(set(names)), f"duplicate names in {names!r}")

    def test_every_baseline_entry_constructs_without_error(self):
        # BASELINE_COMMANDS is built at import time -- if any entry violated
        # CommandEntry.__post_init__'s guard, importing this module would
        # already have raised. This test just pins that the module DID import
        # and the tuple is non-empty and fully typed.
        self.assertTrue(len(BASELINE_COMMANDS) >= 5)
        for entry in BASELINE_COMMANDS:
            self.assertIsInstance(entry, CommandEntry)


class TestAllowlistEligiblePrefixes(unittest.TestCase):
    def test_contains_every_known_read_only_prefix(self):
        prefixes = allowlist_eligible_prefixes()
        for name in ("capability_invariants", "capability_health", "bulk-review", "bulk-verify"):
            entry = find_command(name)
            self.assertIn(entry.command_prefix, prefixes)

    def test_never_contains_the_live_write_prefix(self):
        prefixes = allowlist_eligible_prefixes()
        live_entry = find_command("bulk-apply --target live")
        self.assertNotIn(live_entry.command_prefix, prefixes)

    def test_prefix_count_matches_read_only_entry_count(self):
        eligible_count = sum(1 for e in BASELINE_COMMANDS if is_allowlist_eligible(e))
        self.assertEqual(len(allowlist_eligible_prefixes()), eligible_count)


class TestManifestAsDicts(unittest.TestCase):
    def test_round_trips_through_json(self):
        dicts = manifest_as_dicts()
        # Must be plain-JSON-serializable (Task C2's .sh hook shells to
        # python3 and expects a json.dumps()-able result).
        raw = json.dumps(dicts)
        reloaded = json.loads(raw)
        self.assertEqual(reloaded, dicts)

    def test_dict_keys_match_locked_design_field_names(self):
        dicts = manifest_as_dicts()
        self.assertTrue(dicts)
        for d in dicts:
            self.assertIn("class", d)
            self.assertIn("writes_external", d)
            self.assertIn("allowed_outputs", d)
            self.assertIsInstance(d["allowed_outputs"], list)

    def test_live_write_entry_reports_allowlist_eligible_false(self):
        dicts = manifest_as_dicts()
        live = next(d for d in dicts if d["name"] == "bulk-apply --target live")
        self.assertEqual(live["class"], LIVE_WRITE)
        self.assertTrue(live["writes_external"])
        self.assertFalse(live["allowlist_eligible"])

    def test_read_only_entries_report_allowlist_eligible_true(self):
        dicts = manifest_as_dicts()
        for name in ("capability_invariants", "capability_health", "bulk-review", "bulk-verify"):
            entry_dict = next(d for d in dicts if d["name"] == name)
            self.assertTrue(entry_dict["allowlist_eligible"], f"{name} should be eligible")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
