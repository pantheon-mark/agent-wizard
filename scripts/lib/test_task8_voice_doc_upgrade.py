"""Task 8 — voice_and_style.md upgrade adoption verification.

VERIFIED BEHAVIOR (Step 1 finding, load-bearing):
  docs/voice_and_style.md is merge_strategy: warn_on_drift, render_kind: render
  (operating-layer render file, not a classic foundation doc).

  The warn_on_drift branch in upgrade_apply.py (the operating-layer leg, lines 1630-1641)
  behaves as follows:
    - UNEDITED (ours_content == base_content): staged_writes[rel] = theirs_ol
      -> FILE_ADOPTED, note "no operator edits; adopted the new version".
      The live file is replaced with the new version.
    - EDITED + no ack: raises UpgradeApplyError (--ack required).
    - EDITED + ack: staged_writes[rel] = theirs_ol -> FILE_ADOPTED.

  render_apply_result already lists every file in files_written by name, so
  voice_and_style.md appears in the output if it is adopted.

  CONCLUSION: the F4 cross-vendor concern ("doc stays stale") is NOT real for the
  common case (unedited inert stub). No bespoke sentinel detector is needed.
  This test file VERIFIES the behavior and CONFIRMS voice_and_style.md appears in
  the adoption report.

Test structure:
  Class 1 (ContractAssertions): contract-level checks — warn_on_drift + render_kind
    are declared correctly for voice_and_style.md in both v0.6.9 and v0.7.0.
  Class 2 (VoiceDocUpgradeApplyBehavior): applier-level — build a synthetic repo
    that mirrors the v0.6.9->v0.7.0 voice_and_style.md upgrade path:
      test_unedited_voice_doc_clean_adopts: unedited -> FILE_ADOPTED, in files_written
      test_edited_voice_doc_without_ack_refuses: drifted -> UpgradeApplyError
      test_edited_voice_doc_with_ack_adopts: drifted + ack -> FILE_ADOPTED
      test_render_apply_result_names_voice_doc: render_apply_result output names
        docs/voice_and_style.md with an outcome (adopted line)
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
    render_apply_result,
    UpgradeApplyError,
    APPLY_RESULT_APPLIED,
    FILE_ADOPTED,
    FILE_UNCHANGED,
)

_REAL_REPO = Path(__file__).resolve().parents[3]
_REAL_CONTRACT = (
    _REAL_REPO / "wizard" / "foundation-bundles" / "v0" / "contracts"
    / "foundation-manifest-hash-baseline-v1.json"
)
_REAL_V069_CONTRACT = (
    _REAL_REPO / "wizard" / "foundation-bundles" / "v0.6.9" / "system-artifacts.json"
)
_REAL_V070_CONTRACT = (
    _REAL_REPO / "wizard" / "foundation-bundles" / "v0.7.0" / "system-artifacts.json"
)

VOICE_DOC_REL = "docs/voice_and_style.md"

# Foundation doc inputs (minimal subset needed for render_foundation_docs).
_FDI = {
    "PROJECT_NAME": "Test Corp",
    "WIZARD_VERSION": "v0.99.0",
}

# Operating inputs covering the voice_and_style.md placeholders.
_VOICE_INPUTS = {
    "EXPLANATION_DEPTH": "brief summaries",
    "TONE": "professional",
    "TECHNICAL_LEVEL": "non-technical",
    "TABLE_STYLE": "compact",
    "LIST_STYLE": "bullets",
    "LENGTH_PREFERENCE": "concise",
    "LAST_UPDATED_DATE": "2026-06-25",
    "OUTPUT_TEMPLATES": "(operator-configures during setup)",
    "APPROVED_EXAMPLES": "(operator-configures during setup)",
    "ANTI_PATTERNS": "(operator-configures during setup)",
}

# All operating-layer inputs merged.
_ALL_INPUTS = dict(_FDI)
_ALL_INPUTS.update(_VOICE_INPUTS)

_FOUNDATION_DOCS = [
    "vision.md", "approach.md", "technical_architecture.md",
    "execution_plan.md", "test_cases.md", "audit_framework.md",
]


# ---------------------------------------------------------------------------
# Template builders for the synthetic bundles
# ---------------------------------------------------------------------------

def _foundation_template(doc: str, version: str) -> str:
    return (
        f"# {doc}\n\n"
        "Project: {{PROJECT_NAME}}\n\n"
        "## Overview\n\n"
        f"Overview for {doc} at {version}.\n\n"
        "## Details\n\n"
        f"Stable detail for {doc}.\n"
    )


# Minimal voice_and_style templates that mirror the structural change from
# v0.6.9 -> v0.7.0 (v0.6.9 lacks Channel-appropriate rendering + Information
# architecture; v0.7.0 adds them).  Both resolve all _VOICE_INPUTS placeholders.

def _voice_template_v0() -> str:
    """Mimics the v0.6.9 voice_and_style.md shape (no channel/IA sections)."""
    return (
        "# {{PROJECT_NAME}} — Voice and Style Preferences\n\n"
        "*Last updated: {{LAST_UPDATED_DATE}}*\n\n"
        "---\n\n"
        "## General voice\n\n"
        "| Preference | Setting |\n"
        "|-----------|---------|\n"
        "| Explanation depth | {{EXPLANATION_DEPTH}} |\n"
        "| Tone | {{TONE}} |\n"
        "| Technical level | {{TECHNICAL_LEVEL}} |\n\n"
        "---\n\n"
        "## Formatting defaults\n\n"
        "| Preference | Setting |\n"
        "|-----------|---------|\n"
        "| Table style | {{TABLE_STYLE}} |\n"
        "| List style | {{LIST_STYLE}} |\n"
        "| Length preference | {{LENGTH_PREFERENCE}} |\n\n"
        "---\n\n"
        "## Output-specific templates\n\n"
        "*For recurring outputs to third parties.*\n\n"
        "{{OUTPUT_TEMPLATES}}\n\n"
        "---\n\n"
        "## Approved examples and anti-patterns\n\n"
        "**Examples:**\n\n"
        "{{APPROVED_EXAMPLES}}\n\n"
        "**Anti-patterns:**\n\n"
        "{{ANTI_PATTERNS}}\n"
    )


def _voice_template_v1() -> str:
    """Mimics the v0.7.0 voice_and_style.md shape (adds Channel-appropriate + IA)."""
    return (
        "# {{PROJECT_NAME}} — Voice and Style Preferences\n\n"
        "*Last updated: {{LAST_UPDATED_DATE}}*\n\n"
        "---\n\n"
        "## General voice\n\n"
        "| Preference | Setting |\n"
        "|-----------|---------|\n"
        "| Explanation depth | {{EXPLANATION_DEPTH}} |\n"
        "| Tone | {{TONE}} |\n"
        "| Technical level | {{TECHNICAL_LEVEL}} |\n\n"
        "---\n\n"
        "## Formatting defaults\n\n"
        "| Preference | Setting |\n"
        "|-----------|---------|\n"
        "| Table style | {{TABLE_STYLE}} |\n"
        "| List style | {{LIST_STYLE}} |\n"
        "| Length preference | {{LENGTH_PREFERENCE}} |\n\n"
        "---\n\n"
        "## Channel-appropriate rendering\n\n"
        "| Channel | Render as |\n"
        "|---|---|\n"
        "| Email | HTML |\n"
        "| SMS / push (NTFY) | Plain text |\n"
        "| On-disk deliverable | Markdown |\n\n"
        "## Information architecture\n\n"
        "- Lead with what needs the operator's action.\n"
        "- Suppress noise.\n"
        "- Show what changed since the last message.\n\n"
        "---\n\n"
        "## Output-specific templates\n\n"
        "*For recurring outputs to third parties.*\n\n"
        "{{OUTPUT_TEMPLATES}}\n\n"
        "---\n\n"
        "## Approved examples and anti-patterns\n\n"
        "**Examples:**\n\n"
        "{{APPROVED_EXAMPLES}}\n\n"
        "**Anti-patterns:**\n\n"
        "{{ANTI_PATTERNS}}\n"
    )


def _render_voice(template_fn) -> str:
    raw = template_fn()
    for k, v in _ALL_INPUTS.items():
        raw = raw.replace("{{" + k + "}}", v)
    return raw


# ---------------------------------------------------------------------------
# Synthetic build repo + operator project helpers
# ---------------------------------------------------------------------------

def _write_bundle(build_root: Path, version: str, *, migration_from: str,
                  voice_template_fn=None):
    bundle_dir = build_root / "wizard" / "foundation-bundles" / version
    templates_dir = bundle_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    # Foundation doc templates.
    for doc in _FOUNDATION_DOCS:
        (templates_dir / doc).write_text(
            _foundation_template(doc, version), encoding="utf-8"
        )

    # docs/ directory for the voice template.
    docs_dir = templates_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    fn = voice_template_fn or _voice_template_v0
    (docs_dir / "voice_and_style.md").write_text(fn(), encoding="utf-8")

    # system-artifacts.json: declare docs/voice_and_style.md as a render-kind
    # warn_on_drift operating-layer file (mirrors the real v0.6.9 / v0.7.0 contract).
    contract = {
        "contract_id": "system-artifacts",
        "contract_version": "system-artifacts-v1",
        "bundle_version": version,
        "artifacts": [{
            "delivery": "wizard",
            "relpath": "docs/voice_and_style.md",
            "render_kind": "render",
            "merge_strategy": "warn_on_drift",
            "mode": "0644",
            "template_path": "templates/docs/voice_and_style.md",
            "inputs": {
                "persisted": ["PROJECT_NAME", "LAST_UPDATED_DATE"],
                "derived": [
                    "TONE", "TECHNICAL_LEVEL", "EXPLANATION_DEPTH",
                    "LENGTH_PREFERENCE", "LIST_STYLE", "TABLE_STYLE",
                ],
            },
        }],
    }
    (bundle_dir / "system-artifacts.json").write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
    )

    # Provenance sidecar.
    (bundle_dir / "foundation-bundle.provenance.json").write_text(
        json.dumps({"generator_version": f"gen-{version}"}) + "\n", encoding="utf-8"
    )

    # Migration manifest.
    (bundle_dir / "migration-manifest.json").write_text(
        json.dumps({
            "target_version": version,
            "migrations": [{
                "from": migration_from,
                "class": "minor-additive",
                "requires_operator_approval": True,
                "stop_condition": "",
                "breaking_changes_summary": "",
                "supported": True,
            }],
        }, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_build_repo(tmp: Path) -> tuple:
    """Synthetic build repo: vVS.0 (v0) and vVS.1 (target) with voice_and_style."""
    build_root = tmp / "build_repo"
    base_ver = "v0.99.0"
    target_ver = "v0.99.1"

    # Required-docs contract (verbatim copy from the real authority).
    contract_dst = (
        build_root / "wizard" / "foundation-bundles" / "v0" / "contracts"
        / "foundation-manifest-hash-baseline-v1.json"
    )
    contract_dst.parent.mkdir(parents=True, exist_ok=True)
    contract_dst.write_text(_REAL_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")

    _write_bundle(build_root, base_ver, migration_from=base_ver,
                  voice_template_fn=_voice_template_v0)
    _write_bundle(build_root, target_ver, migration_from=base_ver,
                  voice_template_fn=_voice_template_v1)

    registry = {
        "schema_version": "v1",
        "bundles": [
            {"foundation_bundle_version": base_ver,
             "path": f"wizard/foundation-bundles/{base_ver}/",
             "source_commit": "aaa0000", "status": "prerelease"},
            {"foundation_bundle_version": target_ver,
             "path": f"wizard/foundation-bundles/{target_ver}/",
             "source_commit": "bbb1111", "status": "prerelease"},
        ],
    }
    reg_path = build_root / "wizard" / "registry" / "foundation-bundles.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return build_root, reg_path


def _build_operator_project(tmp: Path, build_root: Path,
                             base_ver: str = "v0.99.0") -> tuple:
    """Emit a synthetic operator project on base_ver with voice_and_style.md managed."""
    proj = tmp / "operator_project"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".wizard").mkdir(parents=True, exist_ok=True)
    (proj / "docs").mkdir(parents=True, exist_ok=True)

    # Foundation docs.
    managed_files = {}
    rendered_fd = render_foundation_docs(base_ver, _FDI, build_root)
    for rec in rendered_fd:
        rel = rec.operator_relpath
        (proj / rel).write_text(rec.content, encoding="utf-8")
        if rel == "prd.md":
            continue
        digest = "sha256:" + sha256_bytes(rec.content.encode("utf-8"))
        managed_files[rel] = {
            "managed": "true",
            "managed_by": "shared",
            "base_hash": digest,
            "base_content_hash": digest,
            "current_hash_last_seen": digest,
            "local_modifications": "expected",
            "merge_strategy": rec.contract_policy.get("merge_strategy", "three_way"),
            "render_kind": "render",
            "source_refs": [],
            "live_lineage_version": base_ver,
        }

    # voice_and_style.md operating-layer render file (v0 version, unedited).
    voice_content = _render_voice(_voice_template_v0)
    (proj / "docs" / "voice_and_style.md").write_text(voice_content, encoding="utf-8")
    digest = "sha256:" + sha256_bytes(voice_content.encode("utf-8"))
    managed_files[VOICE_DOC_REL] = {
        "managed": "true",
        "managed_by": "wizard",
        "base_hash": digest,
        "base_content_hash": digest,
        "current_hash_last_seen": digest,
        "local_modifications": "not_recommended",
        "merge_strategy": "warn_on_drift",
        "render_kind": "render",
        "source_refs": [],
        "live_lineage_version": base_ver,
        "template_path": "templates/docs/voice_and_style.md",
    }

    manifest = {
        "manifest_schema_version": "manifest-v2",
        "foundation_bundle_version": base_ver,
        "source_commit": "aaa0000",
        "generator_version": "g" * 40,
        "project_name": "Test Corp",
        "system_shape": "markdown-CC",
        "managed_files": managed_files,
        "control_files": [".wizard/manifest.json", ".wizard/upgrade-history.log"],
    }
    manifest_path = proj / ".wizard" / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (proj / ".wizard" / "upgrade-history.log").write_text("# history\n", encoding="utf-8")

    # v2 capsule: includes an `operating` block so capsule_supports_operating_replay
    # returns True. resolved_scaffold_inputs carries all the voice_and_style placeholders
    # so the operating-layer render can reproduce the file from capsule inputs.
    capsule = {
        "schema_version": "replay-capsule-v2",
        "foundation_bundle_version": base_ver,
        "generator_version": "g" * 40,
        "system_shape": "markdown-CC",
        "foundation_only_mode": False,
        "canonicalization_version": "v1",
        "hash_algorithm": "sha256-lf",
        "foundation_doc_inputs": dict(_FDI),
        "operating": {
            "resolved_scaffold_inputs": dict(_VOICE_INPUTS),
            "by_relpath": {},
        },
    }
    (proj / ".wizard" / "replay-capsule.json").write_text(
        json.dumps(capsule, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return proj, manifest_path


def _apply(proj, manifest_path, registry_path, build_root,
           target_ver="v0.99.1", ack=False):
    manifest = load_operator_manifest(manifest_path)
    registry = load_registry(registry_path)
    return apply_upgrade(
        proj, target_ver, build_root,
        registry=registry, registry_path=registry_path,
        manifest=manifest, manifest_path=manifest_path,
        ack=ack,
    )


# ===========================================================================
# Class 1: Contract-level assertions
# ===========================================================================

class ContractAssertions(unittest.TestCase):
    """Verify the real v0.6.9 and v0.7.0 contracts declare docs/voice_and_style.md
    with merge_strategy: warn_on_drift and render_kind: render.

    This is the contract baseline that makes the warn_on_drift behavior the
    authoritative rule for this file on upgrade.
    """

    def _load_contract(self, path: Path) -> dict:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            e["relpath"]: e
            for e in data.get("artifacts", [])
            if "relpath" in e
        }

    def test_v069_voice_doc_is_warn_on_drift(self):
        by_rel = self._load_contract(_REAL_V069_CONTRACT)
        self.assertIn(VOICE_DOC_REL, by_rel,
                      "docs/voice_and_style.md not declared in v0.6.9 contract")
        self.assertEqual(by_rel[VOICE_DOC_REL]["merge_strategy"], "warn_on_drift")

    def test_v069_voice_doc_is_render_kind_render(self):
        by_rel = self._load_contract(_REAL_V069_CONTRACT)
        self.assertEqual(by_rel[VOICE_DOC_REL]["render_kind"], "render")

    def test_v070_voice_doc_is_warn_on_drift(self):
        by_rel = self._load_contract(_REAL_V070_CONTRACT)
        self.assertIn(VOICE_DOC_REL, by_rel,
                      "docs/voice_and_style.md not declared in v0.7.0 contract")
        self.assertEqual(by_rel[VOICE_DOC_REL]["merge_strategy"], "warn_on_drift")

    def test_v070_voice_doc_is_render_kind_render(self):
        by_rel = self._load_contract(_REAL_V070_CONTRACT)
        self.assertEqual(by_rel[VOICE_DOC_REL]["render_kind"], "render")

    def test_v070_voice_doc_has_channel_rendering_section(self):
        """The v0.7.0 template adds Channel-appropriate rendering + Information
        architecture — verifying the target IS genuinely different from v0.6.9."""
        tmpl = (
            _REAL_REPO / "wizard" / "foundation-bundles" / "v0.7.0"
            / "templates" / "docs" / "voice_and_style.md"
        )
        content = tmpl.read_text(encoding="utf-8")
        self.assertIn("Channel-appropriate rendering", content)
        self.assertIn("Information architecture", content)

    def test_v069_voice_doc_lacks_channel_rendering_section(self):
        """The v0.6.9 template does NOT have Channel-appropriate rendering —
        confirming the v0.7.0 template is a genuine content change."""
        tmpl = (
            _REAL_REPO / "wizard" / "foundation-bundles" / "v0.6.9"
            / "templates" / "docs" / "voice_and_style.md"
        )
        content = tmpl.read_text(encoding="utf-8")
        self.assertNotIn("Channel-appropriate rendering", content)


# ===========================================================================
# Class 2: Applier-level behavior verification
# ===========================================================================

class VoiceDocUpgradeApplyBehavior(unittest.TestCase):
    """Applier-level: verify the actual apply decisions for docs/voice_and_style.md
    during a synthetic v0.99.0 -> v0.99.1 upgrade.

    These tests mirror the v0.6.9 -> v0.7.0 path: warn_on_drift, render_kind: render,
    genuine content change between versions.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unedited_voice_doc_clean_adopts(self):
        """CORE VERIFICATION: an unedited (byte-matches v0 baseline) voice_and_style.md
        is CLEAN-ADOPTED on upgrade.

        Mechanism: warn_on_drift with no drift -> staged_writes[rel] = theirs -> FILE_ADOPTED.
        The new v1 content (with Channel/IA sections) replaces the v0 content.
        This is the verified behavior that makes the F4 concern non-real for the common case.
        """
        build_root, reg_path = _write_build_repo(self.tmp)
        proj, mp = _build_operator_project(self.tmp, build_root)

        res = _apply(proj, mp, reg_path, build_root)

        self.assertIn(VOICE_DOC_REL, res.files_written,
                      "unedited voice_and_style.md not in files_written — not adopted")
        dec = next((d for d in res.decisions if d.relpath == VOICE_DOC_REL), None)
        self.assertIsNotNone(dec, "no decision recorded for voice_and_style.md")
        self.assertEqual(dec.disposition, FILE_ADOPTED,
                         f"expected FILE_ADOPTED, got {dec.disposition!r}")
        self.assertFalse(dec.drifted,
                         "unedited voice doc reported as drifted — drift detection wrong")

        # The live file now contains the v1 content (Channel/IA sections present).
        live = (proj / "docs" / "voice_and_style.md").read_text(encoding="utf-8")
        self.assertIn("Channel-appropriate rendering", live,
                      "v1 content not written — adopt did not replace live file")
        self.assertIn("Information architecture", live,
                      "v1 IA section not written — adopt did not replace live file")

    def test_edited_voice_doc_without_ack_refuses(self):
        """An operator-edited (drifted) voice_and_style.md blocks the upgrade without --ack.

        Mechanism: warn_on_drift + drifted + no ack -> UpgradeApplyError.
        No files are changed.
        """
        build_root, reg_path = _write_build_repo(self.tmp)
        proj, mp = _build_operator_project(self.tmp, build_root)

        # Operator edited the voice doc (appended a custom note).
        voice_path = proj / "docs" / "voice_and_style.md"
        original = voice_path.read_text(encoding="utf-8")
        voice_path.write_text(original + "\n## My custom style notes\n\nKeep this.\n",
                               encoding="utf-8")

        with self.assertRaises(UpgradeApplyError) as ctx:
            _apply(proj, mp, reg_path, build_root, ack=False)

        msg = str(ctx.exception)
        self.assertIn("--ack", msg,
                      "refusal message should tell operator to re-run with --ack")
        # Live file must be untouched.
        self.assertIn("My custom style notes",
                      (proj / "docs" / "voice_and_style.md").read_text(encoding="utf-8"),
                      "live voice doc was mutated during a refused upgrade")

    def test_edited_voice_doc_with_ack_adopts(self):
        """An operator-edited voice_and_style.md is ADOPTED when --ack is supplied.

        Mechanism: warn_on_drift + drifted + ack -> staged_writes[rel] = theirs -> FILE_ADOPTED.
        """
        build_root, reg_path = _write_build_repo(self.tmp)
        proj, mp = _build_operator_project(self.tmp, build_root)

        # Operator edited the voice doc.
        voice_path = proj / "docs" / "voice_and_style.md"
        original = voice_path.read_text(encoding="utf-8")
        voice_path.write_text(original + "\n## My custom style notes\n\nKeep this.\n",
                               encoding="utf-8")

        res = _apply(proj, mp, reg_path, build_root, ack=True)

        self.assertIn(VOICE_DOC_REL, res.files_written,
                      "ack'd drifted voice doc not in files_written")
        dec = next((d for d in res.decisions if d.relpath == VOICE_DOC_REL), None)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.disposition, FILE_ADOPTED)
        self.assertTrue(dec.drifted, "drifted doc should have drifted=True")
        self.assertIn("acknowledged", dec.note,
                      "ack'd adoption note should say 'acknowledged'")

        live = (proj / "docs" / "voice_and_style.md").read_text(encoding="utf-8")
        self.assertIn("Channel-appropriate rendering", live,
                      "v1 content not written after ack'd adoption")

    def test_render_apply_result_names_voice_doc_with_outcome(self):
        """render_apply_result names docs/voice_and_style.md in the adoption output.

        Step 3 verification: the operator-facing apply report surfaces this file
        explicitly so the operator can see it was updated.
        """
        build_root, reg_path = _write_build_repo(self.tmp)
        proj, mp = _build_operator_project(self.tmp, build_root)

        res = _apply(proj, mp, reg_path, build_root)
        out = render_apply_result(res)

        self.assertIn(VOICE_DOC_REL, out,
                      "docs/voice_and_style.md not named in render_apply_result output")
        # The file is adopted (not reviewed), so it appears under the "Updated" section.
        self.assertIn("Updated to the new version", out,
                      "adoption section header missing from render_apply_result output")


if __name__ == "__main__":
    unittest.main()
