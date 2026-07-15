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
import os
import stat
import subprocess
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

    def test_operator_review_survives_global_ack(self):
        """Blast-radius guard: --ack is a single GLOBAL flag. When the operator
        passes it to deliver a wizard warn_on_drift file, a correctly-classified
        operator_review file (their accumulated rules/registries) must STILL route to the
        sidecar with the live file preserved -- --ack must never collaterally clobber it."""
        for roster in ("A", "B"):
            build_root, reg = _write_build_repo(self.tmp / roster)
            proj, mp, strat = _build_operator_project(self.tmp / roster, build_root, roster=roster)
            orv_doc = next(d for d, s in strat.items() if s == "operator_review")
            edited = "# operator-edited operator_review doc\nkeep my accumulated content\n"
            (proj / orv_doc).write_text(edited, encoding="utf-8")
            res = _apply(proj, mp, reg, build_root, ack=True)
            dec = next(d for d in res.decisions if d.relpath == orv_doc)
            self.assertEqual(dec.disposition, FILE_REVIEW,
                             f"{roster}: operator_review not routed under global --ack")
            self.assertEqual(_read(proj / orv_doc), edited,
                             f"{roster}: operator_review live clobbered by global --ack")
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

    def test_drift_report_uses_target_contract_merge_strategy_precedence(self):
        """Plan/apply consistency: the plan must resolve merge_strategy with the SAME target-
        contract precedence as the apply, so a STALE manifest (warn_on_drift) does not make
        the plan warn the operator a file is at overwrite-risk when the apply will actually
        operator_review (sidecar-and-preserve) it. Plan must not lie about the apply."""
        from upgrade import sha256_bytes, normalize_for_content_hash, compute_drift_report
        live = "# Rules Library\n\nmy accumulated rule\n"
        (self.tmp / "quality").mkdir()
        (self.tmp / "quality" / "rules_library.md").write_text(live, encoding="utf-8")
        h = "sha256:" + sha256_bytes(live.encode("utf-8"))
        ch = "sha256:" + sha256_bytes(normalize_for_content_hash(live).encode("utf-8"))
        manifest = {
            "manifest_schema_version": "manifest-v2",
            "foundation_bundle_version": "v0.6.0",
            "managed_files": {"quality/rules_library.md": {
                "managed": "true", "managed_by": "wizard",
                "base_hash": h, "base_content_hash": ch, "current_hash_last_seen": h,
                "local_modifications": "not_recommended",
                "merge_strategy": "warn_on_drift",  # STALE manifest value
                "source_refs": [],
            }},
        }
        target_contract = {"quality/rules_library.md": {
            "relpath": "quality/rules_library.md", "delivery": "wizard",
            "merge_strategy": "operator_review",
        }}
        report = compute_drift_report(self.tmp, manifest, "v0.6.1",
                                      target_contract=target_contract)
        self.assertEqual(
            report.entries[0].merge_strategy, "operator_review",
            "plan ignored target-contract precedence; would mislabel a stale warn_on_drift file "
            "the apply will actually operator_review",
        )

    def test_three_way_drift_plan_action_reflects_landed_merge_driver(self):
        # The plan-only action text for a drifted three_way doc must reflect that the
        # apply path now section-merges (the driver landed) — not the stale "deferred to
        # follow-on slice" wording the upgrade-check surfaced to operators.
        from upgrade import _plan_action_for, DRIFT_DETECTED, MERGE_STRATEGY_THREE_WAY
        action = _plan_action_for(DRIFT_DETECTED, MERGE_STRATEGY_THREE_WAY)
        self.assertIn("merge", action.lower())
        self.assertNotIn("deferred", action.lower())
        self.assertNotIn("follow-on", action.lower())


class MergeSurfaceTests(_Base):
    """The merge surface MUST be sourced from the TARGET bundle's
    managed-artifacts contract (system-artifacts.json, delivery=='wizard'), NOT from
    _render_version(current).keys(). Without this, a system whose current bundle
    predates the operating layer never sees the operating-layer files the target adds:
    the upgrade reports 'applied' while delivering nothing."""

    def _target_contract(self, *, op_relpath="operating_discipline.md",
                         op_render_kind="copy", include_collision_only=False):
        """A minimal target system-artifacts.json: the six foundation docs (delivery
        wizard) PLUS one operating-layer file the current (foundation-only) version
        never rendered. render_kind on the operating file is parametrized so the
        capsule-replay branch can be exercised."""
        artifacts = [
            {"delivery": "wizard", "relpath": d, "render_kind": "render",
             "merge_strategy": "three_way",
             "template_path": f"templates/{d}"}
            for d in _TEMPLATE_DOCS
        ]
        if not include_collision_only:
            artifacts.append({
                "delivery": "wizard", "relpath": op_relpath,
                "render_kind": op_render_kind, "merge_strategy": "three_way",
                "template_path": "templates/root/operating_discipline.md",
            })
        else:
            artifacts.append({
                "delivery": "wizard", "relpath": op_relpath,
                "render_kind": op_render_kind, "merge_strategy": "three_way",
                "template_path": "templates/root/operating_discipline.md",
            })
        return {
            "artifacts": artifacts,
            "bundle_version": "v0.5.0",
            "contract_id": "system-artifacts",
            "contract_version": "system-artifacts-v1",
        }

    def _surface(self, *, target_contract, manifest, base_rendered, theirs_rendered,
                 proj, capsule):
        import upgrade_apply as ua
        return ua.compute_merge_surface(
            manifest, target_contract, base_rendered, theirs_rendered,
            Path(proj), capsule,
        )

    def _setup(self, roster="A"):
        """A v0.4.0-style operator project (foundation-only manifest + v1 capsule) and a
        rendered base/theirs for the six foundation docs."""
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster=roster)
        manifest = json.loads(_read(mp))
        base = {r.operator_relpath: r.content
                for r in render_foundation_docs("v0.4.0", _CAPSULE_INPUTS, build_root)}
        theirs = {r.operator_relpath: r.content
                  for r in render_foundation_docs("v0.5.0", _CAPSULE_INPUTS, build_root)}
        capsule = json.loads(_read(proj / ".wizard" / "replay-capsule.json"))
        return build_root, proj, manifest, base, theirs, capsule

    def test_merge_surface_includes_new_in_target_files(self):
        """THE bug: an operating-layer file present in the target contract but NOT in the
        operator manifest must appear on the surface classified `new`, never silently
        dropped. Uses render_kind copy so the capsule-replay branch does not intercept."""
        from upgrade_apply import SURFACE_NEW
        _, proj, manifest, base, theirs, capsule = self._setup()
        contract = self._target_contract(op_relpath="operating_discipline.md",
                                          op_render_kind="copy")
        surface = self._surface(target_contract=contract, manifest=manifest,
                                base_rendered=base, theirs_rendered=theirs,
                                proj=proj, capsule=capsule)
        by_rel = {e.relpath: e for e in surface}
        self.assertIn("operating_discipline.md", by_rel,
                      "operating-layer target file silently dropped from the surface")
        self.assertEqual(by_rel["operating_discipline.md"].classification, SURFACE_NEW)

    def test_surface_source_is_target_manifest_not_current_render(self):
        """The surface derives from the TARGET contract, not from what the current version
        renders. Proof: the current render carries ONLY the six foundation docs, yet the
        surface includes a target-only operating-layer file. A surface built from
        _render_version(current).keys() could not contain it."""
        from upgrade_apply import SURFACE_NEW
        _, proj, manifest, base, theirs, capsule = self._setup()
        # current render surface == the six foundation docs only.
        self.assertEqual(set(base), set(_TEMPLATE_DOCS) | {"prd.md"})
        contract = self._target_contract(op_relpath="agents/prompts/coordinator_prompt.md",
                                          op_render_kind="copy")
        surface = self._surface(target_contract=contract, manifest=manifest,
                                base_rendered=base, theirs_rendered=theirs,
                                proj=proj, capsule=capsule)
        rels = {e.relpath for e in surface}
        self.assertIn("agents/prompts/coordinator_prompt.md", rels)
        new_rels = {e.relpath for e in surface if e.classification == SURFACE_NEW}
        self.assertIn("agents/prompts/coordinator_prompt.md", new_rels)
        # And it is genuinely absent from the current render keys (the OLD surface source).
        self.assertNotIn("agents/prompts/coordinator_prompt.md", set(base))

    def test_new_file_collision_detected(self):
        """A `new` target path where an UNMANAGED file already exists on disk is classified
        a collision (refuse/sidecar) — never silently adopted/overwritten."""
        from upgrade_apply import SURFACE_COLLISION
        _, proj, manifest, base, theirs, capsule = self._setup()
        # Plant an unmanaged file at the target's new path.
        (Path(proj) / "operating_discipline.md").write_text(
            "operator's own pre-existing file\n", encoding="utf-8")
        contract = self._target_contract(op_relpath="operating_discipline.md",
                                          op_render_kind="copy")
        surface = self._surface(target_contract=contract, manifest=manifest,
                                base_rendered=base, theirs_rendered=theirs,
                                proj=proj, capsule=capsule)
        by_rel = {e.relpath: e for e in surface}
        self.assertEqual(by_rel["operating_discipline.md"].classification, SURFACE_COLLISION,
                         "unmanaged file at a new target path was not flagged as a collision")

    def test_render_kind_new_file_with_v1_capsule_needs_capsule_not_crash(self):
        """A render-kind operating-layer NEW file whose theirs needs the capsule operating
        block, with a v1 (foundation-only) capsule, is surfaced as needs_capsule_upgrade —
        graceful, no crash (a follow-on task upgrades the capsule)."""
        from upgrade_apply import SURFACE_NEEDS_CAPSULE
        from replay_capsule import capsule_supports_operating_replay
        _, proj, manifest, base, theirs, capsule = self._setup()
        self.assertFalse(capsule_supports_operating_replay(capsule), "fixture capsule should be v1")
        contract = self._target_contract(op_relpath="CLAUDE.md", op_render_kind="render")
        surface = self._surface(target_contract=contract, manifest=manifest,
                                base_rendered=base, theirs_rendered=theirs,
                                proj=proj, capsule=capsule)
        by_rel = {e.relpath: e for e in surface}
        self.assertEqual(by_rel["CLAUDE.md"].classification, SURFACE_NEEDS_CAPSULE)


class CopyKindWritePathTests(_Base):
    """The write path for copy-kind + new-in-target files (routed through the existing
    transaction). Copy-kind files skip ONLY the replay-conformance gate; they still go
    through drift detection, backup, stage, atomic-replace, and manifest advance.
    """

    # ---- helpers ---------------------------------------------------------------

    def _build_v040_to_v060_repo(self, sub: str = ""):
        """Build a synthetic repo whose target is v0.6.0 with a system-artifacts.json
        contract carrying copy-kind files. Returns (build_root, registry_path)."""
        tmp = self.tmp / sub if sub else self.tmp
        build_root = tmp / "build"
        # required-docs contract
        contract_dst = (build_root / "wizard" / "foundation-bundles" / "v0"
                        / "contracts" / "foundation-manifest-hash-baseline-v1.json")
        contract_dst.parent.mkdir(parents=True, exist_ok=True)
        contract_dst.write_text(_REAL_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")

        # Base bundle (v0.4.0) — foundation-only, no system-artifacts.json
        _write_bundle(build_root, "v0.4.0", migration_from="v0.4.0")

        # Target bundle (v0.6.0) — has a copy-kind file (.claude/statusline.sh)
        _write_bundle(build_root, "v0.6.0", migration_from="v0.4.x",
                      migration_class="minor-additive",
                      migration_extra={"stop_condition": "not_applicable"})

        # Write a real copy-kind template into the target bundle.
        # Use DISTINCT content for the installed version (v0.4.0-era) vs. target (v0.6.0)
        # so the write path can detect a content change.
        tpl_dir = build_root / "wizard" / "foundation-bundles" / "v0.6.0" / "templates" / "claude_config"
        tpl_dir.mkdir(parents=True, exist_ok=True)
        copy_file_content = "#!/bin/bash\n# statusline.sh v0.6.0\necho 'status v060'\n"
        (tpl_dir / "statusline.sh").write_text(copy_file_content, encoding="utf-8")

        # Write the system-artifacts.json contract for v0.6.0
        contract = {
            "artifacts": [
                {
                    "delivery": "wizard",
                    "merge_strategy": "warn_on_drift",
                    "mode": "0755",
                    "relpath": ".claude/statusline.sh",
                    "render_kind": "copy",
                    "template_path": "templates/claude_config/statusline.sh",
                }
            ],
            "bundle_version": "v0.6.0",
            "contract_id": "system-artifacts",
            "contract_version": "system-artifacts-v1",
        }
        contract_path = build_root / "wizard" / "foundation-bundles" / "v0.6.0" / "system-artifacts.json"
        contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

        registry = {
            "schema_version": "v1",
            "bundles": [
                {"foundation_bundle_version": "v0.4.0",
                 "path": "wizard/foundation-bundles/v0.4.0/",
                 "source_commit": "aaa1111", "status": "prerelease"},
                {"foundation_bundle_version": "v0.6.0",
                 "path": "wizard/foundation-bundles/v0.6.0/",
                 "source_commit": "bbb2222", "status": "prerelease"},
            ],
        }
        registry_path = build_root / "wizard" / "registry" / "foundation-bundles.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        return build_root, registry_path, copy_file_content

    def _build_operator_with_copy_file(self, tmp_sub: str, build_root: Path,
                                        *, include_copy_file: bool = True,
                                        copy_file_edited: bool = False,
                                        unmanaged_collision: bool = False):
        """Build an operator project on v0.4.0. Optionally place .claude/statusline.sh
        as an already-managed file (include_copy_file=True) with or without operator
        edits, or as an unmanaged collision file (unmanaged_collision=True).
        Returns (proj_dir, manifest_path)."""
        proj = self.tmp / tmp_sub
        proj.mkdir(parents=True, exist_ok=True)
        (proj / ".wizard").mkdir(parents=True, exist_ok=True)

        rendered = render_foundation_docs("v0.4.0", _CAPSULE_INPUTS, build_root)
        strategies = _strategy_roster("A")
        managed_files = {}
        for rec in rendered:
            rel = rec.operator_relpath
            if rel not in strategies:
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
                "live_lineage_version": "v0.4.0",
            }
            managed_files[rel] = entry

        copy_relpath = ".claude/statusline.sh"
        # The installed (v0.4.0-era) content is distinct from the target bundle template,
        # so the write path detects a content change and stages the new version.
        installed_copy_content = "#!/bin/bash\n# statusline.sh v0.4.0\necho 'status v040'\n"

        if include_copy_file and not unmanaged_collision:
            # The file is managed and on disk (already on v0.4.0)
            disk_content = "#!/bin/bash\n# operator-edited statusline\necho 'CUSTOM'\n" if copy_file_edited else installed_copy_content
            (proj / ".claude").mkdir(parents=True, exist_ok=True)
            (proj / copy_relpath).write_text(disk_content, encoding="utf-8")
            digest = "sha256:" + sha256_bytes(installed_copy_content.encode("utf-8"))
            managed_files[copy_relpath] = {
                "managed": "true",
                "managed_by": "shared",
                "base_hash": digest,
                "base_content_hash": digest,
                "current_hash_last_seen": digest,
                "local_modifications": "expected",
                "merge_strategy": "warn_on_drift",
                "mode": "0755",
                "render_kind": "copy",
                "source_refs": [],
                "live_lineage_version": "v0.4.0",
            }
        elif unmanaged_collision:
            # File on disk but NOT in the manifest — collision scenario
            (proj / ".claude").mkdir(parents=True, exist_ok=True)
            (proj / copy_relpath).write_text("# unmanaged file\n", encoding="utf-8")
            # do NOT add to managed_files

        manifest = {
            "manifest_schema_version": "manifest-v2",
            "foundation_bundle_version": "v0.4.0",
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
            "foundation_bundle_version": "v0.4.0",
            "generator_version": "f" * 40,
            "system_shape": "markdown-CC",
            "foundation_only_mode": False,
            "canonicalization_version": "v1",
            "hash_algorithm": "sha256-lf",
            "foundation_doc_inputs": dict(_CAPSULE_INPUTS),
        }
        (proj / ".wizard" / "replay-capsule.json").write_text(
            json.dumps(capsule, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return proj, manifest_path

    def _apply_v060(self, proj, manifest_path, registry_path, build_root, ack=False):
        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(registry_path)
        return apply_upgrade(
            proj, "v0.6.0", build_root,
            registry=registry, registry_path=registry_path,
            manifest=manifest, manifest_path=manifest_path,
            ack=ack, backup=True,
        )

    # ---- tests -----------------------------------------------------------------

    def test_copy_file_adopted_when_unedited(self):
        """An unedited copy-kind file adopts the target version; manifest advances."""
        build_root, reg, copy_content = self._build_v040_to_v060_repo("unedited")
        proj, mp = self._build_operator_with_copy_file("op_unedited", build_root,
                                                        include_copy_file=True,
                                                        copy_file_edited=False)
        res = self._apply_v060(proj, mp, reg, build_root)

        copy_relpath = ".claude/statusline.sh"
        live = (proj / copy_relpath).read_text(encoding="utf-8")
        self.assertEqual(live, copy_content,
                         "unedited copy-kind file not replaced with target content")
        self.assertIn(copy_relpath, res.files_written,
                      "unedited copy-kind file not in files_written")

        # Manifest base_hash advances
        new_manifest = json.loads((mp).read_text(encoding="utf-8"))
        entry = new_manifest["managed_files"].get(copy_relpath)
        self.assertIsNotNone(entry, "copy-kind file missing from new manifest")
        expected_hash = "sha256:" + sha256_bytes(copy_content.encode("utf-8"))
        self.assertEqual(entry["base_hash"], expected_hash,
                         "manifest base_hash not advanced for adopted copy-kind file")
        self.assertEqual(new_manifest["foundation_bundle_version"], "v0.6.0")

    def test_copy_file_edited_refuses_without_ack(self):
        """Operator-edited copy-kind file (warn_on_drift) refuses without --ack; adopts with --ack; live file never silently overwritten."""
        build_root, reg, copy_content = self._build_v040_to_v060_repo("edited")
        proj, mp = self._build_operator_with_copy_file("op_edited", build_root,
                                                        include_copy_file=True,
                                                        copy_file_edited=True)
        copy_relpath = ".claude/statusline.sh"
        edited_content = "#!/bin/bash\n# operator-edited statusline\necho 'CUSTOM'\n"
        self.assertEqual((proj / copy_relpath).read_text(encoding="utf-8"), edited_content)

        # Without ack: refuses
        before_live = (proj / copy_relpath).read_text(encoding="utf-8")
        with self.assertRaises(UpgradeApplyError) as ctx:
            self._apply_v060(proj, mp, reg, build_root, ack=False)
        self.assertIn("--ack", str(ctx.exception))
        # Live file untouched
        self.assertEqual((proj / copy_relpath).read_text(encoding="utf-8"), before_live,
                         "live file silently overwritten on warn_on_drift refusal")

        # With ack: adopts
        res = self._apply_v060(proj, mp, reg, build_root, ack=True)
        live_after = (proj / copy_relpath).read_text(encoding="utf-8")
        self.assertEqual(live_after, copy_content,
                         "ack'd warn_on_drift copy file not replaced with target content")
        self.assertIn(copy_relpath, res.files_written)

    def test_new_copy_file_created_additively(self):
        """A new copy-kind file in the target is created on a system that lacked it; path exists; mode correct (.sh -> 0755)."""
        build_root, reg, copy_content = self._build_v040_to_v060_repo("newfile")
        # Operator project does NOT have .claude/statusline.sh (neither managed nor on disk)
        proj, mp = self._build_operator_with_copy_file("op_new", build_root,
                                                        include_copy_file=False,
                                                        unmanaged_collision=False)
        copy_relpath = ".claude/statusline.sh"
        self.assertFalse((proj / copy_relpath).exists(), "precondition: file must not exist")

        res = self._apply_v060(proj, mp, reg, build_root)

        # File exists after apply
        dest = proj / copy_relpath
        self.assertTrue(dest.exists(), "new copy-kind file not created additively")
        self.assertEqual(dest.read_text(encoding="utf-8"), copy_content)

        # Mode: 0755 for .sh
        import stat
        mode = dest.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, ".sh copy-kind file not executable (mode 0755)")

        # In files_written
        self.assertIn(copy_relpath, res.files_written)

        # Added to manifest
        new_manifest = json.loads(mp.read_text(encoding="utf-8"))
        self.assertIn(copy_relpath, new_manifest["managed_files"],
                      "new copy-kind file not added to manifest")

    def test_new_file_collision_routes_to_sidecar(self):
        """A new target path with an unmanaged existing file -> sidecar/refuse; live preserved."""
        build_root, reg, copy_content = self._build_v040_to_v060_repo("collision")
        proj, mp = self._build_operator_with_copy_file("op_collision", build_root,
                                                        include_copy_file=False,
                                                        unmanaged_collision=True)
        copy_relpath = ".claude/statusline.sh"
        original_content = "# unmanaged file\n"
        self.assertEqual((proj / copy_relpath).read_text(encoding="utf-8"), original_content)

        res = self._apply_v060(proj, mp, reg, build_root)

        # Live file NOT overwritten
        self.assertEqual((proj / copy_relpath).read_text(encoding="utf-8"), original_content,
                         "collision: live unmanaged file was silently overwritten")
        # Not in files_written
        self.assertNotIn(copy_relpath, res.files_written)
        # Surface has a collision entry for this path
        collision_entries = [e for e in res.surface if e.relpath == copy_relpath]
        self.assertTrue(collision_entries, "no collision surface entry for the colliding path")
        from upgrade_apply import SURFACE_COLLISION
        self.assertEqual(collision_entries[0].classification, SURFACE_COLLISION)


class ManagedModeReconcileTests(_Base):
    """F-54: a managed file's on-disk MODE must be reconciled to its contract mode at
    commit, for BOTH the delivery path (content changes across versions, so the file is
    freshly staged) and the restore path (content is IDENTICAL across versions, so the
    file is never re-written -- yet its mode may have been stripped by a prior buggy
    apply, exactly the estate's `start-session.sh` situation).

    Exercises the render_kind:render operating-layer write path (upgrade_apply step 4c),
    where real scripts like `start-session.sh` / `agents/scripts/*.sh` live. Before the
    fix this path tracked NO mode at all (unlike the copy-kind path, which tracked mode
    only on its content-changed branches) -- so a script here never got chmod'd, changed
    or not.

    Anti-overfit: asserts over TWO distinct managed script relpaths (one delivery, one
    restore), both driven purely by the contract's `mode` field -- plus a negative
    control (a 0644 managed markdown file must NOT be made executable) and an unmanaged
    file (must never be touched at all).
    """

    _BASE = "v0.90.0"
    _TARGET = "v0.90.1"
    _SCRIPT_A = "start-session.sh"              # content CHANGES base -> target (delivery)
    _SCRIPT_B = "agents/scripts/coordinator.sh"  # content UNCHANGED base -> target (restore)
    _MD = "operating_notes.md"                  # 0644 managed file; must stay non-executable

    def _add_operating_contract(self, build_root: Path, version: str, *, script_a_label: str):
        """Add a system-artifacts.json (+ bundle-resident templates) declaring the two
        managed scripts (mode 0755) and one managed markdown (mode 0644) to `version`'s
        bundle. Called for BOTH the base and target bundles (the CURRENT-version render
        used by the replay-conformance gate needs the base bundle's own contract+templates
        too)."""
        bundle_dir = build_root / "wizard" / "foundation-bundles" / version
        root_dir = bundle_dir / "templates" / "root"
        root_dir.mkdir(parents=True, exist_ok=True)
        (root_dir / "start-session.sh").write_text(
            f"#!/bin/bash\n# start-session.sh ({script_a_label})\necho '{script_a_label}'\n",
            encoding="utf-8",
        )
        (root_dir / "coordinator.sh").write_text(
            "#!/bin/bash\n# coordinator.sh (stable)\necho 'stable-coordinator'\n",
            encoding="utf-8",
        )
        (root_dir / "operating_notes.md").write_text(
            "# Operating notes\n\nstable-notes\n", encoding="utf-8",
        )
        artifacts = [
            {"delivery": "wizard", "relpath": self._SCRIPT_A, "render_kind": "render",
             "merge_strategy": "warn_on_drift", "mode": "0755",
             "template_path": "templates/root/start-session.sh"},
            {"delivery": "wizard", "relpath": self._SCRIPT_B, "render_kind": "render",
             "merge_strategy": "warn_on_drift", "mode": "0755",
             "template_path": "templates/root/coordinator.sh"},
            {"delivery": "wizard", "relpath": self._MD, "render_kind": "render",
             "merge_strategy": "three_way", "mode": "0644",
             "template_path": "templates/root/operating_notes.md"},
        ]
        contract = {
            "contract_id": "system-artifacts",
            "contract_version": "system-artifacts-v1",
            "bundle_version": version,
            "artifacts": artifacts,
        }
        (bundle_dir / "system-artifacts.json").write_text(
            json.dumps(contract, indent=2) + "\n", encoding="utf-8",
        )

    def _setup_repo(self):
        build_root, reg = _write_build_repo(
            self.tmp, base_version=self._BASE, target_version=self._TARGET,
        )
        # Base bundle: start-session.sh labeled "base". Target bundle: labeled "TARGET"
        # -- a genuine content change, so start-session.sh exercises the DELIVERY branch.
        # coordinator.sh + operating_notes.md are byte-identical in both bundles, so they
        # exercise the "target unchanged" branch (the RESTORE / negative-control cases).
        self._add_operating_contract(build_root, self._BASE, script_a_label="base")
        self._add_operating_contract(build_root, self._TARGET, script_a_label="TARGET")
        return build_root, reg

    def _build_operator(self, build_root: Path):
        from upgrade_apply import _render_operating_layer

        proj, mp, _ = _build_operator_project(self.tmp, build_root, base_version=self._BASE)

        # Upgrade the capsule to v2 (carries an `operating` block) so the operating-layer
        # render path is taken instead of needs_capsule_upgrade.
        capsule_path = proj / ".wizard" / "replay-capsule.json"
        capsule = json.loads(_read(capsule_path))
        capsule["schema_version"] = "replay-capsule-v2"
        capsule["operating"] = {"resolved_scaffold_inputs": {}, "by_relpath": {}}
        capsule_path.write_text(
            json.dumps(capsule, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )

        project_name = "Acme Helper"
        relpaths = [self._SCRIPT_A, self._SCRIPT_B, self._MD]
        rendered = _render_operating_layer(
            self._BASE, relpaths, capsule=capsule, capsule_inputs=_CAPSULE_INPUTS,
            project_name=project_name, build_repo_root=build_root,
        )

        manifest = json.loads(_read(mp))
        for rel, strategy in (
            (self._SCRIPT_A, "warn_on_drift"),
            (self._SCRIPT_B, "warn_on_drift"),
            (self._MD, "three_way"),
        ):
            content = rendered[rel]
            dest = proj / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            # Simulate the F-54 pre-fix stripped state: EVERY managed file sits at the
            # umask-default 0644 on disk, regardless of what its contract mode says.
            os.chmod(dest, 0o644)
            digest = "sha256:" + sha256_bytes(content.encode("utf-8"))
            manifest["managed_files"][rel] = {
                "managed": "true",
                "managed_by": "shared",
                "base_hash": digest,
                "base_content_hash": digest,
                "current_hash_last_seen": digest,
                "local_modifications": "expected",
                "merge_strategy": strategy,
                "render_kind": "render",
                "source_refs": [],
                "live_lineage_version": self._BASE,
            }

        # An unmanaged, non-contract file -- must never be touched by the reconcile.
        unmanaged = proj / "notes" / "private.txt"
        unmanaged.parent.mkdir(parents=True, exist_ok=True)
        unmanaged.write_text("operator's own private note\n", encoding="utf-8")
        os.chmod(unmanaged, 0o600)

        mp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return proj, mp, rendered, project_name

    def test_delivery_and_restore_reconcile_to_contract_mode(self):
        """RED before the fix / GREEN after: a re-delivered script (content changed) AND
        a content-unchanged script both land at their contract mode (0755) + X_OK after
        apply; a 0644 managed markdown is left non-executable; an unmanaged file is left
        completely untouched."""
        from upgrade_apply import _render_operating_layer

        build_root, reg = self._setup_repo()
        proj, mp, base_rendered, project_name = self._build_operator(build_root)

        # Precondition: both scripts + the md file are all sitting at 0644 (stripped),
        # exactly as a prior buggy apply (or a never-chmod'd emit) would leave them.
        for rel in (self._SCRIPT_A, self._SCRIPT_B, self._MD):
            self.assertEqual(
                stat.S_IMODE((proj / rel).stat().st_mode), 0o644,
                f"precondition: {rel} must start at 0644",
            )

        res = _apply(proj, mp, reg, build_root, target_version=self._TARGET)

        script_a_path = proj / self._SCRIPT_A
        script_b_path = proj / self._SCRIPT_B
        md_path = proj / self._MD
        unmanaged_path = proj / "notes" / "private.txt"

        # --- Delivery case: start-session.sh content changed -> adopted + mode fixed.
        target_rendered = _render_operating_layer(
            self._TARGET, [self._SCRIPT_A], capsule=json.loads(_read(proj / ".wizard" / "replay-capsule.json")),
            capsule_inputs=_CAPSULE_INPUTS, project_name=project_name, build_repo_root=build_root,
        )
        self.assertEqual(
            script_a_path.read_text(encoding="utf-8"), target_rendered[self._SCRIPT_A],
            "delivery case: start-session.sh content not adopted from the target version",
        )
        self.assertIn(self._SCRIPT_A, res.files_written)

        # --- Restore case: coordinator.sh content UNCHANGED, but mode must still heal.
        self.assertEqual(
            script_b_path.read_text(encoding="utf-8"), base_rendered[self._SCRIPT_B],
            "restore case: coordinator.sh content should be unchanged",
        )

        # --- Both scripts: mode == 0755 and executable, driven by the contract, not a
        # hardcoded path.
        for path, label in (
            (script_a_path, "start-session.sh (delivery)"),
            (script_b_path, "agents/scripts/coordinator.sh (restore)"),
        ):
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o755, f"{label}: expected contract mode 0755, got {oct(mode)}")
            self.assertTrue(os.access(path, os.X_OK), f"{label}: not executable (X_OK) after apply")

        # --- Negative control: a 0644 managed markdown must NOT be made executable.
        md_mode = stat.S_IMODE(md_path.stat().st_mode)
        self.assertEqual(md_mode, 0o644, "managed 0644 markdown file's mode changed unexpectedly")
        self.assertFalse(
            os.access(md_path, os.X_OK), "0644 managed markdown was made executable"
        )

        # --- Unmanaged file: never touched (content or mode).
        self.assertEqual(
            stat.S_IMODE(unmanaged_path.stat().st_mode), 0o600,
            "unmanaged/operator file's mode was touched by the reconcile",
        )
        self.assertEqual(
            unmanaged_path.read_text(encoding="utf-8"), "operator's own private note\n",
            "unmanaged/operator file's content was touched by the reconcile",
        )


class GitTrackedExecModeReconcileTests(_Base):
    """F-57: `_reconcile_managed_modes` must persist git's TRACKED mode for managed
    executable-mode files, independent of whether the working-tree chmod fires.

    The critical F-57 scenario: F-54 already healed the working tree to 0755 on a
    prior run, so `current_mode == mode_int` and the working-tree chmod branch does
    NOT fire on a re-run -- yet the git index can still be 100644 (working-tree mode
    and git's tracked mode are independent facts; only `git update-index --chmod` or
    a fresh `git add` moves the index). The git-tracked-mode persist must fire
    regardless of whether the working-tree chmod branch fired.

    Anti-overfit: exercises TWO distinct managed exec relpaths (start-session.sh and
    a nested agents/scripts/*.sh) plus a non-git-repo fixture (working-tree chmod
    still heals; nothing raises) and an untracked-file-in-a-git-repo fixture (git
    persist silently skipped; nothing raises).
    """

    _SCRIPT_A = "start-session.sh"
    _SCRIPT_B = "agents/scripts/run.sh"

    def _contract(self):
        return {
            "contract_id": "system-artifacts",
            "artifacts": [
                {"delivery": "wizard", "relpath": self._SCRIPT_A, "mode": "0755"},
                {"delivery": "wizard", "relpath": self._SCRIPT_B, "mode": "0755"},
            ],
        }

    def _git(self, repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=5,
        )

    def _init_git_repo(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test")
        return repo

    def _write_script(self, repo, rel, working_tree_mode):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
        os.chmod(path, working_tree_mode)
        return path

    def test_git_persist_fires_even_when_working_tree_already_healed(self):
        """The exact F-57 case: the working tree is ALREADY 0755 before the reconcile
        runs (so the working-tree chmod branch does NOT fire), but the git index is
        still 100644. The reconcile must still flip the index to 100755."""
        from upgrade_apply import _reconcile_managed_modes

        repo = self._init_git_repo()
        for rel in (self._SCRIPT_A, self._SCRIPT_B):
            path = self._write_script(repo, rel, 0o644)
            # Track at 0644 first (git records whatever the working-tree mode is at
            # `git add` time).
            self._git(repo, "add", rel)
            # Now heal the WORKING TREE to executable -- simulating a prior F-54 run
            # that already fixed the on-disk mode -- while the index is still 100644.
            os.chmod(path, 0o755)

        # Precondition: the git index is 100644 for both, even though the working
        # tree is already 0755.
        for rel in (self._SCRIPT_A, self._SCRIPT_B):
            staged = self._git(repo, "ls-files", "-s", rel).stdout
            self.assertTrue(staged.startswith("100644"),
                             f"precondition failed for {rel}: {staged!r}")
            self.assertTrue(os.access(repo / rel, os.X_OK),
                             f"precondition: {rel} working tree must already be executable")

        changed = _reconcile_managed_modes(self._contract(), repo)

        # The working-tree chmod branch should NOT have fired (mode already
        # matched) -- `changed` only tracks working-tree changes, so it's empty.
        self.assertEqual(changed, [],
                          "working-tree chmod branch fired even though mode already matched")

        for rel in (self._SCRIPT_A, self._SCRIPT_B):
            staged = self._git(repo, "ls-files", "-s", rel).stdout
            self.assertTrue(staged.startswith("100755"),
                             f"git-tracked mode not persisted for {rel}: {staged!r}")

    def test_git_persist_also_fires_when_working_tree_chmod_fires(self):
        """The ordinary case: the working tree starts at 0644 (needs the chmod) AND
        the git index starts at 100644 -- both the working-tree fix and the git
        persist must land."""
        from upgrade_apply import _reconcile_managed_modes

        repo = self._init_git_repo()
        for rel in (self._SCRIPT_A, self._SCRIPT_B):
            self._write_script(repo, rel, 0o644)
            self._git(repo, "add", rel)

        changed = _reconcile_managed_modes(self._contract(), repo)

        self.assertEqual(sorted(changed), sorted([self._SCRIPT_A, self._SCRIPT_B]))
        for rel in (self._SCRIPT_A, self._SCRIPT_B):
            self.assertTrue(os.access(repo / rel, os.X_OK), f"{rel} working tree not healed")
            staged = self._git(repo, "ls-files", "-s", rel).stdout
            self.assertTrue(staged.startswith("100755"),
                             f"git-tracked mode not persisted for {rel}: {staged!r}")

    def test_non_git_dir_working_tree_chmod_still_heals_and_nothing_raises(self):
        """No `.git` at all: the working-tree chmod must still heal the mode, and the
        git-persist attempt must fail silently (no raise)."""
        from upgrade_apply import _reconcile_managed_modes

        plain = self.tmp / "plain"
        plain.mkdir()
        for rel in (self._SCRIPT_A, self._SCRIPT_B):
            self._write_script(plain, rel, 0o644)

        changed = _reconcile_managed_modes(self._contract(), plain)  # must not raise

        self.assertEqual(sorted(changed), sorted([self._SCRIPT_A, self._SCRIPT_B]))
        for rel in (self._SCRIPT_A, self._SCRIPT_B):
            self.assertTrue(os.access(plain / rel, os.X_OK), f"{rel} not healed in non-git dir")

    def test_untracked_file_in_git_repo_persist_skipped_no_raise(self):
        """A file exists on disk in a git repo but was never `git add`ed: the git
        persist must be skipped silently; the working-tree chmod must still heal."""
        from upgrade_apply import _reconcile_managed_modes

        repo = self._init_git_repo()
        contract = {
            "artifacts": [{"delivery": "wizard", "relpath": self._SCRIPT_A, "mode": "0755"}],
        }
        self._write_script(repo, self._SCRIPT_A, 0o644)  # never `git add`ed

        changed = _reconcile_managed_modes(contract, repo)  # must not raise

        self.assertEqual(changed, [self._SCRIPT_A])
        self.assertTrue(os.access(repo / self._SCRIPT_A, os.X_OK))
        # Confirm it really is untracked (git ls-files returns nothing for it).
        untracked_check = self._git(repo, "ls-files", self._SCRIPT_A)
        self.assertEqual(untracked_check.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
