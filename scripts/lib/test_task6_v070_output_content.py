"""Tests for v0.7.0 template content additions.

Three read-and-assert tests verifying that commit 4305a17 template additions
landed correctly:
  1. voice_and_style.md: new "Channel-appropriate rendering" and
     "Information architecture" sections + regression guard on existing placeholders
  2. deliverables/README.md: exists with expected content
  3. system-artifacts.json: deliverables/README.md entry has correct metadata
"""

import sys
import json
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[3]
V070_BUNDLE = REPO_ROOT / "wizard" / "foundation-bundles" / "v0.7.0"
V070_TEMPLATES = V070_BUNDLE / "templates"


class VoiceAndStyleContentTest(unittest.TestCase):
    """Assert voice_and_style.md has new sections + existing content intact."""

    def test_voice_and_style_has_channel_and_ia_sections(self):
        """New sections: Channel-appropriate rendering + Information architecture."""
        text = (V070_TEMPLATES / "docs" / "voice_and_style.md").read_text(encoding="utf-8")

        # New sections must be present
        self.assertIn("## Channel-appropriate rendering", text,
                      "voice_and_style.md missing '## Channel-appropriate rendering'")
        self.assertIn("## Information architecture", text,
                      "voice_and_style.md missing '## Information architecture'")

        # Regression guard: existing placeholders and note must still be present
        self.assertIn("{{TONE}}", text,
                      "regression: {{TONE}} placeholder removed from voice_and_style.md")
        self.assertIn("{{EXPLANATION_DEPTH}}", text,
                      "regression: {{EXPLANATION_DEPTH}} placeholder removed")
        self.assertIn("{{OUTPUT_TEMPLATES}}", text,
                      "regression: {{OUTPUT_TEMPLATES}} placeholder removed")
        self.assertIn("{{APPROVED_EXAMPLES}}", text,
                      "regression: {{APPROVED_EXAMPLES}} placeholder removed")
        self.assertIn("{{ANTI_PATTERNS}}", text,
                      "regression: {{ANTI_PATTERNS}} placeholder removed")
        self.assertIn("starting defaults", text,
                      "regression: 'starting defaults' note removed from voice_and_style.md")


class DeliverablesReadmeTest(unittest.TestCase):
    """Assert deliverables/README.md exists and has expected content."""

    def test_deliverables_readme_v070_exists(self):
        """File exists and contains expected content."""
        readme_path = V070_TEMPLATES / "deliverables" / "README.md"
        self.assertTrue(readme_path.exists(),
                        f"deliverables/README.md does not exist at {readme_path}")

        text = readme_path.read_text(encoding="utf-8")

        # File must have a Deliverables heading
        self.assertIn("# Deliverables", text,
                      "deliverables/README.md missing '# Deliverables' heading")

        # File must reference both calls/ and research/ directories
        self.assertIn("calls/", text,
                      "deliverables/README.md missing reference to 'calls/'")
        self.assertIn("research/", text,
                      "deliverables/README.md missing reference to 'research/'")


class SystemArtifactsRegistryTest(unittest.TestCase):
    """Assert system-artifacts.json has correct entry for deliverables/README.md."""

    def test_system_artifacts_v070_registers_deliverables_readme(self):
        """Artifact entry exists with correct metadata."""
        artifacts_path = V070_BUNDLE / "system-artifacts.json"
        self.assertTrue(artifacts_path.exists(),
                        f"system-artifacts.json not found at {artifacts_path}")

        with open(artifacts_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Find the deliverables/README.md entry
        artifacts = data.get("artifacts", [])
        readme_entry = None
        for artifact in artifacts:
            if artifact.get("relpath") == "deliverables/README.md":
                readme_entry = artifact
                break

        self.assertIsNotNone(readme_entry,
                             "system-artifacts.json missing entry for relpath='deliverables/README.md'")

        # Verify metadata
        self.assertEqual(readme_entry.get("delivery"), "wizard",
                         "deliverables/README.md entry: delivery must be 'wizard'")
        self.assertEqual(readme_entry.get("render_kind"), "copy",
                         "deliverables/README.md entry: render_kind must be 'copy'")
        self.assertEqual(readme_entry.get("merge_strategy"), "warn_on_drift",
                         "deliverables/README.md entry: merge_strategy must be 'warn_on_drift'")
        self.assertEqual(readme_entry.get("template_path"), "templates/deliverables/README.md",
                         "deliverables/README.md entry: template_path must be 'templates/deliverables/README.md'")


if __name__ == "__main__":
    unittest.main()
