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

------------------------------------------------------------------------------
Evidence-checked apply/undo (Task 2, A2 proof-time — v0.12.0 Slice 1; closes F-38)
------------------------------------------------------------------------------
Before this task, a "verified" claim on `copy_apply_proof`/`copy_undo_proof` was
accepted on the strength of `validate_postwrite_verification`'s RECORD checks alone
(a well-formed record + a non-empty `evidence_ref` STRING) — nothing here ever
opened that evidence to confirm the observed round-trip actually landed. A proof
asserting `claim_strength:"verified"` / `accepted_for_live_use:true` with a
dangling `evidence_ref` therefore passed. That is F-38.

This validator is now the KERNEL that closes it: when `op_kind` has a REGISTERED
adapter (`adapter_registry.get_dispatch`), it constructs a kernel-loaded
`evidence.AdapterEvidence` from the proof's OWN captured `apply_evidence` /
`undo_evidence` content (`unit_id` + observed `poststate` + optional `prestate`)
— never from an operator-supplied path — and pairs it with the `source_lineage`
already declared (and already lineage-locked) on that half's postwrite-
verification record, converting the record's `forbidden_sources` into the
adapter-evidence vocabulary's `forbidden_verification_inputs`. It then evaluates
the adapter's OWN captured `verify_apply_landed` / `verify_undo_restored` (and, for
a persistent-binding op_kind whose adapter declares it, `verify_durability` per
durability check) — never the predicate opening anything itself; see
`evidence.py` and `adapter_registry.AdapterDispatch` for the anti-tautology
property this relies on.

Fail-closed, not a warning: if the op_kind's registered adapter declares NO
evidence predicate, or the proof lacks the evidence content needed to build the
`AdapterEvidence` (missing/malformed `apply_evidence`/`undo_evidence`/
`durability_evidence`), or the predicate evaluates the observed evidence as
NOT-landed / NOT-restored / NOT-durable, the proof FAILS — even when the record
is well-formed and `accepted_for_live_use:true` is asserted. `accepted_for_live_use`
becomes something this validator COMPUTES from the observed evidence, not
something it merely trusts the proof to assert.

Scope note (unchanged by this task): the six seeded field op_kinds
(set_status, complete_tasks, update_due_date, add_note, set_priority,
delete_record) have NO registered adapter by permanent design (see
adapter_registry.py's module docstring) — `get_dispatch` returns None for them,
so this evidence-predicate gate does not fire and their proofs continue to be
governed by the pre-existing record checks alone, unchanged.

Enforcement ceiling: build-time + operator-as-approver, NOT a runtime or OS-level
guarantee.

Stdlib only — no third-party dependencies.
"""

from dataclasses import dataclass
from typing import Any, Optional

from external_write.operations import Operation
from external_write.contracts import get_contract, SourceLineage
from external_write.verifiers import validate_postwrite_verification
from external_write.adapter_registry import get_dispatch
from external_write import evidence
from external_write.evidence import AdapterEvidence


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


def _lineage_from_verification_record(record: Any) -> SourceLineage:
    """Build a `contracts.SourceLineage` from an ALREADY-VALIDATED postwrite-
    verification-v1 record's own `source_lineage` sub-object -- reusing the
    exact declaration `validate_postwrite_verification` already lineage-locked
    (Clause A), rather than letting the evidence side declare its own,
    unchecked lineage. The record's `forbidden_sources` field is the SAME
    vocabulary as `SourceLineage.forbidden_verification_inputs`, just named
    differently (verifiers.py's record shape predates evidence.py)."""
    lineage = (record or {}).get("source_lineage") or {}
    return SourceLineage(
        pre_write_sources=tuple(lineage.get("pre_write_sources", []) or []),
        post_write_sources=tuple(lineage.get("post_write_sources", []) or []),
        forbidden_verification_inputs=tuple(lineage.get("forbidden_sources", []) or []),
    )


def _build_evidence(op_kind: str, verification_record: Any,
                    evidence_block: Any) -> Optional[AdapterEvidence]:
    """Construct a kernel-loaded `evidence.AdapterEvidence` from the proof's OWN
    captured evidence content (`evidence_block`: `unit_id` + observed
    `poststate` + optional `prestate`), paired with the lineage already
    declared on the corresponding postwrite-verification record. Returns None
    (fail-closed at the caller) if `evidence_block` is missing or malformed --
    this function never guesses, fabricates, or opens anything on the proof's
    behalf; it only repackages what the proof already carries."""
    if not isinstance(evidence_block, dict):
        return None
    unit_id = evidence_block.get("unit_id")
    if not (isinstance(unit_id, str) and unit_id.strip()):
        return None
    poststate = evidence_block.get("poststate")
    if not isinstance(poststate, dict):
        return None
    prestate = evidence_block.get("prestate")
    if prestate is not None and not isinstance(prestate, dict):
        return None
    return AdapterEvidence(
        op_kind=op_kind,
        unit_id=unit_id,
        poststate=poststate,
        prestate=prestate,
        source_lineage=_lineage_from_verification_record(verification_record),
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

    # Evidence-checked apply/undo (Task 2, A2 proof-time — v0.12.0 Slice 1; closes
    # F-38). ADDITIONAL to the Clause-A record checks above, never a replacement:
    # fires ONLY when op_kind has a REGISTERED adapter (the six seeded field
    # op_kinds have none, by permanent design -- see adapter_registry.py -- and
    # are unaffected). When an adapter IS registered, a "verified" claim must be
    # EARNED from kernel-loaded, observed evidence, not merely asserted.
    dispatch = get_dispatch(op_kind)
    if dispatch is not None:
        # (Task B1, F-74) Read the required predicate NAMES from the ONE
        # canonical source (evidence.REQUIRED_EVIDENCE_PREDICATES) rather than
        # a hard-coded pair check here -- see that constant's own docstring
        # for why: capability_invariants.check_capability_invariants (the
        # self-QA/Step-4 gate) reads this SAME tuple, so a name added here
        # is required by BOTH gates, never just this one.
        missing_predicates = [
            name for name in evidence.REQUIRED_EVIDENCE_PREDICATES
            if getattr(dispatch, name, None) is None
        ]
        if missing_predicates:
            return _fail(
                f"operation {op_kind!r} has a registered adapter but declares no "
                f"{'/'.join(missing_predicates)} evidence predicate -- "
                "a 'verified' proof with no checkable evidence cannot be accepted"
            )

        apply_evidence = _build_evidence(
            op_kind, apply_proof.get("apply_verification"), apply_proof.get("apply_evidence")
        )
        if apply_evidence is None:
            return _fail(
                f"copy_apply_proof for {op_kind!r} is missing evidence content "
                "(apply_evidence: unit_id + poststate) needed to evaluate the "
                "adapter's verify_apply_landed predicate"
            )
        # (Task B2, F-75) A required predicate CAN be present-but-non-functional: a
        # contract upgrade that adds a required predicate name gets a FAILING
        # `raise NotImplementedError(...)` stub auto-scaffolded onto an existing
        # capability's adapter (capability_code_scaffold.
        # insert_missing_evidence_predicate_stubs) rather than silently leaving the
        # gap invisible -- see that module's own anti-trust-theater docstring for
        # why it is NEVER a passing stub. `getattr(dispatch, name, None) is not None`
        # (this gate's own missing-predicate check above, and capability_invariants
        # Check 7's identical one) only proves the METHOD EXISTS and is callable --
        # it says nothing about whether CALLING it raises. Without this try/except,
        # that raise would propagate out of this function as an uncaught exception --
        # a raw traceback reaching the operator, not the plain-language fail-closed
        # refusal every other branch of this gate produces. Mirrors the SAME
        # convention `adapters.py`'s run-time evaluation of these identical
        # predicates already uses (`except Exception as exc: ... {exc!r}`) --
        # PROOF-time was the one caller that had not yet adopted it.
        try:
            apply_landed = dispatch.verify_apply_landed(dispatch.instance, apply_evidence)
        except Exception as exc:
            return _fail(
                f"verify_apply_landed raised evaluating observed evidence for "
                f"{op_kind!r} ({exc!r}) -- an adapter predicate that cannot run "
                "cannot certify anything landed; this capability stays paused "
                "until a real implementation replaces it"
            )
        if not apply_landed:
            return _fail(
                f"observed evidence does not show the apply for {op_kind!r} landed "
                "(verify_apply_landed returned False) -- a 'verified' claim must be "
                "earned from observed evidence, not asserted"
            )

        undo_evidence = _build_evidence(
            op_kind, undo_proof.get("undo_verification"), undo_proof.get("undo_evidence")
        )
        if undo_evidence is None:
            return _fail(
                f"copy_undo_proof for {op_kind!r} is missing evidence content "
                "(undo_evidence: unit_id + poststate) needed to evaluate the "
                "adapter's verify_undo_restored predicate"
            )
        try:
            undo_restored = dispatch.verify_undo_restored(dispatch.instance, undo_evidence)
        except Exception as exc:
            return _fail(
                f"verify_undo_restored raised evaluating observed evidence for "
                f"{op_kind!r} ({exc!r}) -- an adapter predicate that cannot run "
                "cannot certify anything restored; this capability stays paused "
                "until a real implementation replaces it"
            )
        if not undo_restored:
            return _fail(
                f"observed evidence does not show the undo for {op_kind!r} restored "
                "prestate (verify_undo_restored returned False) -- a 'verified' claim "
                "must be earned from observed evidence, not asserted"
            )

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
            # Evidence-checked durability (Task 2, additional to the self-report
            # above): fires only when the op_kind's registered adapter declares
            # verify_durability (optional even for a binding op_kind -- see
            # adapter_registry.py). A self-reported binding_survived:true is not
            # enough on its own once the adapter can be asked to check.
            if dispatch is not None and dispatch.verify_durability is not None:
                durability_evidence = _build_evidence(
                    op_kind, apply_proof.get("apply_verification"),
                    entry.get("durability_evidence"),
                )
                if durability_evidence is None:
                    return _fail(
                        f"durability check {entry.get('action')!r} for {op_kind!r} "
                        "is missing evidence content (durability_evidence: unit_id "
                        "+ poststate) needed to evaluate the adapter's "
                        "verify_durability predicate"
                    )
                if not dispatch.verify_durability(dispatch.instance, durability_evidence):
                    return _fail(
                        f"observed evidence does not show the binding for {op_kind!r} "
                        f"survived the {entry.get('action')!r} durability check "
                        "(verify_durability returned False) -- a 'verified' claim "
                        "must be earned from observed evidence, not asserted"
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
