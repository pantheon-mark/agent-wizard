"""Redacted, committable audit projection (Task E1, Cut 1.1 Cluster E / F-73).

Why this exists
----------------
The estate close gitignored ``security/run_envelopes/`` and
``security/invocation_ledgers/`` (a correct privacy rationale: a run's frozen
``reviewed_set``/``tranches`` carry the vendor's own raw per-item
identifiers -- message-ids, subjects, account-ids -- a third party's PII,
never committed). But durability-vs-privacy was conflated: because nothing
COMMITTABLE was ever produced FROM those records, the audit trail of ~493
live deletions lived ONLY in the local working tree -- destroyable by
``git clean``, with no durable record surviving a lost laptop, a wiped
checkout, or an operator who never pushes.

This module is the fix: ``project_redacted_audit`` reads a run's DURABLE
records (``run_envelope.load_run_envelope`` + ``run_envelope.
report_run_recoverability`` + the run-level consent receipt) and writes a
REDACTED projection -- counts, digests, and a single consent timestamp, never
a raw id/subject/account-identifier -- to a COMMITTABLE path
(``DEFAULT_AUDIT_PROJECTION_DIR``, NOT gitignored; contrast
``run_envelope.DEFAULT_ENVELOPE_DIR``, which IS gitignored and stays
local-only).

What is REDACTED (never appears in the projection)
----------------------------------------------------
The frozen ``reviewed_set``'s raw ``unit_id``\\ s (a vendor message-id / row
key / task GID), any ``intended_mutation`` / subject / body content, account
identifiers, and raw provider responses. Only COUNTS and AGGREGATE DIGESTS
over those values are emitted -- never a per-item hash. An aggregate digest
binds the whole set as one value (mirrors ``run_envelope.
compute_reviewed_set_digest``'s own convention); a per-item hash would be
linkable/useless (the same raw id hashed the same way is a stable
correlation handle across runs/systems) and is out of scope here -- there is
no stated per-item audit-matching requirement this cut needs to satisfy, so
counts + one aggregate digest suffice.

Consent source (load-bearing)
------------------------------
The projection's consent digest + timestamp come from the ONE run-level
``run_consent_receipt`` (``run_envelope.load_run_consent_receipt`` -- minted
once, at ``mint_run_envelope`` time, bound to ``approved_at``, the real
operator-utterance time; see Task D3 / F-80). This module never derives
consent from a per-chunk operation receipt (a bare integrity receipt with no
``operator_confirmation`` field) -- counting those as approvals is exactly
the F-80 audit-confusion this cluster fixes. One run means one consent in
this projection, always.

"mutation start/complete" and "counts-by-status" -- honest scope note
------------------------------------------------------------------------
Neither ``Tranche`` nor ``finalize_run`` records a wall-clock "mutation
started" / "mutation completed" timestamp anywhere in the landed D-layer
(only ``minted_at`` exists, the CEREMONY moment, deliberately distinct from
"the mutation ran"). Fabricating a start/complete pair from data that was
never durably recorded would repeat exactly the F-80 defect this cluster
exists to fix -- a fabricated timestamp standing in for a real one. This
projection reports ``run_state`` (``pending_run`` / ``executing`` /
``finalized``) instead: the honest, durably-recorded substitute -- it tells a
reviewer whether the mutation has not started, is mid-flight, or is done,
without inventing a clock reading nothing ever took. Likewise, the
"planned/attempted/succeeded/failed/skipped/unmanifested" status vocabulary
has no matching enum anywhere in the landed D-layer; ``counts_by_status``
below is ``run_envelope.report_run_recoverability``'s own real counts dict
(``reviewed``/``applied``/``recoverable_by_system``/etc.), used VERBATIM,
never recomputed or relabeled into an invented vocabulary.

Preservation note (local raw artifacts)
-----------------------------------------
The raw envelope/ledger/receipt this module reads stay exactly where
``run_envelope.py`` / ``write_gate.py`` put them -- ``security/
run_envelopes/``, ``security/invocation_ledgers/`` -- gitignored, local-only,
by design (privacy). They are NOT part of this project's git history, so they
are not protected by git's own history: a ``git clean -fdx``, a wiped
checkout, or a lost machine destroys them with nothing to restore from. Back
them up outside this project's git-clean blast path (a separate encrypted
volume, a password-managed archive, cold storage) if the full raw record is
needed beyond what this committed, redacted projection proves.

Op-kind-agnostic / shape-neutral: this module's own text (docstrings, field
names, log lines) never names a vendor or a concrete data field -- see
``_action_type`` / ``_external_system_class`` below, which classify
generically from the op_kind's own dotted shape / registered contract, never
from a hardcoded vendor mapping.

READ-ONLY, by construction: this module reads ``run_envelope``'s durable
records and writes exactly ONE new file (the projection itself). It never
imports ``adapter_registry``, never references ``run_operation`` /
``run_enveloped_operation``, never constructs or names a write-capable
credential. See ``test_external_write_audit_projection.py``'s scanner-clean
test for the deterministic proof.

Stdlib only -- no third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

# sys.path bootstrap: mirrors every sibling module's own convention (scan.py,
# run_envelope.py, bulk_verify.py, ...) so the ``external_write.*`` imports
# below resolve whether this module is imported as part of the package or
# run/loaded standalone.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.contracts import get_contract  # noqa: E402
from external_write.run_envelope import (  # noqa: E402
    NOT_RECOVERABLE_BY_SYSTEM,
    RECOVERABLE_BY_SYSTEM,
    load_run_consent_receipt,
    load_run_envelope,
    report_run_recoverability,
)

# Schema tag for the persisted redacted projection.
AUDIT_PROJECTION_SCHEMA = "redacted_audit_projection-v1"

# Committable home for the redacted projection -- deliberately DISTINCT from
# run_envelope.DEFAULT_ENVELOPE_DIR (gitignored, local-only raw records).
# Nothing in the emitted `.gitignore` matches this path today: the
# consent/runtime-artifact block there (templates/root/gitignore_template) is
# scoped to four EXACT raw-record paths, never a broad `/security/`
# catch-all -- see test_audit_projection_committable_path_is_not_gitignored
# for the proof this stays true.
DEFAULT_AUDIT_PROJECTION_DIR = "security/audit"

# The three-way final claim-level vocabulary. NOT_RECOVERABLE_BY_SYSTEM is
# reused verbatim from run_envelope (imported above) rather than redeclared --
# one vocabulary, not two independently-spelled copies of the same string.
RECOVERABLE_ALL = "recoverable_all"
RECOVERABLE_PARTIAL = "recoverable_partial"


def _safe_run_id(run_id: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in run_id)


def _projection_path(run_id: str, audit_dir: Optional[str]) -> str:
    directory = audit_dir if audit_dir else DEFAULT_AUDIT_PROJECTION_DIR
    return os.path.join(directory, f"{_safe_run_id(run_id)}.redacted_audit.json")


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".audit_projection.", suffix=".tmp", dir=directory)
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


def _digest_over(value: Any) -> str:
    """A single aggregate SHA-256 digest over ``value`` (sorted-key,
    deterministic JSON canonicalization) -- the SAME pattern
    ``run_envelope.compute_reviewed_set_digest`` already uses for the frozen
    reviewed set. Used here for both the consent-receipt digest and the
    recovery-manifest digest -- one digest per WHOLE set, never per item."""
    canon = json.dumps(value, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _action_type(op_kind: str) -> str:
    """A generic action-verb label derived from op_kind's OWN dotted shape --
    never a hardcoded vendor mapping. A dotted, verb-shaped op_kind (the
    "surface.object.verb" convention ``contracts.py``'s reference adapter
    documents, e.g. "gmail.message.trash") contributes its LAST segment
    (e.g. "trash"); a non-dotted op_kind (the legacy field-write shape, e.g.
    "set_status") contributes itself verbatim. Pure string shape -- no
    per-vendor knowledge lives in this function."""
    if not isinstance(op_kind, str) or not op_kind:
        return ""
    return op_kind.rsplit(".", 1)[-1]


def _external_system_class(op_kind: str) -> str:
    """A generic, non-identifying label for WHAT KIND of external state this
    op_kind mutates -- derived from op_kind's own registered contract's
    declared ``writes`` field names (e.g. "labels", "Status", "__record__"),
    never a vendor name and never an account id/address. Empty when op_kind
    has no registered contract or declares no ``writes``."""
    contract = get_contract(op_kind)
    if contract is None or not contract.writes:
        return ""
    return "+".join(contract.writes)


def _claim_level(recoverable: int, not_recoverable: int) -> str:
    """The three-way final claim: RECOVERABLE_ALL / RECOVERABLE_PARTIAL /
    NOT_RECOVERABLE_BY_SYSTEM, derived from counts already produced by
    ``report_run_recoverability`` (never recomputed here -- this is pure
    three-way classification of two integers already computed elsewhere).
    Zero applied units (both counts zero) is classified
    NOT_RECOVERABLE_BY_SYSTEM: fail-safe -- never fabricate a recoverable
    claim over a run that mutated nothing."""
    total = recoverable + not_recoverable
    if total == 0:
        return NOT_RECOVERABLE_BY_SYSTEM
    if not_recoverable == 0:
        return RECOVERABLE_ALL
    if recoverable == 0:
        return NOT_RECOVERABLE_BY_SYSTEM
    return RECOVERABLE_PARTIAL


@dataclass(frozen=True)
class AuditProjectionResult:
    """The outcome of ``project_redacted_audit``: the COMMITTABLE path the
    projection was written to, and the projection dict itself (identical to
    what was serialized to that path)."""

    path: str
    projection: Dict[str, Any]


def project_redacted_audit(
    run_id: str,
    *,
    envelope_dir: Optional[str] = None,
    audit_dir: Optional[str] = None,
    system_version: str = "",
    bundle_version: str = "",
    git_version: str = "",
    parent_run_id: Optional[str] = None,
) -> AuditProjectionResult:
    """Project a REDACTED, committable audit record for ``run_id`` from D's
    durable records, and write it to ``audit_dir`` (default
    ``DEFAULT_AUDIT_PROJECTION_DIR`` -- committable, NOT gitignored).

    Every value in the returned/written projection is a count, a digest, an
    ISO-8601 timestamp, or a generic classification string -- see the module
    docstring's "What is REDACTED" section for exactly what never appears.
    ``system_version`` / ``bundle_version`` / ``git_version`` /
    ``parent_run_id`` are the CALLER's own responsibility to resolve (this
    common-layer, op-kind-agnostic module has no business locating the
    operator project's own manifest/version files) and are passed through
    verbatim -- pass "" / None for anything the caller does not have.

    Recoverability counts + the claim level are read from a SINGLE call to
    ``report_run_recoverability`` (D5, F-81's fix), scoped to exactly the
    ids this run actually APPLIED (never recomputed, never a mix of
    reviewed-but-unapplied ids diluting the claim about what was mutated).

    Never raises on an absent/malformed run: an absent envelope reports the
    fail-closed empty shape (zero counts, no consent,
    ``not_recoverable_by_system``) rather than crashing the caller --
    mirrors ``run_envelope``'s own fail-closed convention throughout.
    """
    env = load_run_envelope(run_id, envelope_dir=envelope_dir)

    applied_ids = sorted({
        uid for t in env.tranches for uid in t.applied_unit_ids
    })

    report = report_run_recoverability(
        run_id, candidate_unit_ids=applied_ids, envelope_dir=envelope_dir)
    counts = report["counts"]

    recoverable_ids = sorted(
        uid for uid, claim in report["per_id"].items()
        if claim == RECOVERABLE_BY_SYSTEM)

    receipt = load_run_consent_receipt(run_id, receipt_dir=envelope_dir)
    consent_receipt_digest = _digest_over(receipt) if isinstance(receipt, dict) else ""
    consent_timestamp = receipt.get("approved_at", "") if isinstance(receipt, dict) else ""

    projection: Dict[str, Any] = {
        "audit_schema_version": AUDIT_PROJECTION_SCHEMA,
        "system_version": system_version,
        "bundle_version": bundle_version,
        "git_version": git_version,
        "capability_id": env.capability_id,
        "op_kind": env.op_kind,
        "run_id": env.run_id,
        "parent_run_id": parent_run_id or "",
        "action_type": _action_type(env.op_kind),
        "external_system_class": _external_system_class(env.op_kind),
        "adapter_contract_version": env.contract_hash,
        "reviewed_set_count": len(env.reviewed_set),
        "reviewed_set_digest": env.reviewed_set_digest,
        "consent_receipt_digest": consent_receipt_digest,
        "consent_timestamp": consent_timestamp,
        "run_state": env.run_state,
        "counts_by_status": counts,
        "recovery_manifest_digest": _digest_over(recoverable_ids),
        "recovery_manifest_count": len(recoverable_ids),
        "claim_level": _claim_level(
            counts["recoverable_by_system"], counts["not_recoverable_by_system"]),
    }

    path = _projection_path(run_id, audit_dir)
    _atomic_write_json(path, projection)
    return AuditProjectionResult(path=path, projection=projection)
