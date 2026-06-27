import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.verification_modes import (  # noqa: E402
    VerificationMode,
    ClaimStrength,
    MODE_MAX_CLAIM,
    max_claim_for,
    mode_permits_absolute,
)


class TestVerificationModes(unittest.TestCase):
    def test_mode_values_match_spec(self):
        self.assertEqual(VerificationMode.EXTERNAL_AUTHORITATIVE_SOURCE.value,
                         "external_authoritative_source")
        self.assertEqual(VerificationMode.PRESTATE_SNAPSHOT_DIFF.value,
                         "prestate_snapshot_diff")
        self.assertEqual(VerificationMode.PLATFORM_AUDIT_LOG.value, "platform_audit_log")
        self.assertEqual(VerificationMode.OPERATOR_ATTESTED.value, "operator_attested")
        self.assertEqual(VerificationMode.UNVERIFIABLE.value, "unverifiable")

    def test_operator_attested_is_never_verified(self):
        self.assertNotEqual(max_claim_for(VerificationMode.OPERATOR_ATTESTED),
                            ClaimStrength.VERIFIED)
        self.assertEqual(max_claim_for(VerificationMode.OPERATOR_ATTESTED),
                         ClaimStrength.ATTESTED)

    def test_unverifiable_is_downgraded(self):
        self.assertEqual(max_claim_for(VerificationMode.UNVERIFIABLE),
                         ClaimStrength.DOWNGRADED)

    def test_authoritative_and_snapshot_may_be_verified(self):
        self.assertEqual(max_claim_for(VerificationMode.EXTERNAL_AUTHORITATIVE_SOURCE),
                         ClaimStrength.VERIFIED)
        self.assertEqual(max_claim_for(VerificationMode.PRESTATE_SNAPSHOT_DIFF),
                         ClaimStrength.VERIFIED)

    def test_platform_audit_log_may_be_verified(self):
        self.assertEqual(max_claim_for(VerificationMode.PLATFORM_AUDIT_LOG),
                         ClaimStrength.VERIFIED)

    def test_absolutes_only_for_authoritative_or_snapshot(self):
        self.assertTrue(mode_permits_absolute(VerificationMode.EXTERNAL_AUTHORITATIVE_SOURCE))
        self.assertTrue(mode_permits_absolute(VerificationMode.PRESTATE_SNAPSHOT_DIFF))
        self.assertFalse(mode_permits_absolute(VerificationMode.PLATFORM_AUDIT_LOG))
        self.assertFalse(mode_permits_absolute(VerificationMode.OPERATOR_ATTESTED))
        self.assertFalse(mode_permits_absolute(VerificationMode.UNVERIFIABLE))

    def test_every_mode_has_a_ceiling(self):
        for mode in VerificationMode:
            self.assertIn(mode, MODE_MAX_CLAIM)


if __name__ == "__main__":
    unittest.main()
