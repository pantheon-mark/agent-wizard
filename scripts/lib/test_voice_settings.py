"""Tests for voice_settings_inputs — voice-value derivation from foundation_doc_inputs.

TDD: failing tests written before the implementation module exists.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


class VoiceSettingsTests(unittest.TestCase):
    """voice_settings_inputs derives the six voice keys from foundation_doc_inputs."""

    def setUp(self):
        from voice_settings import voice_settings_inputs  # noqa: F401
        self.fn = voice_settings_inputs

    # --- data-driven gate: no source fields -> no injection ---

    def test_no_source_fields_returns_empty(self):
        """An input lacking every voice source field injects nothing (gate closed).

        This is the conformance-restoring contract: a pre-v0.7.0 estate's capsule
        has none of the voice source fields, so voice_settings_inputs returns {} and
        the scaffold sentinels stand, leaving render(released version, old capsule)
        byte-for-byte reproducible.
        """
        self.assertEqual(self.fn({}), {})
        # Unrelated keys present, but none is a voice source field -> still empty.
        self.assertEqual(self.fn({"AUTONOMY_LEVEL": "1", "CORE_PURPOSE": "x"}), {})

    # --- completeness + closed-value discipline ---

    def test_voice_values_complete_and_closed(self):
        """With a source field present, all six keys appear with closed values (no sentinel)."""
        out = self.fn({"UP_TECHNICAL_LITERACY": "mixed"})
        self.assertEqual(
            set(out),
            {"TONE", "TECHNICAL_LEVEL", "EXPLANATION_DEPTH",
             "LENGTH_PREFERENCE", "LIST_STYLE", "TABLE_STYLE"},
        )
        for v in out.values():
            self.assertNotIn("operator-configures", v)
            self.assertNotIn("warm", v.lower())  # project voice rule

    # --- raw-question-ID inputs (brief-spec tests) ---

    def test_voice_values_derived_not_configure(self):
        """Brief-spec: raw question-ID inputs map to correct closed values."""
        out = self.fn({
            "UP-1": "not technical",
            "UP-4": "brief",
            "ERR-1": "quiet",
            "QA-1": "concise",
        })
        self.assertEqual(out["TECHNICAL_LEVEL"], "plain")
        self.assertEqual(out["EXPLANATION_DEPTH"], "brief")
        for v in out.values():
            self.assertNotIn("operator-configures", v)
            self.assertNotIn("warm", v.lower())

    # --- derived field-name inputs (live emit path) ---

    def test_plain_from_up_technical_literacy_not_technical(self):
        """UP_TECHNICAL_LITERACY='plain language only' -> TECHNICAL_LEVEL='plain'."""
        out = self.fn({"UP_TECHNICAL_LITERACY": "plain language only"})
        self.assertEqual(out["TECHNICAL_LEVEL"], "plain")

    def test_technical_from_up_technical_literacy_comfortable(self):
        """UP_TECHNICAL_LITERACY='comfortable with technical terms' -> TECHNICAL_LEVEL='technical'."""
        out = self.fn({"UP_TECHNICAL_LITERACY": "comfortable with technical terms"})
        self.assertEqual(out["TECHNICAL_LEVEL"], "technical")

    def test_some_technical_from_up_technical_literacy_mixed(self):
        """UP_TECHNICAL_LITERACY with no clear signal -> TECHNICAL_LEVEL='some-technical'."""
        out = self.fn({"UP_TECHNICAL_LITERACY": "mixed"})
        self.assertEqual(out["TECHNICAL_LEVEL"], "some-technical")

    def test_brief_depth_from_notification_verbosity_minimal(self):
        """NOTIFICATION_VERBOSITY='Minimal' -> EXPLANATION_DEPTH='brief'."""
        out = self.fn({"NOTIFICATION_VERBOSITY": "Minimal"})
        self.assertEqual(out["EXPLANATION_DEPTH"], "brief")

    def test_detailed_depth_from_notification_verbosity_detailed(self):
        """NOTIFICATION_VERBOSITY='Detailed' -> EXPLANATION_DEPTH='detailed'."""
        out = self.fn({"NOTIFICATION_VERBOSITY": "Detailed"})
        self.assertEqual(out["EXPLANATION_DEPTH"], "detailed")

    def test_standard_depth_from_notification_verbosity_standard(self):
        """NOTIFICATION_VERBOSITY='Standard' (default) -> EXPLANATION_DEPTH='standard'."""
        out = self.fn({"NOTIFICATION_VERBOSITY": "Standard"})
        self.assertEqual(out["EXPLANATION_DEPTH"], "standard")

    def test_concise_length_from_qa_reporting_style_summary(self):
        """QA_REPORTING_STYLE='summary' -> LENGTH_PREFERENCE='concise'."""
        out = self.fn({"QA_REPORTING_STYLE": "summary"})
        self.assertEqual(out["LENGTH_PREFERENCE"], "concise")

    # --- fixed values ---

    def test_tone_is_plain_and_direct(self):
        """TONE is always 'plain-and-direct' (never 'warm' per project voice rule)."""
        out = self.fn({"UP_TECHNICAL_LITERACY": "mixed"})
        self.assertEqual(out["TONE"], "plain-and-direct")
        self.assertNotIn("warm", out["TONE"].lower())

    def test_list_style_is_bullets(self):
        """LIST_STYLE is 'bullets' whenever voice values are injected."""
        out = self.fn({"UP_TECHNICAL_LITERACY": "mixed"})
        self.assertEqual(out["LIST_STYLE"], "bullets")

    def test_table_style_is_tables_when_comparing(self):
        """TABLE_STYLE is 'tables-when-comparing' whenever voice values are injected."""
        out = self.fn({"UP_TECHNICAL_LITERACY": "mixed"})
        self.assertEqual(out["TABLE_STYLE"], "tables-when-comparing")

    # --- no-configure sentinels at the inject site ---

    def test_no_configure_sentinel_in_any_value(self):
        """No value contains the configure sentinel from any input combination."""
        for inputs in [
            {},
            {"UP-1": "very technical", "UP-4": "detailed explanation"},
            {"UP_TECHNICAL_LITERACY": "comfortable", "NOTIFICATION_VERBOSITY": "Detailed"},
        ]:
            out = self.fn(inputs)
            for k, v in out.items():
                self.assertNotIn("operator-configures", v, f"key {k!r} still has sentinel: {v!r}")


if __name__ == "__main__":
    unittest.main()
