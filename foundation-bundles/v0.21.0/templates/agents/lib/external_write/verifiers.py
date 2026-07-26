"""Post-write verification record + validator — the Authority clause keystone.

A success/"verified" claim on a data mutation is honest only with a typed
postwrite-verification-v1 record that:

  * names a verifier registered for THIS operation (op.verifier_set);
  * uses that verifier's declared mode;
  * makes a claim no stronger than the mode allows (operator confirmation is never
    machine "verified"; an unverifiable result is downgraded);
  * declares its source lineage and does NOT consult any source the operation forbids
    (the lineage lock — this blocks the known tautology class of verifying a write
    against the writer's own output);
  * carries real evidence for a 'verified' claim.

This is invariant-anchored: the verifier checks a pre-declared invariant against
pre- vs post-state. It is NOT a general diff engine.

Enforcement ceiling: build-time + operator-as-approver. Semantic independence cannot
be machine-proven; this record makes the declared lineage and mode-bounded claim
machine-checkable and rejects the declared-dependency-overlap failure structurally.

Stdlib only — no third-party dependencies.
"""

from dataclasses import dataclass
from typing import Any, Optional

from external_write.operations import Operation
from external_write.verification_modes import (
    ClaimStrength,
    VerificationMode,
    max_claim_for,
)
from external_write.contracts import get_contract, get_verifier


POSTWRITE_VERIFICATION_SCHEMA = "postwrite-verification-v1"

_REQUIRED_FIELDS = (
    "schema",
    "verification_mode",
    "claim_strength",
    "verifier_id",
    "source_lineage",
    "invariant_checked",
    "evidence_ref",
)

# Required sub-fields within source_lineage.
_REQUIRED_LINEAGE_FIELDS = ("pre_write_sources", "post_write_sources", "forbidden_sources")

# Ordering for the claim-strength ceiling check (higher index = stronger).
_CLAIM_RANK = {
    ClaimStrength.DOWNGRADED: 0,
    ClaimStrength.ATTESTED: 1,
    ClaimStrength.VERIFIED: 2,
}


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    reason: Optional[str]
    claim_strength: Optional[ClaimStrength]


def _fail(reason: str) -> VerificationResult:
    return VerificationResult(ok=False, reason=reason, claim_strength=None)


def validate_postwrite_verification(op: Operation, record: Any) -> VerificationResult:
    """Validate a post-write verification record for op. Returns the first failure."""
    # Step 1: record present + non-empty
    if not record:
        return _fail("post-write verification record is missing or empty")

    # Step 2: schema check
    if record.get("schema") != POSTWRITE_VERIFICATION_SCHEMA:
        return _fail(
            f"record schema must be {POSTWRITE_VERIFICATION_SCHEMA!r}; "
            f"got {record.get('schema')!r}"
        )

    # Step 3: required fields present
    for fld in _REQUIRED_FIELDS:
        if fld not in record:
            return _fail(f"record is missing required field {fld!r}")

    # Step 4: verification_mode is a valid VerificationMode value
    try:
        mode = VerificationMode(record["verification_mode"])
    except ValueError:
        return _fail(
            f"verification_mode {record['verification_mode']!r} is not a valid mode"
        )

    # Parse claim_strength early so we can use it below
    try:
        claim = ClaimStrength(record["claim_strength"])
    except ValueError:
        return _fail(
            f"claim_strength {record['claim_strength']!r} is not a valid claim strength"
        )

    # Step 5: operation has a registered contract; verifier_id ∈ that op's verifier_set
    contract = get_contract(op.op_kind)
    if contract is None:
        return _fail(f"operation kind {op.op_kind!r} has no registered contract")

    verifier_id = record["verifier_id"]
    if verifier_id not in contract.verifier_set:
        return _fail(
            f"verifier {verifier_id!r} is not accepted for operation {op.op_kind!r} "
            f"(accepted: {contract.verifier_set})"
        )

    # Step 6: the registered verifier's mode matches verification_mode
    verifier = get_verifier(verifier_id)
    if verifier is None:
        return _fail(f"verifier {verifier_id!r} is not registered")

    if verifier.mode != mode:
        return _fail(
            f"verification_mode {mode.value!r} does not match registered verifier "
            f"mode {verifier.mode.value!r} for {verifier_id!r}"
        )

    # Step 7: claim_strength does not exceed max_claim_for(mode)
    # Ordering: VERIFIED > ATTESTED > DOWNGRADED
    ceiling = max_claim_for(mode)
    if _CLAIM_RANK[claim] > _CLAIM_RANK[ceiling]:
        return _fail(
            f"claim_strength {claim.value!r} exceeds the ceiling {ceiling.value!r} "
            f"permitted by mode {mode.value!r}"
        )

    # Step 8: lineage lock — three registry-authoritative checks
    lineage = record["source_lineage"] or {}

    # 8a: source_lineage contains the required sub-fields
    for sub in _REQUIRED_LINEAGE_FIELDS:
        if sub not in lineage:
            return _fail(f"source_lineage is missing required sub-field {sub!r}")

    declared = set(lineage.get("pre_write_sources", []) or []) | set(
        lineage.get("post_write_sources", []) or []
    )
    forbidden = set(verifier.source_lineage.forbidden_verification_inputs)

    # 8b: union of pre/post sources must NOT intersect the registry verifier's
    # forbidden_verification_inputs (tautology class: cannot verify against writer output)
    overlap = declared & forbidden
    if overlap:
        return _fail(
            "verification source lineage overlaps forbidden inputs "
            f"{sorted(overlap)!r} — a write cannot be verified against the writer's "
            "own output"
        )

    # 8c: record's forbidden_sources must be a superset (⊇) of the registry
    # verifier's forbidden_verification_inputs — the record must acknowledge the
    # full authoritative forbidden set, not a self-chosen subset
    record_forbidden = set(lineage.get("forbidden_sources", []) or [])
    missing_from_record = forbidden - record_forbidden
    if missing_from_record:
        return _fail(
            "source_lineage.forbidden_sources must include all registry-forbidden inputs "
            f"for verifier {verifier_id!r}; missing: {sorted(missing_from_record)!r}"
        )

    # Step 9: if claim_strength == "verified", evidence_ref must be non-empty
    # and not the literal "operator_attested"
    if claim == ClaimStrength.VERIFIED:
        evidence = record.get("evidence_ref")
        if not evidence or evidence == "operator_attested":
            return _fail(
                "a 'verified' claim requires a real evidence_ref "
                "(operator attestation is not machine-verified evidence)"
            )

    return VerificationResult(ok=True, reason=None, claim_strength=claim)
