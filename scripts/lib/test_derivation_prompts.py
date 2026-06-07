"""Tests for the derivation-prompt loader (T3).

Each per-class derivation prompt (and the agent-intent prompt) loads + carries a content-bound
version hash, recorded into the derivation envelope (_prompt_version) so a prompt change is
visible as protocol drift. Fail-closed on an unknown name or a missing/empty file. RED->GREEN.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from derivation_prompts import (  # noqa: E402
    load_derivation_prompt, load_all_prompts, DerivationPrompt, DerivationPromptError, PROMPT_NAMES,
)
from derivation_replay import content_hash  # noqa: E402


class LoaderTests(unittest.TestCase):
    def test_prompt_names(self):
        self.assertEqual(
            PROMPT_NAMES,
            {"extraction", "synthesis", "classification", "policy", "auto", "authoring", "agent-intent"},
        )

    def test_loads_all_six(self):
        prompts = load_all_prompts()
        self.assertEqual(set(prompts), PROMPT_NAMES)
        for name, p in prompts.items():
            self.assertIsInstance(p, DerivationPrompt)
            self.assertTrue(p.text.strip(), f"{name} is empty")
            self.assertTrue(p.prompt_version.startswith("sha256:"), name)

    def test_load_single(self):
        p = load_derivation_prompt("policy")
        self.assertEqual(p.name, "policy")
        self.assertIn("olicy", p.text)   # the policy prompt mentions policy

    def test_version_is_content_hash(self):
        p = load_derivation_prompt("extraction")
        self.assertEqual(p.prompt_version, content_hash(p.text))

    def test_version_stable_across_loads(self):
        self.assertEqual(
            load_derivation_prompt("synthesis").prompt_version,
            load_derivation_prompt("synthesis").prompt_version,
        )

    def test_unknown_name_fails_closed(self):
        with self.assertRaises(DerivationPromptError):
            load_derivation_prompt("telepathy")

    def test_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(DerivationPromptError):
                load_derivation_prompt("policy", prompts_dir=Path(td))

    def test_empty_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "policy.md").write_text("   \n", encoding="utf-8")
            with self.assertRaises(DerivationPromptError):
                load_derivation_prompt("policy", prompts_dir=Path(td))

    def test_version_changes_with_content(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "auto.md"
            f.write_text("# Auto\nversion one\n", encoding="utf-8")
            v1 = load_derivation_prompt("auto", prompts_dir=Path(td)).prompt_version
            f.write_text("# Auto\nversion two\n", encoding="utf-8")
            v2 = load_derivation_prompt("auto", prompts_dir=Path(td)).prompt_version
            self.assertNotEqual(v1, v2)


if __name__ == "__main__":
    unittest.main()
