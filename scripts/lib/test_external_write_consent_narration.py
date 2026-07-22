"""Tests for the machine-generated consent sentence + ceiling check-in prose
(Task 6, A1/T6 — v0.12.0 Slice 1, design §4/§5; closes the F-49 narration gap).

Invariants under test:
  * Facts prescribed, tone voice-tuned: the exact count, the action, the
    reversibility, and the session cap ALWAYS appear, correctly, in the
    generated consent sentence — regardless of EXPLANATION_DEPTH /
    TECHNICAL_LEVEL voice settings.
  * NO internal label / digest / registry-name / tier leaks into any
    generated operator string (Operator Interaction Contract §1's forbidden
    set — run_id, reviewed_set_digest, ledger_window_id, "Tier-N", etc, and
    the raw op_kind identifier itself).
  * Standing-automation narration states the ongoing/unattended nature and
    makes NO false per-batch-pause promise (F-49).
  * Ceiling check-in prose shows what changed, the exact count + remaining, a
    sample, the PRIOR tranche's honest verification + restore result, and an
    explicit stop/defer.
  * Fail-safe: unknown/absent recovery tier or voice values resolve to the
    most-protected / plainest rendering, never a permissive one.

Anti-overfit (Global Constraint #3): every behavior is exercised on >= 2
divergent op_kinds — gmail.message.trash (Gmail label op) AND a
field/spreadsheet-shaped op_kind fixture.

Runner: unittest, from wizard/scripts. Stdlib only.
"""

import sys
import tempfile
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.consent_narration import (  # noqa: E402
    FORBIDDEN_INTERNAL_TERMS,
    build_consent_sentence,
    build_ceiling_checkin_prose,
    build_run_envelope_checkin_prose,
    build_run_envelope_consent_sentence,
    build_standing_automation_notice,
    load_voice_settings_from_file,
    reversibility_phrase,
)


GMAIL_OP = "gmail.message.trash"          # sensitive_data -> reversible tier
GMAIL_FILTER_OP = "gmail.filter.create"   # standing_automation -> irreversible tier
FIELD_OP = "_consent_narration_field_probe"


def _register_field_contract():
    contracts_mod.OPERATION_CONTRACTS[FIELD_OP] = OperationContract(
        op_kind=FIELD_OP, writes=("Status",), produces=(), dependency_set=(),
        verifier_set=(), introduces_persistent_binding=False,
        risk_class="reversible_external")


def _unregister_field_contract():
    contracts_mod.OPERATION_CONTRACTS.pop(FIELD_OP, None)


_VOICE_COMBOS = [
    {"EXPLANATION_DEPTH": depth, "TECHNICAL_LEVEL": tech}
    for depth in ("brief", "standard", "detailed")
    for tech in ("plain", "some-technical", "technical")
]


# ===========================================================================
# Facts prescribed, regardless of tone — the core F-49 / consent-fidelity gate
# ===========================================================================

class TestFactsPrescribedRegardlessOfTone(unittest.TestCase):

    def setUp(self):
        _register_field_contract()

    def tearDown(self):
        _unregister_field_contract()

    def _assert_states_reversibility_substance(self, text, voice):
        low = text.lower()
        self.assertTrue(
            "undo" in low or "reversed" in low or "reversible" in low,
            f"reversibility substance missing for {voice}: {text!r}")

    def test_gmail_op_states_exact_count_action_reversibility_cap_every_voice(self):
        for voice in _VOICE_COMBOS:
            text = build_consent_sentence(
                count=42, op_kind=GMAIL_OP, recovery_tier="reversible",
                session_cap=25, voice=voice)
            self.assertIn("42", text, voice)
            self.assertIn("trash", text.lower(), voice)
            self._assert_states_reversibility_substance(text, voice)
            self.assertIn("25", text, voice)

    def test_field_op_states_exact_count_action_reversibility_cap_every_voice(self):
        contract = contracts_mod.get_contract(FIELD_OP)
        for voice in _VOICE_COMBOS:
            text = build_consent_sentence(
                count=5, op_kind=FIELD_OP, recovery_tier="reversible",
                session_cap=25, contract=contract, voice=voice)
            self.assertIn("5", text, voice)
            self.assertIn("status", text.lower(), voice)
            self._assert_states_reversibility_substance(text, voice)
            self.assertIn("25", text, voice)

    def test_irreversible_tier_never_claims_undo_is_available(self):
        for voice in _VOICE_COMBOS:
            text = build_consent_sentence(
                count=3, op_kind="delete_record", recovery_tier="irreversible",
                session_cap=5, voice=voice)
            low = text.lower()
            self.assertNotIn("you'll be able to undo", low, voice)
            self.assertTrue(
                "cannot be undone" in low or "not reversible" in low
                or "irreversible" in low or "no restore path" in low,
                f"irreversible tier must state no-undo substance; got: {text!r}")

    def test_reversible_tier_states_undo_available(self):
        text = build_consent_sentence(
            count=3, op_kind="delete_record", recovery_tier="reversible",
            session_cap=5)
        low = text.lower()
        self.assertTrue(
            "undo" in low or "reversed" in low or "reversible" in low,
            f"reversible tier must state undo is available; got: {text!r}")

    def test_unknown_recovery_tier_fails_safe_to_irreversible_wording(self):
        text = build_consent_sentence(
            count=3, op_kind=FIELD_OP, recovery_tier="not_a_real_tier",
            session_cap=5)
        low = text.lower()
        self.assertNotIn("you'll be able to undo", low)

    def test_rejects_zero_count(self):
        with self.assertRaises(ValueError):
            build_consent_sentence(count=0, op_kind=GMAIL_OP,
                                   recovery_tier="reversible", session_cap=25)

    def test_rejects_zero_session_cap(self):
        with self.assertRaises(ValueError):
            build_consent_sentence(count=3, op_kind=GMAIL_OP,
                                   recovery_tier="reversible", session_cap=0)


# ===========================================================================
# No internal label / digest leaks (Operator Interaction Contract §1)
# ===========================================================================

class TestNoInternalLeak(unittest.TestCase):

    def setUp(self):
        _register_field_contract()

    def tearDown(self):
        _unregister_field_contract()

    def _assert_clean(self, text):
        for term in FORBIDDEN_INTERNAL_TERMS:
            self.assertNotIn(term, text, f"leaked forbidden term {term!r}: {text!r}")

    def test_gmail_consent_sentence_has_no_leak_any_voice(self):
        for voice in _VOICE_COMBOS:
            text = build_consent_sentence(
                count=42, op_kind=GMAIL_OP, recovery_tier="reversible",
                session_cap=25, voice=voice)
            self._assert_clean(text)
            self.assertNotIn(GMAIL_OP, text)

    def test_field_op_consent_sentence_has_no_leak_any_voice(self):
        contract = contracts_mod.get_contract(FIELD_OP)
        for voice in _VOICE_COMBOS:
            text = build_consent_sentence(
                count=5, op_kind=FIELD_OP, recovery_tier="reversible",
                session_cap=25, contract=contract, voice=voice)
            self._assert_clean(text)
            self.assertNotIn(FIELD_OP, text)

    def test_standing_automation_notice_has_no_leak(self):
        text = build_standing_automation_notice(op_kind=GMAIL_FILTER_OP, session_cap=5)
        self._assert_clean(text)
        self.assertNotIn(GMAIL_FILTER_OP, text)

    def test_checkin_prose_has_no_leak(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            sample_descriptions=["a promo message from example.com"],
            prior_tranche_status="verified", prior_restore_verified=True)
        self._assert_clean(text)

    def test_direct_construction_cannot_reach_a_digest_shaped_value(self):
        # Structural guarantee: build_consent_sentence's signature has no
        # parameter through which a digest/run_id/ledger_window_id could ever
        # flow — confirm no such keyword is even accepted.
        import inspect
        params = set(inspect.signature(build_consent_sentence).parameters)
        for forbidden in ("run_id", "reviewed_set_digest", "ledger_window_id",
                          "contract_hash", "implementation_hash"):
            self.assertNotIn(forbidden, params)


# ===========================================================================
# Standing automation — F-49: ongoing/unattended nature, no false per-batch-
# pause promise
# ===========================================================================

class TestStandingAutomationNarration(unittest.TestCase):

    def test_notice_states_ongoing_unattended_nature(self):
        text = build_standing_automation_notice(op_kind=GMAIL_FILTER_OP, session_cap=25)
        low = text.lower()
        self.assertTrue(
            "on its own" in low or "automatically" in low or "background" in low,
            f"must state the ongoing/unattended nature; got: {text!r}")

    def test_notice_makes_no_per_batch_pause_promise(self):
        text = build_standing_automation_notice(op_kind=GMAIL_FILTER_OP, session_cap=25)
        low = text.lower()
        # The exact F-49 defect: "every batch pauses for your yes — that
        # never goes away". Assert the negation is explicit, not just absent.
        self.assertIn("will not stop and ask before each", low)
        self.assertNotIn("every batch pauses", low)
        self.assertNotIn("pauses for your yes", low)

    def test_consent_sentence_for_standing_automation_includes_the_notice(self):
        text = build_consent_sentence(
            count=1, op_kind=GMAIL_FILTER_OP, recovery_tier="irreversible",
            session_cap=25, is_standing_automation=True)
        low = text.lower()
        self.assertIn("will not stop and ask before each", low)

    def test_consent_sentence_without_the_flag_makes_no_ongoing_claim(self):
        # A one-shot reversible op (not standing automation) must NOT claim
        # ongoing/unattended behavior it doesn't have.
        text = build_consent_sentence(
            count=3, op_kind=GMAIL_OP, recovery_tier="reversible",
            session_cap=25, is_standing_automation=False)
        low = text.lower()
        self.assertNotIn("on its own in the background", low)

    def test_wired_via_run_envelope_consent_sentence_from_standing_automation_contract(self):
        contract = contracts_mod.get_contract(GMAIL_FILTER_OP)
        reviewed_set = [{"unit_id": f"m{i}"} for i in range(7)]

        class _Ceiling:
            granted_this_approval = 5
            recovery_tier = "irreversible"

        text = build_run_envelope_consent_sentence(
            reviewed_set=reviewed_set, op_kind=GMAIL_FILTER_OP,
            ceiling=_Ceiling(), contract=contract)
        low = text.lower()
        self.assertIn("7", text)
        self.assertIn("5", text)
        self.assertIn("will not stop and ask before each", low)

    def test_wired_via_run_envelope_consent_sentence_from_non_standing_contract(self):
        contract = contracts_mod.get_contract(GMAIL_OP)
        reviewed_set = [{"unit_id": f"m{i}"} for i in range(3)]

        class _Ceiling:
            granted_this_approval = 25
            recovery_tier = "reversible"

        text = build_run_envelope_consent_sentence(
            reviewed_set=reviewed_set, op_kind=GMAIL_OP, ceiling=_Ceiling(),
            contract=contract)
        self.assertNotIn("on its own in the background", text.lower())

    def test_run_envelope_consent_sentence_flags_multiple_approvals_when_population_exceeds_ceiling(self):
        # V15-2/E: population (reviewed_set) well above what THIS approval
        # covers (ceiling.granted_this_approval) -> must say a fresh/separate
        # approval is needed for the rest, using the real per-approval cap.
        contract = contracts_mod.get_contract(GMAIL_OP)
        reviewed_set = [{"unit_id": f"m{i}"} for i in range(50)]

        class _Ceiling:
            granted_this_approval = 25
            recovery_tier = "reversible"

        text = build_run_envelope_consent_sentence(
            reviewed_set=reviewed_set, op_kind=GMAIL_OP, ceiling=_Ceiling(),
            contract=contract)
        self.assertIn("25", text)
        self.assertIn("50", text)
        self.assertRegex(
            text.lower(), r"(another|separate|more than one) approval")

    def test_run_envelope_consent_sentence_quiet_when_population_within_ceiling(self):
        # The whole job fits inside one approval -> no multi-approval framing.
        contract = contracts_mod.get_contract(GMAIL_OP)
        reviewed_set = [{"unit_id": f"m{i}"} for i in range(10)]

        class _Ceiling:
            granted_this_approval = 25
            recovery_tier = "reversible"

        text = build_run_envelope_consent_sentence(
            reviewed_set=reviewed_set, op_kind=GMAIL_OP, ceiling=_Ceiling(),
            contract=contract)
        self.assertNotRegex(
            text.lower(), r"(another|separate|more than one) approval")


# ===========================================================================
# Ceiling check-in / re-confirm prose
# ===========================================================================

class TestCeilingCheckinProse(unittest.TestCase):

    def test_shows_count_and_remaining(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche_status="verified")
        self.assertIn("10", text)
        self.assertIn("32", text)

    def test_zero_remaining_states_completion_not_a_bogus_noun_phrase(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=5, remaining_count=0,
            prior_tranche_status="verified")
        self.assertIn("5", text)
        self.assertIn("complete", text.lower())

    def test_shows_sample_descriptions(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            sample_descriptions=["a coupon email from shop.example", "a receipt from store.example"],
            prior_tranche_status="verified")
        self.assertIn("coupon email from shop.example", text)
        self.assertIn("receipt from store.example", text)

    def test_verified_prior_tranche_states_verified_substance(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche_status="verified")
        self.assertIn("checked it actually landed", text)

    def test_applied_not_verified_prior_tranche_is_honest_never_claims_verified(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche_status="applied_not_verified")
        self.assertIn("could not double-check", text)
        self.assertNotIn("checked it actually landed", text)

    def test_unknown_prior_status_fails_safe_to_not_verified_phrasing(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche_status="some_unexpected_value")
        self.assertIn("could not double-check", text)

    def test_restore_verified_true_states_undo_confirmed(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche_status="verified", prior_restore_verified=True)
        self.assertIn("confirmed working", text)

    def test_restore_verified_false_flags_concern(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche_status="verified", prior_restore_verified=False)
        self.assertIn("did not confirm as working", text)

    def test_restore_verified_none_adds_no_fabricated_claim(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche_status="verified", prior_restore_verified=None)
        self.assertNotIn("confirmed working", text)
        self.assertNotIn("did not confirm as working", text)

    def test_includes_explicit_stop_or_defer(self):
        text = build_ceiling_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche_status="verified")
        low = text.lower()
        self.assertIn("stop", low)
        self.assertTrue("come back to this later" in low or "defer" in low)

    def test_field_op_checkin_prose_no_leak_and_facts_present(self):
        text = build_ceiling_checkin_prose(
            op_kind=FIELD_OP, count_now=8, remaining_count=17,
            prior_tranche_status="applied_not_verified")
        self.assertIn("8", text)
        self.assertIn("17", text)
        for term in FORBIDDEN_INTERNAL_TERMS:
            self.assertNotIn(term, text)

    def test_wired_via_run_envelope_checkin_prose_from_a_tranche_object(self):
        class _Tranche:
            verification_status = "verified"
            restore_verified = True

        text = build_run_envelope_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche=_Tranche())
        self.assertIn("checked it actually landed", text)
        self.assertIn("confirmed working", text)

    def test_wired_via_run_envelope_checkin_prose_with_no_prior_tranche(self):
        text = build_run_envelope_checkin_prose(
            op_kind=GMAIL_OP, count_now=10, remaining_count=32,
            prior_tranche=None)
        self.assertIn("could not double-check", text)


# ===========================================================================
# Voice settings — reads the actual rendered voice_and_style.md table shape
# ===========================================================================

class TestVoiceSettingsFromFile(unittest.TestCase):

    def test_absent_file_returns_empty_dict(self):
        self.assertEqual(load_voice_settings_from_file("/no/such/path.md"), {})

    def test_unrendered_template_placeholders_return_empty_dict(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "voice_and_style.md"
            p.write_text(
                "| Explanation depth | {{EXPLANATION_DEPTH}} |\n"
                "| Technical level | {{TECHNICAL_LEVEL}} |\n",
                encoding="utf-8")
            self.assertEqual(load_voice_settings_from_file(str(p)), {})

    def test_rendered_brief_plain_settings_parse_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "voice_and_style.md"
            p.write_text(
                "| Explanation depth | Minimal, just the essentials |\n"
                "| Tone | plain-and-direct |\n"
                "| Technical level | Not technical at all |\n",
                encoding="utf-8")
            settings = load_voice_settings_from_file(str(p))
            self.assertEqual(settings["EXPLANATION_DEPTH"], "brief")
            self.assertEqual(settings["TECHNICAL_LEVEL"], "plain")

    def test_rendered_detailed_technical_settings_parse_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "voice_and_style.md"
            p.write_text(
                "| Explanation depth | Detailed, walk me through it |\n"
                "| Technical level | Very technical, I write code |\n",
                encoding="utf-8")
            settings = load_voice_settings_from_file(str(p))
            self.assertEqual(settings["EXPLANATION_DEPTH"], "detailed")
            self.assertEqual(settings["TECHNICAL_LEVEL"], "technical")

    def test_parsed_settings_feed_straight_into_build_consent_sentence(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "voice_and_style.md"
            p.write_text(
                "| Explanation depth | Minimal |\n"
                "| Technical level | Not technical |\n",
                encoding="utf-8")
            voice = load_voice_settings_from_file(str(p))
            text = build_consent_sentence(
                count=42, op_kind=GMAIL_OP, recovery_tier="reversible",
                session_cap=25, voice=voice)
            self.assertIn("42", text)
            self.assertIn("25", text)

    def test_literal_emitted_technical_level_tokens_round_trip_to_themselves(self):
        # This is the REAL format the scaffold substitutes into the table
        # cell: the literal closed-vocabulary token
        # voice_settings.voice_settings_inputs emits (see
        # wizard/scripts/lib/voice_settings.py ~L82-92: "plain" /
        # "some-technical" / "technical") — NOT free-form prose like "Very
        # technical, I write code". Prose-only fixtures (above) never
        # exercised this literal format and masked a real bug: the
        # prose-heuristic branch `"technical" in low` also matches as a
        # substring of the literal token "some-technical", so the real
        # emitted token was misresolved to "technical". Prove every real
        # token round-trips to itself.
        for tech_token in ("plain", "some-technical", "technical"):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "voice_and_style.md"
                p.write_text(
                    "| Explanation depth | standard |\n"
                    f"| Technical level | {tech_token} |\n",
                    encoding="utf-8")
                settings = load_voice_settings_from_file(str(p))
                self.assertEqual(
                    settings.get("TECHNICAL_LEVEL"), tech_token,
                    f"literal emitted token {tech_token!r} must round-trip "
                    f"to itself; got {settings.get('TECHNICAL_LEVEL')!r}")

    def test_literal_emitted_explanation_depth_tokens_round_trip_to_themselves(self):
        # Same fixture-format fix as above, for EXPLANATION_DEPTH's literal
        # emitted tokens ("brief" / "standard" / "detailed").
        for depth_token in ("brief", "standard", "detailed"):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "voice_and_style.md"
                p.write_text(
                    f"| Explanation depth | {depth_token} |\n"
                    "| Technical level | plain |\n",
                    encoding="utf-8")
                settings = load_voice_settings_from_file(str(p))
                self.assertEqual(
                    settings.get("EXPLANATION_DEPTH"), depth_token,
                    f"literal emitted token {depth_token!r} must round-trip "
                    f"to itself; got {settings.get('EXPLANATION_DEPTH')!r}")


# ===========================================================================
# Cross-module vocabulary drift pin — consent_narration's accepted
# TECHNICAL_LEVEL/EXPLANATION_DEPTH tokens must never silently diverge from
# voice_settings.py's ACTUAL emitted token set (the exact module boundary
# that caused the literal-token misparse bug above).
# ===========================================================================

class TestVoiceVocabularyDriftPin(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _SCRIPTS_LIB = Path(__file__).resolve().parent
        if str(_SCRIPTS_LIB) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS_LIB))
        from voice_settings import voice_settings_inputs  # noqa: E402
        import external_write.consent_narration as cn_mod  # noqa: E402
        cls.voice_settings_inputs = staticmethod(voice_settings_inputs)
        cls.cn_mod = cn_mod

    def test_technical_level_vocab_matches_voice_settings_emitter(self):
        emitted = {
            self.voice_settings_inputs({"UP_TECHNICAL_LITERACY": raw})["TECHNICAL_LEVEL"]
            for raw in ("not technical at all", "very technical, I write code",
                        "somewhat familiar")
        }
        self.assertEqual(
            emitted, set(self.cn_mod._VALID_TECH_LEVELS),
            "consent_narration._VALID_TECH_LEVELS has drifted from the "
            "TECHNICAL_LEVEL tokens voice_settings.py actually emits — "
            "update _VALID_TECH_LEVELS (and its parse branches) to match.")

    def test_explanation_depth_vocab_matches_voice_settings_emitter(self):
        emitted = {
            self.voice_settings_inputs({"NOTIFICATION_VERBOSITY": raw})["EXPLANATION_DEPTH"]
            for raw in ("minimal", "detailed", "standard, please")
        }
        self.assertEqual(
            emitted, set(self.cn_mod._VALID_DEPTHS),
            "consent_narration._VALID_DEPTHS has drifted from the "
            "EXPLANATION_DEPTH tokens voice_settings.py actually emits — "
            "update _VALID_DEPTHS (and its parse branches) to match.")


# ===========================================================================
# reversibility_phrase — direct unit coverage of the fail-safe mapping
# ===========================================================================

class TestReversibilityPhrase(unittest.TestCase):

    def test_all_known_combinations_are_distinct_and_substantive(self):
        seen = set()
        for tier in ("reversible", "irreversible"):
            for tech in ("plain", "some-technical", "technical"):
                phrase = reversibility_phrase(tier, tech)
                self.assertTrue(phrase)
                seen.add(phrase)
        self.assertEqual(len(seen), 6)

    def test_unknown_tier_falls_back_to_irreversible(self):
        self.assertEqual(
            reversibility_phrase("garbage", "plain"),
            reversibility_phrase("irreversible", "plain"))

    def test_unknown_technical_level_falls_back_to_plain(self):
        self.assertEqual(
            reversibility_phrase("reversible", "garbage"),
            reversibility_phrase("reversible", "plain"))


if __name__ == "__main__":
    unittest.main()
