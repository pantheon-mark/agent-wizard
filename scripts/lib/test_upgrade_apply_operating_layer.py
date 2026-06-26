"""B3: Verify the applier honours merge_strategy-by-class for operating-layer files.

Two test classes:

  MergeStrategyByClassOperatingLayer
      Contract-level: assert the v0.6.0 system-artifacts.json assigns the right
      merge_strategy to a representative cross-class sample (script -> warn_on_drift,
      operating markdown -> three_way, agent prompt -> three_way,
      operator-derived -> operator_review). Divergent files only -- anti-overfit.

  EditedOperatingMarkdownMergesNotBlocks
      Applier-level: build a synthetic build repo that carries two "operating-layer-
      aware" bundle versions (vOL.0 -> vOL.1). The target bundle changes one section
      of the operating markdown; the operator edits a DIFFERENT section. Assert:
        clean case  -> section_merge produces a merged live file (both edits present,
                       no git markers, disposition == FILE_MERGED).
        conflict case -> routes to review sidecar; live file = ours exactly
                        (no clobber, no git markers).

The synthetic bundles use the real required-docs contract so render_foundation_docs
resolves. Operating-layer render files are declared in a synthetic system-artifacts.json
(the real contract format). The capsule is v2 (carries an `operating` block) so the
needs_capsule_upgrade surface path is never taken.

Stdlib-only. No real estate emitted. No real transcript required.
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
    RENDER_KIND_RENDER,
    RENDER_KIND_COPY,
)

_REAL_REPO = Path(__file__).resolve().parents[3]
_REAL_CONTRACT = (
    _REAL_REPO / "wizard" / "foundation-bundles" / "v0" / "contracts"
    / "foundation-manifest-hash-baseline-v1.json"
)
_REAL_CONTRACT_V060 = _REAL_REPO / "wizard" / "foundation-bundles" / "v0.6.0" / "system-artifacts.json"


# ---------------------------------------------------------------------------
# Helpers for the synthetic operating-layer bundle pair
# ---------------------------------------------------------------------------

# Foundation doc inputs (minimal; matches what render_foundation_docs needs).
_FDI = {
    "PROJECT_NAME": "Test Project",
    "WIZARD_VERSION": "v0.99.0",
}

# Operating render inputs (resolves all placeholders in our synthetic templates).
_OPERATING_INPUTS = {
    "OL_COLOR": "blue",
    "OL_STYLE": "minimal",
}

# The two synthetic operating-layer markdown relpaths we exercise.
_OP_MARKDOWN_A = "CLAUDE.md"          # three_way
_OP_MARKDOWN_B = "operating_discipline.md"  # three_way (second divergent target)

_FOUNDATION_DOCS = [
    "vision.md", "approach.md", "technical_architecture.md",
    "execution_plan.md", "test_cases.md", "audit_framework.md",
]


def _foundation_template(doc: str, version: str) -> str:
    """Minimal multi-section foundation template for both synthetic versions."""
    return (
        f"# {doc}\n\n"
        "Project: {{PROJECT_NAME}}\n\n"
        "## Overview\n\n"
        f"Overview for {doc} at {version}.\n\n"
        "## Details\n\n"
        f"Stable detail for {doc}.\n"
    )


def _op_template_v0(relpath: str) -> str:
    """Operating-layer template for vOL.0 -- two stable sections + OL_COLOR."""
    return (
        f"# {relpath}\n\n"
        "Color: {{OL_COLOR}}\n\n"
        "## Section A\n\n"
        "Original content of Section A (v0).\n\n"
        "## Section B\n\n"
        "Stable content of Section B.\n"
    )


def _op_template_v1_clean(relpath: str) -> str:
    """Operating-layer template for vOL.1 -- Section A changed, Section B stable.
    Non-overlapping with an operator edit of Section B -> clean merge expected."""
    return (
        f"# {relpath}\n\n"
        "Color: {{OL_COLOR}}\n\n"
        "## Section A\n\n"
        "UPDATED content of Section A (v1).\n\n"
        "## Section B\n\n"
        "Stable content of Section B.\n"
    )


def _op_template_v1_conflict(relpath: str) -> str:
    """Operating-layer template for vOL.1 -- Section B also changed.
    Overlapping with an operator edit of Section B -> conflict -> sidecar expected."""
    return (
        f"# {relpath}\n\n"
        "Color: {{OL_COLOR}}\n\n"
        "## Section A\n\n"
        "Original content of Section A (v0).\n\n"
        "## Section B\n\n"
        "THEIRS changed Section B content (v1).\n"
    )


def _write_foundation_bundle(
    build_root: Path,
    version: str,
    *,
    migration_from: str,
    migration_class: str = "minor-additive",
    stop_condition: str = "",
    op_template_fn=None,
) -> Path:
    """Write a synthetic bundle with foundation docs + an operating layer."""
    bundle_dir = build_root / "wizard" / "foundation-bundles" / version
    templates_dir = bundle_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    # Foundation doc templates.
    for doc in _FOUNDATION_DOCS:
        (templates_dir / doc).write_text(
            _foundation_template(doc, version), encoding="utf-8"
        )

    # Operating-layer templates (root/CLAUDE.md and root/operating_discipline.md).
    root_dir = templates_dir / "root"
    root_dir.mkdir(parents=True, exist_ok=True)
    fn = op_template_fn or _op_template_v0
    for relpath in (_OP_MARKDOWN_A, _OP_MARKDOWN_B):
        (root_dir / relpath).write_text(fn(relpath), encoding="utf-8")

    # system-artifacts.json: declare the operating-layer files with their strategies.
    artifacts = []
    for relpath in (_OP_MARKDOWN_A, _OP_MARKDOWN_B):
        artifacts.append({
            "delivery": "wizard",
            "relpath": relpath,
            "render_kind": "render",
            "merge_strategy": "three_way",
            "mode": "0644",
            "template_path": f"templates/root/{relpath}",
            "inputs": {
                "persisted": [],
                "derived": ["OL_COLOR"],
            },
        })
    contract = {
        "contract_id": "system-artifacts",
        "contract_version": "system-artifacts-v1",
        "bundle_version": version,
        "artifacts": artifacts,
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


def _write_synthetic_build_repo(
    tmp: Path,
    base_version: str = "v0.99.0",
    target_version: str = "v0.99.1",
    target_op_template_fn=None,
) -> tuple:
    """Build a synthetic repo with two bundles + registry + contract.
    Returns (build_root, registry_path)."""
    build_root = tmp / "build_repo"

    # Required-docs contract (verbatim copy of the real authority).
    contract_dst = (
        build_root / "wizard" / "foundation-bundles" / "v0" / "contracts"
        / "foundation-manifest-hash-baseline-v1.json"
    )
    contract_dst.parent.mkdir(parents=True, exist_ok=True)
    contract_dst.write_text(_REAL_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")

    # Base bundle (vOL.0) -- the system was emitted from this.
    _write_foundation_bundle(
        build_root, base_version, migration_from=base_version,
        op_template_fn=_op_template_v0,
    )
    # Target bundle (vOL.1).
    fn = target_op_template_fn or _op_template_v1_clean
    _write_foundation_bundle(
        build_root, target_version, migration_from=base_version,
        op_template_fn=fn,
    )

    registry = {
        "schema_version": "v1",
        "bundles": [
            {"foundation_bundle_version": base_version,
             "path": f"wizard/foundation-bundles/{base_version}/",
             "source_commit": "aaa0000", "status": "prerelease"},
            {"foundation_bundle_version": target_version,
             "path": f"wizard/foundation-bundles/{target_version}/",
             "source_commit": "bbb1111", "status": "prerelease"},
        ],
    }
    reg_path = build_root / "wizard" / "registry" / "foundation-bundles.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return build_root, reg_path


def _render_op_file(relpath: str, template_fn, inputs: dict) -> str:
    """Render an operating-layer file from a template function + inputs dict."""
    raw = template_fn(relpath)
    for k, v in inputs.items():
        raw = raw.replace("{{" + k + "}}", v)
    return raw


def _build_operating_layer_project(
    tmp: Path,
    build_root: Path,
    base_version: str = "v0.99.0",
) -> tuple:
    """Emit a synthetic operator project that is on base_version with:
      - all six foundation docs rendered + managed
      - _OP_MARKDOWN_A and _OP_MARKDOWN_B rendered + managed as three_way
      - a v2 capsule (carries an `operating` block so needs_capsule_upgrade is avoided)
    Returns (proj_dir, manifest_path).
    """
    proj = tmp / "operator_project"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".wizard").mkdir(parents=True, exist_ok=True)

    # Render foundation docs.
    rendered_fd = render_foundation_docs(base_version, _FDI, build_root)
    managed_files = {}

    for rec in rendered_fd:
        rel = rec.operator_relpath
        if rel == "prd.md":
            (proj / rel).write_text(rec.content, encoding="utf-8")
            continue
        (proj / rel).write_text(rec.content, encoding="utf-8")
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
            "live_lineage_version": base_version,
        }

    # Render + record the operating-layer files.
    all_inputs = dict(_FDI)
    all_inputs.update(_OPERATING_INPUTS)
    for relpath in (_OP_MARKDOWN_A, _OP_MARKDOWN_B):
        content = _render_op_file(relpath, _op_template_v0, all_inputs)
        (proj / relpath).write_text(content, encoding="utf-8")
        digest = "sha256:" + sha256_bytes(content.encode("utf-8"))
        managed_files[relpath] = {
            "managed": "true",
            "managed_by": "shared",
            "base_hash": digest,
            "base_content_hash": digest,
            "current_hash_last_seen": digest,
            "local_modifications": "expected",
            "merge_strategy": "three_way",
            "render_kind": "render",
            "source_refs": [],
            "live_lineage_version": base_version,
            "template_path": f"templates/root/{relpath}",
        }

    manifest = {
        "manifest_schema_version": "manifest-v2",
        "foundation_bundle_version": base_version,
        "source_commit": "aaa0000",
        "generator_version": "g" * 40,
        "project_name": "Test Project",
        "system_shape": "markdown-CC",
        "managed_files": managed_files,
        "control_files": [".wizard/manifest.json", ".wizard/upgrade-history.log"],
    }
    manifest_path = proj / ".wizard" / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (proj / ".wizard" / "upgrade-history.log").write_text("# history\n", encoding="utf-8")

    # v2 capsule: carries an `operating` block so capsule_supports_operating_replay
    # returns True. The `resolved_scaffold_inputs` carries OL_COLOR (the only placeholder
    # our synthetic templates use beyond PROJECT_NAME which is in foundation_doc_inputs).
    capsule = {
        "schema_version": "replay-capsule-v2",
        "foundation_bundle_version": base_version,
        "generator_version": "g" * 40,
        "system_shape": "markdown-CC",
        "foundation_only_mode": False,
        "canonicalization_version": "v1",
        "hash_algorithm": "sha256-lf",
        "foundation_doc_inputs": dict(_FDI),
        "operating": {
            "resolved_scaffold_inputs": dict(_OPERATING_INPUTS),
            "by_relpath": {},
        },
    }
    (proj / ".wizard" / "replay-capsule.json").write_text(
        json.dumps(capsule, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return proj, manifest_path


def _apply_ol(proj, manifest_path, registry_path, build_root,
              target_version="v0.99.1", ack=False):
    manifest = load_operator_manifest(manifest_path)
    registry = load_registry(registry_path)
    return apply_upgrade(
        proj, target_version, build_root,
        registry=registry, registry_path=registry_path,
        manifest=manifest, manifest_path=manifest_path,
        ack=ack,
    )


def _read(p) -> str:
    return Path(p).read_text(encoding="utf-8")


# ===========================================================================
# Test 1: contract-level assertions (no applier needed)
# ===========================================================================

class MergeStrategyByClassOperatingLayer(unittest.TestCase):
    """Assert the v0.6.0 system-artifacts.json assigns the correct merge_strategy
    to a representative cross-class sample. Exercises DIVERGENT files so no single
    file dominates (anti-overfit).

    Expected assignments (from the contract):
      .claude/context_monitor.sh  -> warn_on_drift   (script class)
      .claude/statusline.sh       -> warn_on_drift   (second script, divergent path)
      CLAUDE.md                   -> three_way        (operating markdown)
      operating_discipline.md     -> three_way        (second operating markdown, divergent)
      agents/prompts/coordinator_prompt.md -> three_way  (agent prompt)
      agents/prompts/orchestrator_prompt.md -> three_way (second agent prompt, divergent)
      prd.md                      -> operator_review  (operator-derived)
      agents/roster.md            -> operator_review  (second operator-derived, divergent)
    """

    def setUp(self):
        raw = _REAL_CONTRACT_V060.read_text(encoding="utf-8")
        data = json.loads(raw)
        self._by_relpath = {
            e["relpath"]: e
            for e in data.get("artifacts", [])
            if "relpath" in e
        }

    def _strategy(self, relpath: str) -> str:
        entry = self._by_relpath.get(relpath)
        self.assertIsNotNone(entry, f"relpath not found in v0.6.0 contract: {relpath!r}")
        return entry["merge_strategy"]

    # -- scripts -> warn_on_drift ------------------------------------------

    def test_script_context_monitor_is_warn_on_drift(self):
        self.assertEqual(self._strategy(".claude/context_monitor.sh"), "warn_on_drift")

    def test_script_statusline_is_warn_on_drift(self):
        """Divergent script: different relpath, same class -> same strategy."""
        self.assertEqual(self._strategy(".claude/statusline.sh"), "warn_on_drift")

    # -- operating markdown -> three_way -----------------------------------

    def test_operating_markdown_CLAUDE_md_is_three_way(self):
        self.assertEqual(self._strategy("CLAUDE.md"), "three_way")

    def test_operating_markdown_operating_discipline_is_three_way(self):
        """Divergent operating markdown: different relpath, same strategy."""
        self.assertEqual(self._strategy("operating_discipline.md"), "three_way")

    def test_operating_markdown_project_instructions_is_three_way(self):
        """Third operating markdown: ensures the class is consistent, not file-specific."""
        self.assertEqual(self._strategy("project_instructions.md"), "three_way")

    # -- agent prompts -> three_way ----------------------------------------

    def test_agent_prompt_coordinator_is_three_way(self):
        self.assertEqual(self._strategy("agents/prompts/coordinator_prompt.md"), "three_way")

    def test_agent_prompt_orchestrator_is_three_way(self):
        """Divergent agent prompt: different relpath, same strategy."""
        self.assertEqual(self._strategy("agents/prompts/orchestrator_prompt.md"), "three_way")

    # -- operator-derived -> operator_review ------------------------------

    def test_operator_derived_prd_is_operator_review(self):
        self.assertEqual(self._strategy("prd.md"), "operator_review")

    def test_operator_derived_roster_is_operator_review(self):
        """Divergent operator-derived: different relpath, same strategy."""
        self.assertEqual(self._strategy("agents/roster.md"), "operator_review")

    # -- render_kind consistency checks ------------------------------------

    def test_operating_markdown_CLAUDE_md_is_render_kind_render(self):
        entry = self._by_relpath.get("CLAUDE.md")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.get("render_kind"), "render")

    def test_operating_markdown_operating_discipline_is_render_kind_render(self):
        entry = self._by_relpath.get("operating_discipline.md")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.get("render_kind"), "render")

    def test_scripts_are_render_kind_copy_or_render_but_not_missing(self):
        """Scripts must declare a render_kind (copy or render; never absent)."""
        for relpath in (".claude/context_monitor.sh", ".claude/statusline.sh"):
            entry = self._by_relpath.get(relpath)
            self.assertIsNotNone(entry, f"missing: {relpath}")
            rk = entry.get("render_kind")
            self.assertIn(rk, ("copy", "render"),
                          f"{relpath} has unexpected render_kind {rk!r}")


# ===========================================================================
# Test 2: applier-level: edited operating markdown merges not blocks
# ===========================================================================

@unittest.skipUnless(
    _REAL_CONTRACT.exists(),
    "requires the real foundation-manifest-hash-baseline-v1.json (build repo not found)"
)
class EditedOperatingMarkdownMergesNotBlocks(unittest.TestCase):
    """Applier exercises: operator edits an operating-layer three_way markdown file;
    upgrade with non-conflicting change -> clean merge; conflicting change -> sidecar."""

    BASE = "v0.99.0"
    TARGET = "v0.99.1"

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _build_clean_case(self):
        """Build repo with vOL.1 template that changes Section A (operator edits Section B)."""
        return _write_synthetic_build_repo(
            self.tmp / "clean",
            base_version=self.BASE,
            target_version=self.TARGET,
            target_op_template_fn=_op_template_v1_clean,
        )

    def _build_conflict_case(self):
        """Build repo with vOL.1 template that changes Section B (operator also edits B)."""
        return _write_synthetic_build_repo(
            self.tmp / "conflict",
            base_version=self.BASE,
            target_version=self.TARGET,
            target_op_template_fn=_op_template_v1_conflict,
        )

    # -- clean merge case (non-overlapping edits) --------------------------

    def test_non_overlapping_edit_produces_clean_merge_for_both_op_markdowns(self):
        """Both _OP_MARKDOWN_A and _OP_MARKDOWN_B are three_way.
        Operator edits Section B; target changes Section A -> non-overlapping
        -> section_merge succeeds -> live file carries BOTH sections preserved.
        Asserted on BOTH relpaths (anti-overfit: not just one file)."""
        build_root, reg = self._build_clean_case()
        proj, mp = _build_operating_layer_project(self.tmp / "clean", build_root)

        # Operator edits Section B of BOTH operating markdowns (non-overlapping
        # with the target's Section A change).
        operator_additions = {}
        for relpath in (_OP_MARKDOWN_A, _OP_MARKDOWN_B):
            live_path = proj / relpath
            original = live_path.read_text(encoding="utf-8")
            edited = original.replace(
                "Stable content of Section B.",
                "Operator-customised content of Section B.",
            )
            live_path.write_text(edited, encoding="utf-8")
            operator_additions[relpath] = edited

        result = _apply_ol(proj, mp, reg, build_root)

        # Applier must not refuse.
        self.assertNotEqual(
            result.classification, "refused",
            f"upgrade refused: {result.refusal_reason}",
        )

        for relpath in (_OP_MARKDOWN_A, _OP_MARKDOWN_B):
            with self.subTest(relpath=relpath):
                dec = next(
                    (d for d in result.decisions if d.relpath == relpath), None
                )
                self.assertIsNotNone(dec, f"no decision for {relpath}")

                # Disposition must be FILE_MERGED (clean section-merge).
                self.assertEqual(
                    dec.disposition, FILE_MERGED,
                    f"{relpath}: expected FILE_MERGED, got {dec.disposition!r}; "
                    "the applier may not have dispatched operating-layer render files "
                    "through the three_way merge path.",
                )
                self.assertIn(relpath, result.files_merged)
                self.assertNotIn(relpath, result.files_in_review)

                # Live file carries BOTH the operator's Section B edit AND the target's
                # Section A change. No git markers.
                live = _read(proj / relpath)
                self.assertIn("Operator-customised content of Section B.", live,
                              f"{relpath}: operator edit lost in merge")
                self.assertIn("UPDATED content of Section A (v1).", live,
                              f"{relpath}: target change not merged in")
                self.assertNotIn("<<<<<<<", live,
                                 f"{relpath}: git conflict marker in live file")
                self.assertNotIn("=======", live,
                                 f"{relpath}: git conflict marker in live file")

    # -- conflict -> sidecar case ------------------------------------------

    def test_overlapping_edit_routes_to_sidecar_live_untouched(self):
        """Operator edits Section B; target ALSO changes Section B -> conflict ->
        section_merge fails -> review sidecar; live file = ours exactly.
        Asserted on BOTH operating-markdown relpaths (anti-overfit)."""
        build_root, reg = self._build_conflict_case()
        proj, mp = _build_operating_layer_project(self.tmp / "conflict", build_root)

        # Operator edits Section B of both files (overlapping with theirs).
        ours_text = {}
        for relpath in (_OP_MARKDOWN_A, _OP_MARKDOWN_B):
            live_path = proj / relpath
            original = live_path.read_text(encoding="utf-8")
            edited = original.replace(
                "Stable content of Section B.",
                "OURS changed Section B content (operator edit).",
            )
            live_path.write_text(edited, encoding="utf-8")
            ours_text[relpath] = edited

        result = _apply_ol(proj, mp, reg, build_root)

        # Applier must not refuse (conflict -> sidecar, not a hard refusal).
        self.assertNotEqual(
            result.classification, "refused",
            f"upgrade refused unexpectedly: {result.refusal_reason}",
        )
        # At least one file in review (partial).
        self.assertEqual(result.classification, APPLY_RESULT_PARTIAL)

        for relpath in (_OP_MARKDOWN_A, _OP_MARKDOWN_B):
            with self.subTest(relpath=relpath):
                dec = next(
                    (d for d in result.decisions if d.relpath == relpath), None
                )
                self.assertIsNotNone(dec, f"no decision for {relpath}")

                # Disposition must be FILE_REVIEW (conflict -> sidecar).
                self.assertEqual(
                    dec.disposition, FILE_REVIEW,
                    f"{relpath}: expected FILE_REVIEW, got {dec.disposition!r}",
                )
                self.assertIn(relpath, result.files_in_review)
                self.assertNotIn(relpath, result.files_merged)
                self.assertNotIn(relpath, result.files_written)

                # Live file = ours exactly (no clobber, no git markers).
                live = _read(proj / relpath)
                self.assertEqual(
                    live, ours_text[relpath],
                    f"{relpath}: live file was changed (clobbered)",
                )
                self.assertNotIn("<<<<<<<", live,
                                 f"{relpath}: git marker in live file")

                # Review sidecar exists and carries theirs + overlay note.
                upgrade_id = f"{self.BASE}-to-{self.TARGET}"
                review_dir = proj / ".wizard" / "upgrade-review" / upgrade_id
                new_sidecar = review_dir / (relpath + ".new")
                self.assertTrue(
                    new_sidecar.exists(),
                    f"{relpath}: .new sidecar not written",
                )
                sidecar_text = _read(new_sidecar)
                self.assertIn("THEIRS changed Section B content (v1).", sidecar_text,
                              f"{relpath}: sidecar does not carry theirs content")
                self.assertNotIn("<<<<<<<", sidecar_text,
                                 f"{relpath}: git marker in sidecar")


# ===========================================================================
# Test N: operator-owned files must be operator_review in EVERY bundle (operator-state clobber fix)
# ===========================================================================

# The operator/system WRITES these during operation (accumulated rules/registries/
# advisor KB, operator-tuned config, system-mutated runtime state). A single global
# `--ack` (needed to deliver a wizard warn_on_drift file) would collaterally overwrite
# their content if they were warn_on_drift. They MUST be operator_review (route theirs
# to a sidecar; live file preserved). Principle: "a file the operator or the system
# writes during operation is not warn_on_drift" (operator-state clobber fix).
_OPERATOR_OWNED_RELPATHS = (
    # operator-data accumulators
    "quality/rules_library.md",
    "quality/source_registry.md",
    "quality/advisor_knowledge_base.md",
    # operator config (seeded once, operator-tuned)
    "quality/validation_gate_config.md",
    "quality/co-protected-workflows.md",
    # system-mutated runtime state
    "quality/human_review_queue.md",
    "docs/future_items.md",
    "docs/architectural_review_staging.md",
    "docs/document_impact_map.md",
    "agents/cron/cron_config.md",
)

_BUNDLES_WITH_CONTRACT = ("v0.6.0", "v0.6.1")


def _contract_by_relpath(version: str) -> dict:
    p = _REAL_REPO / "wizard" / "foundation-bundles" / version / "system-artifacts.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return {e["relpath"]: e for e in data.get("artifacts", []) if "relpath" in e}


class OperatorOwnedFilesAreOperatorReview(unittest.TestCase):
    """Operator-state clobber fix: operator/system-written files must be operator_review in
    EVERY bundle that carries a contract, so a global `--ack` can never clobber them."""

    def test_operator_owned_files_are_operator_review_in_every_bundle(self):
        for version in _BUNDLES_WITH_CONTRACT:
            by_rel = _contract_by_relpath(version)
            for rel in _OPERATOR_OWNED_RELPATHS:
                entry = by_rel.get(rel)
                self.assertIsNotNone(entry, f"{version}: {rel} missing from contract")
                self.assertEqual(
                    entry["merge_strategy"], "operator_review",
                    f"{version}: {rel} must be operator_review (operator/system-written; "
                    f"warn_on_drift lets a global --ack clobber operator content)",
                )

    def test_system_authored_templates_are_not_warn_on_drift(self):
        """Forward guard (machine-checkable principle): any DELIVERED file whose template
        self-declares it is system-maintained ('Never edited manually') must not be
        warn_on_drift -- catches the NEXT misclassified system-state file before it ships."""
        for version in _BUNDLES_WITH_CONTRACT:
            bundle = _REAL_REPO / "wizard" / "foundation-bundles" / version
            for rel, entry in _contract_by_relpath(version).items():
                tp = entry.get("template_path")
                if not tp:
                    continue
                tpath = bundle / tp
                if not tpath.is_file():
                    continue
                if "Never edited manually" in tpath.read_text(encoding="utf-8"):
                    self.assertNotEqual(
                        entry.get("merge_strategy"), "warn_on_drift",
                        f"{version}: {rel} template says 'Never edited manually' but is "
                        f"warn_on_drift -- a global --ack would wipe its system-written state",
                    )


class ManifestMergeStrategyRefreshTests(unittest.TestCase):
    """Plan/apply-consistency hygiene: after an apply, a SURVIVING managed file's manifest
    merge_strategy is refreshed from the TARGET contract, so a stale manifest value
    (e.g. an older emit's warn_on_drift on a file later reclassified operator_review)
    does not keep mislabeling the file post-upgrade."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_surviving_file_merge_strategy_refreshed_from_contract(self):
        build_root, reg = _write_synthetic_build_repo(self.tmp)
        proj, mp = _build_operating_layer_project(self.tmp, build_root)
        # Make the manifest STALE for _OP_MARKDOWN_A: the target contract declares it
        # three_way, but the operator's manifest still says warn_on_drift (older emit).
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        manifest["managed_files"][_OP_MARKDOWN_A]["merge_strategy"] = "warn_on_drift"
        mp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _apply_ol(proj, mp, reg, build_root, ack=True)
        new_manifest = json.loads(mp.read_text(encoding="utf-8"))
        self.assertEqual(
            new_manifest["managed_files"][_OP_MARKDOWN_A]["merge_strategy"], "three_way",
            "post-apply manifest kept the stale merge_strategy instead of refreshing it "
            "from the target contract (plan/manifest would keep mislabeling the file)",
        )


class ControlPlaneRendererRegistry(unittest.TestCase):
    """`.wizard/update-source.json` must NOT be upgrade-refreshed (it is delivered once at emit
    and is thereafter operator/system runtime state — its `last_known_good_commit` is written by
    every verified self-update, so re-rendering the default body routed it to review as noise on
    every upgrade and demoted the result to `partial`). The control-plane renderer returns None
    for it (-> the apply skips it, leaving the operator's pin untouched), while a genuine
    control-plane guidance file (UPGRADING.md) still renders."""

    def test_update_source_is_not_control_plane_refreshed(self):
        from upgrade_apply import _render_control_plane_body  # noqa: E402
        self.assertIsNone(
            _render_control_plane_body(".wizard/update-source.json"),
            "update-source.json must not be upgrade-refreshed (operator/system runtime state)",
        )

    def test_upgrading_md_still_control_plane_refreshed(self):
        from upgrade_apply import _render_control_plane_body  # noqa: E402
        self.assertIsNotNone(
            _render_control_plane_body(".wizard/UPGRADING.md"),
            "UPGRADING.md is genuine wizard guidance and must still refresh on upgrade",
        )


# ===========================================================================
# Regression test: old capsule (pre-v0.7.0) missing OPERATOR_OUTPUT_POINTER
# ===========================================================================

class OldCapsuleNewPlaceholderFallsBackToDefault(unittest.TestCase):
    """Regression guard for the v0.7.0 OPERATOR_OUTPUT_POINTER upgrade-refusal bug.

    When a pre-v0.7.0 operator project upgrades to a bundle whose agent-layer
    template references {{OPERATOR_OUTPUT_POINTER}}, the old capsule's by_relpath
    entry for that agent file does NOT contain OPERATOR_OUTPUT_POINTER (it was added
    in v0.7.0).  Before the fix, _render_operating_layer used by_relpath[rel] as the
    sole sub_inputs dict, so the missing key caused an UpgradeApplyError (refusal).
    After the fix, _default_scaffold_inputs() is seeded first so OPERATOR_OUTPUT_POINTER
    defaults to "" and the render succeeds.

    Two assertions:
      1. Render succeeds (no UpgradeApplyError / no GeneratorError) and
         OPERATOR_OUTPUT_POINTER resolves to "" (the safe empty default from
         _default_scaffold_inputs) in the rendered output.
      2. A capsule-provided value WINS over the default for a key the capsule
         already carries (e.g. PROJECT_NAME, which is also in _default_scaffold_inputs
         as a placeholder text).

    This test calls _render_operating_layer directly (unit-level) to isolate the
    fixed code path from the full apply_upgrade transaction.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    # --- helpers ----------------------------------------------------------------

    def _build_synthetic_bundle(self, build_root: Path, version: str) -> None:
        """Write the minimal synthetic bundle needed by _render_operating_layer.

        The agent-layer template references {{OPERATOR_OUTPUT_POINTER}} (the new v0.7.0
        placeholder) plus {{PROJECT_NAME}} (an existing key the capsule carries).
        Foundation doc templates are included so derive_scaffold_render_inputs resolves.
        The required-docs contract is copied from the real authority.
        """
        bundle_dir = build_root / "wizard" / "foundation-bundles" / version
        templates_dir = bundle_dir / "templates"
        agent_tpl_dir = templates_dir / "agents" / "prompts"
        agent_tpl_dir.mkdir(parents=True, exist_ok=True)

        # Agent-layer template: references OPERATOR_OUTPUT_POINTER (new) + PROJECT_NAME (old).
        agent_tpl = agent_tpl_dir / "coordinator_prompt.md"
        agent_tpl.write_text(
            "# Coordinator -- {{PROJECT_NAME}}\n\n"
            "Output pointer: {{OPERATOR_OUTPUT_POINTER}}\n\n"
            "Stable agent body.\n",
            encoding="utf-8",
        )

        # Foundation doc templates (minimal; needed by derive_scaffold_render_inputs).
        for doc in _FOUNDATION_DOCS:
            (templates_dir / doc).write_text(
                _foundation_template(doc, version), encoding="utf-8"
            )

        # system-artifacts.json: declare the agent-layer file.
        contract = {
            "contract_id": "system-artifacts",
            "contract_version": "system-artifacts-v1",
            "bundle_version": version,
            "artifacts": [
                {
                    "delivery": "wizard",
                    "relpath": "agents/prompts/coordinator_prompt.md",
                    "render_kind": "render",
                    "merge_strategy": "three_way",
                    "mode": "0644",
                    "template_path": "templates/agents/prompts/coordinator_prompt.md",
                    "inputs": {
                        "persisted": ["PROJECT_NAME"],
                        "derived": ["OPERATOR_OUTPUT_POINTER"],
                    },
                }
            ],
        }
        (bundle_dir / "system-artifacts.json").write_text(
            json.dumps(contract, indent=2) + "\n", encoding="utf-8"
        )

        # Provenance sidecar (read by upgrade path helpers).
        (bundle_dir / "foundation-bundle.provenance.json").write_text(
            json.dumps({"generator_version": f"gen-{version}"}) + "\n", encoding="utf-8"
        )

        # Required-docs contract (copied verbatim from the real authority).
        contract_dst = (
            build_root / "wizard" / "foundation-bundles" / "v0" / "contracts"
            / "foundation-manifest-hash-baseline-v1.json"
        )
        contract_dst.parent.mkdir(parents=True, exist_ok=True)
        contract_dst.write_text(_REAL_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")

    def _build_old_capsule(self) -> dict:
        """Build a pre-v0.7.0 capsule whose by_relpath entry for the agent file
        lacks OPERATOR_OUTPUT_POINTER -- simulating an operator project set up before
        that placeholder was introduced in v0.7.0."""
        return {
            "schema_version": "replay-capsule-v2",
            "foundation_bundle_version": "v0.6.9",
            "generator_version": "g" * 40,
            "system_shape": "markdown-CC",
            "foundation_only_mode": False,
            "canonicalization_version": "v1",
            "hash_algorithm": "sha256-lf",
            "foundation_doc_inputs": {
                "PROJECT_NAME": "OldProject",
                "WIZARD_VERSION": "v0.6.9",
            },
            "operating": {
                "resolved_scaffold_inputs": {},
                # by_relpath carries the agent file's substitution dict as recorded at
                # v0.6.9 emit -- OPERATOR_OUTPUT_POINTER is intentionally absent here,
                # simulating the real state of any pre-v0.7.0 operator project.
                "by_relpath": {
                    "agents/prompts/coordinator_prompt.md": {
                        "PROJECT_NAME": "OldProject",
                        # OPERATOR_OUTPUT_POINTER deliberately absent: not in old capsules.
                    }
                },
            },
        }

    # --- test methods -----------------------------------------------------------

    @unittest.skipUnless(
        _REAL_CONTRACT.exists(),
        "requires the real foundation-manifest-hash-baseline-v1.json (build repo not found)"
    )
    def test_missing_placeholder_falls_back_to_empty_default(self):
        """_render_operating_layer must NOT raise UpgradeApplyError when an old capsule's
        by_relpath entry lacks OPERATOR_OUTPUT_POINTER but the new bundle template references it.
        The placeholder must resolve to "" (the _default_scaffold_inputs safe default), not
        left as a raw {{...}} and not cause a refusal."""
        from upgrade_apply import _render_operating_layer, UpgradeApplyError as UAError  # noqa: E402

        version = "v0.7.0-regtest"
        build_root = self.tmp / "build_repo_fallback"
        self._build_synthetic_bundle(build_root, version)

        capsule = self._build_old_capsule()
        capsule_inputs = capsule["foundation_doc_inputs"]

        # Must not raise -- this is the regression: old capsule missing a new key.
        try:
            rendered = _render_operating_layer(
                version,
                ["agents/prompts/coordinator_prompt.md"],
                capsule=capsule,
                capsule_inputs=capsule_inputs,
                project_name="OldProject",
                build_repo_root=build_root,
            )
        except UAError as exc:
            self.fail(
                "REGRESSION: _render_operating_layer raised UpgradeApplyError on an old "
                "capsule missing OPERATOR_OUTPUT_POINTER (pre-fix behaviour restored):\n"
                f"{exc}"
            )

        content = rendered["agents/prompts/coordinator_prompt.md"]

        # The raw placeholder must not survive into the rendered output.
        self.assertNotIn(
            "{{OPERATOR_OUTPUT_POINTER}}",
            content,
            "OPERATOR_OUTPUT_POINTER was not substituted -- raw placeholder leaked into output",
        )
        # The resolved value from _default_scaffold_inputs is ""; the rendered line
        # becomes "Output pointer: \n" (key replaced by its empty-string default).
        self.assertIn(
            "Output pointer: \n",
            content,
            "OPERATOR_OUTPUT_POINTER did not resolve to the expected empty-string default; "
            "check that _default_scaffold_inputs() seeds sub_inputs before the capsule overlay",
        )

    @unittest.skipUnless(
        _REAL_CONTRACT.exists(),
        "requires the real foundation-manifest-hash-baseline-v1.json (build repo not found)"
    )
    def test_capsule_provided_value_wins_over_default(self):
        """A key the capsule's by_relpath entry DOES provide must use the capsule value,
        not the _default_scaffold_inputs fallback -- capsule values always win over defaults."""
        from upgrade_apply import _render_operating_layer  # noqa: E402

        version = "v0.7.0-regtest"
        build_root = self.tmp / "build_repo_win"
        self._build_synthetic_bundle(build_root, version)

        capsule = self._build_old_capsule()
        # PROJECT_NAME is in the capsule's by_relpath entry; _default_scaffold_inputs
        # carries a different sentinel for it -- the capsule value "OldProject" must win.
        capsule_inputs = capsule["foundation_doc_inputs"]

        rendered = _render_operating_layer(
            version,
            ["agents/prompts/coordinator_prompt.md"],
            capsule=capsule,
            capsule_inputs=capsule_inputs,
            project_name="OldProject",
            build_repo_root=build_root,
        )
        content = rendered["agents/prompts/coordinator_prompt.md"]

        # The capsule's PROJECT_NAME "OldProject" must appear in the heading.
        self.assertIn(
            "# Coordinator -- OldProject",
            content,
            "capsule-provided PROJECT_NAME was overridden by the scaffold default "
            "(capsule values must always win over _default_scaffold_inputs fallback)",
        )
        # The scaffold default for PROJECT_NAME contains "operator-configures"; it must
        # not appear (that would mean the default stomped the capsule value).
        self.assertNotIn(
            "operator-configures",
            content,
            "scaffold default text leaked into output -- capsule value did not win "
            "over _default_scaffold_inputs; check the overlay order (defaults seeded first, "
            "then capsule overlaid on top)",
        )


if __name__ == "__main__":
    unittest.main()
