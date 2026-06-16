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
    """A small deterministic template body. `{{PROJECT_NAME}}` is the placeholder
    fillable from the capsule. `version_label` distinguishes base vs theirs so the
    rendered bytes differ between versions."""
    body = (
        f"# {doc_name} ({version_label})\n\n"
        "Project: {{PROJECT_NAME}}\n\n"
        f"This is the {version_label} body of {doc_name}.\n"
    )
    if extra_placeholder:
        # A NEW placeholder a migration would have to supply; absent from the capsule.
        body += "\nNew field: {{BRAND_NEW_KEY}}\n"
    return body


def _write_bundle(build_root: Path, version: str, *, doc_version_labels=None,
                  extra_placeholder_doc=None, migration_from="v0.4.0",
                  migration_class="minor-additive", stop_condition=""):
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
    (bundle_dir / "migration-manifest.json").write_text(
        json.dumps({
            "target_version": version,
            "migrations": [{
                "from": migration_from,
                "class": migration_class,
                "requires_operator_approval": True,
                "stop_condition": stop_condition,
                "breaking_changes_summary": "",
                "supported": True,
            }],
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def _write_build_repo(tmp: Path, *, target_extra_placeholder_doc=None,
                      target_stop_condition="", base_version="v0.4.0",
                      target_version="v0.5.0"):
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
                  migration_from=base_version, migration_class="minor-additive",
                  stop_condition=target_stop_condition)

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
                            roster="A", extra_unmanaged=True):
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
        managed_files[rel] = {
            "managed": "true",
            "managed_by": "shared",
            "base_hash": digest,
            "current_hash_last_seen": digest,
            "local_modifications": "expected",
            "merge_strategy": strategies[rel],
            "source_refs": [],
        }

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

    def test_manifest_base_hash_advanced_only_for_adopted(self):
        build_root, reg = _write_build_repo(self.tmp)
        proj, mp, strat = _build_operator_project(self.tmp, build_root, roster="A")
        # Make the three_way doc drift so it routes to review (NOT adopted).
        tw_doc = next(d for d, s in strat.items() if s == "three_way")
        (proj / tw_doc).write_text("# drifted\n", encoding="utf-8")
        old_manifest = json.loads(_read(mp))
        old_tw_hash = old_manifest["managed_files"][tw_doc]["base_hash"]

        res = _apply(proj, mp, reg, build_root)
        new_manifest = json.loads(_read(mp))
        self.assertEqual(new_manifest["foundation_bundle_version"], "v0.5.0")

        # The drifted three_way doc was routed to review -> base_hash NOT advanced.
        self.assertEqual(new_manifest["managed_files"][tw_doc]["base_hash"], old_tw_hash,
                         "base_hash advanced for a file left in review")
        # An adopted file's base_hash == the freshly written theirs bytes.
        for adopted in res.files_written:
            theirs = _read(proj / adopted)
            self.assertEqual(new_manifest["managed_files"][adopted]["base_hash"],
                             "sha256:" + sha256_bytes(theirs.encode("utf-8")),
                             f"{adopted}: base_hash != written bytes")
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


if __name__ == "__main__":
    unittest.main()
