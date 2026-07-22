"""Verification modes and claim-strength ceilings for post-write verification.

A post-write verification record declares HOW it established truth (its mode) and
how strong a claim it is therefore allowed to make. Claim strength is bounded by
mode: a human-confirmed result is never recorded as a machine-"verified" fact, and
absolute language ("never / zero / all / proven") is permitted only when the mode is
an independent authoritative source or a snapshot-diff with a passing invariant.

This is the build-time + operator-as-approver enforcement ceiling, NOT a runtime or
OS-level guarantee.

Stdlib only — no third-party dependencies.
"""

from enum import Enum


class VerificationMode(str, Enum):
    """How a post-write claim was established. Values are the canonical mode names."""

    EXTERNAL_AUTHORITATIVE_SOURCE = "external_authoritative_source"
    PRESTATE_SNAPSHOT_DIFF = "prestate_snapshot_diff"
    PLATFORM_AUDIT_LOG = "platform_audit_log"
    OPERATOR_ATTESTED = "operator_attested"
    UNVERIFIABLE = "unverifiable"


class ClaimStrength(str, Enum):
    """The strongest claim a verification record may assert.

    verified   — a machine-checked fact (requires raw evidence + an independent mode).
    attested   — a human confirmed it; NEVER recorded as machine-verified.
    downgraded — the fact could not be independently established; the claim language
                 must be explicitly weakened.
    """

    VERIFIED = "verified"
    ATTESTED = "attested"
    DOWNGRADED = "downgraded"


# The ceiling each mode may assert. operator_attested can never reach 'verified';
# unverifiable can only make a downgraded claim.
MODE_MAX_CLAIM = {
    VerificationMode.EXTERNAL_AUTHORITATIVE_SOURCE: ClaimStrength.VERIFIED,
    VerificationMode.PRESTATE_SNAPSHOT_DIFF: ClaimStrength.VERIFIED,
    VerificationMode.PLATFORM_AUDIT_LOG: ClaimStrength.VERIFIED,
    VerificationMode.OPERATOR_ATTESTED: ClaimStrength.ATTESTED,
    VerificationMode.UNVERIFIABLE: ClaimStrength.DOWNGRADED,
}

# Absolute language is honest only for these two modes.
_ABSOLUTE_PERMITTED_MODES = frozenset(
    {
        VerificationMode.EXTERNAL_AUTHORITATIVE_SOURCE,
        VerificationMode.PRESTATE_SNAPSHOT_DIFF,
    }
)


def max_claim_for(mode: VerificationMode) -> ClaimStrength:
    """Return the strongest claim the given mode may assert."""
    return MODE_MAX_CLAIM[mode]


def mode_permits_absolute(mode: VerificationMode) -> bool:
    """True iff absolute language is honest for this mode (authoritative or snapshot-diff)."""
    return mode in _ABSOLUTE_PERMITTED_MODES
