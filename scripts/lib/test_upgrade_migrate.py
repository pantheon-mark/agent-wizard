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
    _replay_conformance_check,
    _foundation_managed_entries,
    _render_version,
    LIVE_LINEAGE_VERSION_FIELD,
    RENDER_KIND_RENDER,
    CONTRACT_BASENAME,
)
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


if __name__ == "__main__":
    unittest.main()
