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

    def test_mechanism_id_with_no_corroboration_stays_unresolved(self):
        # (Coordinator review, round 2, CRITICAL fix) This test previously asserted that a
        # THIRD, unrelated historical name ("inbox_labels_legacy" -- not the module stem, not
        # the descriptor id, not the declared SURFACE) resolved to inbox_management purely
        # because it was the project's only unmatched mechanism_id and its only capability.
        # That was the sole-candidate cardinality GUESS this review removed: an id with zero
        # corroborating evidence must stay unresolved no matter how few capabilities exist.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            _write_descriptors(root, [{"id": "inbox-labels"}])
            _write_pending_migrations(root, [{"mechanism_id": "inbox_labels_legacy"}])
            idx = ci.build_capability_index(root)
            with self.assertRaises(ci.IdentityResolutionError) as cm:
                idx.resolve("inbox_labels_legacy", "mechanism_id")
            self.assertEqual(cm.exception.kind, "unresolved")

    def test_unknown_namespace_resolves_across_all_namespaces(self):
        # A mechanism_id that carries genuine corroboration (here: it equals
        # inbox_management's own declared SURFACE) must resolve via "unknown" even though the
        # caller doesn't know it came from the mechanism_id namespace specifically -- "unknown"
        # searches module_stem, then descriptor_id/mechanism_id, then surface, in that order.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            _write_descriptors(root, [{"id": "inbox-labels"}])
            _write_pending_migrations(root, [{"mechanism_id": "inbox-labels"}])
            idx = ci.build_capability_index(root)
            got = idx.resolve("inbox-labels", "unknown")
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

    def test_reassigned_surface_returns_the_last_assignment_matching_runtime(self):
        # (xvendor R-6 fix) A module that assigns SURFACE more than once at module level -- the
        # AST scanner must return the LAST assignment, mirroring Python's own runtime
        # last-assignment-wins semantics. Before the fix, the scanner returned on the FIRST
        # match, decoupling static corroboration from what the module actually holds at runtime.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            d = Path(root) / "agents/capabilities"
            d.mkdir(parents=True, exist_ok=True)
            (d / "acme_reassigned_capability.py").write_text(
                'SURFACE = "a"\n'
                '# some code in between\n'
                'SURFACE = "b"\n',
                encoding="utf-8")
            got = ci._extract_surface(d / "acme_reassigned_capability.py")
            self.assertEqual(got, "b")

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

    # --- coordinator review fix: resolve() precedence (surface must never outrank an exact
    # canonical-id / own-module-stem match) ---

    def test_own_canonical_id_wins_over_another_capabilitys_surface_corroboration(self):
        # A NEW capability whose capability_id happens to equal an UNRELATED existing
        # capability's own declared SURFACE must resolve to ITSELF -- never be
        # "corroborated away" to the other capability. Before the fix, resolve("foo",
        # "unknown") unioned module_stem_map's direct {"foo"} hit with surface_map's {"bar_sync"}
        # hit (bar_sync's own SURFACE=="foo"), producing a false "ambiguous" refusal for a
        # perfectly legitimate, unrelated new capability.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "foo", "foo_surface_unused")
            _write_capability(root, "bar_sync", "foo")  # bar_sync's OWN surface happens to be "foo"
            idx = ci.build_capability_index(root)
            got = idx.resolve("foo", "unknown")
            self.assertEqual(got.canonical_id, "foo")

    # --- coordinator review round 2: the sole-candidate cardinality fallback itself is an
    # uncorroborated GUESS and must be removed entirely, not just narrowed. ---

    def test_single_capability_uncorroborated_id_stays_unresolved(self):
        # CRITICAL regression (round-2 review finding): with exactly ONE capability in the
        # project and exactly ONE unmatched descriptor id, the (now-removed) sole-candidate
        # fallback resolved that id to the sole capability purely on cardinality -- "there's
        # only one capability, so this stray must mean that one" -- with ZERO corroborating
        # evidence (not the module's own stem, not a declared SURFACE). That is a fuzzy/
        # heuristic guess, exactly what this module's fail-closed design forbids. An id with
        # NO corroboration signal must stay unresolved no matter how few (or many) capabilities
        # exist in the project -- cardinality is not evidence.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "solo_cap", "solo_cap_surface")
            _write_descriptors(root, [{"id": "totally_unrelated_name"}])
            idx = ci.build_capability_index(root)
            with self.assertRaises(ci.IdentityResolutionError) as cm:
                idx.resolve("totally_unrelated_name", "descriptor_id")
            self.assertEqual(cm.exception.kind, "unresolved")

    def test_single_capability_uncorroborated_mechanism_id_stays_unresolved(self):
        # Same regression, mechanism_id namespace (the pending_migrations.json shape) --
        # a lone, uncorroborated mechanism_id must not be swept up either.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "solo_cap", "solo_cap_surface")
            _write_pending_migrations(root, [{"mechanism_id": "some_other_legacy_name"}])
            idx = ci.build_capability_index(root)
            with self.assertRaises(ci.IdentityResolutionError) as cm:
                idx.resolve("some_other_legacy_name", "mechanism_id")
            self.assertEqual(cm.exception.kind, "unresolved")

    def test_canonical_ids_property_exposes_known_capabilities(self):
        # Public accessor (added alongside the round-2 fix) so a caller can reason about
        # project cardinality without reaching into the private _identities map.
        ci = _load(MODPATH)
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "inbox_management", "inbox-labels")
            idx = ci.build_capability_index(root)
            self.assertEqual(idx.canonical_ids, frozenset({"inbox_management"}))

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
