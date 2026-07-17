"""Tests for the emitted capability-identity module
(external_write.capability_identity — Task A1 / A3.2).

Why this exists
----------------
A capability's identity was found split across four names in the field:
descriptor id (``security/capability_descriptors.json``), mechanism id
(``agents/handoffs/pending_migrations.json``), module stem
(``agents/capabilities/<capability_id>_capability.py``), and surface (the
external SYSTEM the capability talks to, e.g. ``acme_crm``). This module
gives ONE canonical identity — the module-derived ``capability_id`` — that
every lifecycle consumer (migration-close, health, pause markers) can
resolve any of those four names TO, fail-closed: an alias that resolves to
more than one canonical, or to none at all, must never be silently guessed.

``surface`` is deliberately EXCLUDED from identity equality: it is the
external system's own identifier and MAY be shared by two distinct
capabilities (e.g. ``gmail_label`` and ``gmail_archive`` both talk to
``gmail``). It is preserved on ``CapabilityIdentity`` as a field, but
resolving a shared surface must fail closed as ambiguous rather than ever
guess which capability it means.

ANTI-OVERFIT (v0.13.0 T7 lesson, reused here per the task brief): every
fixture is written at the REAL emitted relative path
(``agents/capabilities/<capability_id>_capability.py``,
``security/capability_descriptors.json``,
``agents/handoffs/pending_migrations.json``) inside a fresh
``tempfile.TemporaryDirectory()`` — never a ``copytree`` of the dev tree.
At least two distinct capability_ids are exercised.

The module under test is loaded via ``importlib.util`` directly from its
real emitted path (not a package import) per the task brief's own test
harness — this also means the module must be import-clean when loaded
standalone (stdlib only, no relative-package requirement).
"""

import json
import tempfile
import unittest
from pathlib import Path
import importlib.util


def _load(mod_path):
    spec = importlib.util.spec_from_file_location("capability_identity", mod_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


MODPATH = str(Path(__file__).resolve().parents[2] / "agents/lib/external_write/capability_identity.py")


def _write_capability(root, cap_id, surface):
    d = Path(root) / "agents/capabilities"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cap_id}_capability.py").write_text(f'SURFACE = "{surface}"\n# capability {cap_id}\n', encoding="utf-8")


def _write_capability_without_surface(root, cap_id):
    d = Path(root) / "agents/capabilities"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cap_id}_capability.py").write_text(f'# capability {cap_id}, no SURFACE declared\n', encoding="utf-8")


def _write_descriptors(root, entries):
    d = Path(root) / "security"
    d.mkdir(parents=True, exist_ok=True)
    (d / "capability_descriptors.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _write_pending_migrations(root, entries):
    d = Path(root) / "agents/handoffs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pending_migrations.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")


class TestCapabilityIndex(unittest.TestCase):
    def test_estate_three_way_split_resolves_to_module_canonical(self):
        # The estate case: module/canonical = inbox_management; descriptor id + surface = inbox-labels.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            _write_descriptors(root, [{"id": "inbox-labels", "name": "Inbox", "risk_class": "sensitive_data"}])
            idx = ci.build_capability_index(root)
            got = idx.resolve("inbox-labels", "descriptor_id")
            self.assertEqual(got.canonical_id, "inbox_management")
            self.assertEqual(got.surface, "inbox-labels")   # surface preserved, NOT the identity
            self.assertIn("inbox-labels", got.aliases)

    def test_surface_shared_across_two_capabilities_is_not_identity(self):
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "gmail_label", "gmail")
            _write_capability(root, "gmail_archive", "gmail")   # same surface, distinct identities
            _write_descriptors(root, [{"id": "gmail_label"}, {"id": "gmail_archive"}])
            idx = ci.build_capability_index(root)
            self.assertEqual(idx.resolve("gmail_label", "descriptor_id").canonical_id, "gmail_label")
            # surface 'gmail' is ambiguous as an identity token -> fail-closed, never a wrong guess
            with self.assertRaises(ci.IdentityResolutionError) as cm:
                idx.resolve("gmail", "surface")
            self.assertEqual(cm.exception.kind, "ambiguous")

    def test_unresolved_is_failclosed_with_operator_message(self):
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            _write_descriptors(root, [{"id": "inbox-labels"}])
            idx = ci.build_capability_index(root)
            with self.assertRaises(ci.IdentityResolutionError) as cm:
                idx.resolve("does_not_exist", "mechanism_id")
            self.assertEqual(cm.exception.kind, "unresolved")
            self.assertTrue(cm.exception.operator_message)          # plain-language, present
            self.assertNotIn("Traceback", cm.exception.operator_message)

    # --- additional edge cases beyond the brief's starting RED set ---

    def test_module_stem_namespace_resolves_directly(self):
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            _write_descriptors(root, [{"id": "inbox-labels"}])
            idx = ci.build_capability_index(root)
            got = idx.resolve("inbox_management", "module_stem")
            self.assertEqual(got.canonical_id, "inbox_management")
            self.assertEqual(got.module_stem, "inbox_management")

    def test_mechanism_id_alias_resolves_via_pending_migrations(self):
        # Three-way link: module/canonical = inbox_management; descriptor id +
        # surface = inbox-labels; the migration queue carries a THIRD historical
        # name (mechanism_id) for the same capability.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            _write_descriptors(root, [{"id": "inbox-labels"}])
            _write_pending_migrations(root, [{"mechanism_id": "inbox_labels_legacy"}])
            idx = ci.build_capability_index(root)
            got = idx.resolve("inbox_labels_legacy", "mechanism_id")
            self.assertEqual(got.canonical_id, "inbox_management")
            self.assertIn("inbox_labels_legacy", got.aliases)

    def test_unknown_namespace_resolves_across_all_namespaces(self):
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            _write_descriptors(root, [{"id": "inbox-labels"}])
            _write_pending_migrations(root, [{"mechanism_id": "inbox_labels_legacy"}])
            idx = ci.build_capability_index(root)
            # Caller doesn't know which namespace "inbox_labels_legacy" (a
            # mechanism_id) came from -- "unknown" must still resolve it
            # unambiguously since it only appears in one namespace's map.
            got = idx.resolve("inbox_labels_legacy", "unknown")
            self.assertEqual(got.canonical_id, "inbox_management")

    def test_capability_without_surface_constant_has_none_surface(self):
        # A legacy capability module predating the SURFACE convention must
        # not crash AST extraction -- it simply has no surface on record.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability_without_surface(root, "legacy_task_sync")
            _write_descriptors(root, [{"id": "legacy_task_sync"}])
            idx = ci.build_capability_index(root)
            got = idx.resolve("legacy_task_sync", "module_stem")
            self.assertIsNone(got.surface)

    def test_unresolved_surface_namespace_also_failcloses(self):
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            _write_descriptors(root, [{"id": "inbox-labels"}])
            idx = ci.build_capability_index(root)
            with self.assertRaises(ci.IdentityResolutionError) as cm:
                idx.resolve("no-such-surface", "surface")
            self.assertEqual(cm.exception.kind, "unresolved")

    # --- coordinator review fixes ---

    def test_unrelated_stale_descriptor_does_not_ride_single_canonical_shortcut(self):
        # CRITICAL regression (review finding): with only ONE capability in
        # the project, the single-canonical fallback previously fired for
        # EVERY unmatched descriptor id -- including one that has nothing to
        # do with this capability at all. A genuinely-unrelated/stale
        # descriptor entry must never be silently attributed to the sole
        # capability just because it's the only one that exists.
        #
        # "inbox-labels" IS genuinely this capability's own alias (it is the
        # module's own declared SURFACE too, an exact cross-reference) and
        # must still resolve; "totally_unrelated_stale_descriptor" matches
        # nothing at all (not the module stem, not the declared surface) and
        # must stay unresolved rather than being swept up by "there's only
        # one capability so it must mean that one".
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            _write_descriptors(root, [
                {"id": "inbox-labels"},
                {"id": "totally_unrelated_stale_descriptor"},
            ])
            idx = ci.build_capability_index(root)
            got = idx.resolve("inbox-labels", "descriptor_id")
            self.assertEqual(got.canonical_id, "inbox_management")
            with self.assertRaises(ci.IdentityResolutionError) as cm:
                idx.resolve("totally_unrelated_stale_descriptor", "descriptor_id")
            self.assertEqual(cm.exception.kind, "unresolved")

    def test_malformed_descriptor_file_sets_state_read_error_and_says_so(self):
        # IMPORTANT (review finding): a present-but-corrupted descriptor file
        # must not be silently treated the same as an absent one -- an
        # operator told "does not exist" when the truth is "a state file is
        # broken" would be misdirected toward the wrong remedy (recreating
        # the capability) instead of the right one (repairing the file).
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            sec_dir = Path(root) / "security"
            sec_dir.mkdir(parents=True, exist_ok=True)
            (sec_dir / "capability_descriptors.json").write_text(
                "{ this is not valid json", encoding="utf-8")
            idx = ci.build_capability_index(root)
            self.assertTrue(idx.state_read_error)
            with self.assertRaises(ci.IdentityResolutionError) as cm:
                idx.resolve("inbox-labels", "descriptor_id")
            self.assertEqual(cm.exception.kind, "unresolved")
            msg = cm.exception.operator_message
            self.assertNotIn("Traceback", msg)
            # Must NOT claim non-existence as fact (the plain "not found"
            # wording used when there is no read error) -- it may still
            # explicitly DISCLAIM that reading, e.g. "this is NOT a
            # confirmation that X does not exist", which is the opposite of
            # asserting it.
            self.assertNotIn("was not found among", msg.lower())
            self.assertTrue(
                "could not be read" in msg.lower() or "corrupted" in msg.lower()
                or "could not verify" in msg.lower(),
                msg,
            )

    def test_absent_descriptor_file_is_normal_not_state_read_error(self):
        # Absent is NOT the same as unreadable/malformed -- a project that
        # simply has no descriptor file yet must not report state_read_error.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            idx = ci.build_capability_index(root)
            self.assertFalse(idx.state_read_error)


if __name__ == "__main__":
    unittest.main()
