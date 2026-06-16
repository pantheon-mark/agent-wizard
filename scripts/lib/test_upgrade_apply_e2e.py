"""Held-out END-TO-END test for the foundation-bundle merge-apply mutator.

Unlike test_upgrade_apply.py (which builds a SMALL synthetic build repo + synthetic
operator project), this test exercises the WHOLE real path on the REAL build repo:

  emit a real operator project on v0.4.0 (real transcript -> real generator -> real
  bundle) -> apply_upgrade(..., 'v0.5.0', real_repo) -> assert the v0.5.0 additive
  section migrates into the clean-adopted docs while operator edits are preserved.

It is "held-out" because nothing here is mocked: the v0.5.0 bundle, its migration
manifest, the registry entry, the replay capsule, and the manifest are all the real
artifacts the wizard ships. The test proves the version cut + the mutator compose
correctly on real inputs, which the synthetic unit tests cannot.

Setup of three managed-file conditions over the emitted estate:
  (a) hand-edit ONE operator_review doc (execution_plan.md) so it diverges from base
      -> expect routed to .wizard/upgrade-review/ with the LIVE file preserved.
  (b) leave the warn_on_drift doc (audit_framework.md) unchanged -> expect adopted
      cleanly (its rendered bytes changed at v0.5.0 only via the schema-version
      frontmatter bump, with no operator drift, so warn_on_drift adopts without ack).
  (c) leave a clean three_way doc (vision.md) unedited -> expect clean-adopt of the
      new Vision Recap section.
  (d) a SECOND emit where the three_way vision.md IS operator-edited -> expect the
      new version routed to a review sidecar and the LIVE file left exactly as edited
      (NO clobber, NO git markers).

Plus a conflict/refusal case: tamper a foundation doc's manifest base_hash so the
replay-conformance gate fails -> assert apply_upgrade REFUSES with NO live writes.

The estate is emitted with an explicit generator_version_override so the test does
not depend on a clean build worktree (the v0.5.0 cut leaves the tree dirty during the
slice; the real emit path fails closed on a dirty worktree by design).
"""

import json
import shutil
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
)
from upgrade_apply import (  # noqa: E402
    apply_upgrade,
    UpgradeApplyError,
    APPLY_RESULT_PARTIAL,
    APPLY_RESULT_APPLIED,
    FILE_ADOPTED,
    FILE_REVIEW,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"
TRANSCRIPT = Path.home() / "wizard-pilot-2026-06-01" / "wizard_transcript.jsonl"
SHAPE = "markdown-CC"
SOURCE_VERSION = "v0.4.0"
TARGET_VERSION = "v0.5.0"
# A real 40-char SHA (the slice HEAD when v0.5.0 was cut) so emit does not require a
# clean worktree. The value is opaque to the test's assertions; it only needs to be a
# stable, valid generator-version identity recorded in the emitted manifest + capsule.
_GEN_OVERRIDE = "c3b5609fbbe566d73f3097ff0d1cd087dfe19245"


def _have_prereqs() -> bool:
    if not TRANSCRIPT.exists():
        return False
    try:
        reg = load_registry(REGISTRY_PATH)
    except Exception:
        return False
    versions = {e.get("foundation_bundle_version") for e in reg.get("bundles", [])}
    return SOURCE_VERSION in versions and TARGET_VERSION in versions


@unittest.skipUnless(
    _have_prereqs(),
    f"requires the preserved pilot transcript at {TRANSCRIPT} and both "
    f"{SOURCE_VERSION} + {TARGET_VERSION} registered bundles",
)
class UpgradeApplyE2E(unittest.TestCase):
    """Real emit -> real apply over the real v0.4.0 -> v0.5.0 cut."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    # ---- helpers ----------------------------------------------------------

    def _emit_estate(self, name: str) -> Path:
        """Emit a fresh real operator project on v0.4.0 into the tmp dir."""
        proj = self.tmp / name
        cli.cmd_emit_system(
            str(TRANSCRIPT), SHAPE, str(proj), str(REPO_ROOT),
            bundle_version=SOURCE_VERSION,
            generator_version_override=_GEN_OVERRIDE,
        )
        # Sanity: emitted on the source version with the real foundation docs present.
        self.assertTrue((proj / ".wizard" / "manifest.json").exists())
        self.assertTrue((proj / ".wizard" / "replay-capsule.json").exists())
        self.assertTrue((proj / "vision.md").exists())
        m = json.loads((proj / ".wizard" / "manifest.json").read_text())
        self.assertEqual(m["foundation_bundle_version"], SOURCE_VERSION)
        return proj

    def _apply(self, proj: Path, *, ack=False):
        manifest_path = proj / ".wizard" / "manifest.json"
        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(REGISTRY_PATH)
        return apply_upgrade(
            proj, TARGET_VERSION, REPO_ROOT,
            registry=registry, registry_path=REGISTRY_PATH,
            manifest=manifest, manifest_path=manifest_path,
            ack=ack,
        )

    def _strategy(self, proj: Path, relpath: str) -> str:
        m = json.loads((proj / ".wizard" / "manifest.json").read_text())
        return m["managed_files"][relpath]["merge_strategy"]

    # ---- the main e2e ------------------------------------------------------

    def test_clean_estate_migrates_new_section_and_preserves_operator_edits(self):
        proj = self._emit_estate("estate-main")

        # The real estate's strategy roster (verifies the test's premise on real data).
        self.assertEqual(self._strategy(proj, "vision.md"), "three_way")
        self.assertEqual(self._strategy(proj, "execution_plan.md"), "operator_review")
        self.assertEqual(self._strategy(proj, "audit_framework.md"), "warn_on_drift")

        # (a) hand-edit one operator_review doc so it diverges from base.
        ep = proj / "execution_plan.md"
        operator_text = ep.read_text() + "\n\n## My own notes\nHand-written by the operator.\n"
        ep.write_text(operator_text, encoding="utf-8")

        # (c) clean three_way (vision.md) left unedited; (b) warn_on_drift left unchanged.
        vision_before = (proj / "vision.md").read_text()
        self.assertNotIn("## Vision Recap", vision_before)

        # An untracked operator file that the upgrade must not touch.
        untracked = proj / "my_personal_notes.md"
        untracked.write_text("nothing to do with the wizard\n", encoding="utf-8")

        res = self._apply(proj)

        # ---- replay-conformance passed (it didn't refuse on that ground) -----
        self.assertNotEqual(res.classification, "refused", res.refusal_reason)
        # operator_review doc in review => partial (not "applied").
        self.assertEqual(res.classification, APPLY_RESULT_PARTIAL)

        # ---- the new v0.5.0 section is present in the clean-adopted three_way doc.
        vision_after = (proj / "vision.md").read_text()
        self.assertIn("## Vision Recap", vision_after)
        self.assertIn("vision.md", res.files_written)
        vdec = next(d for d in res.decisions if d.relpath == "vision.md")
        self.assertEqual(vdec.disposition, FILE_ADOPTED)

        # ---- operator-edited operator_review doc: routed to review, LIVE preserved.
        self.assertIn("execution_plan.md", res.files_in_review)
        self.assertEqual(ep.read_text(), operator_text)  # NOT clobbered
        self.assertNotIn("<<<<<<<", ep.read_text())       # NO git markers
        review_dir = proj / ".wizard" / "upgrade-review" / f"{SOURCE_VERSION}-to-{TARGET_VERSION}"
        self.assertTrue((review_dir / "execution_plan.md.new").exists())
        self.assertTrue((review_dir / "execution_plan.md.diff").exists())
        self.assertTrue((review_dir / "execution_plan.md.ours").exists())
        # the .ours sidecar is the operator's edited content
        self.assertEqual((review_dir / "execution_plan.md.ours").read_text(), operator_text)
        # NO git markers leaked into the .new sidecar either
        self.assertNotIn("<<<<<<<", (review_dir / "execution_plan.md.new").read_text())

        # ---- warn_on_drift doc with no operator edits: adopted (no ack needed).
        audit_dec = next(d for d in res.decisions if d.relpath == "audit_framework.md")
        self.assertEqual(audit_dec.disposition, FILE_ADOPTED)
        self.assertFalse(audit_dec.drifted)

        # ---- untracked operator file untouched.
        self.assertEqual(untracked.read_text(), "nothing to do with the wizard\n")

        # ---- manifest advanced to v0.5.0; base_hash advanced ONLY for adopted files.
        nm = json.loads((proj / ".wizard" / "manifest.json").read_text())
        self.assertEqual(nm["foundation_bundle_version"], TARGET_VERSION)
        # vision (adopted): base_hash == hash of the new live bytes.
        vlive_hash = "sha256:" + sha256_bytes(vision_after.encode("utf-8"))
        self.assertEqual(nm["managed_files"]["vision.md"]["base_hash"], vlive_hash)
        # execution_plan (in review): base_hash NOT advanced to the operator's edited bytes.
        ep_live_hash = "sha256:" + sha256_bytes(operator_text.encode("utf-8"))
        self.assertNotEqual(nm["managed_files"]["execution_plan.md"]["base_hash"], ep_live_hash)

        # ---- history appended + backup exists.
        hist = proj / ".wizard" / "upgrade-history.log"
        self.assertTrue(hist.exists())
        self.assertIn(f"{SOURCE_VERSION} -> {TARGET_VERSION}", hist.read_text())
        self.assertTrue((proj / ".wizard" / "backups" / f"pre-{TARGET_VERSION}").exists())

    def test_operator_edited_three_way_routes_to_sidecar_live_untouched(self):
        """The new section lives in a three_way doc; when that doc is operator-edited the
        upgrade must NOT clean-adopt — it overlays a review sidecar and leaves the live
        file exactly as the operator left it (no git markers)."""
        proj = self._emit_estate("estate-vision-edited")
        self.assertEqual(self._strategy(proj, "vision.md"), "three_way")

        vision = proj / "vision.md"
        edited = vision.read_text() + "\n\n## Operator addendum\nI changed the vision.\n"
        vision.write_text(edited, encoding="utf-8")

        res = self._apply(proj)
        self.assertNotEqual(res.classification, "refused", res.refusal_reason)

        # vision.md routed to review, NOT written, live preserved verbatim.
        self.assertIn("vision.md", res.files_in_review)
        self.assertNotIn("vision.md", res.files_written)
        self.assertEqual(vision.read_text(), edited)        # live untouched
        self.assertNotIn("<<<<<<<", vision.read_text())     # no git markers

        review_dir = proj / ".wizard" / "upgrade-review" / f"{SOURCE_VERSION}-to-{TARGET_VERSION}"
        new_sidecar = review_dir / "vision.md.new"
        self.assertTrue(new_sidecar.exists())
        # the offered new version carries the additive section + the plain-language overlay note.
        new_body = new_sidecar.read_text()
        self.assertIn("## Vision Recap", new_body)
        self.assertIn("did NOT change your file", new_body)
        self.assertNotIn("<<<<<<<", new_body)

        # base_hash for vision NOT advanced (still represents the prior version).
        nm = json.loads((proj / ".wizard" / "manifest.json").read_text())
        live_hash = "sha256:" + sha256_bytes(edited.encode("utf-8"))
        self.assertNotEqual(nm["managed_files"]["vision.md"]["base_hash"], live_hash)

    def test_tampered_base_hash_refuses_with_no_live_writes(self):
        """Conflict case: corrupt a foundation doc's manifest base_hash so the
        replay-conformance gate fails. apply_upgrade must REFUSE and write nothing."""
        proj = self._emit_estate("estate-tampered")

        manifest_path = proj / ".wizard" / "manifest.json"
        m = json.loads(manifest_path.read_text())
        m["managed_files"]["vision.md"]["base_hash"] = "sha256:" + ("0" * 64)
        manifest_path.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # Snapshot every file's bytes to prove NOTHING is written on refusal.
        before = {
            p: p.read_bytes()
            for p in proj.rglob("*")
            if p.is_file() and ".wizard/backups" not in str(p)
        }

        with self.assertRaises(UpgradeApplyError) as ctx:
            self._apply(proj)
        self.assertIn("replay-conformance", str(ctx.exception).lower())

        after = {
            p: p.read_bytes()
            for p in proj.rglob("*")
            if p.is_file() and ".wizard/backups" not in str(p)
        }
        # No new files, no removed files, no mutated bytes (the tampered manifest is the
        # only pre-existing edit, and it must be unchanged by the refused apply).
        self.assertEqual(set(before), set(after), "refusal created/removed files")
        for p, b in before.items():
            self.assertEqual(after[p], b, f"refusal mutated {p}")
        # No review sidecars written either.
        self.assertFalse(
            (proj / ".wizard" / "upgrade-review").exists(),
            "refusal wrote review sidecars",
        )


if __name__ == "__main__":
    unittest.main()
