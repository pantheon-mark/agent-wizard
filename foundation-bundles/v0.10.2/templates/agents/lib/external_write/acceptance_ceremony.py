"""B2-T3 — the acceptance ceremony: the SOLE deterministic writer of ``accepted: true`` in
``security/capability_descriptors.json``.

The runtime ``write_gate`` authorizes a LIVE external write only for a descriptor whose
``accepted`` is exactly ``True`` and whose surface + risk class cover the operation. A descriptor
is ALWAYS emitted ``accepted: false`` (``capability_descriptor_registry.build_descriptor_entries``
and ``base_declared_descriptors`` never emit ``true``; the add-capability cascade only ever ADDS
``accepted: false`` entries). This module is the ONE legitimate mechanism that flips a specific
descriptor from ``accepted: false`` to ``accepted: true`` — the point at which live external side
effects become authorized. It is therefore the most trust-critical unit of the substrate.

THE OVERRIDING PROPERTY is fail-safe: on ANY missing, ambiguous, or invalid input the ceremony
REFUSES — it does not write, it leaves ``accepted: false``, and it returns a clear failure. It
never guesses a bypass. Every validation branch below defaults to refuse.

Enforcement ceiling (deliberate, disclosed): this is a BUILD-TIME + OPERATOR-AS-APPROVER gate,
NOT a runtime or OS-level guarantee. A post-build hand edit of the descriptor file can still flip
the field; the ceremony is the sole LEGITIMATE path to acceptance and makes NO claim of
tamper-proofness. It removes the accidental / model-authored acceptance, not the deliberate
operator edit.

The deterministic algorithm (no LLM, no clock or randomness in the decision)
-----------------------------------------------------------------------------
Given a target ``capability_id`` (== descriptor id), an accepted ``phase_id``, a reference to the
capability's validated ``copy_run_proof`` artifact, and an operator-acceptance receipt, the
ceremony flips exactly that descriptor's ``accepted`` to ``true`` IFF every invariant below holds:

  1. The descriptor set loads (readable, valid JSON, a list) and the target descriptor exists,
     is a well-formed dict with an in-vocabulary ``risk_class``, and is NOT a reserved base
     ``__builtin__:`` placeholder. Else refuse.
  2. NO RISK DOWNGRADE — verified against the hash-bound canon (``proof_hash``), NOT by trusting
     the mutable descriptor field: the proof declares an ``op_kind`` whose registered contract
     supplies the authoritative risk class; the descriptor's ``risk_class`` must equal it, AND
     the proof's declared ``contract_hash`` / ``implementation_hash`` must equal the freshly
     recomputed canon (any post-proof change to a hash-bound risk field — most importantly a
     ``risk_class`` downgrade — breaks the recomputed hash). Else refuse.
  3. BLAST-RADIUS CAP PRESENT — a gated descriptor must carry a positive-integer
     ``blast_radius_cap`` on the descriptor itself. Else refuse.
  4. VALIDATED COPY_RUN_PROOF — a ``copy_run_proof-v1`` artifact (the copy-run-proof contract)
     whose verdict is success (apply AND undo AND verify-restored, per
     ``validate_copy_run_proof``). Absent, failed, or unverifiable → refuse. (delete_record and
     every gated class have a success representation via the copy machinery — the ceremony
     invents no irreversible bypass.)
  4b. PROOF BOUND TO THIS CAPABILITY — the proof's ``capability_id`` must be present and equal
     the target descriptor's id (== ``capability_id``). Without this the proof↔capability join
     sits at RISK-CLASS altitude: a valid proof for a DIFFERENT same-op-kind / same-risk
     capability would cross-authorize. Absent / non-string / mismatched → refuse.
  5. OPERATOR-ACCEPTANCE RECEIPT PRESENT + BOUND — the receipt B2-T6's next-phase Step-6 produces,
     bound to this exact acceptance (its ``capability_id`` / ``phase_id`` / ``copy_run_proof_ref``
     match the ceremony inputs and it carries a non-empty verbatim operator confirmation). Else
     refuse.
  6. PHASE MATCH — the descriptor's owning ``phase_id`` equals the accepted ``phase_id``. Else
     refuse.

Only a gated capability (an effective risk class in ``write_gate.GATED_RISK_CLASSES``) is in
scope — acceptance is meaningless for read-only / plain-reversible descriptors, so the ceremony
refuses those rather than flipping a field with no live-write semantics.

The write is ATOMIC (temp file in the same directory + ``os.replace``) so a crash can never
corrupt the trust file, and deterministic (``json.dumps(..., indent=2, ensure_ascii=False)`` +
trailing newline — the SAME formatting ``render_descriptor_registry_json`` emits, so re-emit /
parity stays reproducible). Exactly the target entry's ``accepted`` is set; every other entry and
every other key is left byte-identical.

Forward input contract (T4/T5/T6 MUST conform — documented here because downstream tasks produce
these inputs):

  * copy_run_proof ref  — a filesystem path to a JSON file holding one ``copy_run_proof-v1``
                          artifact (``copy_run_proof.COPY_RUN_PROOF_SCHEMA``); carries the
                          ``op_kind`` + ``implementation_hash`` + ``contract_hash`` this ceremony
                          re-verifies against the canon. B2-T4 (approved-design artifact) /
                          B2-T6 (Step-6 acceptance) produce it.
  * operator receipt    — a filesystem path to a JSON file matching
                          ``OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA`` (see ``_REQUIRED_RECEIPT_FIELDS``):
                          {schema, capability_id, phase_id, copy_run_proof_ref,
                          operator_confirmation, accepted_at}. B2-T6's Step-6 mints it from the
                          real operator confirmation and passes its path here.
  * phase binding       — the descriptor set today carries no phase field
                          (``capability_descriptor_registry.ENTRY_KEYS`` has none). This ceremony
                          defines a minimal additive ``phase_id`` string key on each descriptor
                          entry (ignored by write_gate / coverage_gate, which read only their own
                          keys). B2-T4 declares the owning phase; B2-T5's emit / add-capability
                          cascade MUST populate ``phase_id`` on each emitted descriptor entry, or
                          no capability can ever be accepted (fail-safe).

Emission: this module runs at OPERATOR-SIDE acceptance time (next-phase Step-6, in the operator's
project), so it must be emitted into operator systems. B2-T9 must add it to
``_EXTERNAL_WRITE_LIB_FILES`` + the foundation bundle (NOT wired here — CANONICAL-ONLY).

Stdlib only — no third-party dependencies.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# sys.path bootstrap (mirrors coverage_gate.py): when invoked as a direct script from the project
# root (e.g. python3 agents/lib/external_write/acceptance_ceremony.py ...), Python puts this
# file's OWN directory on sys.path, not the package parent, so the sibling
# ``from external_write...`` imports below would fail. Make the package parent (agents/lib)
# importable if it is not already (a no-op under the test harness, which sets the path itself).
# Anchored to __file__, not cwd. MUST run before the package imports below.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.contracts import RISK_CLASSES, get_contract
from external_write.copy_run_proof import validate_copy_run_proof
from external_write.proof_hash import (
    compute_contract_hash,
    compute_implementation_hash,
    ProofHashError,
)
from external_write.write_gate import GATED_RISK_CLASSES


# The operator-acceptance receipt schema (produced by B2-T6's next-phase Step-6).
OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA = "operator_acceptance_receipt-v1"

# The durable acceptance-record schema written to the audit log on a successful flip.
ACCEPTANCE_RECORD_SCHEMA = "capability_acceptance_record-v1"

# The default append-only audit log for acceptance records (disk-first + audit convention).
DEFAULT_AUDIT_LOG_PATH = "security/capability_acceptance_log.jsonl"

# The additive per-entry phase-binding key this ceremony introduces (see module docstring).
PHASE_ID_KEY = "phase_id"

# Reserved base-descriptor id/name prefix — DUPLICATED from
# capability_descriptor_registry.BASE_DESCRIPTOR_ID_PREFIX (external_write cannot import the
# build-side tree — D-B1-a) and pinned equal by
# test_external_write_acceptance_ceremony.test_base_prefix_matches_build_side, exactly as the
# write_gate vocabulary constants are pinned. A base entry is a placeholder describing that a
# built-in op EXISTS and is unaccepted; it is never a real acceptable capability, so the ceremony
# refuses it outright (defense-in-depth; the phase / receipt binding would refuse it anyway).
BASE_DESCRIPTOR_ID_PREFIX = "__builtin__:"

# Required operator-receipt fields (fail-safe: any absent field refuses).
_REQUIRED_RECEIPT_FIELDS = (
    "schema", "capability_id", "phase_id", "copy_run_proof_ref",
    "operator_confirmation", "accepted_at",
)


@dataclass(frozen=True)
class AcceptanceResult:
    """Outcome of the acceptance ceremony.

    accepted:      True IFF every invariant held and the atomic flip succeeded.
    reason:        On refusal, a specific human-readable reason (never None when not accepted).
                   None on success.
    capability_id: The target capability id (echoed for the caller/audit).
    phase_id:      The accepted phase id.
    record_ref:    On success, the path of the audit log the acceptance record was appended to
                   (None if the record could not be written — see ``warning``).
    warning:       A non-fatal note (e.g. the audit-record append failed AFTER a successful,
                   authoritative flip). None otherwise.
    """
    accepted: bool
    reason: Optional[str] = None
    capability_id: Optional[str] = None
    phase_id: Optional[str] = None
    record_ref: Optional[str] = None
    warning: Optional[str] = None


def _refuse(reason: str, capability_id: Optional[str], phase_id: Optional[str]) -> AcceptanceResult:
    return AcceptanceResult(accepted=False, reason=reason,
                            capability_id=capability_id, phase_id=phase_id)


def _strict_load_descriptor_set(path: str) -> Any:
    """Read + parse the descriptor set STRICTLY (raises on unreadable / malformed / non-list).

    Distinct from ``write_gate.load_descriptor_set`` (which swallows errors to ``[]`` — correct
    for the read-side gate, which must fail SAFE to 'nothing accepted'). Here the ceremony must
    both distinguish 'unreadable/malformed set' as its own refusal AND obtain the exact parsed
    structure it will mutate + write back, so it parses strictly and the caller refuses on any
    exception."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("descriptor set is not a JSON array")
    return data


def _load_json_file(path: str) -> Any:
    """Fail-safe JSON load: returns None on a missing / unreadable / malformed file (the caller
    refuses on None). Never raises."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _atomic_write_json_list(path: str, data: List[Any]) -> None:
    """Write ``data`` to ``path`` atomically, matching render_descriptor_registry_json formatting.

    Writes to a temp file in the SAME directory (so ``os.replace`` is an atomic same-filesystem
    rename), flushes + fsyncs, then replaces. On ANY failure the temp file is removed and the
    original ``path`` is left untouched (``os.replace`` is atomic — a crash or exception before it
    leaves the original intact; one after it has already fully swapped in the new content)."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".capability_descriptors.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _append_acceptance_record(audit_path: str, record: Dict[str, Any]) -> None:
    """Append one acceptance record as a single JSONL line (audit trail). Best-effort: the caller
    surfaces a failure as a warning AFTER the authoritative flip has already succeeded."""
    directory = os.path.dirname(os.path.abspath(audit_path))
    os.makedirs(directory, exist_ok=True)
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def accept_capability_for_live_use(
    capability_id: str,
    phase_id: str,
    copy_run_proof_ref: str,
    operator_receipt_ref: str,
    *,
    descriptor_set_path: Optional[str] = None,
    lib_dir: Optional[Path] = None,
    audit_log_path: Optional[str] = None,
) -> AcceptanceResult:
    """Accept exactly one capability for live use by flipping its descriptor's ``accepted`` to
    ``true`` — IFF every invariant in the module docstring holds. Fail-safe: on any missing /
    ambiguous / invalid input, refuse (no write; ``accepted`` stays false; a clear failure).

    Parameters
    ----------
    capability_id:         The target descriptor id to accept.
    phase_id:              The accepted phase id (must match the descriptor's owning phase).
    copy_run_proof_ref:    Filesystem path to the capability's ``copy_run_proof-v1`` JSON artifact.
    operator_receipt_ref:  Filesystem path to the operator-acceptance receipt JSON
                           (``OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA``).
    descriptor_set_path:   The descriptor-set file (default ``write_gate.DESCRIPTOR_SET_PATH``,
                           i.e. ``security/capability_descriptors.json``, project-root-relative).
    lib_dir:               Directory to resolve write-affecting dependency files for the
                           implementation-hash recomputation (default: proof_hash's own lib dir).
    audit_log_path:        Append-only acceptance-record log (default DEFAULT_AUDIT_LOG_PATH).
    """
    # Basic input sanity — a non-string identifier is ambiguous; refuse.
    if not (isinstance(capability_id, str) and capability_id):
        return _refuse("no target capability_id supplied", None, phase_id)
    if not (isinstance(phase_id, str) and phase_id):
        return _refuse("no accepted phase_id supplied", capability_id, None)
    if not (isinstance(copy_run_proof_ref, str) and copy_run_proof_ref):
        return _refuse("no copy_run_proof reference supplied", capability_id, phase_id)
    if not (isinstance(operator_receipt_ref, str) and operator_receipt_ref):
        return _refuse("no operator-acceptance receipt reference supplied",
                       capability_id, phase_id)

    if descriptor_set_path is None:
        from external_write.write_gate import DESCRIPTOR_SET_PATH
        descriptor_set_path = DESCRIPTOR_SET_PATH
    if not descriptor_set_path:
        return _refuse("no descriptor-set path configured", capability_id, phase_id)
    if audit_log_path is None:
        audit_log_path = DEFAULT_AUDIT_LOG_PATH

    # --- Invariant 1: descriptor set loads + target well-formed ---------------------------
    try:
        entries = _strict_load_descriptor_set(descriptor_set_path)
    except Exception as e:
        return _refuse(
            f"descriptor set is unreadable / malformed / not a JSON array: {e}",
            capability_id, phase_id)

    target: Optional[Dict[str, Any]] = None
    for e in entries:
        if isinstance(e, dict) and e.get("id") == capability_id:
            target = e
            break
    if target is None:
        return _refuse(
            f"no descriptor with id {capability_id!r} in the set — nothing to accept",
            capability_id, phase_id)

    if capability_id.startswith(BASE_DESCRIPTOR_ID_PREFIX):
        return _refuse(
            f"{capability_id!r} is a reserved base placeholder descriptor, never an acceptable "
            "capability",
            capability_id, phase_id)

    descriptor_risk = target.get("risk_class")
    if not (isinstance(descriptor_risk, str) and descriptor_risk in RISK_CLASSES):
        return _refuse(
            f"target descriptor has an absent / out-of-vocabulary risk_class "
            f"{descriptor_risk!r}; known: {sorted(RISK_CLASSES)}",
            capability_id, phase_id)

    # Scope: only GATED capabilities have live-write acceptance semantics.
    if descriptor_risk not in GATED_RISK_CLASSES:
        return _refuse(
            f"acceptance applies only to gated capabilities; risk_class {descriptor_risk!r} is "
            "not gated (a read-only / plain-reversible descriptor needs no live-write acceptance)",
            capability_id, phase_id)

    # --- Invariant 3: blast-radius cap present on the gated descriptor --------------------
    cap = target.get("blast_radius_cap")
    if not (isinstance(cap, int) and not isinstance(cap, bool) and cap > 0):
        return _refuse(
            f"gated descriptor {capability_id!r} has no positive-integer blast_radius_cap "
            f"(got {cap!r}); an unbounded gated capability is never accepted",
            capability_id, phase_id)

    # --- Invariant 6: phase binding -------------------------------------------------------
    descriptor_phase = target.get(PHASE_ID_KEY)
    if not (isinstance(descriptor_phase, str) and descriptor_phase):
        return _refuse(
            f"descriptor {capability_id!r} carries no {PHASE_ID_KEY!r} binding — it cannot be "
            "accepted until its owning phase is populated (forward obligation on T4/T5)",
            capability_id, phase_id)
    if descriptor_phase != phase_id:
        return _refuse(
            f"phase mismatch: descriptor {capability_id!r} is owned by phase "
            f"{descriptor_phase!r}, not the accepted phase {phase_id!r}",
            capability_id, phase_id)

    # --- Invariant 5: operator-acceptance receipt present + bound -------------------------
    receipt = _load_json_file(operator_receipt_ref)
    if not isinstance(receipt, dict):
        return _refuse(
            "operator-acceptance receipt is missing / unreadable / malformed",
            capability_id, phase_id)
    for fld in _REQUIRED_RECEIPT_FIELDS:
        if fld not in receipt:
            return _refuse(
                f"operator receipt is missing required field {fld!r}", capability_id, phase_id)
    if receipt.get("schema") != OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA:
        return _refuse(
            f"operator receipt schema must be {OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA!r}; got "
            f"{receipt.get('schema')!r}",
            capability_id, phase_id)
    if receipt.get("capability_id") != capability_id:
        return _refuse(
            "operator receipt capability_id does not match the target — the receipt does not "
            "authorize accepting this capability",
            capability_id, phase_id)
    if receipt.get("phase_id") != phase_id:
        return _refuse(
            "operator receipt phase_id does not match the accepted phase", capability_id, phase_id)
    if receipt.get("copy_run_proof_ref") != copy_run_proof_ref:
        return _refuse(
            "operator receipt copy_run_proof_ref does not match the proof supplied — the operator "
            "did not attest to this proof",
            capability_id, phase_id)
    confirmation = receipt.get("operator_confirmation")
    if not (isinstance(confirmation, str) and confirmation.strip()):
        return _refuse(
            "operator receipt carries no non-empty operator_confirmation", capability_id, phase_id)

    # --- Invariant 4: validated copy_run_proof present ------------------------------------
    proof = _load_json_file(copy_run_proof_ref)
    if not isinstance(proof, dict):
        return _refuse(
            "copy_run_proof is missing / unreadable / malformed", capability_id, phase_id)
    proof_result = validate_copy_run_proof(proof)
    if not proof_result.ok:
        return _refuse(
            f"copy_run_proof did not validate (apply/undo/verify-restored): {proof_result.reason}",
            capability_id, phase_id)

    # --- Invariant 4b: proof BOUND to THIS specific capability ----------------------------
    # The proof must name the exact capability it proves and it must equal the target
    # descriptor's id (== capability_id). Without this, a valid proof produced for a DIFFERENT
    # same-op-kind / same-risk-class capability could satisfy the ceremony — the join would sit
    # at risk-class altitude, not at the specific capability. Fail-safe: an absent, non-string,
    # or mismatched proof capability_id refuses (a proof that does not name its capability cannot
    # authorize accepting one).
    proof_capability_id = proof.get("capability_id")
    if not (isinstance(proof_capability_id, str) and proof_capability_id):
        return _refuse(
            "copy_run_proof carries no capability_id — it does not name the capability it "
            "proves, so it cannot authorize accepting this one",
            capability_id, phase_id)
    if proof_capability_id != capability_id:
        return _refuse(
            f"copy_run_proof capability_id {proof_capability_id!r} does not match the target "
            f"capability {capability_id!r} — the proof belongs to a different capability; "
            "refusing (a same-risk proof must not cross-authorize)",
            capability_id, phase_id)

    # --- Invariant 2: no risk downgrade, verified against the hash-bound canon -------------
    op_kind = proof.get("op_kind")
    contract = get_contract(op_kind) if isinstance(op_kind, str) else None
    if contract is None:
        return _refuse(
            f"copy_run_proof op_kind {op_kind!r} has no registered contract — cannot verify risk "
            "against the canon",
            capability_id, phase_id)
    # The descriptor's declared risk must equal the operation's contract risk (do not trust the
    # descriptor field in isolation — bind it to the contract).
    if descriptor_risk != contract.risk_class:
        return _refuse(
            f"risk mismatch: descriptor risk_class {descriptor_risk!r} does not equal the "
            f"contract risk_class {contract.risk_class!r} for op_kind {op_kind!r} — a downgrade "
            "or mis-binding; refusing",
            capability_id, phase_id)
    # The proof must be bound to the CURRENT hash canon: any post-proof change to a hash-bound
    # risk field (risk_class / requires_accepted_phase / blast_radius_cap) or to any
    # write-affecting dependency breaks these recomputed hashes.
    try:
        expected_contract_hash = compute_contract_hash(op_kind)
        expected_impl_hash = compute_implementation_hash(op_kind, lib_dir=lib_dir)
    except ProofHashError as e:
        return _refuse(
            f"could not recompute the proof-bound canon for op_kind {op_kind!r}: {e}",
            capability_id, phase_id)
    if proof.get("contract_hash") != expected_contract_hash:
        return _refuse(
            "copy_run_proof contract_hash does not match the recomputed canon — the contract "
            "(risk fields included) changed since the proof; refusing (possible risk downgrade)",
            capability_id, phase_id)
    if proof.get("implementation_hash") != expected_impl_hash:
        return _refuse(
            "copy_run_proof implementation_hash does not match the recomputed canon — the "
            "write-affecting code changed since the proof; refusing",
            capability_id, phase_id)

    # --- All invariants held: perform the atomic flip -------------------------------------
    if target.get("accepted") is True:
        # Idempotent: already accepted. Nothing to write; report success without a spurious
        # duplicate audit record.
        return AcceptanceResult(accepted=True, reason=None, capability_id=capability_id,
                                phase_id=phase_id, record_ref=None,
                                warning="descriptor was already accepted; no change written")

    # Build the new entry list, flipping ONLY the target entry's `accepted` (its other keys and
    # every other entry stay byte-identical after re-dump).
    new_entries: List[Any] = []
    for e in entries:
        if e is target:
            flipped = dict(e)
            flipped["accepted"] = True
            new_entries.append(flipped)
        else:
            new_entries.append(e)

    try:
        _atomic_write_json_list(descriptor_set_path, new_entries)
    except Exception as e:
        # Atomic write failed — the original file is intact (os.replace never happened, or
        # happened wholly). Refuse; accepted stays false.
        return _refuse(
            f"atomic write of the descriptor set failed; no change made: {e}",
            capability_id, phase_id)

    # Authoritative act succeeded. Append the durable acceptance record (best-effort — a log
    # failure does NOT undo a legitimate acceptance; it is surfaced as a warning).
    record = {
        "schema": ACCEPTANCE_RECORD_SCHEMA,
        "capability_id": capability_id,
        "phase_id": phase_id,
        "risk_class": descriptor_risk,
        "op_kind": op_kind,
        "copy_run_proof_ref": copy_run_proof_ref,
        "operator_receipt_ref": operator_receipt_ref,
        "contract_hash": expected_contract_hash,
        "implementation_hash": expected_impl_hash,
        "operator_confirmation": confirmation,
        "receipt_accepted_at": receipt.get("accepted_at"),
    }
    try:
        _append_acceptance_record(audit_log_path, record)
    except Exception as e:
        return AcceptanceResult(
            accepted=True, reason=None, capability_id=capability_id, phase_id=phase_id,
            record_ref=None,
            warning=f"capability accepted, but the acceptance record could not be written: {e}")

    return AcceptanceResult(accepted=True, reason=None, capability_id=capability_id,
                            phase_id=phase_id, record_ref=audit_log_path)


# ---------------------------------------------------------------------------
# CLI wrapper — mirrors coverage_gate.py's invocation shape. Run from the operator project root
# so the default descriptor-set path resolves. Exits 0 on acceptance, 1 on refusal, 2 on usage.
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _args = _sys.argv[1:]
    _opts: Dict[str, Optional[str]] = {
        "--capability-id": None, "--phase-id": None, "--copy-run-proof": None,
        "--operator-receipt": None, "--descriptor-set": None, "--audit-log": None,
    }
    _i = 0
    _usage = ("Usage: acceptance_ceremony.py --capability-id <id> --phase-id <id> "
              "--copy-run-proof <path> --operator-receipt <path> "
              "[--descriptor-set <path>] [--audit-log <path>]")
    while _i < len(_args):
        _a = _args[_i]
        if _a in _opts:
            if _i + 1 >= len(_args):
                print(_usage, file=_sys.stderr)
                _sys.exit(2)
            _opts[_a] = _args[_i + 1]
            _i += 2
        else:
            print(f"unknown argument {_a!r}\n{_usage}", file=_sys.stderr)
            _sys.exit(2)

    for _req in ("--capability-id", "--phase-id", "--copy-run-proof", "--operator-receipt"):
        if not _opts[_req]:
            print(f"missing required {_req}\n{_usage}", file=_sys.stderr)
            _sys.exit(2)

    _res = accept_capability_for_live_use(
        _opts["--capability-id"], _opts["--phase-id"],
        _opts["--copy-run-proof"], _opts["--operator-receipt"],
        descriptor_set_path=_opts["--descriptor-set"],
        audit_log_path=_opts["--audit-log"])
    if _res.accepted:
        _msg = f"ACCEPTED: capability {_res.capability_id!r} is now live-authorized for phase " \
               f"{_res.phase_id!r}."
        if _res.warning:
            _msg += f" (warning: {_res.warning})"
        print(_msg)
        _sys.exit(0)
    else:
        print(f"REFUSED: {_res.reason}", file=_sys.stderr)
        _sys.exit(1)
