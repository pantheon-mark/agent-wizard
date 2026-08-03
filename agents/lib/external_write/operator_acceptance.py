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
from typing import Dict, Optional, Tuple

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
from external_write.capability_identity import (
    build_capability_index,
    CAPABILITIES_DIR_REL,
    CAPABILITY_FILE_SUFFIX,
    IdentityResolutionError,
)
from external_write.contracts import get_contract
from external_write.copy_run_proof import (
    COPY_RUN_PROOF_DIR, copy_run_proof_path,
)
from external_write.effects_manifest import unresolvable_adapter_seal_gap
from external_write._ext_write_state import (
    open_bespoke_writer_migrations,
    blocking_bespoke_writer_migrations,
    classify_bespoke_writer_entry,
    describe_blocking_entry,
    is_bypass_writer_entry,
    WriterState,
    ExternalWriteStateReadError,
)
from external_write.proof_hash import (
    compute_contract_hash,
    compute_implementation_hash,
    ProofHashError,
)
from external_write.write_gate import load_descriptor_set

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

# Default on-disk home for the copy-run proof (project-root-relative; V15-2 fix). The proof's
# location is deterministic from capability_id (the next-phase supervised-trial convention), so
# the operator-acceptance CLI can default the path instead of requiring it as a raw argument --
# collapsing the documented command toward a single paste-safe line without weakening the
# operator-authority requirement itself (the proof file at this path must still exist and
# validate; see the default block in record_operator_acceptance below).
#
# ALIAS, not a second spelling: the directory and the whole path-building rule now live in
# `copy_run_proof.py`, the module that owns the artifact's schema, so that the journaled trial
# executor that PRODUCES the proof and this consumer that READS it cannot drift apart. This name
# is kept because callers already import it.
DEFAULT_COPY_RUN_PROOF_DIR = COPY_RUN_PROOF_DIR

# Duplicated from wizard/scripts/lib/upgrade_reconcile.MIGRATION_QUEUE_REL (D-B1-a boundary:
# this module lives in the operator-emitted external_write package and must not import the
# build-side tree -- same duplication discipline as BASE_DESCRIPTOR_ID_PREFIX and
# REGISTERED_ENTRY_KEYS, pinned equal to their build-side originals by cross-tree tests).
PENDING_MIGRATIONS_REL = "agents/handoffs/pending_migrations.json"


@dataclass(frozen=True)
class MigrationCloseResult:
    """Outcome of ``close_pending_migration_if_matched`` (Task A3 / F-60 fix)
    — SURFACED (never a bare, silently-swallowed bit) so a caller on the
    acceptance path can see WHAT happened to the pending-migration queue,
    not just whether *something* closed.

    closed:            True iff at least one pending entry was removed this call.
    closed_raw_ids:    The raw ``mechanism_id`` values (as written in the queue file) of the
                       entries removed — empty when nothing closed.
    unresolved_note:   None when nothing noteworthy happened. Otherwise a plain-language note
                       (no traceback) describing an identity-resolution problem hit while
                       examining the queue — e.g. a raw id matched more than one capability
                       (ambiguous) and could not be attributed with confidence. This is surfaced
                       so a genuinely-unresolved or mismatched migration id is never a silent
                       no-op; it never blocks or undoes the acceptance itself (which has already
                       completed by the time this runs) — it is visibility into the bookkeeping
                       step only.
    """
    closed: bool
    closed_raw_ids: Tuple[str, ...] = ()
    unresolved_note: Optional[str] = None


@dataclass(frozen=True)
class OperatorAcceptanceResult:
    """Outcome of the operator-acceptance step.

    accepted:        True IFF the receipt was minted AND the ceremony flipped the descriptor.
    reason:          On refusal, a specific human-readable reason (None on success).
    receipt_ref:     Path of the minted receipt (None if minting itself refused before writing).
    acceptance:      The underlying AcceptanceResult from the ceremony (None if the helper
                     refused before invoking it — e.g. an empty operator confirmation).
    migration_close: The outcome of the best-effort pending-migration-queue cleanup
                     (``close_pending_migration_if_matched``), populated whenever the ceremony
                     itself succeeded (None if acceptance did not reach that point). SURFACED
                     here (Task A3 / F-60 fix) so a caller can see whether the queue cleanup
                     found and closed a matching entry, found nothing (normal), or hit an
                     identity-resolution problem it could not silently resolve — never just a
                     dropped return value.
    reconcile_note:  None on a clean, successful reconcile (the normal case) or when acceptance
                     did not reach that point. Otherwise a plain-language note (Task A1 / F-70
                     fix) describing why the post-acceptance ``lifecycle_state.reconcile_state``
                     call did not finish cleanly — surfaced rather than silently swallowed, but
                     NEVER a reason to treat the acceptance itself (already durably recorded by
                     this point) as failed.
    """
    accepted: bool
    reason: Optional[str] = None
    receipt_ref: Optional[str] = None
    acceptance: Optional[AcceptanceResult] = None
    migration_close: Optional[MigrationCloseResult] = None
    reconcile_note: Optional[str] = None


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


def _load_descriptor_entries(*, descriptor_set_path: Optional[str] = None,
                              project_root: Optional[str] = None) -> list:
    """Load the full descriptor set (Task 5 / V15-2 phase-id derivation), reusing
    ``write_gate.load_descriptor_set`` -- the SAME fail-safe loader the runtime gate and the
    ceremony both read through -- rather than hand-rolling a second JSON-read convention here.

    ``load_descriptor_set`` itself only resolves its path against the process cwd (the
    project-root-relative convention documented on ``write_gate.DESCRIPTOR_SET_PATH``); this
    helper additionally composes an explicit ``project_root`` (as ``resolve_pending_phase``'s
    tests pass, since the resolver is called in-process rather than via a subprocess run from
    the operator project root), mirroring how other helpers in this module (e.g.
    ``close_pending_migration_if_matched``) accept ``project_root`` for the identical reason.
    Fail-safe by construction (matches ``load_descriptor_set``): a missing/unreadable/malformed
    set is never distinguished from "no descriptors" here -- returns ``[]``."""
    from external_write.write_gate import DESCRIPTOR_SET_PATH
    rel_path = descriptor_set_path if descriptor_set_path else DESCRIPTOR_SET_PATH
    if not rel_path:
        return []
    root = project_root if project_root is not None else "."
    full_path = rel_path if os.path.isabs(rel_path) else os.path.join(root, rel_path)
    return load_descriptor_set(full_path)


def resolve_pending_phase(capability_id: str, *, descriptor_set_path: Optional[str] = None,
                          project_root: Optional[str] = None) -> Optional[str]:
    """Derive the ``phase_id`` for ``capability_id`` from its descriptor entry (Task 5 / V15-2):
    the CLI-facing convenience that lets the operator's paste-safe acceptance command drop
    ``--phase-id`` the same way V15-2 already dropped ``--copy-run-proof`` (both defaults are
    convenience over a deterministic, already-recorded value -- never a second authority; the
    acceptance ceremony re-validates the phase against the descriptor regardless of how it got
    here).

    Fail-closed on any ambiguity, by design (never guess a phase at a trust surface):
      * zero or MORE THAN ONE descriptor entry with ``id == capability_id`` -> ``None``
      * the single match is already ``accepted`` (truthy) -> ``None`` (nothing left pending to
        derive a phase FOR -- re-accepting an already-accepted capability is not this helper's
        job, and guessing its now-stale ``phase_id`` would be worse than refusing)
      * the single match's ``phase_id`` is missing / not a string / blank -> ``None``

    Fail-soft on the READ side only (mirrors ``close_pending_migration_if_matched``'s own
    read-side fail-soft convention): any load/parse error surfaces as ``None`` here, never a
    traceback -- the CLI turns a ``None`` into a clear, actionable operator-facing message
    (exit 2), it never silently proceeds with a guessed phase."""
    try:
        entries = _load_descriptor_entries(
            descriptor_set_path=descriptor_set_path, project_root=project_root)
    except Exception:
        return None
    matches = [e for e in entries if isinstance(e, dict) and e.get("id") == capability_id]
    if len(matches) != 1:
        return None
    entry = matches[0]
    if entry.get("accepted"):
        return None
    phase = entry.get("phase_id")
    return phase if isinstance(phase, str) and phase.strip() else None


@dataclass(frozen=True)
class PhaseDiagnosis:
    """(Task 4 / F-2) WHY ``resolve_pending_phase`` returned ``None`` for a given
    ``capability_id`` -- computed only when it has, so the CLI can give the operator a
    branch-specific, always-paste-safe next step instead of one generic "re-run with
    --phase-id" message (the exact wrapping-command hazard V15-2 already fixed for
    ``--copy-run-proof``/``--phase-id`` themselves, but that this fallback message was
    still re-introducing).

    kind:
      * ``"already_accepted"`` -- the exact given id has exactly one descriptor entry, and
        it is already accepted. Nothing pending to derive a phase for.
      * ``"identity_conflict"`` -- the exact given id has MORE THAN ONE descriptor entry.
        Every entry necessarily shares this id (that's the definition of "match"), so this
        is always a data-integrity same-id twin, never normal ambiguity -- see the module
        docstring. No accept command is ever produced for this case; healing happens at
        the source (upgrade-reconcile / capability registration), not by the operator.
      * ``"phase_id_missing"`` -- the exact given id has exactly one descriptor entry, it is
        NOT accepted (a real, still-pending entry), but its ``phase_id`` is missing or blank.
        This is NOT the same situation as ``"zero_match"`` -- an entry genuinely exists, it
        has a data-integrity problem, not a "nothing was found" problem -- so it gets its own
        label and its own accurate operator-facing message (never the "no pending descriptor
        entry was found" wording, which would be misleading here).
      * ``"zero_match"`` -- nothing at all was found for the given id, AND no OTHER
        capability in the descriptor set is genuinely pending either. A plain diagnostic;
        there is nothing to offer instead.
      * ``"multiple_pending"`` -- nothing matched the given id, but one or more OTHER,
        DISTINCT capabilities in the descriptor set ARE genuinely pending (unaccepted, with
        a usable ``phase_id``, and themselves free of a same-id conflict). ``candidates``
        names each one so the CLI can print a ready-to-paste command per capability,
        rather than a dead end.

        IMPORTANT (review finding on this task): ``_ready_accept_command`` (below) raises if
        ``operator_confirmation`` contains an embedded newline/carriage-return -- ``shlex.quote``
        does not strip one, so interpolating it would silently break the single-physical-line
        guarantee this whole mechanism exists to provide. A caller building a ready command from
        ``candidates`` MUST check ``operator_confirmation`` for a newline/carriage-return itself
        BEFORE calling ``_ready_accept_command`` and degrade to a plain diagnostic instead (see
        the CLI's ``multiple_pending`` branch below) -- the raise is a defense-in-depth backstop,
        not the primary guard.

    candidates: ``(capability_id, phase_id)`` pairs, populated only for ``"multiple_pending"``
                (empty otherwise). Deterministically ordered by capability_id.
    """
    kind: str
    candidates: Tuple[Tuple[str, str], ...] = ()


def diagnose_phase_resolution(capability_id: str, *, descriptor_set_path: Optional[str] = None,
                              project_root: Optional[str] = None) -> PhaseDiagnosis:
    """(Task 4 / F-2) Classify WHY ``resolve_pending_phase(capability_id, ...)`` returned
    ``None`` -- see ``PhaseDiagnosis`` for the branch meanings. Callers only invoke this
    AFTER ``resolve_pending_phase`` has already returned ``None`` for the same arguments;
    it re-reads the same descriptor set independently (this module's existing convention --
    every helper here reads its own fail-safe snapshot rather than threading state between
    calls) rather than being a second authority: it classifies, it never derives a phase
    itself, and it is never consulted by ``record_operator_acceptance``/the ceremony.

    Fail-soft on the READ side (mirrors ``resolve_pending_phase``'s own convention): any
    load/parse error is treated the same as an empty descriptor set (``"zero_match"``),
    never a traceback."""
    try:
        entries = _load_descriptor_entries(
            descriptor_set_path=descriptor_set_path, project_root=project_root)
    except Exception:
        entries = []

    matches = [e for e in entries if isinstance(e, dict) and e.get("id") == capability_id]
    if len(matches) > 1:
        return PhaseDiagnosis(kind="identity_conflict")
    if len(matches) == 1:
        if matches[0].get("accepted"):
            return PhaseDiagnosis(kind="already_accepted")
        # Exactly one match, not accepted -- resolve_pending_phase only returns None here
        # when phase_id itself is missing/blank. That is a real, existing entry with a data
        # problem, never a "nothing was found" situation -- give it its own distinct label
        # (review finding on this task) rather than folding it into "zero_match", which the
        # CLI renders as "no pending descriptor entry was found ... nothing to accept" --
        # misleading, since an entry DOES exist here.
        phase = matches[0].get("phase_id")
        if not (isinstance(phase, str) and phase.strip()):
            return PhaseDiagnosis(kind="phase_id_missing")
        # Defensive fallback only -- unreachable in practice, since a valid phase_id here
        # would have made resolve_pending_phase itself return non-None, so diagnose_phase_
        # resolution would never have been called for this id at all.
        return PhaseDiagnosis(kind="zero_match")

    # Zero matches for the EXACT given id. Rather than a dead end, look at what else is
    # genuinely pending across the whole descriptor set -- grouped by id so a same-id twin
    # for some OTHER capability is excluded from the offered candidates (never suggest an
    # accept command against a corrupted registry entry, even one the operator didn't ask
    # about).
    pending_by_id: Dict[str, list] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        eid = e.get("id")
        if not (isinstance(eid, str) and eid):
            continue
        if e.get("accepted") is True:
            continue
        phase = e.get("phase_id")
        if not (isinstance(phase, str) and phase.strip()):
            continue
        pending_by_id.setdefault(eid, []).append(phase)

    candidates = tuple(
        (eid, phases[0]) for eid, phases in sorted(pending_by_id.items()) if len(phases) == 1
    )
    if not candidates:
        return PhaseDiagnosis(kind="zero_match")
    return PhaseDiagnosis(kind="multiple_pending", candidates=candidates)


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


def _resolve_or_literal(index, raw: Optional[str]) -> Tuple[Optional[str], Optional[str], bool]:
    """Resolve ``raw`` to its canonical capability id via the identity index, falling back to
    the literal string itself when the index has nothing to say about it (e.g. a project with
    no scaffolded capability modules at all yet — the pre-A1 literal-match convention this
    function preserves for that case). Returns ``(canonical_or_literal, ambiguous_note,
    corroborated)``.

    ``corroborated`` is True IFF ``index.resolve`` actually succeeded against real evidence
    (an exact canonical id / module stem, or SURFACE corroboration) — never for a fallback to
    the bare literal string. A caller that needs to know whether a match is a REAL identity
    match, as opposed to two literal strings merely being equal by coincidence, checks this flag
    rather than just comparing the returned values (see ``close_pending_migration_if_matched``'s
    single-capability near-miss surfacing, coordinator review round 2).

    An UNRESOLVED lookup is a completely normal outcome (most raw ids in a queue simply do not
    correspond to the capability being examined) and falls back silently to the literal value —
    no note. An AMBIGUOUS lookup (the raw id corroborates two or more DIFFERENT capabilities) is
    a genuine identity problem that must not be silently guessed either way: it is surfaced via
    the returned note, and the canonical slot is left ``None`` so it can never spuriously equal
    anything (F-60 fix — the acceptance path must see this, not swallow it)."""
    if not (isinstance(raw, str) and raw):
        return None, None, False
    try:
        identity = index.resolve(raw, "unknown")
    except IdentityResolutionError as e:
        if e.kind == "ambiguous":
            return None, e.operator_message, False
        return raw, None, False  # unresolved -- normal; fall back to the literal id.
    return identity.canonical_id, None, True


def close_pending_migration_if_matched(
    capability_id: str,
    pending_migrations_path: Optional[str] = None,
    *,
    project_root: Optional[str] = None,
) -> MigrationCloseResult:
    """Best-effort cleanup (Task 10 — external-write-gate-generalization; carries the T9
    CARRY item forward; Task A3 / F-60 fix): if `capability_id` matches a pending migration's
    `mechanism_id`, remove that entry from the queue so it stops being surfaced as still-pending.

    The matching convention (documented to the operator via add-capability.md Step A/E): when
    a capability is designed to migrate a mechanism that upgrade-reconcile (Task 9) safe-paused,
    it is given the SAME id as the paused mechanism's `mechanism_id`. That is what lets this
    closure match automatically — no new field, no schema change to the pinned descriptor-entry
    shape (`capability_registration.REGISTERED_ENTRY_KEYS`).

    F-60 fix: matching is no longer a RAW string join. Both the pending entry's `mechanism_id`
    and the accepted `capability_id` are resolved to their CANONICAL capability id via
    `capability_identity.build_capability_index(project_root).resolve(raw, "unknown")` before
    being compared — so a capability whose identity is split across names (the estate case:
    accepted capability_id `inbox_management`, stray queue entry `mechanism_id="inbox-labels"`,
    corroborated via `inbox_management`'s own declared `SURFACE`) still closes correctly. A raw
    id the index cannot resolve at all falls back to a literal comparison (preserves the
    pre-A1 behavior for a project with no capability modules on disk yet); a raw id the index
    finds AMBIGUOUS (matches two or more different capabilities) is never silently treated as a
    match OR a non-match — it is surfaced via the returned result's `unresolved_note`.

    Deliberately fail-soft on the WRITE side only: this runs AFTER the ceremony has already
    flipped the descriptor (the trust-critical write is already done by the time this is
    called) — it is bookkeeping tidy-up on a best-effort queue file, never a second authority,
    and NEVER raises or blocks the caller's already-completed acceptance. A missing file,
    malformed JSON, or a non-list body are all silent no-ops (``MigrationCloseResult(closed=
    False)``, no note — these are not identity problems). But an identity-resolution ambiguity
    encountered while examining actual entries is SURFACED via `unresolved_note` rather than
    disappearing into a bare `False` (the F-60 silent-no-op this fix closes).

    Coordinator review, round 2 (CRITICAL fix): a pending entry only ever CLOSES when its
    `mechanism_id` is CORROBORATED (real index evidence, not a bare literal-string fallback) to
    the SAME canonical as the accepted capability — see `_resolve_or_literal`'s `corroborated`
    flag. A raw id that merely happens to equal the accepted id LITERALLY, with neither side
    corroborated by the index, no longer counts as a match (that path was only ever reachable
    via `capability_identity`'s now-removed sole-candidate cardinality guess — see that
    module's docstring). Separately: when this project has EXACTLY ONE known capability and an
    examined entry's `mechanism_id` fails to resolve to ANY capability at all (not this one, not
    any other), that is surfaced via `unresolved_note` too — with only one capability in the
    whole project, an inexplicable leftover queue entry is inherently suspicious (it can't
    plausibly belong to "some other, not-yet-built capability" the way it could in a
    multi-capability project), so silence would hide exactly the CRITICAL-2 failure mode this
    fix closes (an unrelated stray entry the operator can no longer see)."""
    path = pending_migrations_path or PENDING_MIGRATIONS_REL
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        return MigrationCloseResult(closed=False)
    if not isinstance(entries, list):
        return MigrationCloseResult(closed=False)

    index = build_capability_index(project_root or ".")
    accepted_canonical, accepted_note, accepted_corroborated = _resolve_or_literal(
        index, capability_id)
    single_capability_project = len(index.canonical_ids) == 1

    notes = []
    if accepted_note:
        notes.append(accepted_note)

    remaining = []
    closed_raw_ids = []
    for e in entries:
        if not isinstance(e, dict):
            remaining.append(e)
            continue
        raw_mechanism_id = e.get("mechanism_id")
        entry_canonical, entry_note, entry_corroborated = _resolve_or_literal(
            index, raw_mechanism_id)
        if entry_note:
            notes.append(entry_note)
        # NOTE: matching is plain equality of the resolved-or-literal values, not a
        # "both sides corroborated" requirement -- a raw mechanism_id that is LITERALLY the
        # same string as the accepted capability_id is a real, intentional identity (the
        # documented add-capability convention: a migrating capability is deliberately given
        # the SAME id as the mechanism it replaces, often before that capability even has a
        # scaffolded module on disk), not a guess. What must never happen is a DIFFERENT raw
        # string being misattributed to this canonical -- that hole was `capability_identity`'s
        # now-removed sole-candidate fallback, not this equality check.
        matched = (
            accepted_canonical is not None
            and entry_canonical is not None
            and accepted_canonical == entry_canonical
        )
        if matched:
            closed_raw_ids.append(raw_mechanism_id)
            continue
        remaining.append(e)
        # Single-capability near-miss (coordinator review round 2): the ACCEPTED capability
        # itself is a real, corroborated capability, this entry could not be corroborated to
        # ANY capability (not just "not this one"), and there is exactly one capability in the
        # whole project (necessarily the one just accepted) -- an inexplicable orphan worth
        # surfacing rather than a silent non-match, since it can't plausibly belong to some
        # other capability that simply hasn't been built yet.
        if (accepted_corroborated and not entry_note and not entry_corroborated
                and isinstance(raw_mechanism_id, str) and raw_mechanism_id
                and single_capability_project):
            (only_canonical,) = index.canonical_ids
            notes.append(
                f'the pending-migration entry for mechanism_id "{raw_mechanism_id}" could not '
                f'be matched to any known capability, even though this project currently has '
                f'exactly one capability ("{only_canonical}"). This may be a stale or '
                f"unrelated leftover entry, or it may be this capability's own migration "
                f"source recorded under a name this project can't recognize -- review "
                f"{path} by hand if this is unexpected.")

    note = "; ".join(notes) if notes else None
    if not closed_raw_ids:
        return MigrationCloseResult(closed=False, unresolved_note=note)

    try:
        _atomic_write_text(path, json.dumps(remaining, indent=2, ensure_ascii=False) + "\n")
    except Exception:
        return MigrationCloseResult(closed=False, unresolved_note=note)
    return MigrationCloseResult(
        closed=True, closed_raw_ids=tuple(closed_raw_ids), unresolved_note=note)


def record_operator_acceptance(
    capability_id: str,
    phase_id: str,
    # NOTE: no literal `= None` here -- `operator_confirmation` (next positional
    # parameter) has no default and must never get one (its emptiness is refused,
    # never fabricated -- see the docstring below), so a default on this parameter
    # would be a SyntaxError ("non-default argument follows default argument").
    # `None` is still a fully supported value: every caller (the CLI wrapper below,
    # and every other caller in this codebase) always passes this position
    # explicitly, so the type stays `Optional[str]` and the None-handling default
    # block below covers the CLI's omitted-argument case.
    copy_run_proof_ref: Optional[str],
    operator_confirmation: str,
    *,
    receipt_path: Optional[str] = None,
    descriptor_set_path: Optional[str] = None,
    lib_dir: Optional[Path] = None,
    audit_log_path: Optional[str] = None,
    accepted_at: Optional[str] = None,
    pending_migrations_path: Optional[str] = None,
    project_root: Optional[str] = None,
) -> OperatorAcceptanceResult:
    """Mint the operator-acceptance receipt from the operator's VERBATIM confirmation and drive
    the acceptance ceremony. Fail-safe: on any missing / empty / ambiguous input, refuse and
    write nothing that could authorize a live write.

    Parameters
    ----------
    capability_id:         The target descriptor id being accepted.
    phase_id:              The accepted phase id (must match the descriptor's owning phase).
    copy_run_proof_ref:    Path to the capability's validated ``copy_run_proof-v1`` artifact
                           (produced by the supervised copy-run in Step 5). ``None`` defaults
                           (V15-2) to the deterministic per-capability convention
                           ``<DEFAULT_COPY_RUN_PROOF_DIR>/<capability_id>.copy_run_proof.json``
                           -- a convenience for the operator-facing CLI only; this is a PATH
                           default, not a trust shortcut: the file at that path must still
                           exist and validate (an explicit empty string still refuses below,
                           and a defaulted path that does not exist still refuses at the
                           pre-check a few lines down).
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
    project_root:          Default ``"."`` — this package's convention of assuming the process
                           runs from the operator project root. Used to build the capability
                           identity index TWICE: (cross-vendor review fix) before the ceremony
                           call, to resolve `capability_id` to its canonical form ONLY for
                           deriving the `capability_module_path` the ceremony hashes (never for
                           the id passed to the ceremony itself — see the comment at that call
                           site below); and (F-60, unchanged) forwarded to
                           `close_pending_migration_if_matched` on success for the canonical-id
                           migration-queue match.
    """
    if not (isinstance(capability_id, str) and capability_id.strip()):
        return _refuse("no target capability_id supplied")
    capability_id = capability_id.strip()
    if not (isinstance(phase_id, str) and phase_id.strip()):
        return _refuse("no accepted phase_id supplied")
    phase_id = phase_id.strip()

    # V15-2: default the copy-run-proof path from capability_id (deterministic per-capability
    # convention -- mirrors the receipt_path default below) so the operator-facing CLI can drop
    # the raw --copy-run-proof argument from the documented command. This is a PATH default
    # only -- an explicit empty/whitespace string below still refuses, and a defaulted path
    # that does not exist still refuses at the pre-check a few lines down (nothing here weakens
    # the operator-authority requirement: the proof file must still exist and validate).
    if copy_run_proof_ref is None:
        # Built by the SHARED builder the producer also uses -- see
        # `copy_run_proof.copy_run_proof_path`. The path-separator substitution
        # this used to perform inline lives there now, unchanged in behaviour.
        copy_run_proof_ref = copy_run_proof_path(capability_id)

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
            "step: enroll this capability's adapter module in "
            "agents/lib/external_write/operator_adapters.json (the add-capability "
            "build cascade does this for you via "
            "wizard/scripts/lib/capability_code_scaffold.py; registered_adapters.py "
            "imports it from there at process start) so it registers at import "
            "time, then re-run this command; nothing was written")
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

    # (Cross-vendor review fix) Resolve `capability_id` to its canonical form ONLY to
    # derive the capability-module hash path the ceremony records — mirrors lifecycle_state.
    # complete_migration's own fix for this exact bug (lifecycle_state.py, ~1120-1132,
    # "capability_module_path's own default inside the ceremony is ALSO CWD-relative"). Before
    # this fix, this function passed NO capability_module_path at all, so the ceremony fell back
    # to its own default of `<cwd>/agents/capabilities/<capability_id>_capability.py` using the
    # RAW capability_id — wrong for a SPLIT install (descriptor id != module stem, e.g. the
    # estate: descriptor id "inbox-labels", module "inbox_management_capability.py"). A wrong
    # path means `_compute_capability_module_hash` returns None, the acceptance record gets
    # `capability_module_hash: null`, and `lifecycle_state.acceptance_hash_is_stale` treats null
    # as ALWAYS stale — an immediate, false re-flag right after a real, successful acceptance.
    #
    # CRITICAL: this canonical resolution is used ONLY for the module-hash path below. The
    # `capability_id` passed to the ceremony (a few lines down) stays the RAW value — the
    # ceremony finds the descriptor by literal `e.get("id") == capability_id` (acceptance_
    # ceremony.py), and for a split install the descriptor's own id IS the alias, not the
    # canonical, so passing the canonical there would break the descriptor lookup itself.
    #
    # Reuses `_resolve_or_literal` (already used by `close_pending_migration_if_matched` just
    # below for the identical F-60 canonical-resolution need) rather than a second resolution
    # convention: an id the identity index cannot resolve AT ALL (no capability module
    # scaffolded under this exact alias/surface yet — the pre-A1 / no-capabilities-yet case)
    # falls back to the literal `capability_id`, preserving this function's prior behavior
    # exactly. An AMBIGUOUS resolution (the id corroborates two or more DIFFERENT capabilities)
    # is a genuine identity problem that must not silently guess a module path either way — this
    # refuses fail-closed with the exception's own plain-language `operator_message`, before
    # anything (receipt included) is written.
    identity_root = project_root if project_root is not None else "."
    identity_index = build_capability_index(identity_root)
    resolved_module_id, ambiguous_note, _corroborated = _resolve_or_literal(
        identity_index, capability_id)
    if ambiguous_note is not None:
        return _refuse(ambiguous_note)
    resolved_capability_module_path = os.path.join(
        identity_root, CAPABILITIES_DIR_REL, f"{resolved_module_id}{CAPABILITY_FILE_SUFFIX}")

    # --- Task C (Cut 1.5 / v0.19.0): live-enable-only external-write-bypass gate. ---
    # BEFORE anything that could authorize a live write -- the receipt mint just below AND the
    # ceremony's atomic `accepted:true` flip (accept_capability_for_live_use, a few lines down)
    # -- REFUSE to live-enable while the project carries ANY OPEN external-write bypass (a
    # bespoke writer that routes AROUND the sanctioned bulk path; see _ext_write_state.
    # open_bespoke_writer_migrations). This closes the V15-3 false green: previously the ceremony
    # flipped `accepted:true` FIRST and only then ran the best-effort
    # close_pending_migration_if_matched (which is now no longer load-bearing but is left in
    # place as a tidy), so a capability could go green AROUND an unmigrated bespoke writer.
    #
    # Attribution-free by design: the mere EXISTENCE of an open bespoke-writer entry pauses the
    # LIVE-ENABLE transition for the whole project, regardless of which capability owns the writer
    # (safety must never depend on attributing the writer to a capability -- that is a separate,
    # advisory-only concern).
    #
    # This gate is placed AHEAD of the atomic flip AND ahead of the receipt mint, so a refusal
    # leaves NO partial state: `accepted` stays false, no receipt is minted, no acceptance record
    # is written. It gates the LIVE-ENABLE transition ONLY -- it never runs on edit/scan/prove/
    # repair (those do not go through this helper), so the writer's repair is always available
    # while the capability is paused. THIS SEQUENCING IS THE ANTI-DEADLOCK PROPERTY: once the
    # writer is fixed and Task B (reap_resolved_writer_migrations, run inside reconcile_state)
    # clears the entry, this SAME acceptance call succeeds.
    #
    # Fail-closed on read error: an EXISTING-but-unreadable/malformed queue makes
    # open_bespoke_writer_migrations RAISE ExternalWriteStateReadError. Cannot verify safety ->
    # do NOT live-enable: caught and turned into a plain-language refusal here, never allowed to
    # crash the flow or fall through to acceptance (falling through would be exactly the false
    # green this cut exists to close).
    # (Cut 1.6 / Task 2) Keys on the BLOCKING SUBSET, not on every open entry. The
    # presence-of-violation principle is unchanged; what changed is which entries are ADMITTED to
    # the blocking set (see _ext_write_state's Task 1 section). A non-live test module or an
    # operator-acknowledged unrepairable writer stays visible in `capability_health --overall` but
    # no longer refuses acceptance for every capability in the project, forever (F-VAL19-1 /
    # F-VAL19-5). NEEDS_PERSON deliberately REMAINS blocking -- see the refusal branch below.
    try:
        _open_bypasses = blocking_bespoke_writer_migrations(identity_root)
    except ExternalWriteStateReadError:
        # C(a) scrub: never surface the raw exception to a non-technical operator (repo
        # "no raw errors to the operator" convention). Keep it plain-language + actionable.
        return _refuse(
            "cannot verify whether an external-write bypass is still open, so this capability "
            "cannot be live-enabled right now -- fix step: the pending-migrations queue at "
            "agents/handoffs/pending_migrations.json could not be read (it may be malformed); "
            "repair it so it can be read, then re-run acceptance; nothing was accepted")
    if _open_bypasses:
        # Kind-aware RENDERING only -- the predicate just above stays coarse and
        # kind-free (precision here is a wording affordance, never a safety
        # input). A real bespoke-writer bypass (is_bypass_writer_entry) keeps the
        # exact grouped-by-state wording this block has always used. Any other
        # entry recorded a different fact on this same shared queue (for example,
        # that a safety check itself could not finish) and is described in its
        # own words below instead -- the generic "rebuild it" sentence names a
        # fix that does not apply to it.
        _bypass_entries = [e for e in _open_bypasses if is_bypass_writer_entry(e)]
        _other_entries = [e for e in _open_bypasses if not is_bypass_writer_entry(e)]

        # Split the bypass refusal by STATE. Telling a non-technical operator to "rebuild it"
        # when the file cannot be repaired by any tooling we ship is a dead end -- it is exactly
        # what stalled the real estate, where the flagged file also delivered the operator's
        # daily alert and could be neither made scan-clean nor deleted. Each group gets the next
        # step that is actually available to it.
        _needs_person, _rebuildable = [], []
        for _e in _bypass_entries:
            _rel = str(_e.get("writer_relpath"))
            try:
                _state = classify_bespoke_writer_entry(identity_root, _e)
            except Exception:
                _state = WriterState.BLOCKING_LIVE_ENABLE   # unclassifiable -> treat as rebuildable.
            (_needs_person if _state == WriterState.NEEDS_PERSON else _rebuildable).append(_rel)

        _parts = []
        if _rebuildable:
            _parts.append(
                "an external-write bypass is unrepaired: "
                + ", ".join(f"`{r}`" for r in sorted(_rebuildable))
                + " -- rebuild it so it routes through the sanctioned bulk path")
        if _needs_person:
            _parts.append(
                "this cannot be fixed automatically and needs a person: "
                + ", ".join(f"`{r}`" for r in sorted(_needs_person))
                + " -- it does something the rebuild flow cannot rewrite for you, so either "
                "change it by hand until it passes the check, or record that you accept the "
                "risk of leaving it as it is (that decision is kept on file and shown again "
                "whenever the file changes)")
        for _e in sorted(_other_entries, key=lambda e: str(e.get("writer_relpath"))):
            _parts.append(describe_blocking_entry(_e))
        return _refuse("; ".join(_parts) + "; then re-run acceptance; nothing was accepted")

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
        audit_log_path=audit_log_path,
        capability_module_path=resolved_capability_module_path)

    if not acceptance.accepted:
        return OperatorAcceptanceResult(
            accepted=False, reason=acceptance.reason, receipt_ref=receipt_path,
            acceptance=acceptance)

    # Task 10 carry-forward from Task 9: a capability that migrates a paused mechanism
    # closes that mechanism's pending-migration entry the moment it is actually accepted —
    # best-effort, never blocks the acceptance that already happened above. Task A3 / F-60:
    # the outcome is captured and returned (never silently dropped) so a caller can see whether
    # a matching entry actually closed, or whether the queue examination hit an identity problem
    # it could not resolve with confidence.
    migration_close = close_pending_migration_if_matched(
        capability_id, pending_migrations_path, project_root=project_root)

    # F-70 fix (Task A1, primary): mirror lifecycle_state.complete_migration's own FINAL step --
    # now that acceptance genuinely holds, make the pause-marker / migration-queue materialized
    # views coherent with the just-written SSOT (descriptor.accepted) by calling
    # lifecycle_state.reconcile_state. Without this, THIS normal accept path can leave a stale
    # `paused_live_write` marker behind even though the descriptor itself is now accepted --
    # exactly the estate defect: the rebuild went through record_operator_acceptance (this
    # function), which closed the migration queue entry and flipped `accepted` but never called
    # reconcile_state, so the write gate kept refusing an already-accepted capability's op_kind
    # until an operator hand-invoked reconcile. `complete_migration` was the only sanctioned path
    # that reconciled; this fix makes reconciliation happen regardless of which accept path a
    # caller chooses, rather than relying on the caller having picked the right one.
    #
    # Ordering / fail-safety: this MUST run LAST, after the trust-critical write above
    # (`accept_capability_for_live_use`, already durably recorded) has succeeded --
    # `reconcile_state` only ever CLEARS a marker/queue entry once `accepted` reads true (it
    # never flips `accepted` itself; see lifecycle_state.py's module docstring), and is
    # idempotent by construction, so re-running it -- including a second, later call landing here
    # after a prior partial failure -- never corrupts or undoes the acceptance that already
    # holds. A failure here (e.g. `IdentityResolutionError` for an id with no capability module
    # scaffolded on disk yet, or `ReconcileStateError` on an unreadable descriptor/queue file)
    # must never be allowed to make this call look like the ACCEPTANCE itself failed -- the
    # descriptor write already holds by this point -- so it is caught and surfaced as a
    # plain-language note (never silently swallowed, mirroring `migration_close`'s own
    # `unresolved_note` convention) rather than raised. A marker this call could not reconcile is
    # still self-healed the next time anything reads capability health (Task A2 / F-70's
    # crash-safety half -- a separate task, not implemented here).
    reconcile_note: Optional[str] = None
    try:
        # Local import, deliberately deferred to call time: lifecycle_state imports THIS module
        # at ITS OWN top level (for close_pending_migration_if_matched), so importing
        # lifecycle_state back at this module's top level would be a circular import. By the
        # time this function actually runs, both modules have already finished loading.
        from external_write import lifecycle_state as _lifecycle_state
        _lifecycle_state.reconcile_state(identity_root, resolved_module_id)
    except Exception as e:
        reconcile_note = (
            f"acceptance for {capability_id!r} succeeded, but reconciling its lifecycle views "
            f"afterward did not finish cleanly ({e}). If a stale pause marker remains for this "
            "capability, the next capability-health read will self-heal it, or reconcile it by "
            "hand.")

    return OperatorAcceptanceResult(
        accepted=True, reason=None, receipt_ref=receipt_path, acceptance=acceptance,
        migration_close=migration_close, reconcile_note=reconcile_note)


# ---------------------------------------------------------------------------
# CLI wrapper — the next-phase skill invokes this once the operator has confirmed. The verbatim
# confirmation is passed as an argument (captured from what the operator actually typed). Run
# from the operator project root so default paths resolve. Exits 0 on acceptance, 1 on refusal,
# 2 on usage.
# ---------------------------------------------------------------------------

def _ready_accept_command(capability_id: str, phase_id: str, operator_confirmation: str) -> str:
    """(Task 4 / F-2) Render the fully paste-safe, ready-to-run accept command for
    ``capability_id`` -- a SINGLE PHYSICAL LINE, every interpolated value ``shlex.quote``'d, so
    it can never wrap-and-break on paste (the exact V15-2 hazard this fix closes) regardless of
    what the operator's confirmation text contains (quotes, spaces, punctuation). Matches the
    documented invocation shape (``wizard/skills/next-phase.md`` Step 6 / ``rebuild-paused-
    capability.md`` Step 4) exactly, with ``--phase-id`` pre-filled -- never left for the
    operator to add by hand.

    Fail-closed guard (review finding on this task): ``shlex.quote`` escapes shell
    metacharacters but does NOT strip or reject a literal embedded newline/carriage-return
    inside the quoted argument -- e.g. ``shlex.quote("a\\nb")`` returns ``"'a\\nb'"``, which
    STILL spans two physical lines when printed. Since ``operator_confirmation`` is free
    operator text, a confirmation containing an embedded newline would otherwise make this
    function silently emit a "single line" command that is not actually one physical line --
    the exact paste-safety hazard this whole helper exists to eliminate. This function
    therefore refuses (raises) rather than emit anything unsafe; every caller that might feed
    it operator text must check for a newline/carriage-return FIRST and degrade to a plain
    diagnostic instead (see the CLI's ``multiple_pending`` branch) -- this raise is a
    defense-in-depth backstop, not the primary guard."""
    if "\n" in operator_confirmation or "\r" in operator_confirmation:
        raise ValueError(
            "_ready_accept_command refuses to build a command: operator_confirmation "
            "contains an embedded newline/carriage-return, and shlex.quote does not strip "
            "one -- interpolating it here would produce a command that is not actually a "
            "single physical line. The caller must check for this before calling this "
            "function and degrade to a plain single-line diagnostic instead.")
    import shlex as _shlex
    parts = [
        "python3", "agents/lib/external_write/operator_acceptance.py",
        "--capability-id", capability_id,
        "--phase-id", phase_id,
        "--operator-confirmation", operator_confirmation,
    ]
    return " ".join(_shlex.quote(p) for p in parts)


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _args = _sys.argv[1:]
    _opts = {
        "--capability-id": None, "--phase-id": None, "--copy-run-proof": None,
        "--operator-confirmation": None, "--receipt-out": None,
        "--descriptor-set": None, "--audit-log": None,
    }
    _usage = ("Usage: operator_acceptance.py --capability-id <id> "
              "--operator-confirmation <verbatim text> "
              "[--phase-id <id>] [--copy-run-proof <path>] [--receipt-out <path>] "
              "[--descriptor-set <path>] [--audit-log <path>]\n"
              "(V15-2: --copy-run-proof may be omitted -- it then defaults to "
              "agents/handoffs/<capability-id>.copy_run_proof.json)\n"
              "(V15-2 Task 5: --phase-id may also be omitted -- it is then derived from the "
              "single pending descriptor matching --capability-id; if it cannot be uniquely "
              "determined, this prints a plain diagnostic or a ready-to-paste command per "
              "pending capability -- Task 4/F-2 -- never a flag to hand-append)")
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

    # V15-2: --copy-run-proof is NOT in this required list -- its path is deterministic from
    # --capability-id (see DEFAULT_COPY_RUN_PROOF_DIR / record_operator_acceptance's default
    # block), so omitting it is a valid, paste-safe-collapsing invocation, not a usage error.
    # Task 5: --phase-id joins it -- it is derived below when omitted, fail-closed.
    for _req in ("--capability-id", "--operator-confirmation"):
        if _opts[_req] is None:
            print(f"missing required {_req}\n{_usage}", file=_sys.stderr)
            _sys.exit(2)

    # Task 5 (V15-2): when --phase-id is omitted, derive it from the single pending descriptor
    # matching --capability-id. Fail-closed -- this is a convenience over an already-recorded
    # value, never a second authority, so any ambiguity must refuse rather than guess.
    #
    # Task 4 (F-2): when it CAN'T be uniquely derived, the branch below reacts to the SPECIFIC
    # cause instead of one generic "re-run with --phase-id" message -- that message told a
    # non-technical operator to hand-append a flag to a wrapping command, the exact paste-safety
    # hazard the single-line command was meant to kill. Every branch here prints either a plain
    # single-line diagnostic (nothing to hand-assemble) or a fully ready, already-paste-safe
    # command -- never an instruction to edit/extend a command by hand.
    _phase = _opts["--phase-id"]
    if _phase is None:
        _phase = resolve_pending_phase(
            _opts["--capability-id"], project_root=".",
            descriptor_set_path=_opts["--descriptor-set"])
        if _phase is None:
            _diag = diagnose_phase_resolution(
                _opts["--capability-id"], project_root=".",
                descriptor_set_path=_opts["--descriptor-set"])
            if _diag.kind == "already_accepted":
                print(
                    f"capability {_opts['--capability-id']!r} is already accepted -- there is "
                    "nothing pending to accept.", file=_sys.stderr)
            elif _diag.kind == "identity_conflict":
                print(
                    f"capability {_opts['--capability-id']!r} has more than one pending "
                    "descriptor entry sharing that id (identity_conflict) -- this is a "
                    "data-integrity problem with the registry, not normal ambiguity, and it "
                    "cannot be safely accepted until the duplicate entries are healed. Run "
                    "your upgrade/reconcile step and try again.", file=_sys.stderr)
            elif _diag.kind == "phase_id_missing":
                print(
                    f"capability {_opts['--capability-id']!r} has a pending descriptor entry, "
                    "but its phase binding (phase_id) is missing or blank -- this is a "
                    "data-integrity problem with that registry entry, not something re-running "
                    "this command can fix. Ask whoever built this capability to backfill its "
                    "phase_id, then try again.", file=_sys.stderr)
            elif _diag.kind == "multiple_pending":
                # (Review finding on this task) shlex.quote does NOT strip an embedded
                # newline/carriage-return from a quoted argument -- interpolating an operator
                # confirmation that contains one would make the "ready-to-paste" command below
                # actually span more than one physical line, the exact V15-2 wrap-and-break
                # hazard this fix exists to eliminate. Check BEFORE building any command; if
                # unsafe, degrade to a single-line diagnostic and emit no command at all.
                _confirmation = _opts["--operator-confirmation"]
                if "\n" in _confirmation or "\r" in _confirmation:
                    print(
                        "the --operator-confirmation text you supplied contains a line break, "
                        "so a ready-to-paste accept command cannot be safely generated -- "
                        "re-run this command with a single-line confirmation (no line breaks) "
                        "and try again.", file=_sys.stderr)
                else:
                    print(
                        f"capability {_opts['--capability-id']!r} does not have a pending "
                        "acceptance -- but the following capabilities ARE currently pending. "
                        "Paste the ONE command below that matches what you want to accept:",
                        file=_sys.stderr)
                    for _cid, _cphase in _diag.candidates:
                        print(
                            _ready_accept_command(_cid, _cphase, _confirmation),
                            file=_sys.stderr)
            else:  # "zero_match"
                print(
                    f"no pending descriptor entry was found for capability "
                    f"{_opts['--capability-id']!r} -- there is nothing to accept.",
                    file=_sys.stderr)
            _sys.exit(2)

    _res = record_operator_acceptance(
        _opts["--capability-id"], _phase, _opts["--copy-run-proof"],
        _opts["--operator-confirmation"],
        receipt_path=_opts["--receipt-out"],
        descriptor_set_path=_opts["--descriptor-set"],
        audit_log_path=_opts["--audit-log"])
    if _res.accepted:
        print(f"ACCEPTED: capability {_res.acceptance.capability_id!r} is now live-authorized "
              f"for phase {_res.acceptance.phase_id!r}. Receipt: {_res.receipt_ref}")
        # IMPORTANT fix (coordinator review round 2): the acceptance itself already succeeded
        # (this print never gates on it) -- but if the best-effort pending-migration-queue
        # cleanup hit something it could not confidently resolve (an ambiguous alias, or an
        # uncorroborated stray in a single-capability project), that must reach whoever is
        # reading this CLI's output, not stay buried in the Python-only OperatorAcceptanceResult
        # field. wizard/skills/next-phase.md's Step 6 invokes exactly this CLI and otherwise
        # sees only ACCEPTED/REFUSED + the exit code. A normal, clean close (or a queue with
        # nothing to close) stays quiet -- only a genuine surfaced miss prints.
        if _res.migration_close is not None and _res.migration_close.unresolved_note:
            print(f"NOTE: {_res.migration_close.unresolved_note}")
        # Task A1 / F-70 fix: same discipline -- a reconcile that did not finish cleanly must
        # reach this CLI's output, not stay buried in the Python-only result field.
        if _res.reconcile_note:
            print(f"NOTE: {_res.reconcile_note}")
        _sys.exit(0)
    else:
        print(f"REFUSED: {_res.reason}", file=_sys.stderr)
        _sys.exit(1)
