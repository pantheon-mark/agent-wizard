"""Operator-invocable commands over the writer-state machinery -- the top layer.

It validates through the structural-state core and writes through the
acknowledgement store, and it is the only place those two meet for the purpose of
CHANGING something. That is what makes it the right home for an eligibility rule:
asking "what state is this writer in?" here costs nothing, because this layer
already depends on the core, whereas asking it from inside the store is what used
to close a two-way import cycle between the store and the state module.

Layering, in one line each:

    writer_state_core   structural state; imports no sibling.
    writer_ack_store    the records and the hash-validity rule; imports no sibling.
    _ext_write_state    the state SERVICE: structural state combined with the
                        recorded decisions, plus the reap and the advisory owner
                        derivation.
    writer_commands     this module. Validates via the core, writes via the store,
                        and deliberately does NOT depend on the service -- that
                        edge is the one whose absence keeps the graph a DAG.

Enforcement ceiling (disclosure): build-time + operator-as-approver, NOT a
runtime/OS sandbox -- the same ceiling every module in this package discloses. A
command here records an operator's decision; it does not make any writer safe.

Zoning note: listed in ``zones.SEALED_KERNEL_MODULE_PATHS`` because it imports
sibling kernel submodules, which is ordinary internal kernel wiring and is exactly
what that allowlist exists to declare. It imports no vendor SDK, constructs no
credential, names no adapter, and never calls ``run_operation``. Membership grants
NO capability the right to import it (that allowlist is the independent
``scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES`` set).

Stdlib only -- no third-party dependencies. The only non-stdlib imports are two
sibling modules of this same trusted package, both themselves stdlib-only; it never
imports across the build/runtime boundary.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# Spelled `import external_write.<submodule> as _x` rather than the
# `from external_write import <submodule>` form several older modules in this
# package use. Both mean the same thing to Python, but only this one is a form the
# sibling bypass scanner's sealed-kernel module-boundary rule actually matches — so
# this module's SEALED_KERNEL membership is load-bearing (remove the entry and the
# scan flags these two lines) rather than decorative. The counterfactual is
# asserted in test_external_write_writer_state_layers.py.
import external_write.writer_ack_store as _store
import external_write.writer_state_core as _core


# ---------------------------------------------------------------------------
# WHY THE ELIGIBILITY CHECK IS A STATE CHECK AND NOT A MEMBERSHIP CHECK.
#
# This command used to ask only "is there an OPEN entry for this file?". Every
# state is open, so that question admitted all of them -- and the state service,
# which tested the record ahead of everything else, then took the file out of the
# blocking set whatever state it was really in. So a decision recorded against a
# fully REBUILDABLE writer skipped its rebuild, with the operator's entirely
# genuine consent. No consent check could have caught that: the consent was real,
# and it was the QUESTION that was wrong.
#
# The rule now joins on the writer's CURRENT STRUCTURAL STATE, taken from the
# structural-state core (``writer_state_core``), which computes it from the queue
# entry and the file on disk and knows nothing about recorded decisions. That is
# what makes the check possible at all: asked from the store, the question would
# have to come back through the module already asking the store about decisions.
#
# The eligible set is declared ONCE, in the core, and the state service binds the
# SAME constant. Both sites are needed and neither substitutes for the other: this
# one stops a record being written for an ineligible writer, and the service's stops
# a record that arrived some other way from being honoured for one.
# ---------------------------------------------------------------------------

#: What to tell the operator about a writer that is not in a state this decision
#: applies to -- keyed on the state the core actually found, so the sentence names
#: the exit that state really has. Only the states ``structural_classification`` can
#: return are here; anything else falls to ``_UNRECOGNISED_STATE_REASON``, which
#: still REFUSES (an unrecognised state is the fail-closed direction, never a new
#: reason to allow).
_INELIGIBLE_STATE_REASONS = {
    _core.WriterState.BLOCKING_LIVE_ENABLE: (
        "the safety check has not established that `{relpath}` needs a person, and "
        "accepting the risk is only for a file our own tooling cannot fix -- rebuild "
        "it so it routes through the sanctioned bulk path and it clears on its own; "
        "if you believe it genuinely cannot be rebuilt, ask your assistant to go "
        "through what the safety check recorded for it with you"),
    _core.WriterState.NON_LIVE: (
        "`{relpath}` was found to be a test file that nothing in your running system "
        "uses, so it is not holding anything back and there is no risk to accept -- "
        "no action is needed for this one"),
}

#: A state the core produced that this command has no dedicated sentence for --
#: only reachable if a state is added to the vocabulary without this map being
#: updated. It refuses, and says who can tell the operator what to do about it, so
#: the refusal is never a dead end.
_UNRECOGNISED_STATE_REASON = (
    "`{relpath}` is not in a state where accepting the risk is the way forward -- "
    "ask your assistant to go through what the safety check recorded for it with you")


def _ineligible_reason(writer_relpath: str, states: Sequence[str]) -> str:
    """The operator-facing refusal for a writer whose state(s) are not ones a
    recorded decision applies to. Pure: it derives the whole sentence from the
    states it is handed.

    ``states`` is EVERY state found for this relpath, in queue order. More than one
    means the queue carries more than one open entry naming the file, and the
    ambiguity itself is part of what the operator is told -- a path-keyed decision
    cannot say which of them it accepted."""
    ineligible = sorted({s for s in states
                         if s not in _core.ACKNOWLEDGEABLE_WRITER_STATES})
    detail = "; ".join(
        _INELIGIBLE_STATE_REASONS.get(s, _UNRECOGNISED_STATE_REASON).format(
            relpath=writer_relpath)
        for s in ineligible)
    if len(states) > 1:
        return (
            f"nothing was recorded -- more than one open item names `{writer_relpath}` "
            "and they are not all in the one state this decision applies to, so it is "
            f"not clear what you would be accepting: {detail}")
    return f"nothing was recorded -- {detail}"


def acknowledge_writer(project_root: str,
                       writer_relpath: str,
                       *,
                       operator_confirmation: str,
                       acknowledged_at: Optional[str] = None) -> Dict[str, Any]:
    """Record the operator's accepted-risk decision for ONE unrepairable writer.

    Fails closed, with a plain-language reason, when:
      * the confirmation is blank/whitespace-only (no silent acknowledgement);
      * the confirmation contains a newline or carriage return (paste-safety --
        the same fail-closed rule the acceptance CLI applies, since a line-split
        paste can otherwise truncate what the operator "said");
      * the writer file is absent or unreadable (nothing to bind a hash to);
      * there is no OPEN bespoke-writer entry for this relpath (no orphan
        records, and no pre-acknowledging a file that is not flagged);
      * ANY open entry naming this relpath is in a structural state that a
        recorded decision is not the exit from (see
        ``_core.ACKNOWLEDGEABLE_WRITER_STATES``).

    The checks run in that order, and the first four are the order they have always
    run in: what the operator reads when their confirmation is unusable must not
    depend on whether the file happened to be flagged, or on what state it turned
    out to be in.

    The eligibility check evaluates EVERY open entry naming this relpath, not a
    de-duplicated set of paths. ``open_bespoke_writer_migrations`` guarantees no
    relpath uniqueness, and two entries naming one file can record different
    violations and so land in different states. A decision is keyed on the PATH, so
    it cannot say which entry it accepted: if ANY matching entry is ineligible the
    whole thing refuses. Fail-closed on the ambiguous case -- never a best match,
    never a first match.

    Propagates ``ExternalWriteStateReadError`` if the pending-migrations queue
    exists but cannot be read -- an unreadable queue must never present as "this
    file is not flagged" and quietly refuse for the wrong reason, nor as "it is
    flagged" and record against nothing.

    Enforcement ceiling (disclosure): build-time + operator-as-approver. A refusal
    here does not switch anything off at runtime, and a record does not switch
    anything on; what a recorded decision changes is that the entry stops holding
    back live-enable for the project.

    Returns the stored record. Idempotent per relpath: re-acknowledging replaces
    that writer's prior record rather than accumulating duplicates."""
    _store.validate_confirmation(operator_confirmation)
    content_sha256 = _store.require_writer_content_hash(project_root, writer_relpath)

    matching = [e for e in _core.open_bespoke_writer_migrations(project_root)
                if str(e.get("writer_relpath")) == writer_relpath]
    if not matching:
        raise _store.WriterAcknowledgementError(
            f"nothing was recorded -- `{writer_relpath}` is not currently flagged as "
            "needing attention, so there is nothing to accept")

    states: List[str] = [_core.structural_classification(project_root, e).state
                         for e in matching]
    if any(s not in _core.ACKNOWLEDGEABLE_WRITER_STATES for s in states):
        raise _store.WriterAcknowledgementError(
            _ineligible_reason(writer_relpath, states))

    return _store.put_acknowledgement_record(
        project_root, writer_relpath,
        content_sha256=content_sha256,
        operator_confirmation=operator_confirmation,
        acknowledged_at=acknowledged_at,
    )
