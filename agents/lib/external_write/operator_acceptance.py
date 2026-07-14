"""B2-T6 — the operator-acceptance helper: the deterministic step the next-phase skill's
business-acceptance step (Step 6) invokes to turn the operator's explicit "yes" into a live
authorization, WITHOUT any free-form model JSON authoring at the trust surface.

Why this is its own unit
------------------------
Flipping a descriptor's ``accepted`` to true is the exact moment a capability's live external
writes become permitted — the most trust-critical transition in the substrate. The acceptance
ceremony (``acceptance_ceremony.accept_capability_for_live_use``) is the SOLE writer of that
field and demands a well-formed ``operator_acceptance_receipt-v1`` bound to the exact
acceptance. Producing that receipt is the one remaining piece. Rather than let the next-phase
agent hand-author the receipt JSON (a free-form write at a trust surface — the failure mode the
whole flow exists to prevent), this helper MINTS the receipt deterministically from the
operator's VERBATIM confirmation and immediately drives the ceremony. The next-phase skill calls
one helper; it never edits a trust file by hand.

Honest capture (never fabricate the operator's yes)
---------------------------------------------------
``operator_confirmation`` is inherently operator-driven — the operator says yes. This helper
captures whatever the operator actually typed, verbatim, and REFUSES to mint a receipt on an
empty / whitespace-only confirmation. It never invents, paraphrases into, or defaults a
confirmation. If the operator did not confirm, no receipt is minted and nothing is accepted.

Fail-safe
---------
Every branch defaults to refuse + write nothing that could authorize a live write. The receipt
is written atomically (temp file + os.replace) so a crash never leaves a half-written trust
artifact. The ceremony re-validates EVERYTHING this helper passes (it trusts nothing here) — the
proof, the receipt bindings, the hash-bound risk canon, the phase, the proof↔capability binding.
This helper is a convenience + honesty boundary, NOT a second authority.

Enforcement ceiling (deliberate, disclosed): build-time + operator-as-approver, NOT a runtime or
OS-level guarantee — identical to the ceremony it drives.

Emission: this runs at OPERATOR-SIDE acceptance time (next-phase Step 6, in the operator's
project), so it must be emitted into operator systems. B2-T9 must add it to
``_EXTERNAL_WRITE_LIB_FILES`` + the foundation bundle alongside ``acceptance_ceremony.py`` and
``capability_registration.py`` (NOT wired here — CANONICAL-ONLY).

Stdlib only — no third-party dependencies.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# sys.path bootstrap (mirrors acceptance_ceremony.py / capability_registration.py): make the
# package parent importable when run as a direct script from the project root, so the sibling
# ``external_write.*`` imports resolve.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.acceptance_ceremony import (
    accept_capability_for_live_use,
    AcceptanceResult,
    OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA,
)
from external_write.adapter_registry import get_adapter, get_dispatch
from external_write.contracts import get_contract
from external_write.effects_manifest import unresolvable_adapter_seal_gap
from external_write.proof_hash import (
    compute_contract_hash,
    compute_implementation_hash,
    ProofHashError,
)

# Task 7 (A4 / F-37, v0.13.0 Slice 2): importing this ONE module fires every
# shipped AND every capability-added adapter module's module-scope
# `register_adapter`/`register_contract` call -- see registered_adapters.py's
# own docstring for the full "why". This MUST be a top-of-module import (it
# runs once, before any function in this module executes), so BOTH the
# `__main__` CLI wrapper below AND `record_operator_acceptance` (the runner
# every other caller of this module actually goes through) get the fix
# regardless of which one is invoked -- the turnkey acceptance CLI never
# needs its own knowledge of which adapter module a given op_kind lives in.
import external_write.registered_adapters  # noqa: E402,F401

# Default on-disk home for the minted receipt (project-root-relative; disk-first + audit).
DEFAULT_RECEIPT_DIR = "security/acceptance_receipts"

# Duplicated from wizard/scripts/lib/upgrade_reconcile.MIGRATION_QUEUE_REL (D-B1-a boundary:
# this module lives in the operator-emitted external_write package and must not import the
# build-side tree -- same duplication discipline as BASE_DESCRIPTOR_ID_PREFIX and
# REGISTERED_ENTRY_KEYS, pinned equal to their build-side originals by cross-tree tests).
PENDING_MIGRATIONS_REL = "agents/handoffs/pending_migrations.json"


@dataclass(frozen=True)
class OperatorAcceptanceResult:
    """Outcome of the operator-acceptance step.

    accepted:      True IFF the receipt was minted AND the ceremony flipped the descriptor.
    reason:        On refusal, a specific human-readable reason (None on success).
    receipt_ref:   Path of the minted receipt (None if minting itself refused before writing).
    acceptance:    The underlying AcceptanceResult from the ceremony (None if the helper refused
                   before invoking it — e.g. an empty operator confirmation).
    """
    accepted: bool
    reason: Optional[str] = None
    receipt_ref: Optional[str] = None
    acceptance: Optional[AcceptanceResult] = None


def _refuse(reason: str, receipt_ref: Optional[str] = None,
            acceptance: Optional[AcceptanceResult] = None) -> OperatorAcceptanceResult:
    return OperatorAcceptanceResult(accepted=False, reason=reason,
                                    receipt_ref=receipt_ref, acceptance=acceptance)


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json_for_precheck(path: str) -> Optional[dict]:
    """Fail-safe JSON load for the BI-2 pre-check below: returns None on a
    missing / unreadable / malformed / non-dict file. A narrow local copy of
    acceptance_ceremony._load_json_file's fail-safe shape (that helper is
    module-private there) -- deliberately not imported from the ceremony, so
    this module's pre-check does not couple to the ceremony's internals; the
    ceremony re-reads and re-validates the same proof independently regardless
    (it trusts nothing this helper computed -- see the module docstring)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _atomic_write_text(path: str, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file in the same dir + os.replace)."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".acceptance_receipt.", suffix=".tmp", dir=directory)
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


def close_pending_migration_if_matched(
    capability_id: str,
    pending_migrations_path: Optional[str] = None,
) -> bool:
    """Best-effort cleanup (Task 10 — external-write-gate-generalization; carries the T9
    CARRY item forward): if `capability_id` matches a pending migration's `mechanism_id`,
    remove that entry from the queue so it stops being surfaced as still-pending.

    The matching convention (documented to the operator via add-capability.md Step A/E): when
    a capability is designed to migrate a mechanism that upgrade-reconcile (Task 9) safe-paused,
    it is given the SAME id as the paused mechanism's `mechanism_id`. That is what lets this
    closure match automatically — no new field, no schema change to the pinned descriptor-entry
    shape (`capability_registration.REGISTERED_ENTRY_KEYS`).

    Deliberately fail-soft: this runs AFTER the ceremony has already flipped the descriptor (the
    trust-critical write is already done by the time this is called) — it is bookkeeping
    tidy-up on a best-effort queue file, never a second authority. A missing file, malformed
    JSON, a non-list body, or simply no matching entry are all silent no-ops (return False);
    nothing here ever raises or blocks the caller's already-completed acceptance.
    """
    path = pending_migrations_path or PENDING_MIGRATIONS_REL
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        return False
    if not isinstance(entries, list):
        return False
    remaining = [
        e for e in entries
        if not (isinstance(e, dict) and e.get("mechanism_id") == capability_id)
    ]
    if len(remaining) == len(entries):
        return False  # nothing matched -- not a migrated mechanism, or already closed.
    try:
        _atomic_write_text(path, json.dumps(remaining, indent=2, ensure_ascii=False) + "\n")
    except Exception:
        return False
    return True


def record_operator_acceptance(
    capability_id: str,
    phase_id: str,
    copy_run_proof_ref: str,
    operator_confirmation: str,
    *,
    receipt_path: Optional[str] = None,
    descriptor_set_path: Optional[str] = None,
    lib_dir: Optional[Path] = None,
    audit_log_path: Optional[str] = None,
    accepted_at: Optional[str] = None,
    pending_migrations_path: Optional[str] = None,
) -> OperatorAcceptanceResult:
    """Mint the operator-acceptance receipt from the operator's VERBATIM confirmation and drive
    the acceptance ceremony. Fail-safe: on any missing / empty / ambiguous input, refuse and
    write nothing that could authorize a live write.

    Parameters
    ----------
    capability_id:         The target descriptor id being accepted.
    phase_id:              The accepted phase id (must match the descriptor's owning phase).
    copy_run_proof_ref:    Path to the capability's validated ``copy_run_proof-v1`` artifact
                           (produced by the supervised copy-run in Step 5).
    operator_confirmation: The operator's VERBATIM confirmation text. Captured honestly; an
                           empty / whitespace-only value refuses (never fabricated or defaulted).
    receipt_path:          Where to write the minted receipt (default:
                           ``security/acceptance_receipts/<capability_id>.receipt.json``).
    descriptor_set_path:   Forwarded to the ceremony (default write_gate.DESCRIPTOR_SET_PATH).
    lib_dir:               Forwarded to the ceremony (hash recomputation dir).
    audit_log_path:        Forwarded to the ceremony (acceptance-record log).
    accepted_at:           ISO-8601 UTC timestamp for the receipt (default: now).
    pending_migrations_path: Forwarded to close_pending_migration_if_matched on success
                           (default: PENDING_MIGRATIONS_REL). Best-effort only — see that
                           function's docstring.
    """
    if not (isinstance(capability_id, str) and capability_id.strip()):
        return _refuse("no target capability_id supplied")
    capability_id = capability_id.strip()
    if not (isinstance(phase_id, str) and phase_id.strip()):
        return _refuse("no accepted phase_id supplied")
    phase_id = phase_id.strip()
    if not (isinstance(copy_run_proof_ref, str) and copy_run_proof_ref.strip()):
        return _refuse("no copy_run_proof reference supplied")
    copy_run_proof_ref = copy_run_proof_ref.strip()

    # Honest capture: the operator's yes is never fabricated. An empty confirmation is not an
    # acceptance — refuse before minting anything.
    if not (isinstance(operator_confirmation, str) and operator_confirmation.strip()):
        return _refuse(
            "operator confirmation is empty — the operator has not confirmed acceptance; "
            "nothing is minted and nothing is accepted")

    # --- BI-2 (Task 7 / F-37) pre-check: resolve the proof's declared op_kind's
    # contract + (if adapter-backed) dispatch, and confirm the trust-hash canon
    # actually computes, BEFORE anything is written. `external_write.
    # registered_adapters` (imported at this module's top) has already fired
    # every shipped and capability-added adapter module's registration by the
    # time this function runs, so an op_kind that still fails to resolve here
    # is a REAL build-time gap (an adapter module that was never added to
    # registered_adapters.py) -- never a traceback, always a plain,
    # resumable refusal that names the missing piece and the one fix step.
    # Refusing here means the receipt mint below never runs on this path, so
    # a refusal never leaves a stale receipt behind (the deferred
    # "receipt-left-on-refuse" minor this task also closes).
    proof_for_precheck = _load_json_for_precheck(copy_run_proof_ref)
    if proof_for_precheck is None:
        return _refuse(
            f"could not read the copy_run_proof at {copy_run_proof_ref!r} as JSON -- "
            "fix step: confirm the path is correct and the file holds one valid "
            "copy_run_proof-v1 JSON object; nothing was written")
    proof_op_kind = proof_for_precheck.get("op_kind")
    if not (isinstance(proof_op_kind, str) and proof_op_kind.strip()):
        return _refuse(
            "the copy_run_proof carries no op_kind -- fix step: re-run the "
            "supervised copy-run so it records the operation kind being proved; "
            "nothing was written")
    contract = get_contract(proof_op_kind)
    if contract is None:
        return _refuse(
            f"operation kind {proof_op_kind!r} has no registered contract -- fix "
            "step: add this capability's adapter module to "
            "agents/lib/external_write/registered_adapters.py (the add-capability "
            "build cascade does this for you via "
            "wizard/scripts/lib/capability_code_scaffold.py) so it registers at "
            "import time, then re-run this command; nothing was written")
    adapter = get_adapter(proof_op_kind)
    if adapter is not None and get_dispatch(proof_op_kind) is None:
        return _refuse(
            f"operation kind {proof_op_kind!r} has a registered adapter but no "
            "captured dispatch record -- fix step: re-import "
            "agents/lib/external_write/registered_adapters.py cleanly and retry "
            "(this indicates a partial adapter registration); nothing was written")
    seal_gap = unresolvable_adapter_seal_gap(proof_op_kind)
    if seal_gap is not None:
        return _refuse(f"{seal_gap}; nothing was written")
    try:
        compute_contract_hash(proof_op_kind)
        compute_implementation_hash(proof_op_kind)
    except ProofHashError as e:
        return _refuse(
            f"could not compute the trust hashes for operation kind "
            f"{proof_op_kind!r} -- fix step: {e}; nothing was written")

    if receipt_path is None:
        # A per-capability receipt filename; deterministic so a re-run overwrites its own prior
        # receipt rather than accumulating stale ones.
        safe_id = capability_id.replace("/", "_").replace(os.sep, "_")
        receipt_path = os.path.join(DEFAULT_RECEIPT_DIR, f"{safe_id}.receipt.json")

    receipt = {
        "schema": OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA,
        "capability_id": capability_id,
        "phase_id": phase_id,
        "copy_run_proof_ref": copy_run_proof_ref,
        "operator_confirmation": operator_confirmation,
        "accepted_at": accepted_at if accepted_at else _now_iso_z(),
    }
    try:
        _atomic_write_text(receipt_path, json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    except Exception as e:
        return _refuse(f"could not write the operator-acceptance receipt; nothing accepted: {e}")

    # Drive the ceremony — the sole writer of accepted:true. It re-validates everything (it
    # trusts nothing this helper passed).
    acceptance = accept_capability_for_live_use(
        capability_id, phase_id, copy_run_proof_ref, receipt_path,
        descriptor_set_path=descriptor_set_path, lib_dir=lib_dir,
        audit_log_path=audit_log_path)

    if not acceptance.accepted:
        return OperatorAcceptanceResult(
            accepted=False, reason=acceptance.reason, receipt_ref=receipt_path,
            acceptance=acceptance)

    # Task 10 carry-forward from Task 9: a capability that migrates a paused mechanism
    # closes that mechanism's pending-migration entry the moment it is actually accepted —
    # best-effort, never blocks the acceptance that already happened above.
    close_pending_migration_if_matched(capability_id, pending_migrations_path)

    return OperatorAcceptanceResult(
        accepted=True, reason=None, receipt_ref=receipt_path, acceptance=acceptance)


# ---------------------------------------------------------------------------
# CLI wrapper — the next-phase skill invokes this once the operator has confirmed. The verbatim
# confirmation is passed as an argument (captured from what the operator actually typed). Run
# from the operator project root so default paths resolve. Exits 0 on acceptance, 1 on refusal,
# 2 on usage.
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _args = _sys.argv[1:]
    _opts = {
        "--capability-id": None, "--phase-id": None, "--copy-run-proof": None,
        "--operator-confirmation": None, "--receipt-out": None,
        "--descriptor-set": None, "--audit-log": None,
    }
    _usage = ("Usage: operator_acceptance.py --capability-id <id> --phase-id <id> "
              "--copy-run-proof <path> --operator-confirmation <verbatim text> "
              "[--receipt-out <path>] [--descriptor-set <path>] [--audit-log <path>]")
    _i = 0
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

    for _req in ("--capability-id", "--phase-id", "--copy-run-proof", "--operator-confirmation"):
        if _opts[_req] is None:
            print(f"missing required {_req}\n{_usage}", file=_sys.stderr)
            _sys.exit(2)

    _res = record_operator_acceptance(
        _opts["--capability-id"], _opts["--phase-id"], _opts["--copy-run-proof"],
        _opts["--operator-confirmation"],
        receipt_path=_opts["--receipt-out"],
        descriptor_set_path=_opts["--descriptor-set"],
        audit_log_path=_opts["--audit-log"])
    if _res.accepted:
        print(f"ACCEPTED: capability {_res.acceptance.capability_id!r} is now live-authorized "
              f"for phase {_res.acceptance.phase_id!r}. Receipt: {_res.receipt_ref}")
        _sys.exit(0)
    else:
        print(f"REFUSED: {_res.reason}", file=_sys.stderr)
        _sys.exit(1)
