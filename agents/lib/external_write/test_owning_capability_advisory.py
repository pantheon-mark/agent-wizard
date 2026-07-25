"""Task E / Cut 1.5 (bundle v0.19.0) -- ADVISORY owning-capability link on an open
bespoke-writer migration entry. UX ONLY -- NEVER a safety input.

Context: Task A (KEYSTONE) makes the mere EXISTENCE of an open bespoke-writer entry block the
whole project non-green, attribution-free (see ``_ext_write_state``'s module docstring and
``test_completion_global_bespoke_block.py``). That block must NEVER depend on which capability,
if any, the writer belongs to. Task E adds ``derive_owning_capability`` -- a RANKED-EVIDENCE
derivation used ONLY to enrich the plain-language "fix this file (part of X)" message
``lifecycle_state.check_completion`` shows the operator when it names the open bypass. This
suite proves:

  1. the ranked-evidence derivation itself: exactly one strong-evidence owner -> "resolved" (with
     the id); two or more -> "ambiguous" (no id); none -> "unresolved" (no id); weak stem/path
     similarity ALONE is never sufficient.
  2. the message enrichment: a resolved owner is named in ``check_completion``'s operator_message
     ("... (part of `<capability>`)"); an unresolved/ambiguous owner still names the file, just
     without the attribution clause.
  3. THE HARD BOUNDARY, proven directly: ``capability_health.overall_status`` /
     ``lifecycle_state.check_completion`` / ``open_bespoke_writer_migrations`` fire IDENTICALLY
     whether ownership resolves, is ambiguous, or is unresolved -- and even when an entry already
     carries hand-planted (possibly wrong) ``owning_capability_id`` / ``ownership_status`` keys,
     those keys are never read by the predicate.

Run:  python3 -m unittest discover -s wizard/agents/lib/external_write \\
          -p test_owning_capability_advisory.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

_EXTERNAL_WRITE_DIR = Path(__file__).resolve().parent
_AGENTS_LIB = _EXTERNAL_WRITE_DIR.parent  # agents/lib -- external_write is a package under here
_SCRIPTS_LIB = _EXTERNAL_WRITE_DIR.parents[2] / "scripts" / "lib"  # wizard/scripts/lib
for _p in (str(_AGENTS_LIB), str(_SCRIPTS_LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Name-form imports (NOT the dotted-submodule form): every other test file in this dir uses this
# convention so a whole-package bypass scan never trips on a test file's own imports.
from external_write import _ext_write_state  # noqa: E402
from external_write import lifecycle_state  # noqa: E402
from external_write import capability_health  # noqa: E402

# Reuse the REAL full-ceremony fixture mixin (genuinely accepted capability + genuine audit
# record) -- never a hand-authored accepted/audit stand-in. Same reuse test_completion_global_
# bespoke_block.py already establishes.
import test_lifecycle_state as _ls_fixtures  # noqa: E402

derive_owning_capability = _ext_write_state.derive_owning_capability
open_bespoke_writer_migrations = _ext_write_state.open_bespoke_writer_migrations

BESPOKE_WRITER_RELPATH = "agents/inbox/runner.py"
CAP_ID_UNDER_TEST = "inbox_management"


def _write_pending_migrations(root, entries):
    d = Path(root) / "agents" / "handoffs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pending_migrations.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _bespoke_entry(writer_relpath=BESPOKE_WRITER_RELPATH, status="pending", **extra):
    """A bespoke-writer migration entry -- the estate's real shape (relpath-derived mechanism_id,
    NO owning-capability field, unless a test hand-plants one via ``extra`` to prove it is never
    read by the safety predicate)."""
    entry = {
        "mechanism_id": "runner",
        "writer_relpath": writer_relpath,
        "entrypoint_relpath": None,
        "status": status,
        "reason": "flagged non-conformant with the external-write gate on upgrade",
    }
    entry.update(extra)
    return entry


def _write_capability_module(root, cap_id, op_kind=None):
    d = Path(root) / "agents" / "capabilities"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{cap_id}_capability.py"
    lines = [f'"""{cap_id} -- fixture capability module (Task E test)."""', ""]
    if op_kind is not None:
        lines.append(f'OP_KIND = "{op_kind}"')
        lines.append("")
    lines.append("def describe():")
    lines.append(f'    return "{cap_id} ready"')
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_bespoke_writer(root, relpath=BESPOKE_WRITER_RELPATH, source=""):
    p = Path(root) / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source, encoding="utf-8")
    return p


# A hand-rolled writer carrying NO attribution signal at all -- the estate's real shape (see
# _ext_write_state's own module docstring / test_writer_migration_autoreap.py's identical
# fixture).
_NO_EVIDENCE_WRITER_SRC = (
    '"""Hand-rolled per-chunk bulk writer -- bypasses run_sanctioned_bulk."""\n'
    "from external_write.run_envelope import mint_run_envelope\n\n\n"
    "def run_all(chunks):\n"
    "    return [mint_run_envelope(c) for c in chunks]\n"
)


# =============================================================================
# 1. The ranked-evidence derivation itself (pure, no capability_health/lifecycle_state involved).
# =============================================================================

class DeriveOwningCapabilityTest(unittest.TestCase):

    def test_import_of_capability_module_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_capability_module(root, "google_sheets")
            _write_bespoke_writer(root, source=(
                '"""Bespoke writer that imports a capability module directly."""\n'
                "from agents.capabilities import google_sheets_capability\n\n\n"
                "def run():\n"
                "    return google_sheets_capability.describe()\n"
            ))
            result = derive_owning_capability(str(root), _bespoke_entry())
            self.assertEqual(result["ownership_status"], "resolved")
            self.assertEqual(result["owning_capability_id"], "google_sheets")

    def test_envelope_capability_id_literal_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_capability_module(root, "google_sheets")
            _write_bespoke_writer(root, source=(
                '"""Bespoke writer that self-declares its owner."""\n'
                'ENVELOPE_CAPABILITY_ID = "google_sheets"\n'
            ))
            result = derive_owning_capability(str(root), _bespoke_entry())
            self.assertEqual(result["ownership_status"], "resolved")
            self.assertEqual(result["owning_capability_id"], "google_sheets")

    def test_op_kind_shared_with_exactly_one_capability_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_capability_module(root, "google_sheets", op_kind="delete_record")
            _write_bespoke_writer(root, source=(
                '"""Bespoke writer sharing an op_kind with exactly one capability."""\n'
                'OP_KIND = "delete_record"\n'
            ))
            result = derive_owning_capability(str(root), _bespoke_entry())
            self.assertEqual(result["ownership_status"], "resolved")
            self.assertEqual(result["owning_capability_id"], "google_sheets")

    def test_op_kind_shared_with_two_capabilities_does_not_resolve_via_that_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_capability_module(root, "google_sheets", op_kind="delete_record")
            _write_capability_module(root, "gmail", op_kind="delete_record")
            _write_bespoke_writer(root, source='OP_KIND = "delete_record"\n')
            result = derive_owning_capability(str(root), _bespoke_entry())
            # Shared with TWO -> this signal contributes nothing (not "ambiguous" via this
            # signal alone, since neither is individually a strong owner) -- and there is no
            # other signal here, so the overall result is unresolved.
            self.assertEqual(result["ownership_status"], "unresolved")
            self.assertIsNone(result["owning_capability_id"])

    def test_two_distinct_strong_owners_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_capability_module(root, "google_sheets")
            _write_capability_module(root, "gmail")
            _write_bespoke_writer(root, source=(
                "from agents.capabilities import google_sheets_capability\n"
                "from agents.capabilities import gmail_capability\n"
            ))
            result = derive_owning_capability(str(root), _bespoke_entry())
            self.assertEqual(result["ownership_status"], "ambiguous")
            self.assertIsNone(result["owning_capability_id"])

    def test_no_evidence_is_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_capability_module(root, "google_sheets")
            _write_bespoke_writer(root, source=_NO_EVIDENCE_WRITER_SRC)
            result = derive_owning_capability(str(root), _bespoke_entry())
            self.assertEqual(result["ownership_status"], "unresolved")
            self.assertIsNone(result["owning_capability_id"])

    def test_weak_stem_path_similarity_alone_never_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_capability_module(root, "google_sheets")
            relpath = "agents/inbox/google_sheets_runner.py"
            _write_bespoke_writer(root, relpath=relpath, source=(
                '"""Filename LOOKS related to google_sheets but carries no strong evidence."""\n'
                "def run():\n    pass\n"
            ))
            result = derive_owning_capability(str(root), _bespoke_entry(writer_relpath=relpath))
            self.assertEqual(result["ownership_status"], "unresolved")
            self.assertIsNone(result["owning_capability_id"])

    def test_no_capabilities_dir_at_all_is_unresolved_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_bespoke_writer(root, source=_NO_EVIDENCE_WRITER_SRC)
            result = derive_owning_capability(str(root), _bespoke_entry())
            self.assertEqual(result["ownership_status"], "unresolved")
            self.assertIsNone(result["owning_capability_id"])

    def test_missing_writer_file_is_unresolved_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_capability_module(root, "google_sheets")
            # No writer file ever written at BESPOKE_WRITER_RELPATH.
            result = derive_owning_capability(str(root), _bespoke_entry())
            self.assertEqual(result["ownership_status"], "unresolved")
            self.assertIsNone(result["owning_capability_id"])

    def test_non_dict_entry_is_unresolved_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = derive_owning_capability(str(root), "not-a-dict")  # type: ignore[arg-type]
            self.assertEqual(result["ownership_status"], "unresolved")
            self.assertIsNone(result["owning_capability_id"])


# =============================================================================
# 2. Message enrichment: lifecycle_state.check_completion names the resolved owner.
# =============================================================================

class OwnershipMessageEnrichmentTest(_ls_fixtures._CheckCompletionFixtureMixin, unittest.TestCase):
    PHASE_ID = _ls_fixtures._ace_fixtures.PHASE

    def test_resolved_owner_is_named_in_the_operator_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID_UNDER_TEST)
            _write_capability_module(root, "google_sheets")
            _write_bespoke_writer(root, source='ENVELOPE_CAPABILITY_ID = "google_sheets"\n')
            _write_pending_migrations(root, [_bespoke_entry()])

            result = lifecycle_state.check_completion(str(root), CAP_ID_UNDER_TEST)

            self.assertFalse(result.done)
            self.assertIn("open_external_write_bypass", result.failed_conjuncts)
            self.assertIn(BESPOKE_WRITER_RELPATH, result.operator_message)
            self.assertIn("google_sheets", result.operator_message)
            self.assertIn("part of", result.operator_message)
            self.assertNotIn("Traceback", result.operator_message)

    def test_unresolved_owner_still_names_the_file_without_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID_UNDER_TEST)
            _write_bespoke_writer(root, source=_NO_EVIDENCE_WRITER_SRC)
            _write_pending_migrations(root, [_bespoke_entry()])

            result = lifecycle_state.check_completion(str(root), CAP_ID_UNDER_TEST)

            self.assertFalse(result.done)
            self.assertIn(BESPOKE_WRITER_RELPATH, result.operator_message)
            self.assertNotIn("part of", result.operator_message)
            self.assertNotIn("Traceback", result.operator_message)

    def test_ambiguous_owner_still_names_the_file_without_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID_UNDER_TEST)
            _write_capability_module(root, "google_sheets")
            _write_capability_module(root, "gmail")
            _write_bespoke_writer(root, source=(
                "from agents.capabilities import google_sheets_capability\n"
                "from agents.capabilities import gmail_capability\n"
            ))
            _write_pending_migrations(root, [_bespoke_entry()])

            result = lifecycle_state.check_completion(str(root), CAP_ID_UNDER_TEST)

            self.assertFalse(result.done)
            self.assertIn(BESPOKE_WRITER_RELPATH, result.operator_message)
            self.assertNotIn("part of", result.operator_message)


# =============================================================================
# 3. THE HARD BOUNDARY: safety fires IDENTICALLY regardless of ownership resolution.
# =============================================================================

class SafetyIndependenceTest(_ls_fixtures._CheckCompletionFixtureMixin, unittest.TestCase):
    PHASE_ID = _ls_fixtures._ace_fixtures.PHASE

    def _block_signature(self, root):
        """A tuple capturing every safety-relevant signal Task A's block drives -- deliberately
        NOT including anything message/prose-shaped, so this comparison can never pass merely
        because two differently-worded messages happen to share a substring."""
        overall = capability_health.overall_status(str(root))
        result = lifecycle_state.check_completion(str(root), CAP_ID_UNDER_TEST)
        open_entries = open_bespoke_writer_migrations(str(root))
        return (
            overall["normal_status_allowed"],
            overall["open_external_write_bypass"]["blocking"],
            result.done,
            result.core_ok,
            result.projection_ok,
            "open_external_write_bypass" in result.failed_conjuncts,
            len(open_entries),
        )

    def test_block_fires_identically_for_resolved_ambiguous_and_unresolved_ownership(self):
        scenarios = {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID_UNDER_TEST)
            _write_capability_module(root, "google_sheets")
            _write_bespoke_writer(root, source='ENVELOPE_CAPABILITY_ID = "google_sheets"\n')
            _write_pending_migrations(root, [_bespoke_entry()])
            entry = open_bespoke_writer_migrations(str(root))[0]
            self.assertEqual(
                derive_owning_capability(str(root), entry)["ownership_status"], "resolved")
            scenarios["resolved"] = self._block_signature(root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID_UNDER_TEST)
            _write_capability_module(root, "google_sheets")
            _write_capability_module(root, "gmail")
            _write_bespoke_writer(root, source=(
                "from agents.capabilities import google_sheets_capability\n"
                "from agents.capabilities import gmail_capability\n"
            ))
            _write_pending_migrations(root, [_bespoke_entry()])
            entry = open_bespoke_writer_migrations(str(root))[0]
            self.assertEqual(
                derive_owning_capability(str(root), entry)["ownership_status"], "ambiguous")
            scenarios["ambiguous"] = self._block_signature(root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID_UNDER_TEST)
            _write_bespoke_writer(root, source=_NO_EVIDENCE_WRITER_SRC)
            _write_pending_migrations(root, [_bespoke_entry()])
            entry = open_bespoke_writer_migrations(str(root))[0]
            self.assertEqual(
                derive_owning_capability(str(root), entry)["ownership_status"], "unresolved")
            scenarios["unresolved"] = self._block_signature(root)

        self.assertEqual(scenarios["resolved"], scenarios["ambiguous"], scenarios)
        self.assertEqual(scenarios["ambiguous"], scenarios["unresolved"], scenarios)

        # Not a vacuous all-equal-because-all-untouched comparison: every scenario genuinely
        # blocked (non-normal, non-done, the bypass conjunct fired, exactly one open entry).
        for name, sig in scenarios.items():
            (normal_allowed, bypass_blocking, done, core_ok, projection_ok,
             bypass_conjunct_failed, open_count) = sig
            self.assertFalse(normal_allowed, f"{name}: must not be normal")
            self.assertTrue(bypass_blocking, f"{name}: bypass must be blocking")
            self.assertFalse(done, f"{name}: must not be done")
            self.assertFalse(projection_ok, f"{name}: projection must not be ok")
            self.assertTrue(bypass_conjunct_failed, f"{name}: bypass conjunct must fire")
            self.assertEqual(open_count, 1, f"{name}: exactly one open entry")

    def test_hand_planted_ownership_fields_on_the_entry_never_change_the_predicate(self):
        """Even if an entry already carries (possibly fabricated) owning_capability_id /
        ownership_status keys -- e.g. stamped by upgrade_reconcile at an earlier reconcile pass,
        or hand-planted here to simulate that -- the safety predicate must not read them at
        all."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID_UNDER_TEST)
            _write_bespoke_writer(root)

            _write_pending_migrations(root, [_bespoke_entry()])
            without_fields = self._block_signature(root)

            _write_pending_migrations(root, [_bespoke_entry(
                owning_capability_id="totally_fabricated_capability",
                ownership_status="resolved",
            )])
            with_fabricated_resolved = self._block_signature(root)

            _write_pending_migrations(root, [_bespoke_entry(
                owning_capability_id=None, ownership_status="ambiguous")])
            with_fabricated_ambiguous = self._block_signature(root)

            self.assertEqual(without_fields, with_fabricated_resolved)
            self.assertEqual(with_fabricated_resolved, with_fabricated_ambiguous)
            self.assertFalse(without_fields[0], "sanity: this scenario must actually block")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
