"""The trial write-ahead journal — the durable, per-unit record that lets a
journaled trial survive a crash (Cut 1.9 Task 3).

------------------------------------------------------------------------------
Why this exists
------------------------------------------------------------------------------
A trial is `apply -> verify -> undo -> verify-restored` against a real, bounded
live target, and its output is the proof operator acceptance requires. That makes
partial application uniquely disqualifying for a trial: a trial that applies some
units and then cannot enumerate what landed cannot undo itself, cannot emit an
honest proof, and leaves real mutations on the operator's live record.

Three facts about the existing apply path, taken together, are why this journal
is a precondition of correctness rather than a robustness nicety:

  * `adapters._run_adapter_operation` applies units in a bare loop — one
    `dispatch.apply_one(...)` per unit, with no per-unit record of any kind.
  * the adapter layer writes NOTHING to disk. Not a partial-apply marker, not an
    inventory of applied unit ids, not a retained reversal reference.
  * the existing run-state WAL (`run_envelope`) is TRANCHE-granular, and a
    tranche lands AFTER its units have been applied (`append_tranche` is the one
    place a tranche actually lands, and it is what advances the run to
    EXECUTING).

So if `apply_one` raises on the third unit, the first two have mutated the real
external surface and nothing on disk records that they did.

This is NOT a hidden defect in the ordinary bulk path, and it should not be
described as one. That path was deliberately built honest and durable-only:
`run_envelope.report_run_recoverability` reports from durable records ONLY and
returns an explicit not-recoverable-by-system verdict for any id lacking a
durable applied-tranche entry — the system DISCLOSES this gap rather than
pretending to recover from it. The existing WAL closes chunk-restart; it never
claimed to close intra-tranche partial application. This module closes it for the
trial protocol, which is the one flow that cannot proceed without it.

------------------------------------------------------------------------------
WRITE-AHEAD means write-ahead
------------------------------------------------------------------------------
Every state this journal records is one of two kinds, and the distinction is the
whole design:

  WRITE-AHEAD states (`WRITE_AHEAD_STATES`) are persisted and fsynced BEFORE the
  action they authorize.
    * `planned` — the whole plan plus every unit's recovery capsule, durable
      before the FIRST mutation of the trial.
    * `apply_intent` — durable before this unit's `apply_one`.
    * `undo_intent` — durable before this unit's `undo_one`.

  OUTCOME states (`OUTCOME_STATES`) report something that has already happened,
  so they are necessarily recorded afterwards.
    * `apply_confirmed`, `restored_verified`, `recovery_required`.

A state transition persisted AFTER the action it authorizes would leave exactly
the crash window this module exists to close, and the journal would then provide
no more safety than the bare loop does. Two things hold that line:

  1. the record-writing methods for the write-ahead states do not return until
     the new record is on disk AND fsynced (contents and directory entry both);
  2. `LEGAL_TRANSITIONS` makes each OUTCOME state reachable ONLY from the
     write-ahead state that authorizes the action it reports —
     `apply_confirmed` only from `apply_intent`, `restored_verified` only from
     `undo_intent`. An executor that applied without first recording the intent
     cannot record the outcome at all; the transition refuses.

The crash window between `apply_intent` and `apply_confirmed` is AMBIGUOUS BY
DESIGN: nothing on disk can say whether the mutation landed. This module does
not try to find out, and nothing here should ever be built to reconstruct that
history. The safe resolution converges on the invariant instead — reverse the
unit anyway — which is exactly why the trial-eligibility preflight requires the
adapter to declare `undo_one` an ABSOLUTE-state restore. `apply_intent ->
undo_intent` is therefore a LEGAL transition, not an anomaly.

------------------------------------------------------------------------------
`recovery_required` is durable, and it is LEAVABLE — by exactly one route
------------------------------------------------------------------------------
`recovery_required` means a unit could not be established back at its prior state,
so it may still be changed on the operator's live record. It is durable and
outlives the process that wrote it; nothing here clears it as a side effect of
anything.

It is nonetheless not a dead end, and that is deliberate. A durable blocking
record whose named repair cannot actually clear it is a state the operator cannot
get out of — which is the class of failure this protocol was built to remove, so
opening one here would defeat it. The state therefore has exactly ONE successor:
`undo_intent`. A unit a prior attempt could not verify is reversed AGAIN under a
fresh, durable intent record, and only an observed post-condition then moves it to
`restored_verified`.

The two exits the table deliberately does NOT offer are the two wrong ones:

  * `recovery_required -> restored_verified` — a unit marked resolved with no
    fresh write-ahead record and no observation behind it. That is the quiet
    clearing this state exists to prevent, and it stays impossible.
  * `recovery_required -> apply_intent` — a RE-APPLY. `apply_intent` is reachable
    only from `planned`, so no resumed or recovering process can issue a second
    apply for a unit through this journal at all. Recovery converges by reversing.

------------------------------------------------------------------------------
What `apply_confirmed` and `restored_verified` do and do not mean
------------------------------------------------------------------------------
`apply_confirmed` records that the adapter's `apply_one` RETURNED for this unit.
It is NOT evidence the mutation landed on the live surface — that is what the
adapter's `verify_apply_landed` predicate establishes, in a separate later phase
over observed evidence. Reading `apply_confirmed` as "the write is verified"
would be precisely the false-green this package has paid for before.

`restored_verified` records that its caller established restoration from observed
evidence (`verify_undo_restored`). DISCLOSED BOUND: this journal cannot check
that. It records the claim; the caller is what earns it. The name describes the
obligation on the caller, not a check performed here.

------------------------------------------------------------------------------
The recovery capsule — a NEW, JSON-only per-unit contract
------------------------------------------------------------------------------
`EffectUnit.target_ref` and `EffectUnit.undo_ref` are documented as "Opaque,
adapter-defined". Opaque means NOT contractually serializable: nothing may assume
either one can be written to disk as itself. They are also not safely recreatable
by re-running `plan()` after a crash — a second plan is a second observation of a
surface the trial has already mutated.

So a trial carries a per-unit RECOVERY CAPSULE: an explicitly JSON-safe rendering
the adapter supplies, versioned by its own schema tag, holding what a recovery
path needs to reverse one unit from disk alone. `build_recovery_capsule` is the
single sanctioned constructor (so the field names are spelled once) and
`validate_recovery_capsule` is the single validator.

No pickle, anywhere, ever. A capsule holds adapter-defined values whose types
nothing here controls; unpickling one would execute arbitrary code on the
recovery path. JSON is the entire reason the format exists, and serializability
is proven by a real `json.dumps` round trip — never by an isinstance guess.

The FORMAT validated here and the SERIALIZABILITY the trial-eligibility
preflight's capsule clause checks are two different questions with two different
owners, deliberately not duplicated: the preflight proves a capsule survives a
real JSON round trip (and says explicitly that it accepts a degenerate capsule,
because the format did not exist when it was written); this module owns what a
well-formed capsule IS. `serialize_journal_payload` uses the same strictness the
preflight's round trip uses (`sort_keys`, `ensure_ascii`, `allow_nan=False`), so
that proof is a proof about THIS writer and not about a laxer one.

------------------------------------------------------------------------------
Reuse of primitives, NOT of schemas
------------------------------------------------------------------------------
The durability mechanics follow this package's established primitives: a
temp-file + fsync + `os.replace` atomic write (the pattern `lifecycle_state`,
`_ext_write_state`, `run_envelope` and others each carry privately, by the
convention this package already uses), an exclusive POSIX advisory lock around
every read-modify-write (`write_gate.PersistentInvocationLedger`), and a
canonical, key-sorted serialization.

ONE deliberate addition, load-bearing here in a way it is not for a settings
file: the containing DIRECTORY is fsynced after the rename. `os.fsync` on the
file makes the BYTES durable; the rename that publishes them is a
directory-entry change, and without its own fsync a crash can lose the entire
record even though its contents were flushed. A write-ahead log whose publish
step is not durable is not a write-ahead log.

The SCHEMAS are deliberately NOT reused. `run_envelope`'s envelope is
tranche-granular; the invocation ledger records cap consumption; `copy_run_proof`
is TERMINAL evidence about a finished run, not an in-progress log. This surface
is its own: `security/trial_runs/<trial_id>.json`, one file per trial, write-once
at open. It holds adapter-defined prior-state values, so it belongs with its
gitignored siblings under `security/` and is never committed.

`load_trial_journal` FAILS CLOSED by RAISING on an absent, unreadable or
malformed record — a deliberate divergence from `run_envelope.load_run_envelope`,
which reads a missing file as an EMPTY envelope. For a budget, empty is the
fail-safe reading (nothing may be spent). For a recovery record, empty means
"nothing was applied", which is the one claim a missing file cannot support, and
is the fail-OPEN direction.

------------------------------------------------------------------------------
What this module does NOT do
------------------------------------------------------------------------------
  * It performs no external read and no external write, and it never takes,
    resolves or returns a write-capable client. It records; something else
    mutates.
  * It does not execute a trial and it does not recover one. The trial executor
    and the recovery path are separate concerns with their own modules, and there
    is deliberately no stub, hook or placeholder for either one here.
  * It does not authorize anything. Opening a journal requires an
    `AuthorizedPlan` that `write_authorization.authorize_operation` already
    issued for the trial intent; this module re-checks that plan's trial
    invariants at consumption time but implements none of them.
  * It does not decide whether an apply landed. See the ambiguity note above.
  * The enforcement ceiling is UNCHANGED: build-time plus operator-as-approver.
    This is not a runtime sandbox and not an OS-level control. A determined
    hand-edit of a journal file on disk is exactly as available as it has always
    been; what is structurally true is narrower — no path through this module
    advances a unit past an action whose authorizing record is not already
    durable.

Callers, both in production, and they use different entrypoints on purpose. The
journaled TRIAL EXECUTOR opens a journal (`open_trial_journal`) from the same
`AuthorizedPlan` this module requires, and it is the only thing that creates one.
The RECOVERY driver loads an existing one (`load_trial_journal`) and creates
nothing — a resumed run must never be able to bring a second journal into
existence for a trial that already has one, which is why the write-once open and
the load are separate functions rather than one function with a flag.

Zone: SEALED_KERNEL (enumerated in `zones.py`). It reads the sibling kernel
submodules `write_authorization` (the authorization carrier) and `operations`
(the effect-unit type) as ordinary internal kernel wiring, imports no vendor SDK,
constructs no credential, and performs no vendor mutation.

Stdlib only — no third-party dependencies.
"""

import json
import os
import stat
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple
from uuid import uuid4

# sys.path bootstrap (mirrors `run_envelope.py`): make the package parent
# importable when run as a direct script from the project root.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.operations import EffectUnit
from external_write.write_authorization import (
    EXECUTION_INTENT_TRIAL, TRIAL_TARGET, AuthorizedPlan,
)

try:  # POSIX advisory locking. Absent on non-POSIX platforms.
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - non-POSIX only
    _fcntl = None


# ---------------------------------------------------------------------------
# Surface + schema tags
# ---------------------------------------------------------------------------

# Project-root-relative home for trial journals, alongside the other
# consent/runtime records under `security/`. Gitignored: a capsule holds the
# adapter's rendering of a unit's PRIOR STATE, which is operator data.
DEFAULT_TRIAL_JOURNAL_DIR = "security/trial_runs"

TRIAL_JOURNAL_SCHEMA = "trial_journal-v1"
RECOVERY_CAPSULE_SCHEMA = "trial_recovery_capsule-v1"


# ---------------------------------------------------------------------------
# Per-unit states
# ---------------------------------------------------------------------------

STATE_PLANNED = "planned"
STATE_APPLY_INTENT = "apply_intent"
STATE_APPLY_CONFIRMED = "apply_confirmed"
STATE_UNDO_INTENT = "undo_intent"
STATE_RESTORED_VERIFIED = "restored_verified"
STATE_RECOVERY_REQUIRED = "recovery_required"

TRIAL_UNIT_STATES: Tuple[str, ...] = (
    STATE_PLANNED,
    STATE_APPLY_INTENT,
    STATE_APPLY_CONFIRMED,
    STATE_UNDO_INTENT,
    STATE_RESTORED_VERIFIED,
    STATE_RECOVERY_REQUIRED,
)

# States persisted and fsynced BEFORE the action they authorize. See the module
# docstring's "WRITE-AHEAD means write-ahead" section.
WRITE_AHEAD_STATES: Tuple[str, ...] = (
    STATE_PLANNED, STATE_APPLY_INTENT, STATE_UNDO_INTENT,
)

# States that report something already done, and are therefore necessarily
# recorded afterwards. Every state must be in exactly one of these two tuples --
# an unclassified state has no ordering rule, and a state with no ordering rule
# is a state whose ordering nobody checked.
OUTCOME_STATES: Tuple[str, ...] = (
    STATE_APPLY_CONFIRMED, STATE_RESTORED_VERIFIED, STATE_RECOVERY_REQUIRED,
)

# Terminal: this journal never transitions a unit out of one. `restored_verified`
# is the settled end of the protocol -- the unit was observed back at its prior
# state, and there is nothing further to establish about it.
#
# `recovery_required` is deliberately NOT in this set, and the reason is a
# correction of this module's own first shape rather than a loosening of it. It
# WAS terminal here, on the reasoning that nothing should be able to quietly mark
# a unit resolved. That reasoning is right about "quietly" and wrong about
# "terminal": a blocking record with no performable repair is a state the operator
# cannot get out of, which is precisely the class of defect the trial protocol was
# built to remove rather than to add. So the state remains durable and outlives
# the process that wrote it, but it has exactly ONE exit and that exit re-earns
# the guarantee from scratch -- see `LEGAL_TRANSITIONS` immediately below and
# `record_recovery_required`.
TERMINAL_STATES: Tuple[str, ...] = (
    STATE_RESTORED_VERIFIED,
)

# The transition table, read-only. Three entries carry load-bearing guarantees and
# must not be widened without re-deciding them:
#   * `apply_confirmed` appears ONLY as a successor of `apply_intent`;
#   * `restored_verified` appears ONLY as a successor of `undo_intent`;
#   * `apply_intent` appears ONLY as a successor of `planned`.
# The first two are the write-ahead guarantee (an outcome is recordable only from
# the intent that authorized the action it reports). The third is the NEVER
# RE-APPLY guarantee, and it is structural rather than a rule a driver has to
# remember: no state a resumed or recovering process can find a unit in leads back
# to `apply_intent`, so nothing can issue a second apply for a unit through this
# journal at all. A trial that re-applied after a crash would be a live write the
# operator never consented to at that moment.
#
# `apply_intent -> undo_intent` is legal on purpose: after a crash in the
# ambiguous window the safe resolution reverses the unit anyway rather than
# trying to reconstruct whether the mutation landed.
#
# `recovery_required -> undo_intent` is legal for the same reason, one layer out:
# it is the ONLY exit from `recovery_required`, so a unit a prior attempt could
# not verify is reachable again -- and reachable only by reversing it again under
# a fresh, durable undo intent and then re-establishing the observed
# post-condition. The two exits this deliberately does NOT offer are the two wrong
# ones: `restored_verified` directly (that would mark a unit resolved with no
# fresh write-ahead record and no observation behind it -- the quiet clearing) and
# `apply_intent` (a re-apply).
LEGAL_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    STATE_PLANNED: (STATE_APPLY_INTENT, STATE_RECOVERY_REQUIRED),
    STATE_APPLY_INTENT: (STATE_APPLY_CONFIRMED, STATE_UNDO_INTENT,
                         STATE_RECOVERY_REQUIRED),
    STATE_APPLY_CONFIRMED: (STATE_UNDO_INTENT, STATE_RECOVERY_REQUIRED),
    STATE_UNDO_INTENT: (STATE_RESTORED_VERIFIED, STATE_RECOVERY_REQUIRED),
    STATE_RESTORED_VERIFIED: (),
    STATE_RECOVERY_REQUIRED: (STATE_UNDO_INTENT,),
}

# The states in which a unit may STILL be outstanding on the operator's live
# record, and which a resumed trial must therefore drive to a verdict. DECLARED
# here, next to the table, rather than re-derived by each consumer: a recovery
# driver that enumerated these itself would be a second copy of a classification,
# and a state added later without being classified would silently fall out of
# every driver's scope.
#
# `planned` is EXCLUDED deliberately, and it is the one exclusion worth stating:
# the `apply_intent` record is fsynced -- contents and directory entry -- before
# `apply_one` is called, so a unit still recorded `planned` was provably never
# applied and has nothing outstanding. `restored_verified` is excluded because it
# is settled and terminal.
RECOVERY_DRIVEN_STATES: Tuple[str, ...] = (
    STATE_APPLY_INTENT, STATE_APPLY_CONFIRMED, STATE_UNDO_INTENT,
    STATE_RECOVERY_REQUIRED,
)

# The other two dispositions a resumed run can reach, declared POSITIVELY beside
# the driven set so that the three together are a TOTAL PARTITION of
# `TRIAL_UNIT_STATES`. Each is a one-member tuple today and is a tuple anyway, so
# a future state joins whichever disposition it belongs to rather than the tuples
# having to change shape.
#
# WHY THE POSITIVE FORM IS LOAD-BEARING, and this is a correction of the first
# version of this design rather than a decoration of it. A consumer that derived
# this disposition negatively -- "anything not driven and not settled was never
# applied" -- absorbs any state added later into the benign bucket. A unit holding
# a LIVE, UNREVERSED mutation would then be reported as never applied, the run
# would report success, and the operator would be told nothing is outstanding
# while the change was still on their record. The journal's own exhaustiveness
# guard cannot catch that: a new state classified into `OUTCOME_STATES` satisfies
# it completely. So the partition is declared here, a consumer must resolve a
# state into exactly one of the three, and a state in none of them must REFUSE
# rather than default to the safe-looking answer.
RECOVERY_NEVER_APPLIED_STATES: Tuple[str, ...] = (STATE_PLANNED,)
RECOVERY_SETTLED_STATES: Tuple[str, ...] = (STATE_RESTORED_VERIFIED,)

# The partition itself, so a consumer resolves a disposition by lookup over a
# declared mapping rather than by re-listing the three tuples in an if/elif chain
# that could drift from them. Keys are this module's vocabulary for the three
# dispositions; a consumer that finds a state in none of them has found a state
# nobody classified.
RECOVERY_DISPOSITION_DRIVEN = "driven"
RECOVERY_DISPOSITION_NEVER_APPLIED = "never_applied"
RECOVERY_DISPOSITION_SETTLED = "settled"

RECOVERY_DISPOSITIONS: Dict[str, Tuple[str, ...]] = {
    RECOVERY_DISPOSITION_DRIVEN: RECOVERY_DRIVEN_STATES,
    RECOVERY_DISPOSITION_NEVER_APPLIED: RECOVERY_NEVER_APPLIED_STATES,
    RECOVERY_DISPOSITION_SETTLED: RECOVERY_SETTLED_STATES,
}


def recovery_disposition(state: str) -> Optional[str]:
    """Which of the three recovery dispositions `state` belongs to, or **None** if
    it belongs to none.

    Returns None rather than raising, and rather than guessing: the caller is the
    thing that knows what refusing costs and what to say about it, and the one
    answer this function must never invent is a benign disposition for a state it
    does not recognize. A `None` here means a unit whose situation nobody has
    decided about, which may include holding a live unreversed mutation.
    """
    for disposition, states in RECOVERY_DISPOSITIONS.items():
        if state in states:
            return disposition
    return None


# ---------------------------------------------------------------------------
# Recovery capsule format
# ---------------------------------------------------------------------------

CAPSULE_KEY_SCHEMA = "schema"
CAPSULE_KEY_UNIT_ID = "unit_id"
CAPSULE_KEY_OP_KIND = "op_kind"
CAPSULE_KEY_TARGET_REF = "target_ref_json"
CAPSULE_KEY_UNDO_REF = "undo_ref_json"

# The EXACT key set of a conforming capsule. Exact, not minimal: an adapter that
# needs to carry more context carries it INSIDE `target_ref_json` /
# `undo_ref_json`, which are adapter-defined by contract. An unrecognized
# top-level key is refused rather than ignored, because the two ways it arises --
# a misspelled required key, and a newer capsule version declared under this
# version's schema tag -- are both things a recovery path must not silently
# accept.
RECOVERY_CAPSULE_KEYS: Tuple[str, ...] = (
    CAPSULE_KEY_SCHEMA, CAPSULE_KEY_UNIT_ID, CAPSULE_KEY_OP_KIND,
    CAPSULE_KEY_TARGET_REF, CAPSULE_KEY_UNDO_REF,
)


class TrialJournalError(Exception):
    """Raised for anything the journal cannot record faithfully.

    Deliberately an EXCEPTION rather than a refusal value, for the same reason
    `write_authorization.AuthorizationRequiredError` is one: a refusal is the
    answer to a legitimate question ("may this write proceed?"), whereas every
    condition raised here means the durable record cannot be trusted. Failing
    loudly BEFORE a mutation is strictly safer than returning a soft "no" that a
    caller might treat as advisory and step past.
    """


def build_recovery_capsule(op_kind: str, unit: Any, *,
                           target_ref_json: Any,
                           undo_ref_json: Any) -> Dict[str, Any]:
    """Assemble the per-unit recovery capsule for `unit` — the single sanctioned
    constructor, so the capsule's field names are spelled in exactly one place.

    `target_ref_json` / `undo_ref_json` are the ADAPTER's explicitly JSON-safe
    renderings of that unit's opaque `target_ref` / `undo_ref`. This function
    does not derive them: `EffectUnit`'s references are adapter-defined and
    opaque, so only the adapter knows what a faithful JSON rendering of its own
    reference is. Passing the reference object through unchanged is correct
    whenever it already IS JSON-representable, and that is the adapter's call to
    make, not this module's guess.

    Both are KEYWORD-ONLY and have NO DEFAULT, on purpose: a default would let a
    caller omit the undo reference and still produce a capsule, which is the
    silence-passes direction. Omitting either raises `TypeError` at the call
    site.

    For an absolute-state restore -- which the trial-eligibility preflight
    requires the adapter to declare -- `undo_ref_json` is what carries the
    recorded PRIOR state (the prior cell value, the exact prior label set). There
    is deliberately no separate "prior state" field: inventing one would be this
    module designing the adapter's data for it.

    Returns a plain dict. Validate it with `validate_recovery_capsule`; the
    journal validates every capsule itself before it writes anything.
    """
    unit_id = getattr(unit, "unit_id", None)
    if not _usable_unit_id(unit_id):
        raise TrialJournalError(
            "a recovery capsule is keyed by its unit's unit_id, which must be a "
            f"non-blank string; got {unit_id!r}")
    return {
        CAPSULE_KEY_SCHEMA: RECOVERY_CAPSULE_SCHEMA,
        CAPSULE_KEY_UNIT_ID: unit_id,
        CAPSULE_KEY_OP_KIND: op_kind,
        CAPSULE_KEY_TARGET_REF: target_ref_json,
        CAPSULE_KEY_UNDO_REF: undo_ref_json,
    }


def validate_recovery_capsule(op_kind: str, unit_id: str,
                              capsule: Any) -> Optional[str]:
    """Return None if `capsule` is a conforming recovery capsule for `unit_id` of
    `op_kind`; otherwise a plain-language reason naming what is wrong.

    This validates FORMAT and IDENTITY. It deliberately does NOT re-check
    JSON-serializability: that question has exactly one implementation (the
    trial-eligibility preflight's capsule clause, which performs a real
    `json.dumps` round trip), and the journal's own write is itself the real
    round trip -- performed before any mutation, so a capsule that cannot be
    serialized fails the open rather than a later transition.

    Identity is joined on the DECLARED value, never inferred from the key the
    capsule happens to be filed under: a capsule whose own `unit_id` disagrees
    with its key would send a recovery path at the wrong record, and a capsule
    earned by one operation kind never describes another.
    """
    if not isinstance(capsule, Mapping):
        return (f"the recovery capsule for unit {unit_id!r} is a "
                f"{type(capsule).__name__}, not a mapping. A capsule must be a "
                f"{RECOVERY_CAPSULE_SCHEMA} object -- build it with "
                "build_recovery_capsule.")

    present = set(capsule)
    expected = set(RECOVERY_CAPSULE_KEYS)
    missing = sorted(expected - present)
    if missing:
        return (f"the recovery capsule for unit {unit_id!r} is missing the "
                f"required key(s) {missing}. Every key is required and must be "
                "present explicitly -- an absent key is never read as a "
                "declared null.")
    unknown = sorted(present - expected)
    if unknown:
        return (f"the recovery capsule for unit {unit_id!r} carries the "
                f"unrecognized top-level key(s) {unknown}. Carry adapter-specific "
                f"context inside {CAPSULE_KEY_TARGET_REF} / "
                f"{CAPSULE_KEY_UNDO_REF}, which are adapter-defined; a new "
                "top-level key needs a new capsule schema, not a silent "
                "addition under this one.")

    schema = capsule[CAPSULE_KEY_SCHEMA]
    if schema != RECOVERY_CAPSULE_SCHEMA:
        return (f"the recovery capsule for unit {unit_id!r} declares schema "
                f"{schema!r}; this journal writes and reads "
                f"{RECOVERY_CAPSULE_SCHEMA!r} only.")

    declared_unit_id = capsule[CAPSULE_KEY_UNIT_ID]
    if not _usable_unit_id(declared_unit_id):
        return (f"the recovery capsule filed under unit {unit_id!r} declares an "
                f"unusable unit_id ({declared_unit_id!r}); it must be a "
                "non-blank string.")
    if declared_unit_id != unit_id:
        return (f"the recovery capsule filed under unit {unit_id!r} declares "
                f"unit_id {declared_unit_id!r}. A capsule is matched on the id it "
                "DECLARES, never on the key it happens to be filed under, so "
                "these must agree or a recovery path would reverse the wrong "
                "record.")

    declared_op_kind = capsule[CAPSULE_KEY_OP_KIND]
    if declared_op_kind != op_kind:
        return (f"the recovery capsule for unit {unit_id!r} was built for "
                f"operation kind {declared_op_kind!r}, but this trial runs "
                f"{op_kind!r}. A capsule earned by one operation kind never "
                "describes another.")

    if capsule[CAPSULE_KEY_UNDO_REF] is None:
        return (f"the recovery capsule for unit {unit_id!r} declares "
                f"{CAPSULE_KEY_UNDO_REF} = null, so it carries nothing with "
                "which to reverse the unit. A trial must be able to undo every "
                "unit it applies. Fix step: have the adapter render its undo "
                "reference into JSON for every planned unit.")

    # `target_ref_json` may be null -- but only EXPLICITLY, which the
    # missing-key check above already enforced. An adapter whose undo reference
    # alone identifies the target declares that positively.
    return None


# ---------------------------------------------------------------------------
# Durability primitives
# ---------------------------------------------------------------------------

def serialize_journal_payload(payload: Any) -> str:
    """The journal's canonical serialization: key-sorted (so identical content
    yields identical bytes regardless of insertion order), ASCII-escaped, and
    STRICT about non-finite floats.

    `allow_nan=False` is not a style choice. The stdlib default emits bare
    `NaN` / `Infinity`, which is not valid JSON and is rejected by a strict
    reader -- a journal that wrote one would be unreadable by exactly the
    recovery path it exists to serve. It is also the same strictness the
    trial-eligibility preflight's capsule round trip uses, which is what makes
    that preflight a proof about THIS writer rather than about a laxer one.

    Raises `TypeError` / `ValueError` for anything not JSON-representable. The
    caller must not swallow that: it happens before any mutation, and refusing
    to start is the safe direction.
    """
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True,
                      allow_nan=False) + "\n"


def _fsync_directory(directory: str) -> None:
    """fsync the DIRECTORY entry, so the `os.replace` that published the record
    is itself durable. Without this, a crash can lose the whole record even
    though its bytes were flushed -- the rename is a directory-entry change, and
    an fsync of the file does not cover it."""
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _atomic_write_record(path: str, payload: Dict[str, Any]) -> None:
    """Write `payload` to `path` durably: temp file in the same directory, write,
    flush, fsync the contents, atomic `os.replace`, then fsync the directory.

    Mirrors the temp-file + fsync + replace pattern this package already carries
    privately in `lifecycle_state`, `_ext_write_state`, `run_envelope` and
    others, with the one deliberate addition of the directory fsync (see
    `_fsync_directory`). On ANY failure the temp file is removed and the error
    propagates, so an interrupted write leaves the prior record byte-identical
    rather than truncated.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    text = serialize_journal_payload(payload)
    fd, tmp = tempfile.mkstemp(prefix=".trial_journal.", suffix=".tmp",
                               dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        _fsync_directory(directory)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _usable_unit_id(unit_id: Any) -> bool:
    return isinstance(unit_id, str) and bool(unit_id.strip())


_TRIAL_ID_EXTRA_CHARS = "-_."


def _validated_trial_id(trial_id: Any) -> str:
    """Return `trial_id` unchanged if it is safe to use as a filename stem; raise
    otherwise.

    Deliberately VALIDATES rather than sanitizes. Rewriting an unsafe id would
    map two distinct trial ids onto one file, and the second trial would then
    clobber the first trial's recovery record. `open_trial_journal`'s write-once
    refusal would not even catch it: from the filesystem's point of view the two
    trials are the same trial.
    """
    if not (isinstance(trial_id, str) and trial_id):
        raise TrialJournalError(
            f"a trial id must be a non-empty string; got {trial_id!r}")
    if trial_id in (".", ".."):
        raise TrialJournalError(
            f"the trial id {trial_id!r} is a path component, not an id")
    if trial_id.startswith("."):
        raise TrialJournalError(
            f"the trial id {trial_id!r} may not begin with '.' -- a journal is a "
            "durable record, not a hidden file")
    bad = sorted({ch for ch in trial_id
                  if not (ch.isalnum() or ch in _TRIAL_ID_EXTRA_CHARS)})
    if bad:
        raise TrialJournalError(
            f"the trial id {trial_id!r} contains the character(s) {bad}, which "
            "are not allowed. Use letters, digits, and any of "
            f"{_TRIAL_ID_EXTRA_CHARS!r}. The id is NOT rewritten to fit, because "
            "rewriting two different ids onto one filename would let one trial "
            "overwrite another trial's recovery record.")
    return trial_id


def _new_trial_id() -> str:
    return f"trial-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:12]}"


def _journal_path(trial_id: str, journal_dir: Optional[str]) -> str:
    directory = journal_dir if journal_dir else DEFAULT_TRIAL_JOURNAL_DIR
    return os.path.join(directory, f"{trial_id}.json")


# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------

class TrialJournal:
    """A handle on ONE trial's journal file.

    Deliberately holds no cached copy of the record: every read and every
    transition reads the file, so the disk is the single source of truth and two
    handles on the same trial (a resumed process alongside the original, say)
    cannot diverge. This mirrors `write_gate.PersistentInvocationLedger`'s
    read-fresh-every-call discipline, for the same reason.

    Obtain one from `open_trial_journal` (a new trial) or `load_trial_journal`
    (an existing one). Constructing this class directly gets you a handle, not an
    authorization: it cannot create a journal, and every method here refuses on a
    record that is absent or does not validate.
    """

    def __init__(self, trial_id: str, *, journal_dir: Optional[str] = None) -> None:
        self._trial_id = _validated_trial_id(trial_id)
        self._dir = journal_dir if journal_dir else DEFAULT_TRIAL_JOURNAL_DIR
        self._path = _journal_path(self._trial_id, self._dir)
        self._lock_path = self._path + ".lock"

    # -- identity ------------------------------------------------------------

    @property
    def trial_id(self) -> str:
        return self._trial_id

    @property
    def path(self) -> str:
        return self._path

    # -- reads ---------------------------------------------------------------

    def read_record(self) -> Dict[str, Any]:
        """The whole validated record, read fresh from disk.

        FAILS CLOSED: absent, unreadable, or malformed all RAISE. See the module
        docstring for why an empty reading is the fail-open direction for a
        recovery record even though it is the fail-safe one for a budget.
        """
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            raise TrialJournalError(
                f"there is no trial journal at {self._path!r}. A trial's "
                "write-ahead record is what makes the trial recoverable, so an "
                "absent one is never read as 'nothing was applied'.")
        except (OSError, ValueError) as exc:
            raise TrialJournalError(
                f"the trial journal at {self._path!r} could not be read as JSON "
                f"({exc!r}). It is refused rather than partially interpreted.")
        return _validated_record(raw, self._trial_id, self._path)

    def op_kind(self) -> str:
        return self.read_record()["op_kind"]

    def unit_ids(self) -> Tuple[str, ...]:
        """Every unit id, in the order the authorized plan listed them (which is
        apply order, and therefore reverse-undo order)."""
        return tuple(u["unit_id"] for u in self.read_record()["units"])

    def unit_states(self) -> Dict[str, str]:
        return {u["unit_id"]: u["state"] for u in self.read_record()["units"]}

    def unit_state(self, unit_id: str) -> str:
        return _unit_entry(self.read_record(), unit_id, self._path)["state"]

    def recovery_capsule(self, unit_id: str) -> Any:
        return _unit_entry(self.read_record(), unit_id,
                           self._path)["recovery_capsule"]

    # -- write-ahead transitions --------------------------------------------
    #
    # These two do not return until the new record is durable. Everything that
    # follows the call is authorized by a record that is already on disk.

    def record_apply_intent(self, unit_id: str) -> None:
        """Persist the INTENT to apply `unit_id`, then return.

        MUST be called before `apply_one` for this unit. Once this returns, a
        crash at any later instant leaves a durable record naming this unit as
        one whose mutation may have landed -- which is the most that can honestly
        be said, and the least that lets the unit be reversed.
        """
        self._transition(unit_id, STATE_APPLY_INTENT)

    def record_undo_intent(self, unit_id: str) -> None:
        """Persist the INTENT to reverse `unit_id`, then return.

        MUST be called before `undo_one` for this unit. Legal from
        `apply_intent` as well as from `apply_confirmed`: after a crash in the
        ambiguous window the safe resolution reverses the unit regardless of
        whether the apply landed. Legal from `recovery_required` too, and that is
        the whole of that state's exit -- a unit a prior attempt could not verify
        is reversed again under a fresh, durable intent record.

        A unit ALREADY at `undo_intent` is a distinct case a resumed driver must
        handle rather than call this for: the transition is refused, correctly,
        because the intent record it would write is already on disk. That is what
        write-ahead means, so the driver's obligation is to confirm the durable
        state IS `undo_intent` and then issue the reversal -- not to re-record.
        """
        self._transition(unit_id, STATE_UNDO_INTENT)

    # -- outcome records ----------------------------------------------------

    def record_apply_confirmed(self, unit_id: str) -> None:
        """Record that the adapter's `apply_one` RETURNED for `unit_id`.

        NOT a claim that the mutation landed on the live surface -- see the
        module docstring. Reachable only from `apply_intent`, so an executor that
        applied without a durable intent record cannot record this at all.
        """
        self._transition(unit_id, STATE_APPLY_CONFIRMED)

    def record_restored_verified(self, unit_id: str) -> None:
        """Record that `unit_id`'s prior state was observed restored.

        DISCLOSED BOUND: the caller establishes this from the adapter's
        `verify_undo_restored` predicate over observed evidence; this journal
        records the claim and cannot check it. Reachable only from `undo_intent`.
        """
        self._transition(unit_id, STATE_RESTORED_VERIFIED)

    def record_recovery_required(self, unit_id: str, *, reason: str) -> None:
        """Record that `unit_id` could not be brought back to its prior state and
        needs attention.

        `reason` is mandatory and must be non-blank: a durable blocking record
        that does not say what is wrong cannot be acted on. The record outlives
        the process that wrote it -- nothing in this module clears it, and no
        stateless reaper can.

        NOT terminal, and the distinction matters. The state has exactly ONE exit
        (`LEGAL_TRANSITIONS`): a fresh, durable `undo_intent`, then
        `restored_verified` once the observed post-condition is re-established. So
        it cannot be cleared QUIETLY -- there is no route to the settled state
        that skips the write-ahead record or the observation -- but it can be
        cleared, by doing the reversal again and observing that it worked. A
        blocking record whose repair cannot actually clear it is a state the
        operator cannot get out of, which is the failure this protocol exists to
        remove.
        """
        if not (isinstance(reason, str) and reason.strip()):
            raise TrialJournalError(
                f"recording {STATE_RECOVERY_REQUIRED!r} for unit {unit_id!r} "
                "requires a non-blank reason: a durable blocking record with no "
                "stated cause cannot be acted on.")
        self._transition(unit_id, STATE_RECOVERY_REQUIRED, reason=reason)

    # -- internals ----------------------------------------------------------

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Serialize a read-modify-write against every other process holding this
        trial's journal.

        FAILS CLOSED when POSIX advisory locking is unavailable: an unlocked
        read-modify-write can lose an update, and a lost update here is a
        state transition that never became durable -- i.e. a mutation with
        nothing on disk recording it, the exact failure this module exists to
        prevent. Repair: run the trial on a platform providing POSIX advisory
        locks.
        """
        if _fcntl is None:
            raise TrialJournalError(
                "the trial journal refuses to record a state transition without "
                "a cross-process lock: POSIX fcntl.flock is unavailable on this "
                "platform, so an atomic update of the write-ahead record cannot "
                "be guaranteed. Repair: run the trial on a platform that "
                "provides POSIX advisory locks.")
        os.makedirs(self._dir, exist_ok=True)
        with open(self._lock_path, "w", encoding="utf-8") as lock_file:
            _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_EX)
            try:
                yield
            finally:
                _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_UN)

    def _transition(self, unit_id: str, new_state: str,
                    *, reason: Optional[str] = None) -> None:
        with self._exclusive():
            record = self.read_record()
            entry = _unit_entry(record, unit_id, self._path)
            current = entry["state"]
            if new_state not in LEGAL_TRANSITIONS[current]:
                raise TrialJournalError(
                    f"unit {unit_id!r} of trial {self._trial_id!r} is at state "
                    f"{current!r}; {new_state!r} is not a legal next state "
                    f"(legal: {list(LEGAL_TRANSITIONS[current])}). "
                    + (f"{new_state!r} reports an action whose authorizing "
                       "write-ahead record is not on disk, and recording it "
                       "would claim a durability this journal does not have."
                       if new_state in OUTCOME_STATES else
                       # Checked BEFORE the terminal clause: a unit that has been
                       # applied once is never applied again, and that is a
                       # stronger, more specific fact than "this state is
                       # terminal" -- it is the reason recovery converges by
                       # reversing. Saying it plainly is what stops a future
                       # driver author reading the generic ordering sentence and
                       # concluding a re-apply is merely out of sequence.
                       "a unit is applied at most ONCE. Recovery from an "
                       "interrupted trial converges by REVERSING the unit, never "
                       "by re-applying it: re-applying would be a live write "
                       "nobody consented to at that moment."
                       if new_state == STATE_APPLY_INTENT else
                       f"{current!r} is terminal."
                       if current in TERMINAL_STATES else
                       "The trial protocol's states advance in one order only."))
            entry["state"] = new_state
            history_entry: Dict[str, Any] = {"state": new_state,
                                             "at": _now_iso_z()}
            if reason is not None:
                history_entry["reason"] = reason
            entry["history"].append(history_entry)
            _atomic_write_record(self._path, record)


def _unit_entry(record: Dict[str, Any], unit_id: str,
                path: str) -> Dict[str, Any]:
    for entry in record["units"]:
        if entry["unit_id"] == unit_id:
            return entry
    raise TrialJournalError(
        f"unit {unit_id!r} is not in the trial journal at {path!r} (it holds "
        f"{[e['unit_id'] for e in record['units']]}). A journal covers exactly "
        "the units the authorized plan carried; a unit outside that set was "
        "never authorized for this trial.")


def _validated_record(raw: Any, trial_id: str, path: str) -> Dict[str, Any]:
    """Re-validate a record read from disk. FAIL-CLOSED at consumption time, not
    merely at the moment it was written: the file is ordinary bytes on disk and
    the process reading it is usually not the process that wrote it."""
    def bad(detail: str) -> TrialJournalError:
        return TrialJournalError(
            f"the trial journal at {path!r} is not a usable "
            f"{TRIAL_JOURNAL_SCHEMA} record: {detail}. It is refused rather "
            "than partially interpreted -- a half-read recovery record is worse "
            "than none, because it looks authoritative.")

    if not isinstance(raw, dict):
        raise bad(f"the top level is a {type(raw).__name__}, not an object")
    if raw.get("schema") != TRIAL_JOURNAL_SCHEMA:
        raise bad(f"it declares schema {raw.get('schema')!r}")
    if raw.get("trial_id") != trial_id:
        raise bad(f"it declares trial_id {raw.get('trial_id')!r}, but it was "
                  f"loaded as {trial_id!r}")
    op_kind = raw.get("op_kind")
    if not (isinstance(op_kind, str) and op_kind.strip()):
        raise bad(f"its op_kind is {op_kind!r}")
    units = raw.get("units")
    if not (isinstance(units, list) and units):
        raise bad("it lists no units")

    seen = set()
    for index, entry in enumerate(units):
        if not isinstance(entry, dict):
            raise bad(f"unit entry #{index} is a {type(entry).__name__}")
        unit_id = entry.get("unit_id")
        if not _usable_unit_id(unit_id):
            raise bad(f"unit entry #{index} has an unusable unit_id "
                      f"({unit_id!r})")
        if unit_id in seen:
            raise bad(f"unit_id {unit_id!r} appears more than once, so two "
                      "distinct mutations share one record and one capsule")
        seen.add(unit_id)
        if entry.get("state") not in TRIAL_UNIT_STATES:
            raise bad(f"unit {unit_id!r} is at the unrecognized state "
                      f"{entry.get('state')!r}")
        if not isinstance(entry.get("history"), list):
            raise bad(f"unit {unit_id!r} has no history list")
        capsule_reason = validate_recovery_capsule(
            op_kind, unit_id, entry.get("recovery_capsule"))
        if capsule_reason:
            raise bad(capsule_reason)
    return raw


def open_trial_journal(plan: Any, *, trial_id: Optional[str] = None,
                       journal_dir: Optional[str] = None) -> TrialJournal:
    """Open the write-ahead journal for an authorized trial, and return the
    handle. The full plan and EVERY unit's recovery capsule are durable on disk
    before this function returns — and therefore before the trial's first
    mutation, because the caller has no units to apply until it holds the handle.

    `plan` must be an `AuthorizedPlan` that
    `write_authorization.authorize_operation` issued for the TRIAL intent. That
    is the only source of the units, the capsules and the resolved target; this
    module derives none of them and re-plans nothing. The plan's own trial
    invariants are re-checked here rather than assumed, so a plan rewritten after
    it was issued does not open a journal.

    `trial_id` is minted when omitted. A supplied one is VALIDATED, never
    rewritten (see `_validated_trial_id`), and the open FAILS if a journal
    already exists for it: a trial id is write-once, and clobbering a prior
    trial's recovery record is the one thing this file must never do.

    Raises `TrialJournalError` for anything that would produce a journal a
    recovery path could not use. Nothing is written when it raises.
    """
    if not isinstance(plan, AuthorizedPlan):
        raise TrialJournalError(
            "a trial journal is opened from an AuthorizedPlan issued by "
            "write_authorization.authorize_operation; got a "
            f"{type(plan).__name__}. There is no other route: the plan is the "
            "only carrier of the units, the capsules and the authorization "
            "behind them.")
    if plan.intent != EXECUTION_INTENT_TRIAL:
        raise TrialJournalError(
            f"this plan carries the {plan.intent!r} execution intent; a trial "
            f"journal may only be opened for the {EXECUTION_INTENT_TRIAL!r} "
            "intent. An ordinary-intent plan never went through the "
            "trial-eligibility preflight, so nothing has established that its "
            "units can be reversed.")
    if plan.resolved_target != TRIAL_TARGET:
        raise TrialJournalError(
            f"this plan resolves to target {plan.resolved_target!r}; a trial "
            f"journal records a trial against {TRIAL_TARGET!r} only.")

    units = tuple(plan.units or ())
    if not units:
        raise TrialJournalError(
            "this plan carries no effect units, so there is nothing to journal "
            "and nothing a trial could reverse or observe.")

    unit_ids = []
    for index, unit in enumerate(units):
        if not isinstance(unit, EffectUnit):
            raise TrialJournalError(
                f"planned entry #{index} is a {type(unit).__name__}, not an "
                "EffectUnit; the journal reads unit_id off an EffectUnit.")
        if not _usable_unit_id(unit.unit_id):
            raise TrialJournalError(
                f"planned unit #{index} has an unusable unit_id "
                f"({unit.unit_id!r}); every per-unit state and capsule is keyed "
                "on it, through JSON, so it must be a non-blank string.")
        if unit.unit_id in unit_ids:
            raise TrialJournalError(
                f"unit_id {unit.unit_id!r} appears more than once in this plan. "
                "The journal keys each per-unit state and capsule on unit_id, so "
                "duplicates would collapse two distinct mutations into one "
                "record -- and one of them would be applied and never undone.")
        unit_ids.append(unit.unit_id)

    capsules = plan.recovery_capsules
    if not isinstance(capsules, Mapping):
        raise TrialJournalError(
            "this plan carries recovery capsules as a "
            f"{type(capsules).__name__}, not a mapping of unit_id -> capsule, so "
            "no unit's capsule can be located.")
    op_kind = plan.op.op_kind
    for unit_id in unit_ids:
        if unit_id not in capsules:
            raise TrialJournalError(
                f"no recovery capsule was supplied for unit {unit_id!r} of "
                f"{op_kind!r}. The journal must be able to reverse that unit "
                "from disk alone after a crash, so the trial does not start "
                "without one.")
        reason = validate_recovery_capsule(op_kind, unit_id, capsules[unit_id])
        if reason:
            raise TrialJournalError(reason)
    extra = sorted(set(capsules) - set(unit_ids))
    if extra:
        raise TrialJournalError(
            f"the recovery capsules include entries for {extra}, which this plan "
            "does not apply. A capsule set that does not match the plan was "
            "built for a different plan, and using it would file a capsule "
            "against the wrong unit.")

    resolved_id = _validated_trial_id(trial_id) if trial_id is not None \
        else _new_trial_id()
    journal = TrialJournal(resolved_id, journal_dir=journal_dir)

    opened_at = _now_iso_z()
    record = {
        "schema": TRIAL_JOURNAL_SCHEMA,
        "trial_id": resolved_id,
        "op_kind": op_kind,
        "surface": plan.op.surface,
        "operation_digest": plan.op.digest(),
        "resolved_target": plan.resolved_target,
        "opened_at": opened_at,
        "units": [
            {
                "unit_id": unit_id,
                "state": STATE_PLANNED,
                "recovery_capsule": capsules[unit_id],
                "history": [{"state": STATE_PLANNED, "at": opened_at}],
            }
            for unit_id in unit_ids
        ],
    }

    # The REAL JSON round trip, run here -- before any file, directory entry or
    # lock exists. The capsules were checked for FORMAT above; serializability is
    # not re-implemented anywhere (that check has one owner, the trial-eligibility
    # preflight), and this is the actual write's own serializer, so a capsule that
    # cannot be written refuses the OPEN rather than surfacing as a raw
    # `json.dumps` error out of an entrypoint that documents `TrialJournalError` --
    # or, far worse, at a transition after a mutation had already been issued.
    # `_atomic_write_record` below re-serializes the same object with the same
    # function and so cannot fail differently.
    try:
        serialize_journal_payload(record)
    except (TypeError, ValueError) as exc:
        raise TrialJournalError(
            f"the trial journal for {op_kind!r} cannot be serialized to JSON "
            f"({exc!r}), so it could not be written before the first mutation and "
            "the trial does not start. The journal is JSON on disk and every "
            "recovery capsule must survive the round trip; one that carries a "
            "set, a custom object, NaN or Infinity cannot. Fix step: have the "
            "adapter render JSON-representable values into "
            f"{CAPSULE_KEY_TARGET_REF} / {CAPSULE_KEY_UNDO_REF}. Units in this "
            f"plan: {unit_ids}.") from exc

    # The existence check lives INSIDE the exclusive section, so two processes
    # opening the same trial id cannot both pass it. `run_envelope`'s write-once
    # helper checks existence outside any lock; here the lock is already required
    # for every transition, so using it closes that race at no extra cost.
    with journal._exclusive():
        # `os.lstat`, never `os.path.exists`: a fail-closed filesystem check must
        # distinguish ABSENT from INACCESSIBLE. `os.path.exists` answers False for
        # both (and for a dangling symlink), so a permission error here would be
        # read as "no prior trial" and this open would proceed to overwrite a
        # record that may be the only thing that knows a real mutation is
        # outstanding. `lstat` rather than `stat` so a symlink at the journal path
        # counts as PRESENT on its own terms -- a dangling one included, since
        # that is not a state a write-ahead record should be published into.
        try:
            os.lstat(journal.path)
        except FileNotFoundError:
            pass  # genuinely absent -- the one state a new trial may open in
        except OSError as exc:
            raise TrialJournalError(
                "could not determine whether a trial journal already exists at "
                f"{journal.path!r} -- the path is INACCESSIBLE, not absent "
                f"({exc!r}). Refusing rather than assuming there is nothing "
                "there: treating an inaccessible path as empty is how a write-once "
                "record gets overwritten. Fix step: make the trial-journal "
                "directory readable, or open the trial under a fresh id.") from exc
        else:
            raise TrialJournalError(
                f"a trial journal already exists at {journal.path!r}. A trial id "
                "is write-once: reusing one would overwrite a prior trial's "
                "recovery record, which may be the only thing that knows a real "
                "mutation is outstanding. Use load_trial_journal to resume that "
                "trial, or open a new one under a fresh id.")
        _atomic_write_record(journal.path, record)
    return journal


def load_trial_journal(trial_id: str, *,
                       journal_dir: Optional[str] = None) -> TrialJournal:
    """Return a handle on the EXISTING journal for `trial_id`, having confirmed
    the record on disk validates.

    FAILS CLOSED: an absent, unreadable or malformed record raises. It is never
    read as an empty journal -- that would report "nothing was applied", which is
    the one thing a missing recovery record cannot establish.
    """
    journal = TrialJournal(trial_id, journal_dir=journal_dir)
    journal.read_record()
    return journal


# ---------------------------------------------------------------------------
# DISCOVERY FROM DURABLE STATE
#
# Why this is here, and why it may not depend on anything having been printed.
# Process-kill fault injection over this protocol measured that at 100% of
# trial-side kill points the killed process emits ZERO bytes on stdout and
# stderr -- including kills that leave a live, unreversed mutation on the
# operator's real record. The command that puts such a unit back works, and the
# refusal that NAMES that command is real, but both are produced by code the kill
# prevented from running. After the kill the trial id survives in exactly one
# place: the name of a file in this directory.
#
# So the only honest way to discover an interrupted trial is to READ THE FILES,
# and that is what this section does. It is a read-only observer: it never writes,
# never locks, and never self-heals anything it finds. A self-healing read path is
# a WRITE path, and the record it would be repairing is the only evidence that a
# real mutation is outstanding.
# ---------------------------------------------------------------------------

#: The `.json` files in the journal directory that are NOT a published journal:
#: the atomic-write temp files a killed process leaves behind (which carry a
#: partial record and were never published) and the advisory lock files. Skipped
#: by name because that is what they are -- the temp prefix and the lock suffix
#: are this module's own, declared in `_atomic_write_record` / `TrialJournal`.
_TEMP_RECORD_PREFIX = ".trial_journal."
_LOCK_SUFFIX = ".lock"


def outstanding_unit_ids(record: Any) -> Tuple[str, ...]:
    """Every unit id in `record` that may STILL be outstanding on the operator's
    live record, resolved through `recovery_disposition` rather than by re-listing
    the driven states here.

    FAIL-CLOSED IN THE DIRECTION THAT MATTERS. A state the disposition map does
    not carry counts as OUTSTANDING. That is the whole reason this is a function
    and not an `in RECOVERY_DRIVEN_STATES` test at the call site: a consumer that
    resolved the question negatively -- "anything not driven and not settled was
    never applied" -- absorbs any state added later into the benign bucket, and a
    unit holding a live unreversed mutation would then be reported as never
    applied. `recovery_disposition` returns None for exactly that case, and None
    resolves here to "still outstanding", never to "nothing to do".

    Takes the record rather than a journal handle so the branch above is
    reachable in a test: the validated read path cannot produce an unclassified
    state today, and a fail-closed branch nothing exercises is a latent failure.

    Takes a record that has already been through `_validated_record`, so the SHAPE
    is not re-checked here. A malformed unit entry raises, and the caller catches
    it per-record -- see `scan_outstanding_trials`. It deliberately does NOT carry
    a shape fallback of its own: the only one that would fit is a synthetic unit id
    nothing can act on, and a discovered outstanding unit with no actionable id is
    the dead end this protocol exists to remove. Refusing the whole record is
    honest; inventing an id for it is not.
    """
    outstanding = []
    for entry in (record or {})["units"]:
        state = entry.get("state")
        disposition = recovery_disposition(state) if isinstance(state, str) else None
        if disposition in (RECOVERY_DISPOSITION_NEVER_APPLIED,
                           RECOVERY_DISPOSITION_SETTLED):
            continue
        outstanding.append(str(entry.get("unit_id")))
    return tuple(outstanding)


def scan_outstanding_trials(*, journal_dir: Optional[str] = None) -> Dict[str, Any]:
    """Every trial journal on disk that may still hold an outstanding change.

    Returns a plain, JSON-serializable dict::

        {"trials":     [{"trial_id", "path", "op_kind",
                         "outstanding_unit_ids", "unit_states"}, ...],
         "unreadable": [{"path", "reason"}, ...],
         "scan_error": None or a plain-language reason}

    IDENTITY IS JOINED ON THE DECLARED VALUE. A filename is a CANDIDATE id, never
    the identity: each candidate is loaded through this module's own validated
    read, which refuses a record whose declared `trial_id` disagrees with the name
    it was loaded as. A disagreement lands in `unreadable` -- it is reported, never
    resolved by picking one of the two.

    ABSENT IS NOT INACCESSIBLE. A project that has never run a trial has no
    directory, and that is the overwhelmingly common case: it must report nothing
    outstanding, because a check that fires on every deployment is worse than no
    check. A directory that EXISTS but cannot be read is the opposite -- nothing
    can be established about it -- and sets `scan_error`. The two are distinguished
    with `os.stat`, not `os.path.isdir`, because `isdir` answers False for both.

    FAIL-CLOSED, AND BOUNDED. Anything unreadable is reported rather than skipped,
    so the caller can withhold an all-clear. The input set is exactly this one
    directory's own `.json` files, which is what keeps a fail-closed answer from
    being able to brick anything else.
    """
    directory = journal_dir if journal_dir else DEFAULT_TRIAL_JOURNAL_DIR
    result: Dict[str, Any] = {"trials": [], "unreadable": [], "scan_error": None}

    try:
        mode = os.stat(directory).st_mode
    except FileNotFoundError:
        # Never ran a trial. Nothing outstanding, and nothing to say about it.
        return result
    except OSError as exc:
        result["scan_error"] = (
            f"the record of trial runs at {directory!r} could not be examined "
            f"({exc.strerror or exc!r}), so it is not possible to tell whether a "
            "trial was interrupted with a change still outstanding")
        return result
    if not stat.S_ISDIR(mode):
        result["scan_error"] = (
            f"{directory!r} is where the record of trial runs belongs, but it is "
            "not a folder, so it is not possible to tell whether a trial was "
            "interrupted with a change still outstanding")
        return result

    try:
        names = sorted(os.listdir(directory))
    except OSError as exc:
        result["scan_error"] = (
            f"the record of trial runs at {directory!r} could not be listed "
            f"({exc.strerror or exc!r}), so it is not possible to tell whether a "
            "trial was interrupted with a change still outstanding")
        return result

    for name in names:
        if name.startswith(_TEMP_RECORD_PREFIX) or name.endswith(_LOCK_SUFFIX):
            continue
        if not name.endswith(".json"):
            continue
        candidate_id = name[: -len(".json")]
        path = os.path.join(directory, name)
        # Everything derived from this record is inside the try, deliberately: a
        # record whose shape defeats any step of it is reported as UNREADABLE and
        # the sweep continues. Deriving outside would let one malformed file abort
        # the whole scan and take every other trial's discoverability with it --
        # which is fail-closed in the narrow sense and useless in the real one.
        try:
            record = TrialJournal(candidate_id,
                                  journal_dir=directory).read_record()
            entry = {
                "trial_id": record["trial_id"],
                "path": path,
                "op_kind": record["op_kind"],
                "outstanding_unit_ids": list(outstanding_unit_ids(record)),
                "unit_states": {u["unit_id"]: u["state"]
                                for u in record["units"]},
            }
        except Exception as exc:  # noqa: BLE001 -- reported, never swallowed.
            result["unreadable"].append({"path": path, "reason": str(exc)})
            continue
        if not entry["outstanding_unit_ids"]:
            continue
        result["trials"].append(entry)
    result["trials"].sort(key=lambda t: t["trial_id"])
    return result
