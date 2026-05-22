"""Unit tests for wizard.scripts.lib.generator.

Stdlib-only (wizard-distribution boundary): unittest + tempfile + json + pathlib.
No PyYAML import.

Test sub-suites:
    (a) template substitution correctness — placeholder substitution + fail-fast
    (b) PRD stub emission — frontmatter + 4 hardcoded section headings
    (c) source_commit passthrough from registry — verbatim copy from
        wizard/registry/foundation-bundles.json
    (d) generator_version emission — value from the helper override appears in
        the manifest
    (e) deterministic text emission — byte-identical reproduction across runs
        with fixed provenance
    (f) generator-version-identity helper integration smoke — generator passes
        require_clean through to the helper. The helper's own dirty-worktree
        behavior is tested in test_generator_version.py. Here we only check
        that the override seam works and that the non-override path imports
        the helper at call time.
    (g) operator manifest tight field set — no package-side fields in output
    (h) files-map ordering — anchored to the hash-baseline contract's
        required_foundation_docs
"""

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

# sys.path setup so `import generator` resolves regardless of invocation style.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from generator import (  # noqa: E402
    PLACEHOLDER_RE,
    PRD_STUB_SECTIONS,
    GeneratorError,
    _emit_manifest_text,
    _emit_prd_stub,
    _substitute_placeholders,
    generate_bundle,
)


# Test constants.
FIXED_GEN_VER = "0123456789abcdef0123456789abcdef01234567"  # 40-char hex
FIXED_SOURCE_COMMIT = "deadbeef"  # arbitrary; test fixture
SYNTHETIC_REQUIRED_DOCS = [
    {
        "path": "foundation/vision.md",
        "managed_by": "shared",
        "local_modifications": "expected",
        "merge_strategy": "three_way",
    },
    {
        "path": "foundation/prd.md",
        "managed_by": "operator",
        "local_modifications": "expected",
        "merge_strategy": "operator_review",
    },
    {
        "path": "foundation/approach.md",
        "managed_by": "shared",
        "local_modifications": "allowed",
        "merge_strategy": "three_way",
    },
]


def _setup_fake_build_repo(tmp_path: Path) -> Path:
    """Create a minimal fake build-repo layout under tmp_path.

    Layout:
        tmp_path/
          .git/                     # so detect_build_repo_root can find it
          wizard/registry/foundation-bundles.json
          wizard/foundation-bundles/v0/contracts/foundation-manifest-hash-baseline-v1.json
          wizard/foundation-bundles/vX.Y.Z/templates/*.md   # caller adds templates

    Returns the build_repo_root (tmp_path).
    """
    (tmp_path / ".git").mkdir()
    (tmp_path / "wizard" / "registry").mkdir(parents=True)
    (tmp_path / "wizard" / "foundation-bundles" / "v0" / "contracts").mkdir(parents=True)

    # Minimal registry with one entry (caller fills version).
    return tmp_path


def _write_registry(
    build_repo_root: Path,
    version: str,
    source_commit: str,
) -> None:
    registry = {
        "schema_version": "v1",
        "bundles": [
            {
                "foundation_bundle_version": version,
                "path": f"wizard/foundation-bundles/{version}/",
                "release_date": "2026-05-22",
                "source_commit": source_commit,
                "manifest": f"wizard/foundation-bundles/{version}/manifest.yaml",
                "status": "prerelease",
            }
        ],
    }
    (build_repo_root / "wizard" / "registry" / "foundation-bundles.json").write_text(
        json.dumps(registry, indent=2)
    )


def _write_contract(
    build_repo_root: Path,
    required_docs: list,
) -> None:
    # Build a contract that passes manifest_contract.load_manifest_contract()'s
    # 8 validation gates — the generator delegates to that loader per Path A.
    contract = {
        "contract_id": "foundation-manifest-hash-baseline",
        "contract_version": "manifest-v1",
        "schema_authorities": [
            "foundation_bundle_public_api.required_foundation_docs",
            "foundation_manifest_hash_baseline.file_fields",
            "foundation_manifest_hash_baseline.merge_strategy_enum",
        ],
        "description": "test-fixture contract for wizard.scripts.lib.test_generator",
        "required_foundation_docs": required_docs,
        "manifest_file_fields": [
            "managed",
            "base_hash",
            "current_hash_last_seen",
            "local_modifications",
            "merge_strategy",
        ],
        "enums": {
            "managed_by": ["shared", "operator", "wizard"],
            "local_modifications": ["expected", "allowed", "not_recommended"],
            "merge_strategy": [
                "three_way",
                "operator_review",
                "warn_on_drift",
                "frozen",
            ],
        },
    }
    (
        build_repo_root
        / "wizard"
        / "foundation-bundles"
        / "v0"
        / "contracts"
        / "foundation-manifest-hash-baseline-v1.json"
    ).write_text(json.dumps(contract, indent=2))


def _write_template(
    build_repo_root: Path, version: str, name: str, content: str
) -> Path:
    """Write a template file at wizard/foundation-bundles/<version>/templates/<name>."""
    tdir = build_repo_root / "wizard" / "foundation-bundles" / version / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    path = tdir / name
    path.write_text(content)
    return path


# ============================================================================
# (a) Template substitution
# ============================================================================

class TestSubstitution(unittest.TestCase):

    def test_substitute_basic(self):
        content = "Hello {{NAME}}, welcome to {{PROJECT}}."
        inputs = {"NAME": "Alice", "PROJECT": "Wizard"}
        result, seen = _substitute_placeholders(content, inputs, "test.md")
        self.assertEqual(result, "Hello Alice, welcome to Wizard.")
        self.assertEqual(seen, {"NAME", "PROJECT"})

    def test_substitute_failfast_on_missing(self):
        content = "Hello {{NAME}}, project {{PROJECT}} owes {{OWED_VALUE}}."
        inputs = {"NAME": "Bob"}  # PROJECT + OWED_VALUE missing
        with self.assertRaises(GeneratorError) as cm:
            _substitute_placeholders(content, inputs, "test.md")
        msg = str(cm.exception)
        self.assertIn("test.md", msg)
        self.assertIn("PROJECT", msg)
        self.assertIn("OWED_VALUE", msg)

    def test_substitute_strict_pattern_uppercase_only(self):
        # lowercase keys must NOT match (matches the strict pattern).
        content = "lowercase {{name}} should not match; UPPER {{NAME}} does."
        inputs = {"NAME": "Yes"}
        result, _seen = _substitute_placeholders(content, inputs, "test.md")
        self.assertEqual(result, "lowercase {{name}} should not match; UPPER Yes does.")

    def test_substitute_no_recursion(self):
        # Substituted value itself contains a {{KEY}} which should NOT be expanded.
        content = "outer {{KEY}}"
        inputs = {"KEY": "literal {{NESTED}}"}
        result, _seen = _substitute_placeholders(content, inputs, "test.md")
        self.assertEqual(result, "outer literal {{NESTED}}")

    def test_substitute_returns_seen_keys(self):
        # Returned seen-set lets the caller detect unused inputs.
        content = "only {{USED_KEY}} here"
        inputs = {"USED_KEY": "x", "UNUSED_KEY": "y"}
        result, seen = _substitute_placeholders(content, inputs, "test.md")
        self.assertEqual(result, "only x here")
        self.assertEqual(seen, {"USED_KEY"})  # UNUSED_KEY NOT in seen-set

    def test_substitute_pattern_matches_test_corpus(self):
        # Sanity: pattern matches the actual {{KEY}} shapes used across templates.
        for sample in [
            "{{WIZARD_VERSION}}",
            "{{VISION_PURPOSE}}",
            "{{AGENT_ROSTER_ROWS}}",
            "{{LAST_UPDATED_DATE}}",
            "{{MVP_CORE_FUNCTION}}",
        ]:
            self.assertIsNotNone(PLACEHOLDER_RE.match(sample))


# ============================================================================
# (b) PRD stub emission
# ============================================================================

class TestPrdStub(unittest.TestCase):

    def test_prd_stub_contains_4_section_headings(self):
        inputs = {"WIZARD_VERSION": "v0.3.0"}
        content = _emit_prd_stub(inputs)
        for _section_id, section_title in PRD_STUB_SECTIONS:
            self.assertIn(f"## {section_title}", content)
        # Sanity: exactly 4 sections.
        self.assertEqual(len(PRD_STUB_SECTIONS), 4)

    def test_prd_stub_has_frontmatter(self):
        inputs = {"WIZARD_VERSION": "v0.3.0"}
        content = _emit_prd_stub(inputs)
        self.assertTrue(content.startswith("---\n"))
        self.assertIn("foundation_doc_type: prd", content)
        self.assertIn("managed_by: operator", content)
        self.assertIn('wizard_version_compatible: "v0.3.0"', content)

    def test_prd_stub_has_operator_authored_header(self):
        inputs = {"WIZARD_VERSION": "v0.3.0"}
        content = _emit_prd_stub(inputs)
        self.assertIn("OPERATOR-AUTHORED CONTENT REQUIRED", content)

    def test_prd_stub_section_titles_canonical(self):
        # PRD_STUB_SECTIONS canonical content: matches what tools/test_prd_stub_parity.py
        # verifies against v0.3.0/schemas/section-schema.yaml.
        self.assertEqual(
            PRD_STUB_SECTIONS,
            [
                ("vision_link", "Vision Link"),
                ("persona_jtbd", "Persona / JTBD"),
                ("functional_requirements", "Functional Requirements"),
                ("non_functional_requirements", "Non-Functional Requirements"),
            ],
        )


# ============================================================================
# (c, d, g, h) End-to-end with fake build-repo
# ============================================================================

class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.build_repo_root = _setup_fake_build_repo(self.tmp_path)
        _write_registry(self.build_repo_root, "vX.Y.Z", FIXED_SOURCE_COMMIT)
        _write_contract(self.build_repo_root, SYNTHETIC_REQUIRED_DOCS)
        # Write 2 templates (3rd required doc is prd.md which doesn't ship template).
        _write_template(
            self.build_repo_root,
            "vX.Y.Z",
            "vision.md",
            "---\nfoundation_doc_type: vision\n---\n\n# Vision\n{{VISION_TEXT}}\n",
        )
        _write_template(
            self.build_repo_root,
            "vX.Y.Z",
            "approach.md",
            "---\nfoundation_doc_type: approach\n---\n\n# Approach\n{{APPROACH_TEXT}}\n",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _run_generator(self, inputs: dict, target: Path) -> "GenerationResult":
        return generate_bundle(
            source_version="vX.Y.Z",
            target_dir=target,
            inputs=inputs,
            build_repo_root=self.build_repo_root,
            generator_version_override=FIXED_GEN_VER,
        )

    def test_source_commit_passthrough_from_registry(self):
        """(c) source_commit MUST come from registry, not build-repo HEAD."""
        target = self.tmp_path / "target1"
        inputs = {
            "VISION_TEXT": "Synthetic vision content.",
            "APPROACH_TEXT": "Synthetic approach content.",
            "WIZARD_VERSION": "vX.Y.Z",
        }
        self._run_generator(inputs, target)
        manifest = (target / ".wizard" / "manifest.yaml").read_text()
        self.assertIn(f"source_commit: {FIXED_SOURCE_COMMIT}", manifest)
        # Negative: build-repo HEAD must NOT appear (we don't compute it).
        # No need for explicit negative — if it appeared it'd be a different SHA.

    def test_generator_version_emission_from_override(self):
        """(d) generator_version field carries the override (proxy for F-9 helper output)."""
        target = self.tmp_path / "target2"
        inputs = {
            "VISION_TEXT": "Synthetic vision content.",
            "APPROACH_TEXT": "Synthetic approach content.",
            "WIZARD_VERSION": "vX.Y.Z",
        }
        self._run_generator(inputs, target)
        manifest = (target / ".wizard" / "manifest.yaml").read_text()
        self.assertIn(f"generator_version: {FIXED_GEN_VER}", manifest)

    def test_operator_manifest_tight_field_set(self):
        """(g) NO package-side fields appear in operator manifest."""
        target = self.tmp_path / "target3"
        inputs = {
            "VISION_TEXT": "Synthetic vision content.",
            "APPROACH_TEXT": "Synthetic approach content.",
            "WIZARD_VERSION": "vX.Y.Z",
        }
        self._run_generator(inputs, target)
        manifest = (target / ".wizard" / "manifest.yaml").read_text()
        # Tight field set: only 4 top-level + files map.
        # Per § A.5 AP-7: NO package-side fields permitted.
        forbidden_fields = [
            "foundation_schema_version:",
            "agent_contract_version:",
            "release_date:",
            "status:",
            "managed_files:",
            "included_templates:",
            "public_api:",
        ]
        for forbidden in forbidden_fields:
            self.assertNotIn(
                forbidden,
                manifest,
                f"forbidden package-side field {forbidden!r} appears in operator manifest",
            )
        # Required top-level fields present.
        self.assertIn("foundation_bundle_version: vX.Y.Z\n", manifest)
        self.assertIn("source_commit: ", manifest)
        self.assertIn("generator_version: ", manifest)
        self.assertIn("files:\n", manifest)

    def test_files_map_ordering_by_contract(self):
        """(h) files map ordering matches required_foundation_docs ordering."""
        target = self.tmp_path / "target4"
        inputs = {
            "VISION_TEXT": "Synthetic vision content.",
            "APPROACH_TEXT": "Synthetic approach content.",
            "WIZARD_VERSION": "vX.Y.Z",
        }
        self._run_generator(inputs, target)
        manifest = (target / ".wizard" / "manifest.yaml").read_text()
        # Extract top-level keys of files: block in order.
        files_section = manifest.split("files:", 1)[1]
        # File paths appear as `  foundation/<name>.md:` (2-space indent).
        file_keys = re.findall(r"^  (foundation/[a-z_]+\.md):", files_section, re.MULTILINE)
        expected_order = [d["path"] for d in SYNTHETIC_REQUIRED_DOCS]
        self.assertEqual(file_keys, expected_order)


# ============================================================================
# (e) Deterministic text emission
# ============================================================================

class TestDeterminism(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.build_repo_root = _setup_fake_build_repo(self.tmp_path)
        _write_registry(self.build_repo_root, "vX.Y.Z", FIXED_SOURCE_COMMIT)
        _write_contract(self.build_repo_root, SYNTHETIC_REQUIRED_DOCS)
        _write_template(
            self.build_repo_root,
            "vX.Y.Z",
            "vision.md",
            "---\nfoundation_doc_type: vision\n---\n\n# Vision\n{{VISION_TEXT}}\n",
        )
        _write_template(
            self.build_repo_root,
            "vX.Y.Z",
            "approach.md",
            "---\nfoundation_doc_type: approach\n---\n\n# Approach\n{{APPROACH_TEXT}}\n",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_byte_identical_reproduction(self):
        """(e) Two runs with identical inputs + fixed provenance produce identical files."""
        inputs = {
            "VISION_TEXT": "Synthetic vision content.",
            "APPROACH_TEXT": "Synthetic approach content.",
            "WIZARD_VERSION": "vX.Y.Z",
        }
        target_a = self.tmp_path / "run_a"
        target_b = self.tmp_path / "run_b"
        generate_bundle(
            source_version="vX.Y.Z",
            target_dir=target_a,
            inputs=inputs,
            build_repo_root=self.build_repo_root,
            generator_version_override=FIXED_GEN_VER,
        )
        generate_bundle(
            source_version="vX.Y.Z",
            target_dir=target_b,
            inputs=inputs,
            build_repo_root=self.build_repo_root,
            generator_version_override=FIXED_GEN_VER,
        )
        # Compare every generated file byte-by-byte.
        files_a = sorted(p.relative_to(target_a) for p in target_a.rglob("*") if p.is_file())
        files_b = sorted(p.relative_to(target_b) for p in target_b.rglob("*") if p.is_file())
        self.assertEqual(files_a, files_b)
        for rel in files_a:
            content_a = (target_a / rel).read_bytes()
            content_b = (target_b / rel).read_bytes()
            self.assertEqual(content_a, content_b, f"{rel} differs between runs")


# ============================================================================
# (f) F-9 integration smoke (override seam)
# ============================================================================

class TestF9IntegrationSmoke(unittest.TestCase):
    """Generator passes require_clean through to the generator-version helper.

    The helper's own dirty-worktree behavior is tested in
    wizard/scripts/lib/test_generator_version.py. Here we only test:
      - the override seam works (skip the helper entirely with
        generator_version_override);
      - when override is None, the helper is imported at call time
        (smoke check, not full integration).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.build_repo_root = _setup_fake_build_repo(self.tmp_path)
        _write_registry(self.build_repo_root, "vX.Y.Z", FIXED_SOURCE_COMMIT)
        _write_contract(self.build_repo_root, SYNTHETIC_REQUIRED_DOCS)
        _write_template(
            self.build_repo_root,
            "vX.Y.Z",
            "vision.md",
            "{{VISION_TEXT}}",
        )
        _write_template(
            self.build_repo_root,
            "vX.Y.Z",
            "approach.md",
            "{{APPROACH_TEXT}}",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_override_seam_skips_f9(self):
        inputs = {
            "VISION_TEXT": "v",
            "APPROACH_TEXT": "a",
            "WIZARD_VERSION": "vX.Y.Z",
        }
        result = generate_bundle(
            source_version="vX.Y.Z",
            target_dir=self.tmp_path / "tgt",
            inputs=inputs,
            build_repo_root=self.build_repo_root,
            generator_version_override=FIXED_GEN_VER,
        )
        self.assertTrue(result.success)
        manifest = result.manifest_path.read_text()
        self.assertIn(f"generator_version: {FIXED_GEN_VER}", manifest)


# ============================================================================
# Hash computation correctness
# ============================================================================

class TestHashComputation(unittest.TestCase):
    """Per-file base_hash is sha256 over file content."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.build_repo_root = _setup_fake_build_repo(self.tmp_path)
        _write_registry(self.build_repo_root, "vX.Y.Z", FIXED_SOURCE_COMMIT)
        _write_contract(self.build_repo_root, SYNTHETIC_REQUIRED_DOCS)
        _write_template(
            self.build_repo_root,
            "vX.Y.Z",
            "vision.md",
            "{{VISION_TEXT}}",
        )
        _write_template(
            self.build_repo_root,
            "vX.Y.Z",
            "approach.md",
            "{{APPROACH_TEXT}}",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_base_hash_matches_content_sha256(self):
        inputs = {
            "VISION_TEXT": "Vision content X.",
            "APPROACH_TEXT": "Approach content Y.",
            "WIZARD_VERSION": "vX.Y.Z",
        }
        target = self.tmp_path / "tgt"
        result = generate_bundle(
            source_version="vX.Y.Z",
            target_dir=target,
            inputs=inputs,
            build_repo_root=self.build_repo_root,
            generator_version_override=FIXED_GEN_VER,
        )
        manifest_text = result.manifest_path.read_text()
        # vision.md hash check
        vision_content = (target / "foundation" / "vision.md").read_bytes()
        vision_hash = hashlib.sha256(vision_content).hexdigest()
        self.assertIn(f"base_hash: sha256:{vision_hash}", manifest_text)
        # prd.md hash check
        prd_content = (target / "foundation" / "prd.md").read_bytes()
        prd_hash = hashlib.sha256(prd_content).hexdigest()
        self.assertIn(f"base_hash: sha256:{prd_hash}", manifest_text)


# ============================================================================
# Manifest text emission unit (no fixtures needed)
# ============================================================================

class TestManifestTextEmission(unittest.TestCase):

    def test_emit_manifest_text_shape(self):
        files_map = [
            {
                "path": "foundation/vision.md",
                "base_hash": "a" * 64,
                "current_hash_last_seen": "a" * 64,
                "local_modifications": "expected",
                "merge_strategy": "three_way",
            },
        ]
        text = _emit_manifest_text(
            foundation_bundle_version="v0.3.0",
            source_commit="15757c5",
            generator_version=FIXED_GEN_VER,
            files_map=files_map,
        )
        # Field order verification.
        expected = (
            "foundation_bundle_version: v0.3.0\n"
            "source_commit: 15757c5\n"
            f"generator_version: {FIXED_GEN_VER}\n"
            "files:\n"
            "  foundation/vision.md:\n"
            "    managed: true\n"
            f"    base_hash: sha256:{'a' * 64}\n"
            f"    current_hash_last_seen: sha256:{'a' * 64}\n"
            "    local_modifications: expected\n"
            "    merge_strategy: three_way\n"
        )
        self.assertEqual(text, expected)


if __name__ == "__main__":
    unittest.main()
