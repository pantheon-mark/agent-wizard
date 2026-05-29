"""Tests for the foundation-doc emitter (stdlib unittest; pip-install-free).

emit_foundation_docs renders the foundation docs (via the canonical
generator.render_foundation_docs) and writes each at its OPERATOR-PROJECT relpath
(root-level: "vision.md", not "foundation/vision.md") into a STAGING dir, so the
foundation docs join the full operator system and the v2 manifest's full-tree walk.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foundation_doc_emitter import emit_foundation_docs  # noqa: E402
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from generator import PLACEHOLDER_RE  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

FOUNDATION_DOCS = [
    "vision.md", "approach.md", "execution_plan.md", "technical_architecture.md",
    "test_cases.md", "audit_framework.md", "prd.md",
]


class FoundationDocEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _emit(self, into=None):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        if into is None:
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            into = Path(tmp.name)
        written = emit_foundation_docs(plan, into, REPO_ROOT)
        return into, written

    def test_seven_docs_at_root(self):
        staging, written = self._emit()
        for name in FOUNDATION_DOCS:
            self.assertTrue((staging / name).exists(), f"missing foundation doc: {name}")
        self.assertEqual(len(written), len(FOUNDATION_DOCS))
        self.assertEqual({p.name for p in written}, set(FOUNDATION_DOCS))

    def test_no_foundation_subdir(self):
        """Foundation docs are at ROOT, never under foundation/ (the legacy layout)."""
        staging, _ = self._emit()
        self.assertFalse((staging / "foundation").exists())

    def test_no_placeholder_survives(self):
        staging, _ = self._emit()
        for name in FOUNDATION_DOCS:
            leftover = PLACEHOLDER_RE.findall((staging / name).read_text(encoding="utf-8"))
            self.assertEqual(leftover, [], f"{name} has unsubstituted {leftover}")

    def test_vision_content_carries_substituted_value(self):
        staging, _ = self._emit()
        vision = (staging / "vision.md").read_text(encoding="utf-8")
        self.assertIn("Help the demo operator keep track of incoming requests.", vision)

    def test_deterministic(self):
        a = Path(tempfile.mkdtemp()); self.addCleanup(lambda: __import__("shutil").rmtree(a))
        b = Path(tempfile.mkdtemp()); self.addCleanup(lambda: __import__("shutil").rmtree(b))
        self._emit(into=a)
        self._emit(into=b)
        for name in FOUNDATION_DOCS:
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
