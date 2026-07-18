"""Regression test for F-67: the emitted operator project's root `.gitignore`
must cover the four consent/runtime artifact locations the external_write
machinery writes at operate time (`security/acceptance_receipts/`,
`security/run_envelopes/`, `security/invocation_ledgers/`,
`security/capability_acceptance_log.jsonl`). Without ignore coverage, the
operator's always-on commit-hygiene guard surfaces a git decision ("commit
these? ignore them?") that a non-technical operator should never have to make.

No bundle has cut the current `wizard/templates/root/gitignore_template` /
`wizard/templates/security/gitignore_manifest.md` edit yet (the physical bundle
copy lands at this slice's own bundle cut -- this task is source-templates-only
and must not touch foundation-bundles/). So this test builds an isolated
FIXTURE build-repo-root exactly like
`test_operator_system_emitter.ExternalWriteLibRegistryEnrollmentTests`: a full
copy of the real, already-cut v0.13.1 bundle (has the operating-layer
contract), with its `templates/root/gitignore_template` and
`templates/security/gitignore_manifest.md` overlaid by the CURRENT dev-tree
templates -- reproducing exactly what this slice's bundle cut will ship for
those two files -- and drives the REAL production emit surface
(`scaffold_emitter.emit_scaffold`) against it into a fresh temp tree (no
copytree of the dev tree itself; the emit path is what is under test).

Stdlib unittest; pip-install-free.
"""

import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scaffold_emitter import emit_scaffold  # noqa: E402
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# The highest already-cut bundle carrying the operating-layer contract, used as
# the fixture base (its templates/root + templates/security are overlaid by
# the current dev tree below).
FIXTURE_BUNDLE_VERSION = "v0.13.1"

# The four consent/runtime artifact-path tokens the plan requires .gitignore
# coverage for (see DEFAULT_RECEIPT_DIR / DEFAULT_ENVELOPE_DIR / DEFAULT_LEDGER_DIR
# / DEFAULT_AUDIT_LOG_PATH in wizard/agents/lib/external_write/).
REQUIRED_TOKENS = (
    "security/acceptance_receipts",
    "run_envelopes",
    "invocation_ledgers",
    "capability_acceptance_log",
)


class EmitGitignoreCoversConsentRuntimeArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _fixture_build_repo_root(self) -> Path:
        """A synthetic build_repo_root mirroring the real toolkit layout, except
        the fixture bundle's templates/root/gitignore_template and
        templates/security/gitignore_manifest.md are overlaid by the CURRENT
        dev-tree templates -- simulating the not-yet-cut bundle state without
        touching foundation-bundles/."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fixture_root = Path(tmp.name)
        shutil.copytree(
            REPO_ROOT / "wizard" / "registry", fixture_root / "wizard" / "registry")
        shutil.copytree(
            REPO_ROOT / "wizard" / "foundation-bundles",
            fixture_root / "wizard" / "foundation-bundles")

        fixture_bundle_dir = fixture_root / "wizard" / "foundation-bundles" / FIXTURE_BUNDLE_VERSION
        for rel in ("templates/root/gitignore_template", "templates/security/gitignore_manifest.md"):
            dst = fixture_bundle_dir / rel
            dst.unlink()
            shutil.copy(REPO_ROOT / "wizard" / rel, dst)
        return fixture_root

    def _plan(self):
        p = copy.deepcopy(_valid_plan())
        p["bundle_version"] = FIXTURE_BUNDLE_VERSION
        return validate_emission_plan(p, self.contract)

    def test_emitted_gitignore_covers_consent_runtime_artifacts(self):
        plan = self._plan()
        fixture_build_repo_root = self._fixture_build_repo_root()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)

        emit_scaffold(plan, staging, fixture_build_repo_root)

        gitignore_path = staging / ".gitignore"
        self.assertTrue(gitignore_path.is_file(), ".gitignore was not emitted")
        text = gitignore_path.read_text(encoding="utf-8")
        missing = [tok for tok in REQUIRED_TOKENS if tok not in text]
        self.assertEqual(
            missing, [],
            f"emitted .gitignore missing consent/runtime artifact coverage tokens: {missing}",
        )

    def test_gitignore_manifest_documents_the_new_entries(self):
        """The manifest is the project's single-home plain-language mirror of
        .gitignore -- it must not silently drift out of sync with the enforcement
        file (single-home discipline)."""
        plan = self._plan()
        fixture_build_repo_root = self._fixture_build_repo_root()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)

        emit_scaffold(plan, staging, fixture_build_repo_root)

        manifest_path = staging / "security" / "gitignore_manifest.md"
        self.assertTrue(manifest_path.is_file(), "security/gitignore_manifest.md was not emitted")
        text = manifest_path.read_text(encoding="utf-8")
        missing = [tok for tok in REQUIRED_TOKENS if tok not in text]
        self.assertEqual(
            missing, [],
            f"gitignore_manifest.md missing consent/runtime artifact entries: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
