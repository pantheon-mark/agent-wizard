"""Tests for the foundation-bundle merge-apply mutator (upgrade_apply.apply_upgrade).

Anti-overfit posture: every test builds a SMALL synthetic build repo (a registry +
a v0/contracts required-docs contract + two synthetic foundation bundles with their
own templates + migration manifests) and a synthetic operator project (a manifest-v2
+ replay capsule + the rendered foundation docs). Nothing depends on a particular
real estate or on Phase 4's v0.5.0 (which does not exist yet).

The merge surface is the SIX template-backed foundation docs (vision / approach /
technical_architecture / execution_plan / test_cases / audit_framework). prd.md is a
schema-only stub independent of the bundle version, so it is base==theirs (no-op)
here.

Divergent fixtures: tests are parametrized across >=2 operator rosters that assign
DIFFERENT merge strategies to DIFFERENT docs, so an estate-specific assumption (e.g.
"vision is always three_way") fails.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generator import render_foundation_docs  # noqa: E402
from upgrade import sha256_bytes, load_operator_manifest, load_registry  # noqa: E402
from upgrade_apply import (  # noqa: E402
    apply_upgrade,
    UpgradeApplyError,
    APPLY_RESULT_APPLIED,
    APPLY_RESULT_PARTIAL,
    FILE_ADOPTED,
    FILE_MERGED,
    FILE_REVIEW,
    FILE_UNCHANGED,
)

# The real required-docs contract is the canonical authority for which docs exist +
# their default policy; copy it verbatim into each synthetic build repo so the
# generator's _read_required_foundation_docs resolves.
_REAL_REPO = Path(__file__).resolve().parents[3]
_REAL_CONTRACT = (
    _REAL_REPO / "wizard" / "foundation-bundles" / "v0" / "contracts"
    / "foundation-manifest-hash-baseline-v1.json"
)

# The six template-backed foundation docs (doc_name -> a tiny template body with a
# version marker + one placeholder fillable from the capsule inputs).
_TEMPLATE_DOCS = [
    "vision.md",
    "approach.md",
    "technical_architecture.md",
    "execution_plan.md",
    "test_cases.md",
    "audit_framework.md",
]

_CAPSULE_INPUTS = {
    "PROJECT_NAME": "Acme Helper",
    "WIZARD_VERSION": "v0.4.0",
}


def _template_body(doc_name: str, version_label: str, *, extra_placeholder: bool = False) -> str:
    """A small deterministic, MULTI-SECTION template body with STABLE ATX headings.

    `{{PROJECT_NAME}}` is the placeholder fillable from the capsule. The version label
    rides in the `## Overview` body only — the headings (`# {doc}`, `## Overview`,
    `## Details`) are stable across versions, so the section-aware merge sees real
    shared sections (not a heading rename every version). `## Details` is stable
    across versions, so an operator edit there is a non-overlapping change the merge
    can clean-resolve; `## Overview` changes between versions, so editing it conflicts."""
    body = (
        f"# {doc_name}\n\n"
        "Project: {{PROJECT_NAME}}\n\n"
        "## Overview\n\n"
        f"This is the ({version_label}) overview of {doc_name}.\n\n"
        "## Details\n\n"
        f"Stable details for {doc_name}.\n"
    )
    if extra_placeholder:
        # A NEW placeholder a migration would have to supply; absent from the capsule.
        body += "\n## New\n\nNew field: {{BRAND_NEW_KEY}}\n"
    return body


def _write_bundle(build_root: Path, version: str, *, doc_version_labels=None,
                  extra_placeholder_doc=None, migration_from="v0.4.0",
                  migration_class="minor-additive", stop_condition="", migration_extra=None):
    """Create a synthetic foundation bundle under build_root."""
    labels = doc_version_labels or {d: version for d in _TEMPLATE_DOCS}
    bundle_dir = build_root / "wizard" / "foundation-bundles" / version
    templates_dir = bundle_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    for doc in _TEMPLATE_DOCS:
        extra = (doc == extra_placeholder_doc)
        (templates_dir / doc).write_text(
            _template_body(doc, labels.get(doc, version), extra_placeholder=extra),
            encoding="utf-8",
        )
    # provenance sidecar (carries the generator_version the manifest bumps to)
    (bundle_dir / "foundation-bundle.provenance.json").write_text(
        json.dumps({"generator_version": f"{'g' * 39}{version[-1]}"}, indent=2) + "\n",
        encoding="utf-8",
    )
    # migration manifest
    migration = {
        "from": migration_from,
        "class": migration_class,
        "requires_operator_approval": True,
        "stop_condition": stop_condition,
        "breaking_changes_summary": "",
        "supported": True,
    }
    if migration_extra:
        migration.update(migration_extra)
    (bundle_dir / "migration-manifest.json").write_text(
        json.dumps({
            "target_version": version,
            "migrations": [migration],
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def _write_build_repo(tmp: Path, *, target_extra_placeholder_doc=None,
                      target_stop_condition="", base_version="v0.4.0",
                      target_version="v0.5.0", target_migration_class="minor-additive",
                      target_migration_extra=None):
    """Build a synthetic build repo with registry + contract + two bundles.
    Returns (build_root, registry_path)."""
    build_root = tmp / "build_repo"
    # required-docs contract (copied verbatim from the real authority)
    contract_dst = (build_root / "wizard" / "foundation-bundles" / "v0" / "contracts"
                    / "foundation-manifest-hash-baseline-v1.json")
    contract_dst.parent.mkdir(parents=True, exist_ok=True)
    contract_dst.write_text(_REAL_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")

    _write_bundle(build_root, base_version, migration_from=base_version)
    _write_bundle(build_root, target_version,
                  extra_placeholder_doc=target_extra_placeholder_doc,
                  migration_from=base_version, migration_class=target_migration_class,
                  stop_condition=target_stop_condition,
                  migration_extra=target_migration_extra)

    registry = {
        "schema_version": "v1",
        "bundles": [
            {"foundation_bundle_version": base_version,
             "path": f"wizard/foundation-bundles/{base_version}/",
             "source_commit": "aaa1111", "status": "prerelease"},
            {"foundation_bundle_version": target_version,
             "path": f"wizard/foundation-bundles/{target_version}/",
             "source_commit": "bbb2222", "status": "prerelease"},
        ],
    }
    registry_path = build_root / "wizard" / "registry" / "foundation-bundles.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return build_root, registry_path


def _strategy_roster(name: str):
    """Two divergent strategy assignments over the six docs. Each test runs both so a
    doc-specific assumption breaks."""
    if name == "A":
        return {
            "vision.md": "three_way",
            "approach.md": "three_way",
            "technical_architecture.md": "operator_review",
            "execution_plan.md": "warn_on_drift",
            "test_cases.md": "frozen",
            "audit_framework.md": "warn_on_drift",
        }
    # Roster B permutes the strategy<->doc mapping so no single doc is "always X".
    return {
        "vision.md": "operator_review",
        "approach.md": "frozen",
        "technical_architecture.md": "three_way",
        "execution_plan.md": "three_way",
        "test_cases.md": "warn_on_drift",
        "audit_framework.md": "operator_review",
    }


def _build_operator_project(tmp: Path, build_root: Path, *, base_version="v0.4.0",
                            roster="A", extra_unmanaged=True, lineage="__current__"):
    """Render the base-version foundation docs into a synthetic operator project +
    write a manifest-v2 (base_hash = the canonical hash of the rendered bytes) + a
    replay capsule. Returns (proj_dir, manifest_path, strategies)."""
    proj = tmp / f"operator_{roster}"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".wizard").mkdir(parents=True, exist_ok=True)

    rendered = render_foundation_docs(base_version, _CAPSULE_INPUTS, build_root)
    strategies = _strategy_roster(roster)
    managed_files = {}
    for rec in rendered:
        rel = rec.operator_relpath
        if rel not in strategies:
            # prd.md (schema-only stub) — write it but do NOT declare it a managed
            # template-backed doc in this synthetic manifest (it has no template).
            (proj / rel).write_text(rec.content, encoding="utf-8")
            continue
        (proj / rel).write_text(rec.content, encoding="utf-8")
        digest = "sha256:" + sha256_bytes(rec.content.encode("utf-8"))
        entry = {
            "managed": "true",
            "managed_by": "shared",
            "base_hash": digest,
            "current_hash_last_seen": digest,
            "local_modifications": "expected",
            "merge_strategy": strategies[rel],
            "source_refs": [],
        }
        # live_lineage_version: "__current__" sentinel => emit at the base
        # version (a freshly emitted project is uniformly eligible); None => OMIT the
        # field (a legacy manifest — not eligible, back-compat); any other value =>
        # stamp it verbatim (e.g. a stale version to test ineligibility).
        if lineage == "__current__":
            entry["live_lineage_version"] = base_version
        elif lineage is not None:
            entry["live_lineage_version"] = lineage
        managed_files[rel] = entry

    if extra_unmanaged:
        # An operator file NOT in the merge surface — must be left untouched.
        (proj / "my_notes.md").write_text("operator's own notes\n", encoding="utf-8")

    manifest = {
        "manifest_schema_version": "manifest-v2",
        "foundation_bundle_version": base_version,
        "source_commit": "aaa1111",
        "generator_version": "f" * 40,
        "project_name": "Acme Helper",
        "system_shape": "markdown-CC",
        "managed_files": managed_files,
        "control_files": [".wizard/manifest.json", ".wizard/upgrade-history.log"],
    }
    manifest_path = proj / ".wizard" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (proj / ".wizard" / "upgrade-history.log").write_text("# history\n", encoding="utf-8")

    capsule = {
        "schema_version": "replay-capsule-v1",
        "foundation_bundle_version": base_version,
        "generator_version": "f" * 40,
        "system_shape": "markdown-CC",
        "foundation_only_mode": False,
        "canonicalization_version": "v1",
        "hash_algorithm": "sha256-lf",
        "foundation_doc_inputs": dict(_CAPSULE_INPUTS),
    }
    (proj / ".wizard" / "replay-capsule.json").write_text(
        json.dumps(capsule, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proj, manifest_path, strategies


def _apply(proj, manifest_path, registry_path, build_root, target_version="v0.5.0",
           ack=False, backup=True):
    manifest = load_operator_manifest(manifest_path)
    registry = load_registry(registry_path)
    return apply_upgrade(
        proj, target_version, build_root,
        registry=registry, registry_path=registry_path,
        manifest=manifest, manifest_path=manifest_path,
        ack=ack, backup=backup,
    )


def _read(p):
    return Path(p).read_text(encoding="utf-8")


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


class ReplayConformanceTests(_Base):
    def test_replay_conformance_pass_then_apply_runs(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, _ = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            res = _apply(proj, mp, reg, build_root)
            # The gate passed (no refusal); classification is applied or partial.
            self.assertIn(res.classification, (APPLY_RESULT_APPLIED, APPLY_RESULT_PARTIAL),
                          f"roster {roster}")

    def test_tampered_base_hash_refuses(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, _ = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            # Tamper a base_hash so the re-render no longer matches.
            m = json.loads(_read(mp))
            first = sorted(m["managed_files"])[0]
            m["managed_files"][first]["base_hash"] = "sha256:" + "0" * 64
            mp.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            before = {d: _read(proj / d) for d in _TEMPLATE_DOCS}
            with self.assertRaises(UpgradeApplyError) as ctx:
                _apply(proj, mp, reg, build_root)
            self.assertIn("replay-conformance", str(ctx.exception).lower())
            # No live writes.
            for d in _TEMPLATE_DOCS:
                self.assertEqual(_read(proj / d), before[d], f"{roster}:{d} mutated on refusal")


class PerStrategyTests(_Base):
    def test_clean_three_way_adopts_theirs(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            tw_doc = next(d for d, s in strat.items() if s == "three_way")
            res = _apply(proj, mp, reg, build_root)
            self.assertIn(tw_doc, res.files_written, f"{roster}: clean three_way not adopted")
            # Live file == theirs (carries the v0.5.0 version label).
            self.assertIn("(v0.5.0)", _read(proj / tw_doc), f"{roster}:{tw_doc}")
            dec = next(d for d in res.decisions if d.relpath == tw_doc)
            self.assertEqual(dec.disposition, FILE_ADOPTED)

    def test_three_way_with_drift_sidecar_and_live_untouched(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            tw_doc = next(d for d, s in strat.items() if s == "three_way")
            # Operator edits the three_way doc.
            edited = "# my own edits\nkeep this\n"
            (proj / tw_doc).write_text(edited, encoding="utf-8")
            # Re-baseline the manifest so replay-conformance still passes (base_hash is
            # the ORIGINAL rendered bytes; the operator edit creates drift, not a
            # conformance failure). The conformance gate hashes the RE-RENDER vs
            # base_hash, which is unaffected by the live edit.
            res = _apply(proj, mp, reg, build_root)
            # Live file unchanged (= ours).
            self.assertEqual(_read(proj / tw_doc), edited, f"{roster}: live three_way clobbered")
            self.assertNotIn("<<<<<<<", _read(proj / tw_doc))
            # Sidecar written.
            dec = next(d for d in res.decisions if d.relpath == tw_doc)
            self.assertEqual(dec.disposition, FILE_REVIEW)
            new_sidecar = proj / ".wizard" / "upgrade-review" / res.upgrade_id / (tw_doc + ".new")
            self.assertTrue(new_sidecar.exists(), f"{roster}: no .new sidecar")
            self.assertNotIn("<<<<<<<", _read(new_sidecar))
            self.assertIn("(v0.5.0)", _read(new_sidecar))
            # Classification is partial (some files routed to review) => not success.
            self.assertEqual(res.classification, APPLY_RESULT_PARTIAL)

    def test_operator_review_routes_to_sidecar(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            orv_doc = next(d for d, s in strat.items() if s == "operator_review")
            before = _read(proj / orv_doc)
            res = _apply(proj, mp, reg, build_root)
            dec = next(d for d in res.decisions if d.relpath == orv_doc)
            self.assertEqual(dec.disposition, FILE_REVIEW, f"{roster}: operator_review not routed")
            self.assertEqual(_read(proj / orv_doc), before, f"{roster}: operator_review live changed")
            sidecar = proj / ".wizard" / "upgrade-review" / res.upgrade_id / (orv_doc + ".new")
            self.assertTrue(sidecar.exists())
            self.assertNotIn(orv_doc, res.files_written)

    def test_warn_on_drift_without_ack_refuses(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            won_doc = next(d for d, s in strat.items() if s == "warn_on_drift")
            (proj / won_doc).write_text("# operator-edited warn doc\n", encoding="utf-8")
            before = {d: _read(proj / d) for d in _TEMPLATE_DOCS}
            with self.assertRaises(UpgradeApplyError) as ctx:
                _apply(proj, mp, reg, build_root, ack=False)
            self.assertIn("--ack", str(ctx.exception))
            for d in _TEMPLATE_DOCS:
                self.assertEqual(_read(proj / d), before[d], f"{roster}:{d} mutated on warn refusal")

    def test_warn_on_drift_with_ack_adopts(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            won_doc = next(d for d, s in strat.items() if s == "warn_on_drift")
            (proj / won_doc).write_text("# operator-edited warn doc\n", encoding="utf-8")
            res = _apply(proj, mp, reg, build_root, ack=True)
            self.assertIn(won_doc, res.files_written, f"{roster}: ack'd warn not adopted")
            self.assertIn("(v0.5.0)", _read(proj / won_doc))

    def test_frozen_drift_hard_blocks(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            fz_doc = next(d for d, s in strat.items() if s == "frozen")
            (proj / fz_doc).write_text("# operator touched a frozen doc\n", encoding="utf-8")
            before = {d: _read(proj / d) for d in _TEMPLATE_DOCS}
            with self.assertRaises(UpgradeApplyError) as ctx:
                _apply(proj, mp, reg, build_root)
            self.assertIn("protected", str(ctx.exception).lower())
            for d in _TEMPLATE_DOCS:
                self.assertEqual(_read(proj / d), before[d], f"{roster}:{d} mutated on frozen block")

    def test_frozen_clean_adopts(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            fz_doc = next(d for d, s in strat.items() if s == "frozen")
            res = _apply(proj, mp, reg, build_root)
            self.assertIn(fz_doc, res.files_written, f"{roster}: clean frozen not adopted")
            self.assertIn("(v0.5.0)", _read(proj / fz_doc))


class MissingPlaceholderTests(_Base):
    def test_missing_target_placeholder_refuses(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(
                self.tmp / roster, target_extra_placeholder_doc="vision.md")
            proj, mp, _ = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            before = {d: _read(proj / d) for d in _TEMPLATE_DOCS}
            with self.assertRaises(UpgradeApplyError) as ctx:
                _apply(proj, mp, reg, build_root)
            msg = str(ctx.exception).lower()
            self.assertTrue("could not be rendered" in msg or "not available" in msg)
            for d in _TEMPLATE_DOCS:
                self.assertEqual(_read(proj / d), before[d], f"{roster}:{d} mutated on placeholder refusal")


class TransactionTests(_Base):
    def test_backup_created_and_history_appended(self):
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, _ = _build_operator_project(self.tmp, build_root, roster="A")
        res = _apply(proj, mp, reg, build_root)
        backup = proj / ".wizard" / "backups" / "pre-v0.5.0"
        self.assertTrue(backup.exists(), "backup dir not created")
        self.assertTrue((backup / ".wizard" / "manifest.json").exists())
        hist = _read(proj / ".wizard" / "upgrade-history.log")
        self.assertIn("v0.4.0 -> v0.5.0", hist)

    def test_manifest_base_hash_advanced_for_all_surviving_incl_routed(self):
        """Finding A dual-hash contract (was: '...advanced_only_for_adopted', which
        encoded the stuck-chain BUG — it asserted a routed file's base_hash was NOT
        advanced, which strands the file and fails the NEXT replay-conformance gate).

        Post-fix: base_hash advances to the TARGET render for EVERY surviving managed
        file (adopted AND routed). current_hash_last_seen advances ONLY for adopted —
        a routed file keeps its merge-ancestor pointer."""
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster="A")
        # Make the three_way doc drift so it routes to review (NOT adopted).
        tw_doc = next(d for d, s in strat.items() if s == "three_way")
        (proj / tw_doc).write_text("# drifted\n", encoding="utf-8")
        old_manifest = json.loads(_read(mp))
        old_tw_chls = old_manifest["managed_files"][tw_doc]["current_hash_last_seen"]

        res = _apply(proj, mp, reg, build_root)
        new_manifest = json.loads(_read(mp))
        self.assertEqual(new_manifest["foundation_bundle_version"], "v0.5.0")

        # The routed doc was NOT adopted, BUT its base_hash advances to the TARGET
        # render (the un-stuck-chain invariant), and base_content_hash too.
        theirs_routed = render_foundation_docs("v0.5.0", _CAPSULE_INPUTS, build_root)
        routed_target = next(r.content for r in theirs_routed if r.operator_relpath == tw_doc)
        self.assertEqual(
            new_manifest["managed_files"][tw_doc]["base_hash"],
            "sha256:" + sha256_bytes(routed_target.encode("utf-8")),
            "routed file's base_hash not advanced to the target render (stuck chain)",
        )
        self.assertIn("base_content_hash", new_manifest["managed_files"][tw_doc])
        # current_hash_last_seen for the ROUTED file is preserved (merge ancestor),
        # NOT advanced to the live drifted bytes or the target.
        self.assertEqual(new_manifest["managed_files"][tw_doc]["current_hash_last_seen"],
                         old_tw_chls,
                         "routed file's current_hash_last_seen clobbered (lost merge ancestor)")
        # An adopted file's base_hash == the freshly written theirs bytes; its
        # current_hash_last_seen advances too.
        for adopted in res.files_written:
            theirs = _read(proj / adopted)
            adopted_hash = "sha256:" + sha256_bytes(theirs.encode("utf-8"))
            self.assertEqual(new_manifest["managed_files"][adopted]["base_hash"],
                             adopted_hash, f"{adopted}: base_hash != written bytes")
            self.assertEqual(new_manifest["managed_files"][adopted]["current_hash_last_seen"],
                             adopted_hash, f"{adopted}: current_hash_last_seen not advanced")
        # generator_version bumped to the target bundle's provenance value.
        self.assertNotEqual(new_manifest["generator_version"], "f" * 40)

    def test_touch_only_managed_unrelated_file_untouched(self):
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, _ = _build_operator_project(self.tmp, build_root, roster="A")
        before = _read(proj / "my_notes.md")
        _apply(proj, mp, reg, build_root)
        self.assertEqual(_read(proj / "my_notes.md"), before, "unrelated operator file touched")

    def test_staged_validation_failure_rolls_back(self):
        """Force a staged post-validation mismatch and assert NO live writes survive."""
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, _ = _build_operator_project(self.tmp, build_root, roster="A")
        before = {d: _read(proj / d) for d in _TEMPLATE_DOCS}
        before_manifest = _read(mp)

        import upgrade_apply as ua
        real_sha = ua.sha256_file

        # Make the post-validation re-hash disagree with the intended bytes by
        # corrupting sha256_file's verdict during the staged-validation step only.
        def _broken_sha(path):
            return "deadbeef" + ("0" * 56)
        ua.sha256_file = _broken_sha
        try:
            with self.assertRaises(UpgradeApplyError) as ctx:
                _apply(proj, mp, reg, build_root)
            self.assertIn("staged-validation", str(ctx.exception).lower())
        finally:
            ua.sha256_file = real_sha
        # No live writes survive.
        for d in _TEMPLATE_DOCS:
            self.assertEqual(_read(proj / d), before[d], f"{d} mutated despite rollback")
        self.assertEqual(_read(mp), before_manifest, "manifest mutated despite rollback")


class RecomputeManifestInvariantTests(unittest.TestCase):
    """Direct unit tests of the dual-hash manifest recompute (Finding A). These do not
    need a real dropped-file bundle — they call _recompute_manifest with synthetic
    inputs to pin the input-independent invariants of the fix."""

    def _manifest(self):
        """A minimal manifest-v2 with three managed foundation docs at a base render."""
        base_v = {
            "a.md": "# a v1\nbody\n",
            "b.md": "# b v1\nbody\n",
            "c.md": "# c v1\nbody\n",
        }
        managed = {}
        for rel, content in base_v.items():
            digest = "sha256:" + sha256_bytes(content.encode("utf-8"))
            cdigest = "sha256:" + sha256_bytes(content.encode("utf-8"))  # no schema field -> same
            managed[rel] = {
                "managed": "true",
                "managed_by": "shared",
                "base_hash": digest,
                "base_content_hash": cdigest,
                "current_hash_last_seen": digest,
                "local_modifications": "expected",
                "merge_strategy": "three_way",
                "source_refs": [],
            }
        return {
            "manifest_schema_version": "manifest-v2",
            "foundation_bundle_version": "v0.4.0",
            "source_commit": "aaa1111",
            "generator_version": "f" * 40,
            "managed_files": managed,
        }, base_v

    def _recompute(self, manifest, theirs_rendered, staged_writes):
        import upgrade_apply as ua
        foundation_entries = manifest["managed_files"]
        return ua._recompute_manifest(
            manifest, {"source_commit": "bbb2222"}, "v0.5.0",
            staged_writes, foundation_entries, "g" * 40,
            theirs_rendered=theirs_rendered,
        )

    def test_base_hash_advances_for_all_surviving_files(self):
        """BOTH base_hash + base_content_hash advance to the target render for EVERY
        surviving managed file — adopted, routed, AND content-unchanged."""
        manifest, _ = self._manifest()
        theirs = {
            "a.md": "# a v2\nNEW body\n",   # adopted (in staged_writes)
            "b.md": "# b v2\nNEW body\n",   # routed (NOT in staged_writes)
            "c.md": "# c v1\nbody\n",       # content-unchanged
        }
        staged = {"a.md": theirs["a.md"]}  # only a.md cleanly adopted
        nm = self._recompute(manifest, theirs, staged)
        mf = nm["managed_files"]
        for rel in ("a.md", "b.md", "c.md"):
            exp_full = "sha256:" + sha256_bytes(theirs[rel].encode("utf-8"))
            self.assertEqual(mf[rel]["base_hash"], exp_full,
                             f"{rel}: base_hash not advanced to target render")
            self.assertIn("base_content_hash", mf[rel])

    def test_current_hash_last_seen_advances_only_for_adopted(self):
        """current_hash_last_seen advances ONLY for cleanly adopted files (staged_writes);
        the merge-ancestor pointer is preserved for routed/unchanged files."""
        manifest, base_v = self._manifest()
        theirs = {
            "a.md": "# a v2\nNEW body\n",
            "b.md": "# b v2\nNEW body\n",   # routed
            "c.md": "# c v1\nbody\n",
        }
        staged = {"a.md": theirs["a.md"]}
        old_b_chls = manifest["managed_files"]["b.md"]["current_hash_last_seen"]
        old_c_chls = manifest["managed_files"]["c.md"]["current_hash_last_seen"]
        nm = self._recompute(manifest, theirs, staged)
        mf = nm["managed_files"]
        self.assertEqual(mf["a.md"]["current_hash_last_seen"],
                         "sha256:" + sha256_bytes(theirs["a.md"].encode("utf-8")))
        self.assertEqual(mf["b.md"]["current_hash_last_seen"], old_b_chls,
                         "routed file's current_hash_last_seen clobbered (lost merge ancestor)")
        self.assertEqual(mf["c.md"]["current_hash_last_seen"], old_c_chls)

    def test_dropped_file_is_popped(self):
        """A managed file absent from theirs_rendered (the target dropped it) is POPPED
        from the new manifest, so the next gate does not fail on 'not produced by the
        current render surface'."""
        manifest, _ = self._manifest()
        theirs = {  # c.md dropped
            "a.md": "# a v2\nNEW\n",
            "b.md": "# b v2\nNEW\n",
        }
        staged = {"a.md": theirs["a.md"], "b.md": theirs["b.md"]}
        nm = self._recompute(manifest, theirs, staged)
        self.assertNotIn("c.md", nm["managed_files"], "dropped file not popped")
        self.assertIn("a.md", nm["managed_files"])
        self.assertIn("b.md", nm["managed_files"])

    def test_legacy_manifest_without_base_content_hash_backfilled_not_false_routed(self):
        """A legacy manifest entry lacking base_content_hash must, after recompute, gain
        a base_content_hash (advanced to target) rather than being left absent. The
        in-memory backfill at change-detection time is exercised separately via apply;
        here we pin that recompute always WRITES base_content_hash for survivors."""
        manifest, _ = self._manifest()
        for rel in manifest["managed_files"]:
            manifest["managed_files"][rel].pop("base_content_hash", None)
        theirs = {
            "a.md": "# a v2\nNEW\n",
            "b.md": "# b v2\nNEW\n",
            "c.md": "# c v1\nbody\n",
        }
        staged = {"a.md": theirs["a.md"]}
        nm = self._recompute(manifest, theirs, staged)
        from upgrade import normalize_for_content_hash
        for rel in ("a.md", "b.md", "c.md"):
            self.assertIn("base_content_hash", nm["managed_files"][rel],
                          f"{rel}: base_content_hash not written on recompute")
            exp = "sha256:" + sha256_bytes(
                normalize_for_content_hash(theirs[rel]).encode("utf-8"))
            self.assertEqual(nm["managed_files"][rel]["base_content_hash"], exp)


class NormalizeForContentHashTests(unittest.TestCase):
    """The shared normalizer surgically blanks ONLY the foundation_schema_version value."""

    def test_only_schema_version_value_blanked(self):
        from upgrade import normalize_for_content_hash
        text = (
            "---\n"
            "foundation_schema_version: v0.4\n"
            "managed_by: shared\n"
            "---\n"
            "# Title\n\nbody\n"
        )
        out = normalize_for_content_hash(text)
        # The schema-version VALUE is normalized away...
        self.assertIn("foundation_schema_version: <normalized>", out)
        self.assertNotIn("v0.4", out)
        # ...but everything else (incl. other frontmatter like managed_by) is preserved.
        self.assertIn("managed_by: shared", out)
        self.assertIn("# Title", out)
        self.assertIn("body", out)

    def test_schema_bump_only_yields_identical_normalized_content(self):
        from upgrade import normalize_for_content_hash
        v1 = "foundation_schema_version: v0.3\n# T\nbody\n"
        v2 = "foundation_schema_version: v0.4\n# T\nbody\n"
        self.assertEqual(normalize_for_content_hash(v1), normalize_for_content_hash(v2))

    def test_body_change_is_not_masked(self):
        from upgrade import normalize_for_content_hash
        v1 = "foundation_schema_version: v0.3\n# T\nbody one\n"
        v2 = "foundation_schema_version: v0.4\n# T\nbody TWO\n"
        self.assertNotEqual(normalize_for_content_hash(v1), normalize_for_content_hash(v2))

    def test_other_frontmatter_change_is_not_masked(self):
        from upgrade import normalize_for_content_hash
        v1 = "managed_by: shared\nfoundation_schema_version: v0.3\nbody\n"
        v2 = "managed_by: operator\nfoundation_schema_version: v0.3\nbody\n"
        self.assertNotEqual(normalize_for_content_hash(v1), normalize_for_content_hash(v2))


class GuardTests(_Base):
    def test_unknown_target_version_refuses(self):
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, _ = _build_operator_project(self.tmp, build_root, roster="A")
        with self.assertRaises(UpgradeApplyError):
            _apply(proj, mp, reg, build_root, target_version="v9.9.9")

    def test_missing_capsule_refuses(self):
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, _ = _build_operator_project(self.tmp, build_root, roster="A")
        (proj / ".wizard" / "replay-capsule.json").unlink()
        with self.assertRaises(UpgradeApplyError) as ctx:
            _apply(proj, mp, reg, build_root)
        self.assertIn("capsule", str(ctx.exception).lower())

    def test_stop_condition_refuses(self):
        build_root, reg = _write_build_repo(self.tmp, target_stop_condition="manual data migration required")
        proj, mp, _ = _build_operator_project(self.tmp, build_root, roster="A")
        before = {d: _read(proj / d) for d in _TEMPLATE_DOCS}
        with self.assertRaises(UpgradeApplyError) as ctx:
            _apply(proj, mp, reg, build_root)
        self.assertIn("stop condition", str(ctx.exception).lower())
        for d in _TEMPLATE_DOCS:
            self.assertEqual(_read(proj / d), before[d])

    def test_no_migration_from_current_refuses(self):
        # Build a repo whose target migration declares from a DIFFERENT version.
        build_root, reg = _write_build_repo(self.tmp)
        # Rewrite the target migration manifest to not match v0.4.0.
        mm = build_root / "wizard" / "foundation-bundles" / "v0.5.0" / "migration-manifest.json"
        data = json.loads(mm.read_text())
        data["migrations"][0]["from"] = "v0.1.0"
        mm.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        proj, mp, _ = _build_operator_project(self.tmp, build_root, roster="A")
        with self.assertRaises(UpgradeApplyError) as ctx:
            _apply(proj, mp, reg, build_root)
        self.assertIn("migration path", str(ctx.exception).lower())


class SectionMergeIntegrationTests(_Base):
    """The real section-aware text-merge driver wired into the drifted three_way
    branch. A drifted three_way file whose live descends from the current render
    (live_lineage_version == current_version) is section-merged: a clean merge writes the
    merged content live and is treated as adopted; a conflicting/ambiguous merge falls
    back to the existing review sidecar (live untouched, no git markers). A file that does
    NOT descend from the current render keeps routing (never merged against a wrong base)."""

    def _edit_details(self, proj: Path, doc: str, new_details: str) -> str:
        """Edit ONLY the stable `## Details` section of a doc (a section the target does
        not change), leaving the version-bearing `## Overview` as rendered. Returns the
        edited text. This is a non-overlapping operator edit the merge can clean-resolve."""
        live = _read(proj / doc)
        edited = live.replace(
            f"## Details\n\nStable details for {doc}.\n",
            f"## Details\n\n{new_details}\n",
        )
        assert edited != live, f"details edit did not apply for {doc}"
        (proj / doc).write_text(edited, encoding="utf-8")
        return edited

    def test_clean_section_merge_adopts_merged_when_eligible(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            tw = next(d for d, s in strat.items() if s == "three_way")
            edited = self._edit_details(proj, tw, "Operator-customized details kept.")

            res = _apply(proj, mp, reg, build_root)

            dec = next(d for d in res.decisions if d.relpath == tw)
            self.assertEqual(dec.disposition, FILE_MERGED,
                             f"{roster}: clean non-overlapping edit not section-merged")
            merged_live = _read(proj / tw)
            # The merged live carries BOTH the operator's Details edit AND the target's
            # new Overview — and never a git marker.
            self.assertIn("Operator-customized details kept.", merged_live)
            self.assertIn("(v0.5.0)", merged_live)
            self.assertNotIn("<<<<<<<", merged_live)
            # Merged files are written (not routed) -> not in review.
            self.assertIn(tw, res.files_written)
            self.assertNotIn(tw, res.files_in_review)
            # The operator's original edit is preserved within the merge result.
            self.assertIn("Operator-customized details kept.", edited)

    def test_conflicting_section_routes_to_sidecar_live_untouched(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            tw = next(d for d, s in strat.items() if s == "three_way")
            # Edit the SAME section the target changes (## Overview) differently -> conflict.
            live = _read(proj / tw)
            conflicting = live.replace(
                f"This is the (v0.4.0) overview of {tw}.",
                "Operator rewrote the overview entirely.",
            )
            self.assertNotEqual(conflicting, live)
            (proj / tw).write_text(conflicting, encoding="utf-8")

            res = _apply(proj, mp, reg, build_root)

            dec = next(d for d in res.decisions if d.relpath == tw)
            self.assertEqual(dec.disposition, FILE_REVIEW,
                             f"{roster}: conflicting edit not routed to sidecar")
            self.assertEqual(_read(proj / tw), conflicting, f"{roster}: live clobbered on conflict")
            self.assertNotIn("<<<<<<<", _read(proj / tw))
            self.assertNotIn(tw, res.files_written)
            sidecar = proj / ".wizard" / "upgrade-review" / res.upgrade_id / (tw + ".new")
            self.assertTrue(sidecar.exists())
            self.assertEqual(res.classification, APPLY_RESULT_PARTIAL)

    def test_stale_lineage_routes_never_merged(self):
        """A file whose live_lineage_version != current version does NOT descend from the
        current render, so a 3-way merge would run against the WRONG base. Even a
        would-be-clean non-overlapping edit must route to the sidecar, never merge."""
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root,
                                                      roster=roster, lineage="v0.1.0")
            tw = next(d for d, s in strat.items() if s == "three_way")
            self._edit_details(proj, tw, "Operator-customized details kept.")

            res = _apply(proj, mp, reg, build_root)

            dec = next(d for d in res.decisions if d.relpath == tw)
            self.assertEqual(dec.disposition, FILE_REVIEW,
                             f"{roster}: stale-lineage file was merged (wrong base risk)")
            self.assertNotIn(tw, res.files_written)

    def test_legacy_manifest_without_lineage_routes_never_merged(self):
        """A legacy manifest entry lacking live_lineage_version is treated as NOT eligible
        (safe back-compat) — a drifted three_way routes to sidecar rather than merging."""
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root,
                                                      roster=roster, lineage=None)
            tw = next(d for d, s in strat.items() if s == "three_way")
            self._edit_details(proj, tw, "Operator-customized details kept.")

            res = _apply(proj, mp, reg, build_root)

            dec = next(d for d in res.decisions if d.relpath == tw)
            self.assertEqual(dec.disposition, FILE_REVIEW,
                             f"{roster}: legacy (no-lineage) file was merged")

    def test_render_apply_result_names_merged_files_distinctly(self):
        from upgrade_apply import render_apply_result
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster="A")
        tw = next(d for d, s in strat.items() if s == "three_way")
        self._edit_details(proj, tw, "Operator-customized details kept.")
        res = _apply(proj, mp, reg, build_root)
        out = render_apply_result(res)
        # The merged doc is reported as MERGED (operator edits combined), not silently
        # lumped under a plain "updated" list, and never with git-marker jargon.
        self.assertIn(tw, out)
        self.assertIn("merged", out.lower())
        self.assertNotIn("<<<<<<<", out)

    def test_clean_merge_advances_hashes_and_lineage(self):
        """Manifest semantics after a clean merge (design §4): base_hash + base_content_hash
        advance to the TARGET render; current_hash_last_seen advances to the MERGED live
        bytes; live_lineage_version advances to the target (lineage restored to current)."""
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster="A")
        tw = next(d for d, s in strat.items() if s == "three_way")
        self._edit_details(proj, tw, "Operator-customized details kept.")

        res = _apply(proj, mp, reg, build_root)
        merged_live = _read(proj / tw)
        nm = json.loads(_read(mp))
        entry = nm["managed_files"][tw]

        target = next(r.content for r in render_foundation_docs("v0.5.0", _CAPSULE_INPUTS, build_root)
                      if r.operator_relpath == tw)
        self.assertEqual(entry["base_hash"], "sha256:" + sha256_bytes(target.encode("utf-8")),
                         "base_hash not advanced to target render after clean merge")
        self.assertEqual(entry["current_hash_last_seen"],
                         "sha256:" + sha256_bytes(merged_live.encode("utf-8")),
                         "current_hash_last_seen not advanced to merged-live bytes")
        self.assertEqual(entry["live_lineage_version"], "v0.5.0",
                         "live_lineage_version not advanced to target after clean merge")

    def test_routed_three_way_leaves_lineage_unchanged(self):
        """A routed (conflicting) three_way file keeps its prior live_lineage_version so it
        stays ineligible next upgrade (keeps routing until reconciled) — while base_hash
        still advances (the un-stuck-chain invariant)."""
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster="A")
        tw = next(d for d, s in strat.items() if s == "three_way")
        live = _read(proj / tw)
        (proj / tw).write_text(
            live.replace(f"This is the (v0.4.0) overview of {tw}.", "Operator overview rewrite."),
            encoding="utf-8")

        res = _apply(proj, mp, reg, build_root)
        dec = next(d for d in res.decisions if d.relpath == tw)
        self.assertEqual(dec.disposition, FILE_REVIEW)
        nm = json.loads(_read(mp))
        # lineage left at the pre-upgrade value (v0.4.0), NOT advanced to v0.5.0.
        self.assertEqual(nm["managed_files"][tw]["live_lineage_version"], "v0.4.0",
                         "routed file's lineage wrongly advanced (would re-enable a wrong-base merge)")


class TransactionHardeningTests2(_Base):
    """Design §5 hardening: an OSError mid-commit (after review sidecars + content are
    already in the live tree) must roll back EVERYTHING — restore the live docs + manifest
    from the backup AND remove the partially-written review sidecars — and surface a
    refusal, never leave a half-applied tree."""

    def test_oserror_during_commit_rolls_back_and_removes_sidecars(self):
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster="A")
        # Conflict one three_way doc (operator replaces the heading the target edits) so a
        # review sidecar is written; other docs adopt (content writes).
        tw = next(d for d, s in strat.items() if s == "three_way")
        (proj / tw).write_text("# operator total rewrite\nno shared sections\n", encoding="utf-8")
        before = {d: _read(proj / d) for d in _TEMPLATE_DOCS}
        before_manifest = _read(mp)

        import upgrade_apply as ua
        real = ua._atomic_replace

        def flaky(src, dest):
            # Fail when committing the manifest — by then sidecars + content are in live.
            if str(dest).endswith("manifest.json"):
                raise OSError("disk full (injected)")
            return real(src, dest)

        ua._atomic_replace = flaky
        try:
            with self.assertRaises(UpgradeApplyError):
                _apply(proj, mp, reg, build_root)
        finally:
            ua._atomic_replace = real

        # All live docs + manifest rolled back to their pre-apply bytes.
        for d in _TEMPLATE_DOCS:
            self.assertEqual(_read(proj / d), before[d], f"{d} not rolled back after OSError")
        self.assertEqual(_read(mp), before_manifest, "manifest not rolled back after OSError")
        # The conflicting operator edit is preserved (live = ours).
        self.assertEqual(_read(proj / tw), "# operator total rewrite\nno shared sections\n")
        # No review sidecars left behind.
        self.assertFalse((proj / ".wizard" / "upgrade-review").exists(),
                         "review sidecars left behind after rollback")


class MigrationOptOutTests(_Base):
    """Design §6: a release may force sidecar-only (disable auto-merge) — e.g. a
    major/structural release that renames/reorders/rewrites sections, where a
    section-keyed merge could silently combine across a structural change. An explicit
    migration `auto_merge: false` forces routing; major-breaking releases default OFF;
    minor/patch releases default ON."""

    def _edit_details(self, proj: Path, doc: str) -> str:
        live = _read(proj / doc)
        edited = live.replace(f"## Details\n\nStable details for {doc}.\n",
                              "## Details\n\nOperator-customized details kept.\n")
        assert edited != live, f"details edit did not apply for {doc}"
        (proj / doc).write_text(edited, encoding="utf-8")
        return edited

    def test_explicit_auto_merge_false_forces_sidecar(self):
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster,
                                                target_migration_extra={"auto_merge": False})
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            tw = next(d for d, s in strat.items() if s == "three_way")
            self._edit_details(proj, tw)
            res = _apply(proj, mp, reg, build_root)
            dec = next(d for d in res.decisions if d.relpath == tw)
            self.assertEqual(dec.disposition, FILE_REVIEW,
                             f"{roster}: auto_merge:false did not force the sidecar")

    def test_major_breaking_defaults_to_sidecar(self):
        build_root, reg = _write_build_repo(self.tmp, target_version="v1.0.0",
                                            target_migration_class="major-breaking")
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster="A")
        tw = next(d for d, s in strat.items() if s == "three_way")
        self._edit_details(proj, tw)
        res = _apply(proj, mp, reg, build_root, target_version="v1.0.0")
        dec = next(d for d in res.decisions if d.relpath == tw)
        self.assertEqual(dec.disposition, FILE_REVIEW,
                         "major-breaking release auto-merged by default (should default off)")

    def test_major_breaking_explicit_auto_merge_true_merges(self):
        build_root, reg = _write_build_repo(self.tmp, target_version="v1.0.0",
                                            target_migration_class="major-breaking",
                                            target_migration_extra={"auto_merge": True})
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster="A")
        tw = next(d for d, s in strat.items() if s == "three_way")
        self._edit_details(proj, tw)
        res = _apply(proj, mp, reg, build_root, target_version="v1.0.0")
        dec = next(d for d in res.decisions if d.relpath == tw)
        self.assertEqual(dec.disposition, FILE_MERGED,
                         "explicit auto_merge:true on a major release did not merge")

    def test_minor_additive_merges_by_default(self):
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster="A")
        tw = next(d for d, s in strat.items() if s == "three_way")
        self._edit_details(proj, tw)
        res = _apply(proj, mp, reg, build_root)
        dec = next(d for d in res.decisions if d.relpath == tw)
        self.assertEqual(dec.disposition, FILE_MERGED)


class DriftReportReconciliationTests(_Base):
    """compute_drift_report (plan-only upgrade-check) must agree with apply_upgrade on what
    counts as operator drift. Both key off the content-normalized hash (base_content_hash)
    so a pure foundation_schema_version frontmatter difference — which arises after an
    upgrade advances base_hash to a target render whose only delta on a content-unchanged
    doc is the write-only schema-version bump — is NOT reported as drift by the plan while
    the apply treats it as clean."""

    def _manifest(self, *, with_content_hash: bool):
        from upgrade import sha256_bytes, normalize_for_content_hash
        # Live file: schema v0.3 + body. base_hash = the FULL hash of a render whose only
        # difference is the bumped schema value (v0.4) -> mismatches the live full hash.
        live = "---\nfoundation_schema_version: v0.3\n---\n# T\n\nbody\n"
        (self.tmp / "vision.md").write_text(live, encoding="utf-8")
        target_render = "---\nfoundation_schema_version: v0.4\n---\n# T\n\nbody\n"
        base_hash = "sha256:" + sha256_bytes(target_render.encode("utf-8"))
        base_content = "sha256:" + sha256_bytes(
            normalize_for_content_hash(target_render).encode("utf-8"))
        entry = {
            "managed": "true", "managed_by": "shared",
            "base_hash": base_hash, "current_hash_last_seen": base_hash,
            "local_modifications": "expected", "merge_strategy": "operator_review",
            "source_refs": [],
        }
        if with_content_hash:
            entry["base_content_hash"] = base_content
        return {
            "manifest_schema_version": "manifest-v2",
            "foundation_bundle_version": "v0.5.0",
            "generator_version": "f" * 40,
            "managed_files": {"vision.md": entry},
        }

    def test_schema_only_difference_not_drift_when_content_hash_present(self):
        from upgrade import compute_drift_report, DRIFT_NONE
        report = compute_drift_report(self.tmp, self._manifest(with_content_hash=True))
        self.assertEqual(report.entries[0].status, DRIFT_NONE,
                         "plan-only reports a pure schema-version diff as drift (disagrees with apply)")

    def test_real_body_edit_still_reported_as_drift(self):
        from upgrade import compute_drift_report, DRIFT_DETECTED
        m = self._manifest(with_content_hash=True)
        (self.tmp / "vision.md").write_text(
            "---\nfoundation_schema_version: v0.3\n---\n# T\n\nEDITED body\n", encoding="utf-8")
        report = compute_drift_report(self.tmp, m)
        self.assertEqual(report.entries[0].status, DRIFT_DETECTED)

    def test_legacy_manifest_without_content_hash_uses_full_hash(self):
        # No base_content_hash -> legacy full-hash comparison (back-compat); the live full
        # hash != base_hash (schema differs) -> DRIFT_DETECTED under the legacy path.
        from upgrade import compute_drift_report, DRIFT_DETECTED
        report = compute_drift_report(self.tmp, self._manifest(with_content_hash=False))
        self.assertEqual(report.entries[0].status, DRIFT_DETECTED)


if __name__ == "__main__":
    unittest.main()
