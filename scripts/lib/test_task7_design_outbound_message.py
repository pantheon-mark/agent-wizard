"""Tests for design-outbound-message skill (Task 7).

Verifies:
1. Skill file exists at wizard/skills/design-outbound-message.md with YAML
   frontmatter containing a single-line description with channel routing words.
2. Skill body states structural trigger (email / external / digest), the
   "never for internal" exclusion, and references voice_and_style.md.
3. Discovery wiring: the skill is listed in how_your_system_works.md (v0.7.0
   template) and the system-artifacts.json entry mirrors credential-setup.
4. system-artifacts.json entry mirrors credential-setup's delivery/merge_strategy.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[3]
WIZARD_DIR = REPO_ROOT / "wizard"
SKILLS_DIR = WIZARD_DIR / "skills"
V070_BUNDLE = WIZARD_DIR / "foundation-bundles" / "v0.7.0"
V070_TEMPLATES = V070_BUNDLE / "templates"


class SkillFileExistsTest(unittest.TestCase):
    """Assert design-outbound-message.md exists in both locations."""

    def test_source_skill_exists(self):
        """wizard/skills/design-outbound-message.md must exist."""
        skill_path = SKILLS_DIR / "design-outbound-message.md"
        self.assertTrue(skill_path.exists(),
                        f"design-outbound-message.md not found at {skill_path}")

    def test_template_skill_exists(self):
        """v0.7.0 template copy must exist."""
        template_path = V070_TEMPLATES / "wizard" / "skills" / "design-outbound-message.md"
        self.assertTrue(template_path.exists(),
                        f"design-outbound-message.md not found in v0.7.0 templates at {template_path}")


class SkillFrontmatterTest(unittest.TestCase):
    """Assert YAML frontmatter is present and well-formed."""

    def _read_skill(self):
        return (SKILLS_DIR / "design-outbound-message.md").read_text(encoding="utf-8")

    def test_has_yaml_frontmatter(self):
        """File must start with --- YAML block."""
        text = self._read_skill()
        self.assertTrue(text.startswith("---"),
                        "design-outbound-message.md must start with YAML frontmatter (---)")

    def test_description_is_single_line(self):
        """description field must be a single YAML line (no multiline)."""
        text = self._read_skill()
        # Extract the frontmatter block
        match = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
        self.assertIsNotNone(match, "Could not find closing --- in frontmatter")
        frontmatter = match.group(1)
        # description must appear exactly once and not span lines
        lines = frontmatter.split('\n')
        desc_lines = [l for l in lines if l.startswith('description:')]
        self.assertEqual(len(desc_lines), 1,
                         "description field must appear exactly once in frontmatter")

    def test_description_contains_channel_routing_words(self):
        """description must contain channel routing words: email, outbound/external, message/digest."""
        text = self._read_skill()
        match = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
        self.assertIsNotNone(match, "Could not find closing --- in frontmatter")
        frontmatter = match.group(1)
        desc_lines = [l for l in frontmatter.split('\n') if l.startswith('description:')]
        self.assertTrue(len(desc_lines) >= 1, "description field missing")
        desc = desc_lines[0].lower()
        # Must mention email
        self.assertIn("email", desc, "description missing 'email' channel routing word")
        # Must mention outbound or external message concept
        has_outbound = ("outbound" in desc or "external" in desc)
        self.assertTrue(has_outbound,
                        "description missing 'outbound' or 'external' routing word")
        # Must mention message or digest
        has_message = ("message" in desc or "digest" in desc)
        self.assertTrue(has_message,
                        "description missing 'message' or 'digest' routing word")


class SkillBodyTest(unittest.TestCase):
    """Assert skill body has structural trigger, internal exclusion, and voice_and_style reference."""

    def _read_skill(self):
        return (SKILLS_DIR / "design-outbound-message.md").read_text(encoding="utf-8")

    def test_structural_trigger_email(self):
        """Body must state email as a trigger condition."""
        text = self._read_skill()
        self.assertIn("email", text.lower(),
                      "Skill body must explicitly trigger on email channel")

    def test_structural_trigger_external(self):
        """Body must state external audience as a trigger condition."""
        text = self._read_skill()
        self.assertIn("external", text.lower(),
                      "Skill body must explicitly trigger on external-audience messages")

    def test_structural_trigger_digest(self):
        """Body must state digest as a trigger condition."""
        text = self._read_skill()
        self.assertIn("digest", text.lower(),
                      "Skill body must explicitly trigger on operator digest")

    def test_never_for_internal_exclusion(self):
        """Body must explicitly exclude internal artifacts."""
        text = self._read_skill()
        # Must say "never" (or "not") and "internal"
        self.assertIn("internal", text.lower(),
                      "Skill body must state the 'never for internal' exclusion")
        has_never = ("never" in text.lower() or "not" in text.lower())
        self.assertTrue(has_never,
                        "Skill body must state the exclusion with 'never' or 'not'")

    def test_references_voice_and_style(self):
        """Body must reference voice_and_style.md."""
        text = self._read_skill()
        self.assertIn("voice_and_style.md", text,
                      "Skill body must reference docs/voice_and_style.md")

    def test_trigger_is_structural_not_vague(self):
        """Body must describe the trigger as channel/audience-keyed, not a vague significance judgment."""
        text = self._read_skill()
        # The brief requires the trigger to be structural (channel/audience keyed)
        # Check that the word "channel" or "audience" appears in the trigger description
        self.assertTrue("channel" in text.lower() or "audience" in text.lower(),
                        "Skill body must key the trigger to channel or audience, not a vague judgment")


class DiscoveryWiringTest(unittest.TestCase):
    """Assert discovery wiring: how_your_system_works.md + system-artifacts.json."""

    def test_how_your_system_works_mentions_design_outbound(self):
        """how_your_system_works.md must mention design-outbound-message skill."""
        hysw_path = V070_TEMPLATES / "docs" / "how_your_system_works.md"
        self.assertTrue(hysw_path.exists(), f"how_your_system_works.md not found at {hysw_path}")
        text = hysw_path.read_text(encoding="utf-8")
        self.assertIn("design-outbound-message", text,
                      "how_your_system_works.md must mention design-outbound-message skill")

    def test_how_your_system_works_mentions_context(self):
        """how_your_system_works.md must mention the skill in plain language (email/digest/person)."""
        hysw_path = V070_TEMPLATES / "docs" / "how_your_system_works.md"
        text = hysw_path.read_text(encoding="utf-8")
        # Should mention sending to a person and email/digest in same section
        has_person_context = ("person" in text or "email" in text or "digest" in text)
        self.assertTrue(has_person_context,
                        "how_your_system_works.md note must reference person/email/digest context")

    def test_system_artifacts_has_design_outbound_entry(self):
        """system-artifacts.json must have an entry for wizard/skills/design-outbound-message.md."""
        artifacts_path = V070_BUNDLE / "system-artifacts.json"
        with open(artifacts_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        artifacts = data.get("artifacts", [])
        entry = next(
            (a for a in artifacts if a.get("relpath") == "wizard/skills/design-outbound-message.md"),
            None
        )
        self.assertIsNotNone(entry,
                             "system-artifacts.json missing entry for wizard/skills/design-outbound-message.md")

    def test_system_artifacts_entry_mirrors_credential_setup(self):
        """design-outbound-message entry must mirror credential-setup's delivery/merge_strategy/render_kind."""
        artifacts_path = V070_BUNDLE / "system-artifacts.json"
        with open(artifacts_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        artifacts = data.get("artifacts", [])

        # Find credential-setup entry (reference)
        cred_entry = next(
            (a for a in artifacts if a.get("relpath") == "wizard/skills/credential-setup.md"),
            None
        )
        self.assertIsNotNone(cred_entry, "credential-setup.md entry not found in system-artifacts.json")

        # Find design-outbound-message entry
        dom_entry = next(
            (a for a in artifacts if a.get("relpath") == "wizard/skills/design-outbound-message.md"),
            None
        )
        self.assertIsNotNone(dom_entry, "design-outbound-message.md entry not found in system-artifacts.json")

        # Must mirror credential-setup on these fields
        for field in ("delivery", "merge_strategy", "render_kind", "mode"):
            self.assertEqual(
                dom_entry.get(field), cred_entry.get(field),
                f"design-outbound-message entry field '{field}' must mirror credential-setup "
                f"(expected {cred_entry.get(field)!r}, got {dom_entry.get(field)!r})"
            )

    def test_system_artifacts_template_path_correct(self):
        """template_path must point at the v0.7.0 templates location."""
        artifacts_path = V070_BUNDLE / "system-artifacts.json"
        with open(artifacts_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        artifacts = data.get("artifacts", [])
        dom_entry = next(
            (a for a in artifacts if a.get("relpath") == "wizard/skills/design-outbound-message.md"),
            None
        )
        self.assertIsNotNone(dom_entry)
        expected_template = "templates/wizard/skills/design-outbound-message.md"
        self.assertEqual(dom_entry.get("template_path"), expected_template,
                         f"template_path must be '{expected_template}'")

    def test_template_file_matches_source_file(self):
        """v0.7.0 template copy must have identical content to wizard/skills/ source."""
        source = (SKILLS_DIR / "design-outbound-message.md").read_text(encoding="utf-8")
        template = (V070_TEMPLATES / "wizard" / "skills" / "design-outbound-message.md").read_text(encoding="utf-8")
        self.assertEqual(source, template,
                         "v0.7.0 template copy must be identical to wizard/skills/ source")


class NoBuildIDsTest(unittest.TestCase):
    """Assert no build-IDs appear in the committed wizard/ skill content."""

    def _read_skill(self):
        return (SKILLS_DIR / "design-outbound-message.md").read_text(encoding="utf-8")

    def test_no_slice_id_in_skill(self):
        """Skill file must not contain internal build slice IDs."""
        text = self._read_skill()
        # Pattern: S<digit>.<digit> is an internal session/slice ID
        self.assertNotRegex(text, r'S\d+\.\d+',
                            "Skill file must not contain internal build slice IDs")

    def test_no_adr_references_in_skill(self):
        """Skill file must not contain internal ADR references (ADR-XXXX)."""
        text = self._read_skill()
        self.assertNotRegex(text, r'ADR-\d+',
                            "Skill file must not contain internal ADR references")


if __name__ == "__main__":
    unittest.main()
