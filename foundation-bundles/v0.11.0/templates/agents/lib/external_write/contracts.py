"""Per-operation contract registry — the Boundary clause's declared surface and the
Authority clause's accepted-verifier surface.

Each named operation declares, up front and machine-readably:
  * writes            — the field(s)/range(s) it is allowed to change.
  * produces          — any new artifacts it creates (empty for in-place edits).
  * dependency_set    — the STATIC lib modules whose code determines every op's
                        shared write behavior (the field-write funnel). Used by the
                        proof-hash computation so any change to that shared write
                        logic changes every op's identity. This is NOT the complete
                        write-affecting file list for an op_kind that has its own
                        registered adapter (adapter_registry.get_adapter) — the
                        proof-hash computation actually consults
                        effects_manifest.resolve_dependency_files(op_kind), which is
                        this dependency_set UNION the op_kind's registered adapter
                        module, if any (Task 3 — external-write-gate-generalization;
                        closes F-34, where the hash previously covered only the fixed
                        _WRITE_AFFECTING_MODULES tuple below and structurally excluded
                        a capability's own adapter code).
  * verifier_set      — the verifier_ids whose post-write verification this op accepts.
  * introduces_persistent_binding — True iff the op introduces or relies on persistent
                        binding across operator-visible data (stable IDs, anchors,
                        cross-refs, hidden helper columns, formula-derived identity,
                        row mappings, linked records, metadata used for future writes).
                        This is the NARROW trigger for durability checks; False for
                        in-place status edits / one-shot / append-only surfaces.
  * risk_class        — the op_kind's risk class, drawn from RISK_CLASSES below (mirrors
                        the authoritative vocabulary in wizard/scripts/lib/
                        dependency_projection.py RISK_CLASSES — B1-1; kept equal by a
                        cross-tree consistency test since external_write cannot import
                        the build-side module). Defaults to "reversible_external" so
                        every contract predating this field keeps its prior behavior.
  * requires_accepted_phase — True iff running this op requires a covering ACCEPTED
                        descriptor phase (enforced by B1-4's adapter, not here).
                        Defaults to False (existing status ops stay ungated by this
                        flag; they are already gated by the broker + copy_run_proof).
  * blast_radius_cap  — the op_kind's default cap on invocations per window, or None
                        for no inherent cap (enforced by B1-4; the per-capability
                        descriptor cap from B1-2 overrides this at enforcement time).
                        Defaults to None.

  D-B1-b (LOCKED): risk_class / requires_accepted_phase / blast_radius_cap are
  hash-bound — they enter proof_hash._contract_canon so a post-hoc risk-class
  downgrade (or any change to these fields) changes the contract hash and
  invalidates a previously-accepted proof. Fail-safe by construction.

A verifier declares its source lineage so the post-write validator can reject a
verification whose declared source overlaps the operation's forbidden inputs (the
known tautology class: verifying a write against the writer's own output).

This is a build-time + operator-as-approver enforcement ceiling, NOT a runtime or
OS-level guarantee.

Stdlib only — no third-party dependencies.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from external_write.verification_modes import VerificationMode


@dataclass(frozen=True)
class SourceLineage:
    """What sources a verifier may and may not consult."""

    pre_write_sources: Tuple[str, ...]
    post_write_sources: Tuple[str, ...]
    forbidden_verification_inputs: Tuple[str, ...]


@dataclass(frozen=True)
class VerifierDef:
    """A registered post-write verifier and its declared lineage."""

    verifier_id: str
    mode: VerificationMode
    source_lineage: SourceLineage


@dataclass(frozen=True)
class OperationContract:
    """The declared contract for one named operation kind."""

    op_kind: str
    writes: Tuple[str, ...]
    produces: Tuple[str, ...]
    dependency_set: Tuple[str, ...]
    verifier_set: Tuple[str, ...]
    introduces_persistent_binding: bool
    # B1-3 risk fields (each default preserves pre-B1-3 behavior for every contract
    # built before this change; see the module docstring and D-B1-b above).
    risk_class: str = "reversible_external"
    requires_accepted_phase: bool = False
    blast_radius_cap: Optional[int] = None
    # Task 4 (external-write-gate-generalization — credential isolation): the
    # vendor-scoped, READ-ONLY OAuth/API scope (or equivalent credential-scope
    # identifier) that a ReadFacade for this op_kind is built against, e.g.
    # "gmail.readonly". None (the default, preserving every contract built
    # before this field existed) means this op_kind has NOT declared a
    # read-only scope and is therefore INELIGIBLE for the ReadFacade
    # credential-isolation safety model — external_write.read_facade.
    # require_read_only_scope/build_read_facade refuse fail-closed on None.
    # This is a vendor-ELIGIBILITY declaration, not a hash-bound identity
    # field (contrast risk_class/requires_accepted_phase/blast_radius_cap
    # above, D-B1-b): it gates whether a ReadFacade can be built at all, it
    # does not itself change write behavior, so it is deliberately left out
    # of proof_hash._contract_canon.
    read_only_scope: Optional[str] = None


# The risk-class vocabulary, mirrored VERBATIM from wizard/scripts/lib/
# dependency_projection.RISK_CLASSES (B1-1). external_write cannot import the
# build-side module (separate root-of-trust tree — D-B1-a), so this is a deliberate
# duplication guarded by a cross-tree equality test
# (test_external_write_contracts.test_risk_classes_constant_matches_build_side_vocabulary,
# which runs from wizard/scripts and can import both trees). If you change the values
# here, update dependency_projection.RISK_CLASSES in the same commit, or that test fails.
RISK_CLASSES = frozenset({
    "read_only_local", "reversible_external", "irreversible_external",
    "sensitive_data", "standing_automation",
})


# The lib modules whose source determines the SHARED write behavior for every
# seeded in-place operation. Listed by canonical filename; the proof-hash
# computation resolves these against the installed adapter directory. This is
# every existing op_kind's dependency_set today, but it is not the full
# per-op_kind picture once an op_kind has its own registered adapter — see
# effects_manifest.resolve_dependency_files (Task 3) and the dependency_set
# docstring above.
_WRITE_AFFECTING_MODULES = (
    "adapters.py",
    "broker.py",
    "operations.py",
    "verifiers.py",
)

# Public alias (Task 10 — external-write-gate-generalization): a capability's own
# generated adapter module (wizard/scripts/lib/capability_code_scaffold.py) declares its
# OperationContract with this SAME shared dependency_set, exactly like the seeded status
# ops and the Gmail reference adapter (_gmail_message_contract) both already do — this
# name is the stable, public spelling other modules should import rather than reaching
# for the underscore-prefixed one above.
WRITE_AFFECTING_MODULES = _WRITE_AFFECTING_MODULES


VERIFIER_REGISTRY: dict = {
    "prestate_snapshot_diff_v1": VerifierDef(
        verifier_id="prestate_snapshot_diff_v1",
        mode=VerificationMode.PRESTATE_SNAPSHOT_DIFF,
        source_lineage=SourceLineage(
            pre_write_sources=("prewrite_csv_backup",),
            post_write_sources=("live_surface_read",),
            forbidden_verification_inputs=(
                "writer_generated_id_map",
                "live_id_column_as_truth",
                "apply_report",
            ),
        ),
    ),
    "operator_attested_v1": VerifierDef(
        verifier_id="operator_attested_v1",
        mode=VerificationMode.OPERATOR_ATTESTED,
        source_lineage=SourceLineage(
            pre_write_sources=(),
            post_write_sources=(),
            forbidden_verification_inputs=(),
        ),
    ),
}


def _status_contract(op_kind: str, field: str) -> OperationContract:
    """Build a contract for an in-place status-style write (the default seeded shape).

    All seeded status ops are in-place edits on an external tracker: they ARE
    reversible (via prestate snapshot restore), so risk_class is set explicitly
    to "reversible_external" rather than relying on the dataclass default — the
    intent is a deliberate classification, not an unset field that happens to
    match the default. requires_accepted_phase / blast_radius_cap are left at
    their defaults (False / None): these ops are already gated by the broker +
    copy_run_proof and must not be newly restricted by B1-3.
    """
    return OperationContract(
        op_kind=op_kind,
        writes=(field,),
        produces=(),
        dependency_set=_WRITE_AFFECTING_MODULES,
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=False,
        risk_class="reversible_external",
    )


def _delete_record_contract() -> OperationContract:
    """The first NON-status, irreversible op_kind (B1-3 requirement 3).

    delete_record is the generic, domain-neutral shape every irreversible external
    delete follows (no email/Gmail-specific naming — this is the template other
    surfaces' delete ops are cut from).

      writes=("__record__",) — a delete removes the whole record, not one column
        value; "__record__" is a sentinel (matching this module's other
        dunder-sentinel convention, e.g. section_merge._PREAMBLE_KEY) distinct from
        a real field name like "Status" or "Due Date".
      produces=() — a delete does not create a new artifact.
      dependency_set — the same write-affecting modules as every other op; the
        module set that determines write behavior does not change for a delete.
      verifier_set=("prestate_snapshot_diff_v1",) — a naive round-trip read-back
        cannot verify a delete (there is nothing left to read). The registered
        prestate_snapshot_diff_v1 verifier is nonetheless the defensible choice:
        its declared invariant is a pre-write-snapshot vs. live-post-write-read
        diff, and "the record present in the prestate snapshot is now ABSENT from
        the live read" is exactly that invariant, applied to presence rather than
        value equality. It reuses the already-registered, already-lineage-locked
        verifier (pre_write_sources=prewrite_csv_backup, post_write_sources=
        live_surface_read, forbidden=writer_generated_id_map/live_id_column_as_
        truth/apply_report) rather than inventing a new platform_audit_log
        VerifierDef whose forbidden-input lineage this task was not asked to
        design. (See the B1-3 report for the full justification.)
      introduces_persistent_binding=False — a delete does not introduce or rely on
        any persistent binding future operations depend on; it removes a record,
        it does not create stable IDs/anchors/cross-refs for later writes to key
        off of. (This is the narrow trigger defined in the module docstring; a
        delete does not trip it.)
      risk_class="irreversible_external" — the whole reason this op_kind exists:
        it is the FAIL_SAFE_RISK_CLASS in dependency_projection.py, the
        most-protected member of RISK_CLASSES.
      requires_accepted_phase=True — an irreversible delete may only run under a
        covering ACCEPTED descriptor phase (enforced by B1-4).
      blast_radius_cap=5 — irreversible ops never batch, and the slice policy
        ceiling is ~10/session; 5 is a conservative interim per-op_kind default,
        comfortably under that ceiling, that B1-2's per-capability descriptor cap
        can override downward (never upward past this) at B1-4 enforcement time.
    """
    return OperationContract(
        op_kind="delete_record",
        writes=("__record__",),
        produces=(),
        dependency_set=_WRITE_AFFECTING_MODULES,
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=False,
        risk_class="irreversible_external",
        requires_accepted_phase=True,
        blast_radius_cap=5,
    )


def _gmail_message_contract(op_kind: str, *, risk_class: str,
                            requires_accepted_phase: bool,
                            blast_radius_cap: Optional[int]) -> OperationContract:
    """Build a contract for a Gmail per-message label mutation (Task 7 —
    external-write-gate-generalization slice; the reference VERB-shaped
    adapter proving the generalized gate against a real vendor API).

    trash / untrash / modify_labels all mutate the SAME thing structurally —
    a message's label set — so writes=("labels",) is shared across all three;
    produces=() because none of them create a new artifact. dependency_set is
    the same shared write-affecting module tuple every op_kind declares;
    effects_manifest.resolve_dependency_files (Task 3 / F-34) unions in
    adapters_gmail.py — this op_kind's registered adapter module — on top of
    it, exactly like every other adapter-backed op_kind. risk_class is
    "sensitive_data" for all three: Gmail message content is sensitive
    personal data, even though the label mutation itself is recoverable
    (trash/relabel are reversible; the DATA they touch is what earns the
    gated classification, not the recoverability of the edit).

    read_only_scope="gmail.readonly" makes these op_kinds eligible for the
    ReadFacade credential-isolation safety model (Task 4) — the concrete
    GmailReadFacade is registered (via register_read_facade, against the
    kernel registry in read_facade.py) in read_facades_gmail.py, split out
    of adapters_gmail.py per Task R7-T1 so the facade lives in its own
    scanned module, with no adapter and no credential in it.
    """
    return OperationContract(
        op_kind=op_kind,
        writes=("labels",),
        produces=(),
        dependency_set=_WRITE_AFFECTING_MODULES,
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=False,
        risk_class=risk_class,
        requires_accepted_phase=requires_accepted_phase,
        blast_radius_cap=blast_radius_cap,
        read_only_scope="gmail.readonly",
    )


def _gmail_filter_create_contract() -> OperationContract:
    """gmail.filter.create is the one op_kind in this reference set that
    introduces a PERSISTENT BINDING (copy_run_proof's durability_checks
    gating): a created filter is a standing rule that keeps acting on every
    future matching message, not a one-shot edit on existing data — hence
    risk_class="standing_automation" (F-29's non-graduating-recovery-floor
    class), distinct from the per-message ops above."""
    return OperationContract(
        op_kind="gmail.filter.create",
        writes=("filters",),
        produces=("gmail_filter",),
        dependency_set=_WRITE_AFFECTING_MODULES,
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=True,
        risk_class="standing_automation",
        requires_accepted_phase=True,
        blast_radius_cap=5,
        read_only_scope="gmail.readonly",
    )


OPERATION_CONTRACTS: dict = {
    "set_status": _status_contract("set_status", "Status"),
    "complete_tasks": _status_contract("complete_tasks", "Status"),
    "update_due_date": _status_contract("update_due_date", "Due Date"),
    "add_note": _status_contract("add_note", "Note"),
    "set_priority": _status_contract("set_priority", "Priority"),
    "delete_record": _delete_record_contract(),
    # Task 7 — reference verb-shaped adapter (external-write-gate-generalization).
    "gmail.message.trash": _gmail_message_contract(
        "gmail.message.trash", risk_class="sensitive_data",
        requires_accepted_phase=True, blast_radius_cap=25),
    "gmail.message.untrash": _gmail_message_contract(
        "gmail.message.untrash", risk_class="sensitive_data",
        requires_accepted_phase=True, blast_radius_cap=25),
    "gmail.message.modify_labels": _gmail_message_contract(
        "gmail.message.modify_labels", risk_class="sensitive_data",
        requires_accepted_phase=True, blast_radius_cap=25),
    "gmail.filter.create": _gmail_filter_create_contract(),
}


def register_contract(contract: OperationContract) -> None:
    """Register `contract` under its own `op_kind` (Task 10 —
    external-write-gate-generalization; lets a capability added post-build
    declare its op_kind's contract without hand-editing this module's
    literal ``OPERATION_CONTRACTS`` dict).

    Mirrors ``adapter_registry.register_adapter``'s convention exactly: a
    plain, unvalidated registration a real adapter module calls at import
    time (module scope), alongside its own ``register_adapter(op_kind, ...)``
    call — see e.g. ``adapters_gmail.py``'s registration block for the
    established pattern this generalizes. Re-registering the same op_kind
    overwrites the prior entry (last-registered wins); callers own ordering,
    this function does not raise on a duplicate op_kind. No validation of
    `contract` beyond it being an ``OperationContract`` instance is performed
    here — the same "no validation, that's a different layer's job" division
    ``adapter_registry.register_adapter`` already documents.
    """
    OPERATION_CONTRACTS[contract.op_kind] = contract


def get_contract(op_kind: str) -> Optional[OperationContract]:
    """Return the OperationContract for op_kind, or None if unregistered."""
    return OPERATION_CONTRACTS.get(op_kind)


def get_verifier(verifier_id: str) -> Optional[VerifierDef]:
    """Return the VerifierDef for verifier_id, or None if unregistered."""
    return VERIFIER_REGISTRY.get(verifier_id)


def accepted_verifier_ids(op_kind: str) -> Tuple[str, ...]:
    """Return the verifier_set declared by op_kind's contract (empty if unregistered)."""
    c = get_contract(op_kind)
    return c.verifier_set if c is not None else ()
