"""Tests for the pre-v2 upgrade MIGRATION preflight (upgrade_migrate).

These exercise the reconciliation of a "foundation-only manifest + manually-applied
operating layer" system into a state a normal upgrade can run over safely. The fixture
is built on a COPY in a temp dir from the real wizard emit pipeline (anti-overfit: not
estate-specific hardcoding) and then DOWNGRADED to simulate the pre-v2 manual-apply state:

  - capsule reset to v1 (foundation_doc_inputs only; no operating block);
  - one operating render file's manifest entry DELETED (the manually-dropped file: on
    disk, untracked) -> migration must reconcile it (adopt baseline + lineage);
  - one operating render file edited by the operator (live != known) -> migration must
    leave it as operator-drift;
  - the rest left tracked-at-foundation-lineage but byte-equal to the known payload ->
    migration reconciles their lineage.

The live estate at ~/Documents/estate-tracker is NEVER written: these tests run entirely
on emitted copies under a TemporaryDirectory.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # wizard/scripts (interview_cli)

import interview_cli as cli  # noqa: E402
from upgrade import (  # noqa: E402
    load_operator_manifest,
    load_registry,
    sha256_bytes,
    normalize_for_content_hash,
)
from upgrade_apply import (  # noqa: E402
    _render_operating_layer,
    _inject_hooks_for_copy_file,
    _replay_conformance_check,
    _foundation_managed_entries,
    _render_version,
    LIVE_LINEAGE_VERSION_FIELD,
    RENDER_KIND_RENDER,
    RENDER_KIND_COPY,
    CONTRACT_BASENAME,
)
from bundle_templates import read_bundle_template  # noqa: E402
from replay_capsule import (  # noqa: E402
    REPLAY_CAPSULE_REL,
    CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY,
    capsule_supports_operating_replay,
)
import upgrade_migrate as mig  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"
TRANSCRIPT = Path.home() / "wizard-pilot-2026-06-01" / "wizard_transcript.jsonl"
SHAPE = "markdown-CC"
SOURCE_VERSION = "v0.6.0"          # the version the manual operating layer came from
_GEN_OVERRIDE = "c3b5609fbbe566d73f3097ff0d1cd087dfe19245"
PROJECT_NAME = "operator-system"
# A FIXED past emit date, chosen to differ from any real today() the suite runs on, so a
# regeneration that stamps today() diverges from the recorded foundation base_hashes.
PAST_DATE = "2024-01-02"


def _content_hash(text: str) -> str:
    return "sha256:" + sha256_bytes(normalize_for_content_hash(text).encode("utf-8"))


def _full_hash(text: str) -> str:
    return "sha256:" + sha256_bytes(text.encode("utf-8"))


def _have_prereqs() -> bool:
    if not TRANSCRIPT.exists():
        return False
    try:
        reg = load_registry(REGISTRY_PATH)
    except Exception:
        return False
    versions = {e.get("foundation_bundle_version") for e in reg.get("bundles", [])}
    return SOURCE_VERSION in versions


def _operating_render_relpaths() -> list:
    contract = json.loads(
        (REPO_ROOT / "wizard" / "foundation-bundles" / SOURCE_VERSION / CONTRACT_BASENAME)
        .read_text(encoding="utf-8"))
    return sorted(
        e["relpath"] for e in contract.get("artifacts", [])
        if e.get("delivery") == "wizard" and e.get("render_kind") == RENDER_KIND_RENDER
    )


def _operating_copy_relpaths() -> list:
    """The operating-layer `render_kind:copy` relpaths the source bundle carries
    (delivery == wizard, with a real bundle template_path — control-plane-emitted
    entries carry no template and are not bundle-sourced)."""
    contract = json.loads(
        (REPO_ROOT / "wizard" / "foundation-bundles" / SOURCE_VERSION / CONTRACT_BASENAME)
        .read_text(encoding="utf-8"))
    return sorted(
        e["relpath"] for e in contract.get("artifacts", [])
        if e.get("delivery") == "wizard"
        and e.get("render_kind") == RENDER_KIND_COPY
        and e.get("template_path") is not None
    )


@unittest.skipUnless(
    _have_prereqs(),
    f"requires the preserved pilot transcript at {TRANSCRIPT} and the {SOURCE_VERSION} bundle",
)
class UpgradeMigrateTests(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    # ---- fixture: emit a real v0.6.0 system, then downgrade to pre-v2 manual-apply state.
    def _emit_v060(self, name: str) -> Path:
        proj = self.tmp / name
        cli.cmd_emit_system(
            str(TRANSCRIPT), SHAPE, str(proj), str(REPO_ROOT),
            project_name=PROJECT_NAME, bundle_version=SOURCE_VERSION,
            generator_version_override=_GEN_OVERRIDE,
        )
        return proj

    def _emit_v060_at(self, proj: Path, *, clock) -> Path:
        """Emit a v0.6.0 system whose volatile globals (LAST_UPDATED_DATE /
        MANUAL_LAST_UPDATED) are stamped from `clock` — used to force a FIXED past emit
        date so a later regeneration at today() exercises the date-stability path."""
        cli.cmd_emit_system(
            str(TRANSCRIPT), SHAPE, str(proj), str(REPO_ROOT),
            project_name=PROJECT_NAME, bundle_version=SOURCE_VERSION,
            generator_version_override=_GEN_OVERRIDE, clock=clock,
        )
        return proj

    def _downgrade_to_pre_v2(self, proj: Path, *, drop_rel: str, drift_rel: str) -> dict:
        """Simulate the pre-v2 manual-apply state on an emitted v0.6.0 copy:
          - capsule -> v1 (strip the operating block);
          - manifest entry for `drop_rel` DELETED (manually-dropped untracked file);
          - all operating render entries' lineage rolled back to a foundation-era version
            (v0.4.0) so the migration must re-advance them;
          - `drift_rel` live content edited (operator drift) AND its manifest baseline rolled
            back to a stale (wrong) hash.
        Returns the v1 capsule dict written."""
        # 1. capsule -> v1
        cap_path = proj / REPLAY_CAPSULE_REL
        cap = json.loads(cap_path.read_text(encoding="utf-8"))
        v1 = {
            "schema_version": CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY,
            "foundation_bundle_version": "v0.4.0",
            "generator_version": cap["generator_version"],
            "system_shape": cap["system_shape"],
            "foundation_only_mode": cap.get("foundation_only_mode", False),
            "canonicalization_version": cap["canonicalization_version"],
            "hash_algorithm": cap["hash_algorithm"],
            "foundation_doc_inputs": cap["foundation_doc_inputs"],
        }
        cap_path.write_text(json.dumps(v1, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # 2. manifest downgrade
        mp = proj / ".wizard" / "manifest.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["foundation_bundle_version"] = "v0.4.0"
        fb = m["managed_files"]
        ol = _operating_render_relpaths()
        for rel in ol:
            if rel in fb:
                fb[rel][LIVE_LINEAGE_VERSION_FIELD] = "v0.4.0"
        # drop_rel: delete the manifest entry but KEEP the file on disk (untracked).
        self.assertIn(drop_rel, fb, f"{drop_rel} should be a managed render file pre-downgrade")
        del fb[drop_rel]
        # drift_rel: edit the live file + corrupt its manifest baseline to a stale hash.
        drift_path = proj / drift_rel
        original = drift_path.read_text(encoding="utf-8")
        drift_path.write_text(original + "\n\nOPERATOR EDIT during manual operation.\n",
                              encoding="utf-8")
        fb[drift_rel]["base_hash"] = "sha256:" + ("a" * 64)
        fb[drift_rel]["base_content_hash"] = "sha256:" + ("b" * 64)
        mp.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return v1

    # ======================================================================

    def test_migrate_reconciles_known_payload_without_rewriting_drift(self):
        proj = self._emit_v060("recon")
        # Pick a clean render file to DROP (untracked) and a distinct one to DRIFT.
        ol = _operating_render_relpaths()
        drop_rel = "operating_discipline.md"
        drift_rel = "CLAUDE.md"
        self.assertIn(drop_rel, ol)
        self.assertIn(drift_rel, ol)
        self._downgrade_to_pre_v2(proj, drop_rel=drop_rel, drift_rel=drift_rel)

        # Bytes BEFORE for every operating render file (to prove live bytes unchanged).
        before = {rel: (proj / rel).read_bytes() for rel in ol if (proj / rel).exists()}
        drift_before = (proj / drift_rel).read_bytes()

        res = mig.migrate_pre_v2_system(
            proj, SOURCE_VERSION, REPO_ROOT,
            transcript_path=TRANSCRIPT, system_shape=SHAPE, project_name=PROJECT_NAME,
            generator_version_override=_GEN_OVERRIDE,
        )

        m = json.loads((proj / ".wizard" / "manifest.json").read_text())
        fb = m["managed_files"]

        # Recompute the known payload to assert exact reconciliation values.
        cap = json.loads((proj / REPLAY_CAPSULE_REL).read_text())
        ci = cap["foundation_doc_inputs"]
        known = _render_operating_layer(
            SOURCE_VERSION, ol, capsule=cap, capsule_inputs=ci,
            project_name=PROJECT_NAME, build_repo_root=REPO_ROOT)

        # (a) DROPPED-then-reconciled file: entry RE-ADDED with correct baseline + lineage,
        #     bytes unchanged.
        self.assertIn(drop_rel, fb, "dropped file not re-tracked by migration")
        self.assertIn(drop_rel, res.created + res.reconciled)
        self.assertEqual(fb[drop_rel]["base_content_hash"], _content_hash(known[drop_rel]))
        self.assertEqual(fb[drop_rel]["base_hash"], _full_hash(known[drop_rel]))
        self.assertEqual(fb[drop_rel][LIVE_LINEAGE_VERSION_FIELD], SOURCE_VERSION)
        self.assertEqual((proj / drop_rel).read_bytes(), before[drop_rel],
                         "migration changed live bytes of the reconciled file")

        # (b) OPERATOR-DRIFT file: baseline NOT rewritten (still the stale corrupted hash),
        #     lineage NOT advanced, live bytes unchanged.
        self.assertIn(drift_rel, res.operator_drift, "drifted file not classified operator_drift")
        self.assertEqual(fb[drift_rel]["base_hash"], "sha256:" + ("a" * 64),
                         "migration rewrote a drifted file's baseline (lost edit signal)")
        self.assertNotEqual(fb[drift_rel][LIVE_LINEAGE_VERSION_FIELD], SOURCE_VERSION)
        self.assertEqual((proj / drift_rel).read_bytes(), drift_before,
                         "migration changed live bytes of the drifted file")

        # (c) A clean tracked file (live == known, stale lineage): lineage advanced to source,
        #     baseline adopted, bytes unchanged.
        clean = [r for r in ol if r not in (drop_rel, drift_rel)
                 and (proj / r).exists()
                 and _content_hash((proj / r).read_text()) == _content_hash(known[r])]
        self.assertTrue(clean, "no clean tracked render file in the fixture to reconcile")
        sample = clean[0]
        self.assertEqual(fb[sample][LIVE_LINEAGE_VERSION_FIELD], SOURCE_VERSION)
        self.assertEqual(fb[sample]["base_content_hash"], _content_hash(known[sample]))
        self.assertEqual((proj / sample).read_bytes(), before[sample])

    def test_migrate_then_upgrade_replay_passes(self):
        """After migration, the replay-conformance gate (operating-layer leg) passes CLEANLY
        when every tracked operating render file is clean (no operator drift): render(source,
        capsule) reproduces the recorded base_hash for the reconciled files with no false-fail
        and no stuck chain. (A drifted file is verified separately in the reconciliation test;
        here we prove the reconciled baselines are exactly what the gate reproduces.)"""
        proj = self._emit_v060("replay")
        # Downgrade WITHOUT injecting operator drift: drop one file (untracked) and roll back
        # every operating render file's lineage. All live bytes still == the known payload, so
        # after reconciliation the whole operating leg must pass the gate cleanly.
        cap_path = proj / REPLAY_CAPSULE_REL
        cap0 = json.loads(cap_path.read_text(encoding="utf-8"))
        v1 = {
            "schema_version": CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY,
            "foundation_bundle_version": "v0.4.0",
            "generator_version": cap0["generator_version"],
            "system_shape": cap0["system_shape"],
            "foundation_only_mode": cap0.get("foundation_only_mode", False),
            "canonicalization_version": cap0["canonicalization_version"],
            "hash_algorithm": cap0["hash_algorithm"],
            "foundation_doc_inputs": cap0["foundation_doc_inputs"],
        }
        cap_path.write_text(json.dumps(v1, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        mp = proj / ".wizard" / "manifest.json"
        m = json.loads(mp.read_text())
        fb = m["managed_files"]
        for rel in _operating_render_relpaths():
            if rel in fb:
                fb[rel][LIVE_LINEAGE_VERSION_FIELD] = "v0.4.0"
        del fb["operating_discipline.md"]  # manually-dropped untracked file
        mp.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        mig.migrate_pre_v2_system(
            proj, SOURCE_VERSION, REPO_ROOT,
            transcript_path=TRANSCRIPT, system_shape=SHAPE, project_name=PROJECT_NAME,
            generator_version_override=_GEN_OVERRIDE,
        )
        manifest = load_operator_manifest(mp)
        cap = json.loads(cap_path.read_text())
        ci = cap["foundation_doc_inputs"]
        base = _render_version(SOURCE_VERSION, ci, REPO_ROOT)
        foundation_entries = _foundation_managed_entries(manifest, list(base.keys()))
        # Must NOT raise: the operating-layer leg reproduces every reconciled base_hash.
        _replay_conformance_check(
            SOURCE_VERSION, ci, REPO_ROOT, foundation_entries,
            capsule=cap, manifest=manifest, project_name=PROJECT_NAME,
        )
        # And the previously-untracked file is now reconciled + tracked.
        self.assertIn("operating_discipline.md", manifest["managed_files"])
        self.assertEqual(
            manifest["managed_files"]["operating_discipline.md"][LIVE_LINEAGE_VERSION_FIELD],
            SOURCE_VERSION)

    def test_migrate_capsule_upgraded_to_v2(self):
        proj = self._emit_v060("capsule")
        self._downgrade_to_pre_v2(proj, drop_rel="operating_discipline.md", drift_rel="CLAUDE.md")
        # Premise: capsule is v1 after downgrade.
        pre = json.loads((proj / REPLAY_CAPSULE_REL).read_text())
        self.assertFalse(capsule_supports_operating_replay(pre), "fixture capsule not v1")

        res = mig.migrate_pre_v2_system(
            proj, SOURCE_VERSION, REPO_ROOT,
            transcript_path=TRANSCRIPT, system_shape=SHAPE, project_name=PROJECT_NAME,
            generator_version_override=_GEN_OVERRIDE,
        )
        self.assertTrue(res.capsule_upgraded_to_v2)
        post = json.loads((proj / REPLAY_CAPSULE_REL).read_text())
        self.assertTrue(capsule_supports_operating_replay(post),
                        "post-migration capsule is not v2 with an operating block")
        self.assertIn("operating", post)

    def test_migrate_idempotent(self):
        proj = self._emit_v060("idem")
        self._downgrade_to_pre_v2(proj, drop_rel="operating_discipline.md", drift_rel="CLAUDE.md")
        mig.migrate_pre_v2_system(
            proj, SOURCE_VERSION, REPO_ROOT,
            transcript_path=TRANSCRIPT, system_shape=SHAPE, project_name=PROJECT_NAME,
            generator_version_override=_GEN_OVERRIDE,
        )
        manifest_after_1 = (proj / ".wizard" / "manifest.json").read_bytes()
        capsule_after_1 = (proj / REPLAY_CAPSULE_REL).read_bytes()

        res2 = mig.migrate_pre_v2_system(
            proj, SOURCE_VERSION, REPO_ROOT,
            transcript_path=TRANSCRIPT, system_shape=SHAPE, project_name=PROJECT_NAME,
            generator_version_override=_GEN_OVERRIDE,
        )
        self.assertTrue(res2.noop, "second migration run was not a no-op")
        self.assertFalse(res2.capsule_upgraded_to_v2, "second run re-upgraded the capsule")
        self.assertFalse(res2.manifest_changed, "second run mutated the manifest")
        self.assertEqual((proj / ".wizard" / "manifest.json").read_bytes(), manifest_after_1,
                         "second run changed the manifest bytes")
        self.assertEqual((proj / REPLAY_CAPSULE_REL).read_bytes(), capsule_after_1,
                         "second run changed the capsule bytes")


    # ======================================================================
    # FINDING 1 — capsule regeneration must NOT bake in the regeneration-time
    # date/version. The original emit's LAST_UPDATED_DATE / MANUAL_LAST_UPDATED /
    # WIZARD_VERSION must be PRESERVED in the regenerated capsule's
    # foundation_doc_inputs, or the foundation-doc replay-conformance leg false-fails
    # (the regenerated foundation docs carry today's date / the regen version and no
    # longer reproduce the manifest's recorded foundation base_hashes).
    #
    # The pre-existing suite missed this because it emits + regenerates the SAME
    # source system in ONE run on ONE date at the SAME bundle_version, so the volatile
    # values matched by luck. This test FORCES the split: emit at a FIXED PAST date,
    # then regenerate (via the migration) at the REAL today() date, and prove the
    # foundation values are carried from the original capsule + the gate still passes.

    def test_migrate_preserves_original_volatile_inputs_on_regen(self):
        from datetime import date
        proj = self._emit_v060_at(self.tmp / "volatile", clock=lambda: PAST_DATE)
        # Premise: TODAY differs from the fixed original emit date, so a regeneration
        # that stamps today() would diverge from the recorded foundation base_hashes.
        self.assertNotEqual(date.today().isoformat(), PAST_DATE,
                            "test premise broken: today() == the fixed past date")

        # Record the original capsule's volatile foundation values BEFORE downgrade.
        cap_path = proj / REPLAY_CAPSULE_REL
        orig_cap = json.loads(cap_path.read_text(encoding="utf-8"))
        orig_fdi = dict(orig_cap["foundation_doc_inputs"])
        self.assertEqual(orig_fdi.get("LAST_UPDATED_DATE"), PAST_DATE)
        self.assertEqual(orig_fdi.get("MANUAL_LAST_UPDATED"), PAST_DATE)
        self.assertEqual(orig_fdi.get("WIZARD_VERSION"), SOURCE_VERSION)

        # Downgrade the capsule to v1 (strip the operating block) — preserving the
        # original foundation_doc_inputs (the original date/version). The migration must
        # REGENERATE the operating block today() WITHOUT clobbering those values.
        v1 = {
            "schema_version": CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY,
            "foundation_bundle_version": orig_cap["foundation_bundle_version"],
            "generator_version": orig_cap["generator_version"],
            "system_shape": orig_cap["system_shape"],
            "foundation_only_mode": orig_cap.get("foundation_only_mode", False),
            "canonicalization_version": orig_cap["canonicalization_version"],
            "hash_algorithm": orig_cap["hash_algorithm"],
            "foundation_doc_inputs": orig_fdi,
        }
        cap_path.write_text(json.dumps(v1, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # Roll back operating-render lineage so the migration re-advances them (and so the
        # operating leg is exercised end to end).
        mp = proj / ".wizard" / "manifest.json"
        m = json.loads(mp.read_text())
        fb = m["managed_files"]
        for rel in _operating_render_relpaths():
            if rel in fb:
                fb[rel][LIVE_LINEAGE_VERSION_FIELD] = "v0.4.0"
        mp.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # Run the migration — capsule REGENERATION happens at today() (!= PAST_DATE) and
        # at the source bundle_version, the exact split that triggered the bug.
        res = mig.migrate_pre_v2_system(
            proj, SOURCE_VERSION, REPO_ROOT,
            transcript_path=TRANSCRIPT, system_shape=SHAPE, project_name=PROJECT_NAME,
            generator_version_override=_GEN_OVERRIDE,
        )
        self.assertTrue(res.capsule_upgraded_to_v2)

        # (a) The regenerated capsule's foundation_doc_inputs carry the ORIGINAL volatile
        #     values, NOT today() / the regen-time version.
        post = json.loads(cap_path.read_text())
        pfdi = post["foundation_doc_inputs"]
        self.assertEqual(pfdi.get("LAST_UPDATED_DATE"), PAST_DATE,
                         "regeneration baked in today()'s date instead of the original")
        self.assertEqual(pfdi.get("MANUAL_LAST_UPDATED"), PAST_DATE,
                         "regeneration baked in today()'s manual-update date")
        self.assertEqual(pfdi.get("WIZARD_VERSION"), SOURCE_VERSION,
                         "regeneration baked in the regen-time version")
        # And it is a real v2 capsule (operating block regenerated).
        self.assertTrue(capsule_supports_operating_replay(post))

        # (b) The replay-conformance gate passes for ALL foundation docs (no false-fail) —
        #     the foundation leg reproduces every recorded base_hash, AND the operating leg
        #     reproduces its reconciled base_hashes.
        manifest = load_operator_manifest(mp)
        ci = post["foundation_doc_inputs"]
        base = _render_version(SOURCE_VERSION, ci, REPO_ROOT)
        foundation_entries = _foundation_managed_entries(manifest, list(base.keys()))
        # Must NOT raise.
        _replay_conformance_check(
            SOURCE_VERSION, ci, REPO_ROOT, foundation_entries,
            capsule=post, manifest=manifest, project_name=PROJECT_NAME,
        )

    # ======================================================================
    # FINDING 2 — the migration must ALSO adopt UNMANAGED copy-kind operating-layer
    # files whose live == the known bundle payload (verbatim template bytes at
    # source_version, hook-injection replayed). A manually-applied .claude/* + skills
    # file is copy-kind and carries no manifest entry; on upgrade it hits the new-file
    # collision rule instead of being adopted. An operator-EDITED copy (live != known)
    # must be LEFT unmanaged for the collision/sidecar path.

    def _known_copy_payload(self, rel: str, capsule: dict) -> str:
        """The known wizard payload for a copy-kind file = verbatim source-version
        bundle template bytes, with the emitter's deterministic hook-injection replayed
        (a no-op for non-hook-target files)."""
        raw = read_bundle_template(SOURCE_VERSION, rel, REPO_ROOT)
        return _inject_hooks_for_copy_file(rel, raw, capsule, REPO_ROOT)

    def test_migrate_adopts_unmanaged_copy_files_and_leaves_edited(self):
        proj = self._emit_v060("copyadopt")
        cap = json.loads((proj / REPLAY_CAPSULE_REL).read_text())

        copy_rels = _operating_copy_relpaths()
        # Pick MULTIPLE clean unmanaged copies (anti-overfit; not estate-specific) and a
        # distinct one the operator edited. Use only files that exist on disk in the emit.
        present = [r for r in copy_rels if (proj / r).exists()]
        self.assertGreaterEqual(len(present), 3,
                                "need >=3 copy files on disk to test divergent adoption")
        adopt_rels = present[:2]            # unmanaged + live == known -> ADOPT
        edited_rel = present[2]             # unmanaged + operator-edited -> LEAVE

        mp = proj / ".wizard" / "manifest.json"
        m = json.loads(mp.read_text())
        fb = m["managed_files"]
        # Make them UNMANAGED: delete their manifest entries, keep the files on disk.
        for rel in adopt_rels + [edited_rel]:
            self.assertIn(rel, fb, f"{rel} should be managed pre-downgrade")
            del fb[rel]
        mp.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # Operator-edit the edited_rel live file (live != known payload).
        ep = proj / edited_rel
        ep.write_text(ep.read_text(encoding="utf-8") + "\n# OPERATOR LOCAL EDIT\n",
                      encoding="utf-8")

        before_bytes = {rel: (proj / rel).read_bytes() for rel in adopt_rels + [edited_rel]}

        res = mig.migrate_pre_v2_system(
            proj, SOURCE_VERSION, REPO_ROOT,
            transcript_path=TRANSCRIPT, system_shape=SHAPE, project_name=PROJECT_NAME,
            generator_version_override=_GEN_OVERRIDE,
        )

        m2 = json.loads(mp.read_text())
        fb2 = m2["managed_files"]

        # (a) Each clean unmanaged copy is ADOPTED into the manifest with correct
        #     base_hash/base_content_hash + warn_on_drift + render_kind copy +
        #     live_lineage_version == source_version; live bytes UNCHANGED.
        for rel in adopt_rels:
            self.assertIn(rel, fb2, f"{rel} not adopted into the manifest")
            self.assertIn(rel, res.reconciled,
                          f"{rel} not classified reconciled (adopted)")
            known = self._known_copy_payload(rel, cap)
            self.assertEqual(fb2[rel]["base_content_hash"], _content_hash(known))
            self.assertEqual(fb2[rel]["base_hash"], _full_hash(known))
            self.assertEqual(fb2[rel]["merge_strategy"], "warn_on_drift")
            self.assertEqual(fb2[rel]["render_kind"], RENDER_KIND_COPY)
            self.assertEqual(fb2[rel][LIVE_LINEAGE_VERSION_FIELD], SOURCE_VERSION)
            self.assertEqual((proj / rel).read_bytes(), before_bytes[rel],
                             f"migration changed live bytes of adopted copy {rel}")

        # (b) The operator-edited unmanaged copy is NOT adopted (left for the
        #     collision/sidecar path); live bytes unchanged.
        self.assertNotIn(edited_rel, fb2,
                         "operator-edited unmanaged copy was adopted (lost the edit signal)")
        self.assertIn(edited_rel, res.operator_drift)
        self.assertEqual((proj / edited_rel).read_bytes(), before_bytes[edited_rel])


if __name__ == "__main__":
    unittest.main()
