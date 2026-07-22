"""Honest bulk-run outcome narration (Task E3, Cut 1.1 Cluster E / F-85).

Why this exists
----------------
During the estate dogfood run, the operator-facing narration of a bulk run's
outcome ("Applied" / "493 recoverable") was HAND-AUTHORED prose, never
derived from a typed result. That is the un-enforced
``feedback_typed_status_below_llm_for_honest_reporting`` discipline: a
partial or failed run can be verbalized as a clean success whenever the
sentence describing it is composed freehand rather than rendered from a
structured status. This module closes that hole for every bulk-run outcome
report: it takes the typed ``run_envelope.BulkRunSummary`` that
``run_sanctioned_bulk`` (D6a) already returns and renders the ONLY
plain-language operator text this project produces for it -- never a
second, hand-authored sentence beside it.

Structurally impossible to over-claim
--------------------------------------
``render_bulk_run_outcome`` takes exactly one argument -- the typed summary
-- and nothing else. There is no ``status=``/``claim=``/``force_success=``
parameter a caller could pass to override the rendered verb: the headline
verb (COMPLETED / PARTIAL / REFUSED) is derived SOLELY from
``classify_bulk_run_status``, itself a pure function of the summary's own
typed fields (``completed``, ``finalized``, ``refused``, and the durable
recoverability counts already attached to it -- never a caller-supplied
claim). A ``partial`` or ``refused`` classification can never render the
COMPLETED branch's "done"/"applied" success wording -- see
``test_run_narration.py``'s matrix test, which exercises every reachable
combination of those typed fields and asserts the rendered headline always
agrees with ``classify_bulk_run_status``.

Two sources, kept honestly separate (mirrors ``bulk_verify.py``'s own
"Two sources" convention)
-------------------------------------------------------------------------
1. **Completion shape** -- ``summary.completed`` / ``summary.finalized`` /
   ``summary.refused`` / ``summary.applied_unit_ids`` /
   ``summary.skipped_already_applied`` -- ``run_sanctioned_bulk``'s own
   record of what THIS call did.
2. **Recoverability** -- derived from ``summary.recoverability["per_id"]``,
   the SAME ``run_envelope.report_run_recoverability`` (D5) claims every
   other consumer of a run reads, but queried at the SAME SCOPE
   ``audit_projection.project_redacted_audit`` uses: exactly the ids this
   run has APPLIED (``summary.applied_unit_ids`` union
   ``summary.skipped_already_applied`` -- see ``_applied_ids`` below),
   never the wider reviewed-union-applied set ``report_run_recoverability``
   defaults to when queried with no candidate ids. This module previously
   read the wider, unscoped ``summary.recoverability["counts"]`` directly,
   which folded never-applied-but-reviewed ids in as "not recoverable" --
   conflating "we didn't finish" (a COMPLETENESS fact, already reported
   honestly by ``classify_bulk_run_status``'s PARTIAL branch) with "what we
   did apply cannot be undone" (a RECOVERABILITY fact). Scoping to applied
   ids fixes that conflation and makes this module's claim COHERENT with
   ``audit_projection``'s own applied-scoped claim for the same run: same
   scope, same underlying per-id claims, same classifier
   (``audit_projection._claim_level``, imported here rather than
   duplicated -- mirrors ``consent_narration.py``'s own precedent of
   importing a sibling module's private helper rather than re-deriving it).
   Still zero I/O: every claim consulted here is already attached to the
   in-memory summary by ``report_run_recoverability``'s own default
   (reviewed-union-applied) query, which always includes every applied id
   -- this module only narrows WHICH of those already-attached claims it
   reads, it never issues a fresh query.

Op-kind-agnostic / shape-neutral: this module's own text (docstrings,
rendered lines) never names a vendor, an op_kind, or a concrete field
("Gmail", "TRASH", "message") -- the rendered narration speaks only in
counts and the run's own id, exactly like ``bulk_verify.py``'s
``_build_operator_message``.

READ-ONLY, by construction
----------------------------
This module reads only the fields already present on an in-memory
``BulkRunSummary`` / its attached recoverability dict. It performs no I/O,
imports no adapter/registry/client module, and never calls
``run_enveloped_operation`` / ``run_sanctioned_bulk`` itself. See
``test_run_narration.py``'s scanner-clean test for the deterministic proof.

Stdlib only -- no third-party dependencies. Ships into the operator's own
runtime, ``agents/lib/external_write/``, alongside every other module in
this package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

# sys.path bootstrap: mirrors every sibling module's own convention
# (bulk_verify.py, audit_projection.py, run_envelope.py, ...) so the
# ``external_write.*`` imports below resolve whether this module is
# imported as part of the package or run/loaded standalone.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.audit_projection import _claim_level  # noqa: E402
from external_write.run_envelope import RECOVERABLE_BY_SYSTEM  # noqa: E402

# The three-way bulk-run outcome vocabulary this module renders. Deliberately
# distinct from run_envelope's RUN_STATE_* vocabulary (pending_run/executing/
# finalized, a durable STORAGE state) -- these three describe what THIS CALL
# accomplished against that state, from the operator's point of view.
BULK_RUN_COMPLETED = "completed"
BULK_RUN_PARTIAL = "partial"
BULK_RUN_REFUSED = "refused"


def _recoverability_counts(summary: Any) -> Dict[str, int]:
    rec = getattr(summary, "recoverability", None)
    counts = rec.get("counts") if isinstance(rec, dict) else None
    return counts if isinstance(counts, dict) else {}


def _applied_ids(summary: Any) -> Any:
    """The full set of ids APPLIED for this run as of ``summary`` -- this
    call's own ``applied_unit_ids`` UNION any earlier attempt's
    ``skipped_already_applied`` (the durable running total to date across
    every tranche this run has persisted). This is the SAME scope
    ``audit_projection.project_redacted_audit`` uses for its own
    ``applied_ids`` (there: the union of every persisted tranche's
    ``applied_unit_ids`` read fresh from disk) -- coherent with it by
    construction, never independently re-derived from a different source."""
    ids = set(getattr(summary, "applied_unit_ids", ()) or ())
    ids |= set(getattr(summary, "skipped_already_applied", ()) or ())
    return tuple(sorted(ids))


def _applied_scoped_recoverability_counts(summary: Any) -> Dict[str, int]:
    """Recoverable / not-recoverable counts scoped to exactly the APPLIED
    ids (``_applied_ids``, above) -- never the wider reviewed-union-applied
    set ``summary.recoverability["counts"]`` reports. Reads ONLY the
    ``per_id`` claims ``report_run_recoverability`` already attached to
    ``summary.recoverability`` -- no extra query, no I/O. An applied id
    that (for whatever reason) has no claim attached is treated fail-safe
    as NOT recoverable, never assumed recoverable."""
    rec = getattr(summary, "recoverability", None)
    per_id = rec.get("per_id") if isinstance(rec, dict) else None
    per_id = per_id if isinstance(per_id, dict) else {}
    applied = _applied_ids(summary)
    recoverable = sum(1 for uid in applied if per_id.get(uid) == RECOVERABLE_BY_SYSTEM)
    return {
        "recoverable_by_system": recoverable,
        "not_recoverable_by_system": len(applied) - recoverable,
    }


def classify_bulk_run_status(summary: Any) -> str:
    """Classify ``summary`` (a ``run_envelope.BulkRunSummary``) into exactly
    one of ``BULK_RUN_COMPLETED`` / ``BULK_RUN_PARTIAL`` / ``BULK_RUN_REFUSED``
    -- a PURE function of the summary's own typed fields, never a
    caller-supplied claim:

    - ``BULK_RUN_COMPLETED`` iff ``summary.completed`` AND
      ``summary.finalized`` AND NOT ``summary.refused`` -- every planned id
      applied and the run reached a finalized, spent-consent state (this is
      exactly what ``run_sanctioned_bulk``'s own docstring promises
      ``completed`` means).
    - ``BULK_RUN_REFUSED`` iff the run never went live at all -- nothing was
      ever applied, in this call OR any earlier one (checked via the
      DURABLE recoverability counts' ``applied_total``, not just this
      call's own tuples, so a resume attempt that refuses immediately still
      correctly reports PARTIAL if an earlier attempt already applied
      something).
    - ``BULK_RUN_PARTIAL`` -- everything else: some progress exists (this
      call or an earlier one) but the run is not a clean completion --
      a chunk was refused mid-run, an earlier attempt applied some units
      and this one is resuming or re-refusing, or ``finalize_run`` itself
      did not reach a finalized state.
    """
    completed = bool(getattr(summary, "completed", False))
    finalized = bool(getattr(summary, "finalized", False))
    refused = bool(getattr(summary, "refused", False))
    if completed and finalized and not refused:
        return BULK_RUN_COMPLETED

    counts = _recoverability_counts(summary)
    applied_total = counts.get("applied_total", 0) or 0
    applied_this_call = tuple(getattr(summary, "applied_unit_ids", ()) or ())
    already_applied = tuple(getattr(summary, "skipped_already_applied", ()) or ())
    ever_applied = applied_total > 0 or bool(applied_this_call) or bool(already_applied)
    return BULK_RUN_PARTIAL if ever_applied else BULK_RUN_REFUSED


def render_bulk_run_outcome(summary: Any) -> str:
    """Render the ONE honest, plain-language operator-facing report of what
    ``summary`` (a ``run_envelope.BulkRunSummary``) says happened. This is
    the ONLY function in this project that turns a bulk-run outcome into
    operator-facing prose -- a caller must not hand-author its own
    "Applied N" / "Done" sentence beside this.

    Takes exactly ONE argument -- the typed summary -- so there is no
    parameter through which a caller could override the rendered verb; the
    headline (COMPLETED / PARTIAL / REFUSED) is derived solely from
    ``classify_bulk_run_status``, and recoverability is asserted ONLY from
    the per-id claims ``summary.recoverability`` (the durable D5 report)
    already carries, scoped to exactly the ids this run has APPLIED (see
    ``_applied_scoped_recoverability_counts``) -- never invented here, and
    never widened to a never-applied-but-reviewed id. This keeps the
    rendered "Overall recoverability" claim COHERENT with
    ``audit_projection.project_redacted_audit``'s own ``claim_level`` for
    the same run: completeness ("this run has NOT finished" / the applied
    vs. reviewed counts in the headline sentence below) and recoverability
    ("can what WAS applied be undone") are reported as two separate, both
    honest, sentences -- never conflated into one claim.
    """
    status = classify_bulk_run_status(summary)
    counts = _applied_scoped_recoverability_counts(summary)
    recoverable = counts["recoverable_by_system"]
    not_recoverable = counts["not_recoverable_by_system"]
    claim = _claim_level(recoverable, not_recoverable)

    applied_this_call = len(tuple(getattr(summary, "applied_unit_ids", ()) or ()))
    already_applied = len(tuple(getattr(summary, "skipped_already_applied", ()) or ()))
    reason = getattr(summary, "refusal_reason", None)

    lines = [f"Run {summary.run_id!r}:"]

    if status == BULK_RUN_COMPLETED:
        detail = f"{applied_this_call} item(s) applied this call"
        if already_applied:
            detail += f" ({already_applied} were already applied from an earlier attempt)"
        lines.append(
            "COMPLETED -- every planned item went through and the run is "
            f"finalized. {detail}.")
    elif status == BULK_RUN_PARTIAL:
        detail = f"{applied_this_call} item(s) applied this call"
        if already_applied:
            detail += f", {already_applied} already applied from an earlier attempt"
        tail = f" -- reason given: {reason}" if reason else ""
        lines.append(
            "PARTIAL -- this run has NOT finished. "
            f"{detail}. It did not reach a finalized state{tail}.")
    else:
        tail = f" Reason given: {reason}" if reason else ""
        lines.append(
            "REFUSED -- this run never went live. Nothing was applied."
            f"{tail}")

    lines.append(
        f"Recoverable by this system: {recoverable}. "
        f"NOT recoverable by this system: {not_recoverable}.")
    lines.append(f"Overall recoverability: {claim}.")
    return "\n".join(lines)
