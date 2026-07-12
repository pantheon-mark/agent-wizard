"""copy_run_proof-v1 — the Recovery clause (undo-proof) + folded-in durability.

ONE artifact, riding Clauses C+D, that demonstrates on a copy of the operator's real
data class: apply -> undo -> verify-restored. The apply and undo verdicts are split
inside (copy_apply_proof / copy_undo_proof) and EACH verify step must pass the
Authority clause's independent verification (an undo-proof without independent verify
is just another false green).

capability_id binds the proof to the SPECIFIC capability it proves (the descriptor id it will
be accepted against). It is stamped by the producer (the supervised copy-run in the operator
system) and ASSERTED by the acceptance ceremony (proof.capability_id == descriptor.id) so a
valid proof for a different same-op-kind / same-risk capability can never cross-authorize.
It is optional to this structural validator (older copy-run flows that never reach acceptance
do not need it) but MANDATORY at the trust surface: the ceremony refuses a proof that is absent
or mismatched. When present it must be a non-empty string.

capability_module_paths (wire-verification) names the capability's OWN
write-affecting module files (its capability/proposal/read code -- never the trusted adapter
module itself). Like capability_id, it is optional to this structural validator (no filesystem
I/O happens here) but MANDATORY at the trust surface: the acceptance ceremony refuses a proof
that omits it, or whose declared files do not scan clean under the build-time AST bypass
scanner (scan.py) -- the structural proof that this capability's own code can neither reach an
external surface directly nor construct/obtain a write-capable credential, i.e. that its write
path is actually gated. When present here it must be a non-empty list of non-empty path strings.

durability_checks[] is folded in: for operations that introduce or
rely on persistent binding across operator-visible data, ordinary operator actions
(sort/filter/insert/delete/move) are performed against the new structure on the copy
and the binding is proven to survive. This is a TESTED step, not a self-report. It
fires ONLY on persistent-binding operations; it is n/a (and must be empty) for in-place
status / one-shot / append-only surfaces.

Enforcement ceiling: build-time + operator-as-approver, NOT a runtime or OS-level
guarantee.

Stdlib only — no third-party dependencies.
"""

from dataclasses import dataclass
from typing import Any, Optional

from external_write.operations import Operation
from external_write.contracts import get_contract
from external_write.verifiers import validate_postwrite_verification


COPY_RUN_PROOF_SCHEMA = "copy_run_proof-v1"
DURABILITY_ACTIONS = ("sort", "filter", "insert", "delete", "move")

_REQUIRED_FIELDS = (
    "schema",
    "operation_id",
    "op_kind",
    "data_class",
    "copy_source_ref",
    "prestate_snapshot_ref",
    "copy_apply_proof",
    "copy_undo_proof",
    "durability_checks",
    "accepted_for_live_use",
    "implementation_hash",
    "contract_hash",
)


@dataclass(frozen=True)
class ProofResult:
    ok: bool
    reason: Optional[str]


def _fail(reason: str) -> ProofResult:
    return ProofResult(ok=False, reason=reason)


def _synthetic_op(op_kind: str, field: str) -> Operation:
    return Operation(
        surface="copy_surface", object_id="copy:0", field=field,
        new_value="<copy>", op_kind=op_kind, batch_id="copy-run",
    )


def validate_copy_run_proof(proof: Any) -> ProofResult:
    """Validate a copy_run_proof-v1 artifact. Returns the first failure found."""
    if not proof:
        return _fail("copy_run_proof is missing or empty")
    if proof.get("schema") != COPY_RUN_PROOF_SCHEMA:
        return _fail(
            f"schema must be {COPY_RUN_PROOF_SCHEMA!r}; got {proof.get('schema')!r}"
        )
    for fld in _REQUIRED_FIELDS:
        if fld not in proof:
            return _fail(f"copy_run_proof is missing required field {fld!r}")

    # capability_id is optional to this structural validator but, when present, must be a
    # non-empty string (the ceremony asserts it equals the target descriptor id — the trust
    # surface, not this validator, enforces presence + match).
    if "capability_id" in proof:
        cid = proof["capability_id"]
        if not (isinstance(cid, str) and cid.strip()):
            return _fail("capability_id, when present, must be a non-empty string")

    # capability_module_paths is optional to this structural validator but MANDATORY at the
    # trust surface (see module docstring) -- the acceptance ceremony enforces presence + a
    # clean bypass scan; this validator only checks the shape (no filesystem I/O here).
    if "capability_module_paths" in proof:
        module_paths = proof["capability_module_paths"]
        if not (isinstance(module_paths, list) and module_paths
                and all(isinstance(p, str) and p.strip() for p in module_paths)):
            return _fail(
                "capability_module_paths, when present, must be a non-empty list of "
                "non-empty path strings"
            )

    op_kind = proof["op_kind"]
    contract = get_contract(op_kind)
    if contract is None:
        return _fail(f"operation kind {op_kind!r} has no registered contract")
    if not contract.writes:
        return _fail(f"operation {op_kind!r} declares no write field")
    field = contract.writes[0]
    synth = _synthetic_op(op_kind, field)

    # Validate apply proof — must carry a non-empty receipt ref AND pass Clause A
    # independent verification.
    apply_proof = proof["copy_apply_proof"]
    if not isinstance(apply_proof, dict) or not apply_proof.get("apply_receipt_ref"):
        return _fail("copy_apply_proof must carry a non-empty apply_receipt_ref")
    av = validate_postwrite_verification(synth, apply_proof.get("apply_verification"))
    if not av.ok:
        return _fail(f"apply verification failed Clause A: {av.reason}")

    # Validate undo proof — must carry a non-empty receipt ref AND pass Clause A
    # independent verification. A self-referential undo check is the failure we prevent.
    undo_proof = proof["copy_undo_proof"]
    if not isinstance(undo_proof, dict) or not undo_proof.get("undo_receipt_ref"):
        return _fail("copy_undo_proof must carry a non-empty undo_receipt_ref")
    uv = validate_postwrite_verification(synth, undo_proof.get("undo_verification"))
    if not uv.ok:
        return _fail(f"undo (restore) verification failed Clause A: {uv.reason}")

    # Durability gating — fires ONLY on persistent-binding operations.
    # For non-binding operations, durability_checks must be empty (n/a).
    # Over-firing trains rubber-stamping and is explicitly rejected.
    durability = proof["durability_checks"]
    if not isinstance(durability, list):
        return _fail("durability_checks must be a list")
    if contract.introduces_persistent_binding:
        if not durability:
            return _fail(
                f"operation {op_kind!r} introduces persistent binding; "
                "durability_checks must demonstrate the binding survives ordinary "
                "operator actions (sort/filter/insert/delete/move)"
            )
        for entry in durability:
            if not isinstance(entry, dict):
                return _fail("each durability check must be an object")
            if entry.get("action") not in DURABILITY_ACTIONS:
                return _fail(
                    f"durability check action {entry.get('action')!r} is not one of "
                    f"{DURABILITY_ACTIONS!r}"
                )
            if entry.get("binding_survived") is not True:
                return _fail(
                    f"durability check {entry.get('action')!r} did not prove the "
                    "binding survived"
                )
    else:
        if durability:
            return _fail(
                f"operation {op_kind!r} does not introduce persistent binding; "
                "durability_checks must be empty (n/a)"
            )

    if proof.get("accepted_for_live_use") is not True:
        return _fail("accepted_for_live_use must be True for an accepted proof")

    return ProofResult(ok=True, reason=None)
