"""PROCESS-KILL FAULT INJECTION over the trial protocol (Cut 1.9 Task 6).

This file kills the process for real -- `os._exit`, no unwinding, no cleanup
handlers -- at every point where the trial protocol makes something durable or
calls out to the operator's live account, and then asserts what an operator would
find afterwards. It is empirical evidence about crash behaviour rather than
coverage of code paths: the question at each point is not "did this line run" but
"if the machine died exactly here, is the operator's record intact, does the
durable record say what actually happened, and is the operator told the truth
about it".

------------------------------------------------------------------------------
The pass condition, and it is the only one
------------------------------------------------------------------------------
Every kill point must resume to RESTORED-AND-VERIFIED or to RECOVERY-REQUIRED
WITH A RESUMABLE COMMAND. Never to a silently-green state, and never to an
unrecorded one -- where "unrecorded" means any of:

  * the journal exists but a mutation happened that it does not name;
  * the journal says a unit is settled when the surface is not;
  * the process died leaving nothing on disk at all where a mutation had already
    been attempted.

------------------------------------------------------------------------------
THREE assertion surfaces at every kill point, because any one alone can lie
------------------------------------------------------------------------------
  1. THE EXTERNAL SURFACE -- a real JSON file on disk, so "is it at prior state?"
     is answered by reading it rather than by asking the code.
  2. THE JOURNAL -- does its durable record match what actually happened?
  3. THE OPERATOR-FACING TEXT AND EXIT CODE -- does what the operator is told
     match reality?

The third is not decoration. Twice in this cut a mechanism was correct while the
sentence the operator reads was false, and this project's most expensive finding
was a continuity promise that was false when written. So the truth check here is
anchored on the SURFACE, never on the journal: `assertClaimMatchesSurface` derives
what the output is ALLOWED to claim from the surface file's own contents, and a
run that tells the operator nothing is outstanding while the surface is still
changed FAILS -- whatever the journal says.

WHICH KILL POINTS CARRY WHICH SURFACES, stated exactly rather than as "all three
everywhere", because this file's output is evidence and an overstated scope is the
one defect it cannot afford:

  * Every kill point that leaves a journal on disk carries all three: surfaces 1
    and 2 at the instant of the kill, then the resume, then all three again
    (`assertResumesToTerminal`).
  * The six PRE-JOURNAL kill points (`read_client.build`, `write_client.build`,
    the two `ledger.*`, and the two journal-open instants before the publish)
    carry surfaces 1 and 2 only, and cannot carry the third: there is no journal
    to resume from, so no operator-facing producer exists to read. Their coverage
    is `assertNothingWasMutatedAndNoJournalExists` — nothing mutated, no durable
    record — plus `test_an_absent_journal_is_never_read_as_nothing_was_applied`,
    which drives the real command against a non-existent trial and requires a
    fail-closed refusal that does NOT claim an all-clear. That is the correct
    coverage for a state with no record, not a weaker version of the other one.
  * A killed process emits nothing on either stream, so at every trial-side kill
    point surface 3 is produced by the RESUME rather than by the killed run. The
    trial executor's own refusal is asserted separately, by
    `test_the_TRIALS_OWN_refusal_text_is_true_when_a_unit_is_left_changed`, which
    reaches it the only way a killed run cannot: by letting the trial finish.

------------------------------------------------------------------------------
The kill is a real kill
------------------------------------------------------------------------------
`os._exit(137)`, never an exception. An exception unwinds and runs cleanup
handlers, which is precisely what a crash does not do, so a test that raises
proves the wrong thing. The interruptions in
`test_external_write_trial_recovery.py` raise a `BaseException` and say so
plainly; this file is the other thing.

Fault injection has two arms, and neither one edits product code:

  * `killswitch.install()` patches the STDLIB PRIMITIVES the journal, the proof
    writer and the blast-radius ledger call -- `tempfile.mkstemp`, `os.fsync`,
    `os.replace`, `os.open` -- so the process can be killed at a named instant
    INSIDE one atomic write. It is loaded through `sitecustomize`, so the
    operator's command line is byte-identical to the rendered production one.
  * the fixture adapter calls `killswitch.kill_if(...)` at its own external-call
    boundaries (before/after the vendor mutation, before/after the vendor read,
    at client provisioning), which is where the adapter contract puts them.

The write being killed is identified from the DECLARED schema inside the
half-written temp file plus the state that CHANGED relative to the record on disk
-- never from the filename or the call ordinal, except at `*.before_mkstemp` /
`*.after_mkstemp` where nothing has been written yet and there is nothing else to
key on. Those two instants therefore carry an ordinal, and every test that uses
one also asserts the resulting on-disk state, so a mis-aimed kill fails rather
than passing quietly.

------------------------------------------------------------------------------
WHAT PROCESS-KILL CANNOT PROVE -- stated so nothing here is read as more
------------------------------------------------------------------------------
A process kill is not a power loss. When a process dies, the bytes it wrote and
flushed are still in the operating system's cache and still land on disk, so a
kill BEFORE an `fsync` and a kill AFTER it leave the same file. What the fsync
sub-points here do prove is the ORDER: that at the instant of the kill the record
had or had not been PUBLISHED (the `os.replace`), and therefore whether the
mutation the record authorizes could already have been issued. The durability of
each individual fsync against machine-level power loss is not observable by this
method and is not claimed by it. What is claimed -- and asserted -- is that the
sequence exists: a test that kills at `after_dir_fsync` fails if the directory
fsync is removed, because then nothing dies there.

------------------------------------------------------------------------------
What is REUSED from the prior task's harness, and what is not
------------------------------------------------------------------------------
Reused, deliberately, because it is the part that has to be faithful: the project
SHAPE and the ENROLMENT MECHANISM. The emitted lib is copied into a real operator
project, the adapter is enrolled through the shipped `operator_adapters.json`
route so a fresh process registers it with no import a test controls, the reader
sits in its own `read_facades_*` module that nothing imports, and the recovery
command is the one the shipped `recovery_command` renders, run as a subprocess
from the project root.

NOT reused: the fixture SOURCES. The prior harness's adapter kills at one place,
unconditionally, on the presence of a marker file -- it cannot express a named
kill point, a per-unit target, an undo that no-ops, or a kill in the recovery
process rather than the trial one, and this file needs all four. Folding those
into the prior fixture would make a reviewed, green fixture depend on a spec file
and a kill switch, changing the surface of tests that are not this task's. The
duplication is therefore in the fixture's CONTRACT SHAPE only (the same declared
absolute-state restore, the same contract fields), and it fails LOUDLY rather than
drifting: a change to the adapter contract or to `OperationContract` breaks both
fixtures visibly instead of leaving one quietly testing an older shape.

The enumeration is CODE, not prose
------------------------------------------------------------------------------
`BoundaryEnumerationTests` derives every persistence and external-call boundary
in the three modules from their own ASTs and requires the declared enumeration
below to match it exactly, and requires every declared boundary to carry one of
four DECLARED dispositions — killed at, bracketed by instants that are killed at,
excluded by a contract property, or untested with a stated reason. A later task
that adds an `apply_one` call site, a `record_*` site or a second atomic writer
lands in no disposition and fails until it declares the boundary and kills at it.

WHAT THAT GUARD DOES AND DOES NOT CATCH, scoped honestly, because an earlier
version of this claim was broader than the mechanism:

  * CAUGHT: any call to a filesystem mutator in the declared surface of the
    modules this code may import — `os`, `shutil`, `tempfile`, `pathlib`, `json`,
    `io` — whether or not the protocol uses that name today. The vocabulary is
    drawn from those modules' mutating surface, not from observed usage, and
    `test_a_second_durable_writer_BUILT_FROM_UNUSED_NAMES_is_caught` proves it by
    injecting a whole second durable writer spelled with three names the protocol
    never calls. `open` and `os.open` are classified by mode and by flags rather
    than by name, so the lock file's creating `open` is a boundary and the
    journal's read-mode one is not.
  * CAUGHT, fail-closed: any call rooted at one of those modules whose member is
    classified as neither mutating nor read-only. Silence refuses rather than
    defaulting to harmless.
  * NOT CAUGHT: a mutation reached through a callable resolved at run time
    (`getattr`, a name bound from a table) or through a module outside the
    declared import allowlist. Static derivation cannot see either. What bounds
    the first is that these modules are stdlib-only and kernel-zoned; what would
    catch the second is the zone scanner, not this file.

"The brief didn't list it" stops being available as an answer. "No name I
recognised" is now also unavailable.

Uses a file-backed fixture adapter in a real operator-project layout; no network.
Every test writes into its own temp directory.
"""

import ast
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import trial_executor as tx  # noqa: E402
from external_write import trial_journal as tj  # noqa: E402
from external_write import trial_recovery as trc  # noqa: E402

_EXTERNAL_WRITE_DIR = _AGENTS_LIB / "external_write"
_THIS_FILE = Path(__file__).resolve()

# The fixture surface's two states, as the operator's real record would show them.
PRIOR = ["OPEN"]
APPLIED = ["ARCHIVED"]

# The status a killed process exits with. Distinct from every exit code the
# product's own CLIs use (0 / 1 / 2), so "was it really killed?" is assertable.
KILL_STATUS = 137


# ===========================================================================
# 1. THE DECLARED ENUMERATION
#
# Derived from the code (see BoundaryEnumerationTests, which re-derives it and
# requires this to match), not from the plan's list. Spelled
# `module:function:callee`. Several boundaries appear at more than one call site
# in the same function -- `record_recovery_required` sits in three branches of
# `_drive_unit` -- and those collapse to one entry, because the boundary is the
# same durable write reached by three routes.
# ===========================================================================

DECLARED_PERSISTENCE_BOUNDARIES = frozenset({
    # -- the trial executor's own writes -----------------------------------
    "trial_executor:run_trial:open_trial_journal",
    "trial_executor:_drive_unit:record_apply_intent",
    "trial_executor:_drive_unit:record_apply_confirmed",
    "trial_executor:_drive_unit:record_undo_intent",
    "trial_executor:_drive_unit:record_restored_verified",
    "trial_executor:_drive_unit:record_recovery_required",
    "trial_executor:run_trial:_atomic_write_json",
    # -- the proof writer's interior ---------------------------------------
    "trial_executor:_atomic_write_json:makedirs",
    "trial_executor:_atomic_write_json:mkstemp",
    "trial_executor:_atomic_write_json:fdopen",
    "trial_executor:_atomic_write_json:write",
    "trial_executor:_atomic_write_json:flush",
    "trial_executor:_atomic_write_json:fsync",
    "trial_executor:_atomic_write_json:replace",
    "trial_executor:_atomic_write_json:remove",
    # -- the journal's own transitions and its write-once open -------------
    "trial_journal:_transition:_atomic_write_record",
    "trial_journal:open_trial_journal:_atomic_write_record",
    # -- the journal writer's interior -------------------------------------
    "trial_journal:_atomic_write_record:makedirs",
    "trial_journal:_atomic_write_record:mkstemp",
    "trial_journal:_atomic_write_record:fdopen",
    "trial_journal:_atomic_write_record:write",
    "trial_journal:_atomic_write_record:flush",
    "trial_journal:_atomic_write_record:fsync",
    "trial_journal:_atomic_write_record:replace",
    "trial_journal:_atomic_write_record:remove",
    "trial_journal:_fsync_directory:fsync",
    # -- the cross-process lock every transition and the open take ---------
    "trial_journal:_exclusive:makedirs",
    # `open(self._lock_path, "w")` CREATES AND TRUNCATES a real file. Derived
    # because `open` is classified by its mode, which is also what keeps
    # `read_record`'s read-mode `open` correctly out of this set.
    "trial_journal:_exclusive:open",
    "trial_journal:_exclusive:flock",
    # -- recovery's writes -------------------------------------------------
    # `record_recovery_required` sits in the NESTED `_blocked`, and the
    # attribution says so rather than merging it into its outer function.
    "trial_recovery:_converge_unit:record_undo_intent",
    "trial_recovery:_converge_unit:record_restored_verified",
    "trial_recovery:_converge_unit._blocked:record_recovery_required",
})

DECLARED_EXTERNAL_CALL_BOUNDARIES = frozenset({
    "trial_executor:_planned_units:plan",
    "trial_executor:run_trial:resolve_read_only_client",
    "trial_executor:run_trial:resolve_write_client",
    "trial_executor:_drive_unit:apply_one",
    "trial_executor:_drive_unit:undo_one",
    "trial_executor:_drive_unit:observe_unit",
    "trial_executor:observe_unit:verify_one",
    "trial_recovery:recover_trial:resolve_write_client",
    "trial_recovery:_read_facade:resolve_read_only_client",
    "trial_recovery:_converge_unit:undo_one",
    "trial_recovery:_converge_unit:observe_unit",
})

# One boundary on the trial's enforced path that lives OUTSIDE the three modules
# and is reached only through them: the blast-radius ledger's atomic reserve,
# inside `authorize_operation`. It is a durable write that happens BEFORE the
# journal exists, so a kill around it is the one case where a trial can consume
# something of the operator's with no record of a trial at all. Enumerated
# separately because it is not this cut's code, and killed at anyway.
DECLARED_OFF_MODULE_BOUNDARIES = frozenset({
    "write_gate:reserve:replace",
})

# Every kill point this file exercises, mapped to the boundary or boundaries it
# covers. `BoundaryEnumerationTests` requires the union of the values to cover
# every declared boundary, and requires the keys to be exactly the points the
# tests below actually pass to the harness (read off this file's own AST -- a
# point declared here and never used is as much a gap as the reverse).
KILL_POINT_COVERAGE = {
    # --- the write-once open of the journal -------------------------------
    "journal.before_mkstemp": ("trial_journal:open_trial_journal:_atomic_write_record",
                               "trial_journal:_atomic_write_record:mkstemp",
                               "trial_executor:run_trial:open_trial_journal"),
    "journal.after_mkstemp": ("trial_journal:_atomic_write_record:mkstemp",),
    "open.before_fsync": ("trial_journal:_atomic_write_record:fsync",),
    "open.after_fsync": ("trial_journal:_atomic_write_record:fsync",),
    "open.before_replace": ("trial_journal:_atomic_write_record:replace",),
    "open.after_replace": ("trial_journal:_atomic_write_record:replace",),
    "open.before_dir_fsync": ("trial_journal:_fsync_directory:fsync",),
    "open.after_dir_fsync": ("trial_journal:_fsync_directory:fsync",),
    # --- the apply-intent write-ahead record ------------------------------
    "apply_intent.before_fsync": ("trial_executor:_drive_unit:record_apply_intent",
                                  "trial_journal:_transition:_atomic_write_record"),
    "apply_intent.after_fsync": ("trial_executor:_drive_unit:record_apply_intent",),
    "apply_intent.before_replace": ("trial_executor:_drive_unit:record_apply_intent",
                                    "trial_journal:_exclusive:flock"),
    "apply_intent.after_replace": ("trial_executor:_drive_unit:record_apply_intent",),
    "apply_intent.before_dir_fsync": ("trial_executor:_drive_unit:record_apply_intent",),
    "apply_intent.after_dir_fsync": ("trial_executor:_drive_unit:record_apply_intent",),
    # --- the apply itself -------------------------------------------------
    "read_client.build": ("trial_executor:run_trial:resolve_read_only_client",),
    "write_client.build": ("trial_executor:run_trial:resolve_write_client",),
    "apply.before_mutation": ("trial_executor:_drive_unit:apply_one",),
    "apply.after_mutation": ("trial_executor:_drive_unit:apply_one",),
    "apply_confirmed.before_replace": ("trial_executor:_drive_unit:record_apply_confirmed",),
    "apply_confirmed.after_replace": ("trial_executor:_drive_unit:record_apply_confirmed",),
    "apply_confirmed.after_dir_fsync": ("trial_executor:_drive_unit:record_apply_confirmed",),
    # --- the post-apply observation ---------------------------------------
    "verify1.before_read": ("trial_executor:_drive_unit:observe_unit",
                            "trial_executor:observe_unit:verify_one"),
    "verify1.after_read": ("trial_executor:observe_unit:verify_one",),
    # --- the undo-intent write-ahead record and the reversal --------------
    "undo_intent.before_replace": ("trial_executor:_drive_unit:record_undo_intent",),
    "undo_intent.after_replace": ("trial_executor:_drive_unit:record_undo_intent",),
    "undo_intent.after_dir_fsync": ("trial_executor:_drive_unit:record_undo_intent",),
    "undo.before_mutation": ("trial_executor:_drive_unit:undo_one",),
    "undo.after_mutation": ("trial_executor:_drive_unit:undo_one",),
    "verify2.before_read": ("trial_executor:observe_unit:verify_one",),
    "verify2.after_read": ("trial_executor:observe_unit:verify_one",),
    # --- the two outcome records ------------------------------------------
    "restored_verified.before_replace": (
        "trial_executor:_drive_unit:record_restored_verified",),
    "restored_verified.after_replace": (
        "trial_executor:_drive_unit:record_restored_verified",),
    "restored_verified.after_dir_fsync": (
        "trial_executor:_drive_unit:record_restored_verified",),
    "recovery_required.before_replace": (
        "trial_executor:_drive_unit:record_recovery_required",),
    "recovery_required.after_replace": (
        "trial_executor:_drive_unit:record_recovery_required",),
    # --- proof emission ---------------------------------------------------
    "proof.before_mkstemp": ("trial_executor:run_trial:_atomic_write_json",
                             "trial_executor:_atomic_write_json:mkstemp"),
    "proof.after_mkstemp": ("trial_executor:_atomic_write_json:mkstemp",),
    "proof.before_fsync": ("trial_executor:_atomic_write_json:fsync",),
    "proof.before_replace": ("trial_executor:_atomic_write_json:replace",),
    "proof.after_replace": ("trial_executor:_atomic_write_json:replace",),
    "proof.after_dir_fsync": ("trial_executor:_atomic_write_json:fsync",),
    # --- the blast-radius ledger, off-module but on the path --------------
    "ledger.before_replace": ("write_gate:reserve:replace",),
    "ledger.after_replace": ("write_gate:reserve:replace",),
    # --- the recovery process's own boundaries ----------------------------
    "rec_write_client.build": ("trial_recovery:recover_trial:resolve_write_client",),
    "rec_read_client.build": ("trial_recovery:_read_facade:resolve_read_only_client",),
    "rec_undo_intent.before_replace": (
        "trial_recovery:_converge_unit:record_undo_intent",),
    "rec_undo_intent.after_replace": (
        "trial_recovery:_converge_unit:record_undo_intent",),
    "rec_undo.before_mutation": ("trial_recovery:_converge_unit:undo_one",),
    "rec_undo.after_mutation": ("trial_recovery:_converge_unit:undo_one",),
    "rec_verify1.before_read": ("trial_recovery:_converge_unit:observe_unit",),
    "rec_verify1.after_read": ("trial_recovery:_converge_unit:observe_unit",),
    "rec_restored_verified.before_replace": (
        "trial_recovery:_converge_unit:record_restored_verified",),
    "rec_restored_verified.after_replace": (
        "trial_recovery:_converge_unit:record_restored_verified",),
    "rec_recovery_required.before_replace": (
        "trial_recovery:_converge_unit._blocked:record_recovery_required",),
    "rec_recovery_required.after_replace": (
        "trial_recovery:_converge_unit._blocked:record_recovery_required",),
}

# Boundaries excluded by a CONTRACT PROPERTY rather than by a coverage argument.
# Recorded so a later reader can tell a judged exclusion from a miss: the callee is
# derived, so its absence from the kill points is a declared decision with a
# reason, not silence.
BOUNDARIES_EXCLUDED_BY_CONTRACT = {
    "trial_executor:_planned_units:plan":
        "`plan()` is contractually PURE -- no reads and no writes -- which "
        "`_planned_units` states in its own docstring and relies on: it is called "
        "before authorization precisely because calling it touches no surface. So "
        "it is not an external-call boundary, and a kill there is indistinguishable "
        "from a kill anywhere else before the journal exists, which "
        "`read_client.build` already covers. If `plan()` ever became impure the "
        "trial protocol has a much larger problem than this enumeration, and the "
        "journal's capsule-set match at open is what would catch it.",
}

# Boundaries NOT killed at individually, because the whole set of states a kill
# there can leave is bracketed by two instants that ARE killed at. Recorded as
# data rather than as prose so the reason travels with the boundary and cannot
# quietly grow -- `BoundaryEnumerationTests` requires these three groups to
# PARTITION the declared set.
BOUNDARIES_BRACKETED_BY_KILLED_POINTS = {
    "trial_journal:_atomic_write_record:makedirs":
        "runs before the temp file exists; `journal.before_mkstemp` kills at the "
        "instant immediately after it and asserts the only state it can produce "
        "(the directory exists and nothing is published)",
    "trial_journal:_exclusive:makedirs":
        "same instant as above, one layer out; `apply_intent.before_replace` also "
        "kills INSIDE the exclusive section it guards",
    "trial_journal:_exclusive:open":
        "creates and truncates the `.lock` file, and every kill inside the "
        "exclusive section is downstream of it, so both sides are already "
        "observed: `read_client.build` dies before any journal work and leaves NO "
        "lock file, while `journal.before_mkstemp` and "
        "`apply_intent.before_replace` die after it and leave one -- and "
        "`test_the_stale_lock_file_a_killed_process_leaves_blocks_nothing` asserts "
        "the file is present AND that the next process is not blocked by it. It "
        "carries no operator data and no durable record, so there is no third "
        "state to find",
    "trial_executor:_atomic_write_json:makedirs":
        "as above, for the proof writer; `proof.before_mkstemp` kills immediately "
        "after it",
    "trial_journal:_atomic_write_record:fdopen":
        "inside the temp-file window. Both ends are killed at "
        "(`journal.after_mkstemp` and `open.before_replace` / "
        "`apply_intent.before_replace`), and every state reachable between them "
        "is the same one: an unpublished dotfile with a .tmp suffix",
    "trial_journal:_atomic_write_record:write":
        "writes into the temp file, so a kill here can only leave that temp file "
        "short or empty -- and nothing reads a temp file. The published record is "
        "untouched, which is what `apply_intent.before_replace` asserts",
    "trial_journal:_atomic_write_record:flush":
        "pushes the temp file's bytes to the operating system. A kill on either "
        "side leaves the same thing on disk (a process death does not discard the "
        "OS's copy) and publishes nothing, so the two instants are not "
        "distinguishable by this method -- see the module docstring's limits",
    "trial_executor:_atomic_write_json:fdopen":
        "inside the proof writer's temp-file window; both ends are killed at "
        "(`proof.after_mkstemp` and `proof.before_replace`), and every state "
        "reachable between them is an unpublished .tmp file with no artifact at "
        "the path acceptance reads from",
    "trial_executor:_atomic_write_json:write":
        "writes into the proof's temp file, so a kill here can only leave that "
        "temp file short. Nothing reads it, and `proof.before_replace` asserts "
        "the artifact is absent from the acceptance path",
    "trial_executor:_atomic_write_json:flush":
        "as for the journal writer's flush: a process kill on either side of it "
        "leaves the same unpublished temp file, so the two instants are not "
        "distinguishable by process-kill injection",
}

# Boundaries genuinely NOT kill-tested, each with the reason. Two, and they are
# the same one twice.
BOUNDARIES_NOT_KILL_TESTED = {
    "trial_journal:_atomic_write_record:remove":
        "reached ONLY from the `except` cleanup path, i.e. only once the write "
        "itself has already raised. A kill is not an exception, so process-kill "
        "fault injection cannot enter this branch at all, and inducing the "
        "exception would be testing the failure handler rather than a crash. The "
        "state it produces -- temp file gone, prior record byte-intact -- is the "
        "state `apply_intent.before_replace` already asserts by another route "
        "(`test_a_killed_transition_leaves_the_prior_record_byte_intact`)",
    "trial_executor:_atomic_write_json:remove":
        "the same exception-only cleanup branch in the proof writer, for the same "
        "reason. Its leftover-temp-file case IS covered, from the other side: "
        "`proof.after_mkstemp` asserts an unpublished temp file with the .tmp "
        "suffix and no artifact at the acceptance path",
}


# ===========================================================================
# 2. THE OPERATOR PROJECT -- sources written into a real project layout
# ===========================================================================

_FIXTURE_OP_KIND = "fixture.faultinjection.set_exact_labels"

# The kill switch. Two arms, ONE decision function, because a second copy of
# "is this the point we were told to die at?" is one more thing that has to agree.
_KILLSWITCH_SOURCE = '''\
"""Process-kill fault injection. NOT product code, and it edits none.

Arm 1 -- `install()` wraps the stdlib primitives the atomic writers call, so the
process can be killed at a named instant INSIDE one atomic write:

    makedirs -> mkstemp -> write/flush -> fsync(contents) -> replace -> fsync(dir)

Arm 2 -- `kill_if(point, unit_id)` is called by the fixture adapter at its own
external-call boundaries.

WHICH write is being killed is read from the DECLARED schema inside the temp file
the writer has already flushed, plus the unit state that CHANGED relative to the
record currently on disk. Not from the filename, and not from a call ordinal --
except at the two mkstemp instants, where nothing has been written yet and the
prefix plus an ordinal is all that exists. Every test that uses one of those also
asserts the resulting on-disk state.

Every replacement is installed as a CALLABLE OBJECT rather than as a function,
and that is load-bearing rather than stylistic. A plain function stored on a
module and then reached through an INSTANCE attribute becomes a bound method, so
`pathlib`'s accessor -- which reaches `os.open` that way -- would hand the wrapper
the accessor as an extra first argument. A callable instance is not a descriptor,
so it cannot be bound, and the wrapper receives exactly the arguments the caller
passed. (Found the hard way: the first run of this battery failed 63 of 69 tests
with `open() takes at most 3 positional arguments (4 given)` raised from inside
`Path.read_text`.)
"""
import json
import os
import stat as _stat
import sys
import tempfile

SPEC_FILE = "kill_spec.json"
KILL_STATUS = 137

_JOURNAL_SCHEMA = "trial_journal-v1"
_PROOF_SCHEMA = "copy_run_proof-v1"
_LEDGER_SCHEMA = "invocation_ledger-v1"

# Which writer a temp-file prefix belongs to. Used ONLY at the mkstemp instants.
_PREFIX_KIND = {".trial_journal.": "journal",
                ".copy_run_proof.": "proof",
                ".invocation_ledger.": "ledger"}


def role():
    """Which process this is. The spec names the process it targets, so a spec
    aimed at the recovery command installs nothing in the trial driver."""
    name = os.path.basename(sys.argv[0] or "")
    if name == "drive_trial.py":
        return "trial"
    if name == "trial_recovery.py":
        return "recovery"
    return "other"


def spec():
    """Read fresh every call: the test rewrites the spec between the trial run
    and the recovery run, and they are different processes."""
    try:
        with open(SPEC_FILE, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _armed(point, unit_id=None):
    current = spec()
    if current.get("point") != point or current.get("proc") != role():
        return False
    wanted_unit = current.get("unit")
    return wanted_unit is None or wanted_unit == unit_id


def kill_if(point, unit_id=None):
    if _armed(point, unit_id):
        os._exit(KILL_STATUS)


def _payload(path):
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def _site(tmp_path, dst_path):
    """The write site: a journal STATE, or `open`, or `proof`, or `ledger`."""
    payload = _payload(tmp_path)
    if payload is None:
        return None, None
    schema = payload.get("schema")
    if schema == _PROOF_SCHEMA:
        return "proof", None
    if schema == _LEDGER_SCHEMA:
        return "ledger", None
    if schema != _JOURNAL_SCHEMA:
        return None, None
    prior = _payload(dst_path) if dst_path else None
    if prior is None:
        return "open", None
    prior_states = {u["unit_id"]: u["state"] for u in prior.get("units", ())}
    for unit in payload.get("units", ()):
        if prior_states.get(unit["unit_id"]) != unit["state"]:
            return unit["state"], unit["unit_id"]
    return None, None


class _Unbindable:
    """A callable that is NOT a descriptor, so replacing a stdlib function with it
    is safe even where the caller reaches that function through an instance
    attribute. See the module docstring."""

    def __init__(self, call):
        self._call = call

    def __call__(self, *args, **kwargs):
        return self._call(*args, **kwargs)


def _destination_for(tmp_path):
    """The journal file this temp file is about to replace, resolved from the temp
    file's OWN declared trial id -- never from directory listing order."""
    payload = _payload(tmp_path)
    if not payload or payload.get("schema") != _JOURNAL_SCHEMA:
        return None
    trial_id = payload.get("trial_id")
    if not trial_id:
        return None
    return os.path.join(os.path.dirname(tmp_path), "%s.json" % trial_id)


def _is_directory_fd(fd):
    try:
        return _stat.S_ISDIR(os.fstat(fd).st_mode)
    except OSError:
        return False


def install():
    current = spec()
    point = current.get("point")
    if not point or current.get("proc") != role():
        return
    site_wanted, _, instant = point.rpartition(".")
    # A kill point carries a `rec_` prefix when the catalogue needs to say WHICH
    # process it targets, and the site itself is the same journal state either way
    # (`proc` is what actually selects the process). Normalized here so the
    # catalogue can stay unambiguous without the site vocabulary doubling.
    if site_wanted.startswith("rec_"):
        site_wanted = site_wanted[4:]
    wanted_unit = current.get("unit")
    ordinal_wanted = current.get("nth", 1)

    real_mkstemp = tempfile.mkstemp
    real_fsync = os.fsync
    real_replace = os.replace

    temp_fds = {}          # fd -> temp path, for the contents fsync
    armed_dir = [False]    # set by the replace that immediately precedes it
    counts = {}

    def die():
        os._exit(KILL_STATUS)

    def targeted(tmp_path, dst_path):
        site, unit_id = _site(tmp_path, dst_path)
        if site != site_wanted:
            return False
        return wanted_unit is None or unit_id is None or unit_id == wanted_unit

    def wrapped_mkstemp(*args, **kwargs):
        prefix = kwargs.get("prefix") or (args[0] if args else "")
        kind = _PREFIX_KIND.get(prefix)
        if kind is not None and kind == site_wanted:
            counts[kind] = counts.get(kind, 0) + 1
            nth = counts[kind]
            if nth == ordinal_wanted and instant == "before_mkstemp":
                die()
            fd, path = real_mkstemp(*args, **kwargs)
            temp_fds[fd] = path
            if nth == ordinal_wanted and instant == "after_mkstemp":
                die()
            return fd, path
        fd, path = real_mkstemp(*args, **kwargs)
        temp_fds[fd] = path
        return fd, path

    def wrapped_fsync(fd):
        # A directory fd is identified by `fstat`, not by remembering which
        # `os.open` produced it: `os.open` is reached through an instance
        # attribute elsewhere in the stdlib, and patching it is the route that
        # broke this harness once already.
        if _is_directory_fd(fd):
            if armed_dir[0] and instant == "before_dir_fsync":
                die()
            real_fsync(fd)
            if armed_dir[0] and instant == "after_dir_fsync":
                die()
            return None
        tmp_path = temp_fds.get(fd)
        if tmp_path is not None and instant in ("before_fsync", "after_fsync"):
            # The destination is not an argument at this instant, so the site is
            # read from the temp file's own declared schema plus the record the
            # temp file's declared trial id points at.
            if targeted(tmp_path, _destination_for(tmp_path)):
                if instant == "before_fsync":
                    die()
                real_fsync(fd)
                die()
        return real_fsync(fd)

    def wrapped_replace(src, dst, *args, **kwargs):
        hit = targeted(src, dst)
        if hit and instant == "before_replace":
            die()
        result = real_replace(src, dst, *args, **kwargs)
        if hit:
            if instant == "after_replace":
                die()
            if instant in ("before_dir_fsync", "after_dir_fsync"):
                armed_dir[0] = True
        return result

    tempfile.mkstemp = _Unbindable(wrapped_mkstemp)
    os.fsync = _Unbindable(wrapped_fsync)
    os.replace = _Unbindable(wrapped_replace)
'''

_SITECUSTOMIZE_SOURCE = '''\
"""Loads the kill switch into EVERY interpreter started with this project root on
PYTHONPATH -- including the one running the rendered production recovery command,
whose argv must stay byte-identical to what the shipped function renders."""
import killswitch

killswitch.install()
'''

_FIXTURE_ADAPTER_SOURCE = '''\
"""A trial-eligible adapter over a JSON file, for killing a real process at the
adapter contract's own external-call boundaries. Not a claim about any shipped or
operator-authored adapter -- it reproduces the CONTRACT SHAPE only, and adds
`killswitch.kill_if` calls where an adapter touches the outside world."""
import json
from pathlib import Path

import killswitch

from external_write.adapter_registry import register_adapter
from external_write.contracts import (
    OPERATION_CONTRACTS, OperationContract, WRITE_AFFECTING_MODULES,
    register_contract,
)
from external_write.operations import EffectUnit

OP_KIND = "fixture.faultinjection.set_exact_labels"
SURFACE_PATH = Path(__file__).resolve().parents[3] / "surface.json"

_reads = [0]


def _read():
    return json.loads(SURFACE_PATH.read_text(encoding="utf-8"))


def _write(state):
    SURFACE_PATH.write_text(json.dumps(state), encoding="utf-8")


class _FileWriteClient:
    def set_labels(self, unit_id, labels):
        state = _read()
        state[unit_id] = list(labels)
        _write(state)


class _FileReadOnlyClient:
    def get_state(self, unit_id):
        return {"unit_id": unit_id, "labels": sorted(_read().get(unit_id, ()))}


class FixtureFaultInjectionAdapter:
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def build_write_client(self, op):
        killswitch.kill_if("write_client.build")
        killswitch.kill_if("rec_write_client.build")
        return _FileWriteClient()

    def build_read_only_client(self, op):
        killswitch.kill_if("read_client.build")
        killswitch.kill_if("rec_read_client.build")
        return _FileReadOnlyClient()

    def plan(self, params):
        return [
            EffectUnit(unit_id=r["unit_id"],
                       target_ref={"unit_id": r["unit_id"]},
                       undo_ref={"unit_id": r["unit_id"],
                                 "prior_labels": list(r["prior_labels"])})
            for r in (params or {}).get("records", [])
        ]

    def apply_one(self, raw_client, unit):
        killswitch.kill_if("apply.before_mutation", unit.unit_id)
        raw_client.set_labels(unit.target_ref["unit_id"], ["ARCHIVED"])
        killswitch.kill_if("apply.after_mutation", unit.unit_id)

    def undo_one(self, raw_client, unit):
        killswitch.kill_if("undo.before_mutation", unit.unit_id)
        killswitch.kill_if("rec_undo.before_mutation", unit.unit_id)
        if not killswitch.spec().get("undo_noop"):
            raw_client.set_labels(unit.undo_ref["unit_id"],
                                  unit.undo_ref["prior_labels"])
        killswitch.kill_if("undo.after_mutation", unit.unit_id)
        killswitch.kill_if("rec_undo.after_mutation", unit.unit_id)

    def verify_one(self, observer, unit):
        _reads[0] += 1
        nth = _reads[0]
        killswitch.kill_if("verify%d.before_read" % nth, unit.unit_id)
        killswitch.kill_if("rec_verify%d.before_read" % nth, unit.unit_id)
        observed = observer.get_state(unit.unit_id)["labels"]
        prior = sorted((unit.undo_ref or {}).get("prior_labels", ()))
        killswitch.kill_if("verify%d.after_read" % nth, unit.unit_id)
        killswitch.kill_if("rec_verify%d.after_read" % nth, unit.unit_id)
        return {"unit_id": unit.unit_id, "observed_labels": observed,
                "applied": observed == ["ARCHIVED"],
                "matches_prestate": observed == prior}

    def verify_apply_landed(self, evidence):
        return bool(evidence.poststate.get("applied"))

    def verify_undo_restored(self, evidence):
        return bool(evidence.poststate.get("matches_prestate"))


if OP_KIND not in OPERATION_CONTRACTS:
    register_contract(OperationContract(
        op_kind=OP_KIND, writes=("labels",), produces=(),
        dependency_set=WRITE_AFFECTING_MODULES,
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=False,
        risk_class="sensitive_data", requires_accepted_phase=True,
        blast_radius_cap=25, read_only_scope="fixture.readonly"))

register_adapter(OP_KIND, FixtureFaultInjectionAdapter())
'''

_FIXTURE_FACADE_SOURCE = '''\
"""The read-only reader the declaration topology resolves for the fixture
op_kind. Its own module, declaring at top level, exactly as the shipped readers
do -- nothing imports it, which is the condition recovery has to survive."""
from external_write.read_facade import ReadFacade, register_read_facade

OP_KIND = "fixture.faultinjection.set_exact_labels"


class FixtureFaultInjectionReadFacade(ReadFacade):
    read_methods = ("get_state",)

    def get_state(self, unit_id):
        return self._read("get_state", unit_id)


register_read_facade(OP_KIND, FixtureFaultInjectionReadFacade)
'''

_TRIAL_DRIVER_SOURCE = '''\
"""Drives one real trial in the operator project, to be killed at a named
boundary. Reads `trial_spec.json` so the unit count and the ledger kind are the
test's to choose."""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "agents" / "lib"))

import external_write.registered_adapters  # noqa: F401

# The TRIAL path needs a warm read-facade registry and does not warm it itself:
# in the real flow the proposal step has already imported the declaring module by
# the time a trial runs. This driver stands in for that. The RECOVERY entrypoint
# deliberately does NOT get this line -- it runs in a fresh process where nothing
# has, which is the condition it has to survive.
import external_write.read_facades_fixturefaultinjection  # noqa: F401
from external_write import trial_executor as tx
from external_write.lifecycle_test_fixtures import hermetic_paused_mechanisms
from external_write.operations import Operation
from external_write.write_gate import InvocationLedger, PersistentInvocationLedger

OP_KIND = "fixture.faultinjection.set_exact_labels"

try:
    spec = json.loads(Path("trial_spec.json").read_text(encoding="utf-8"))
except Exception:
    spec = {}
unit_ids = spec.get("units") or ["r1"]

op = Operation(surface="fixture_surface", object_id=unit_ids[0], field="labels",
               new_value="ARCHIVED", op_kind=OP_KIND, batch_id="b1",
               params={"records": [{"unit_id": u, "prior_labels": ["OPEN"]}
                                   for u in unit_ids]})
receipt = {
    "approved_operation_digest":
        hashlib.sha256(op.canonical_repr().encode()).hexdigest(),
    "expires_at": (datetime.now(timezone.utc)
                   + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
entry = {"id": "fixture_surface", "name": "fixture_surface",
         "action_class": "modify", "risk_class": "sensitive_data",
         "recovery_profile_ref": None, "declared_test_target": "native_undo",
         "blast_radius_cap": 25, "accepted": False}

if spec.get("ledger") == "persistent":
    ledger = PersistentInvocationLedger("faultwindow", ledger_dir="security/ledger")
else:
    ledger = InvocationLedger()

with hermetic_paused_mechanisms() as paused_root:
    outcome = tx.run_trial(
        op, receipt, capability_id="fixture_capability",
        capability_module_paths=("agents/capabilities/fixture_capability.py",),
        descriptor_set=[entry], cap_ledger=ledger,
        paused_root=paused_root, journal_dir="security/trial_runs",
        proof_dir="agents/handoffs")
print(json.dumps({"ok": outcome.ok, "refusal": outcome.refusal,
                  "trial_id": outcome.trial_id}))
'''


class _Project:
    """A real operator-project layout with the emitted lib in it.

    Deliberately the same shape the prior task's harness used -- the emitted lib
    copied in, a file-backed adapter enrolled through the shipped
    `operator_adapters.json` mechanism so a fresh process registers it with no
    import the test controls, and a reader in its own module that nothing
    imports. Reused rather than rebuilt: a second harness modelling the same
    project shape is one more thing that has to agree.
    """

    def __init__(self, case, *, units=("r1",), ledger="memory"):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.case = case
        self.root = Path(tmp.name)
        self.units = tuple(units)
        lib = self.root / "agents" / "lib" / "external_write"
        shutil.copytree(
            _EXTERNAL_WRITE_DIR, lib,
            ignore=shutil.ignore_patterns("test_*.py", "__pycache__"))
        (lib / "__init__.py").touch(exist_ok=True)
        (lib / "adapters_fixturefaultinjection.py").write_text(
            _FIXTURE_ADAPTER_SOURCE, encoding="utf-8")
        (lib / "read_facades_fixturefaultinjection.py").write_text(
            _FIXTURE_FACADE_SOURCE, encoding="utf-8")
        (lib / "operator_adapters.json").write_text(
            json.dumps(["adapters_fixturefaultinjection"]), encoding="utf-8")
        (self.root / "killswitch.py").write_text(
            _KILLSWITCH_SOURCE, encoding="utf-8")
        (self.root / "sitecustomize.py").write_text(
            _SITECUSTOMIZE_SOURCE, encoding="utf-8")
        (self.root / "drive_trial.py").write_text(
            _TRIAL_DRIVER_SOURCE, encoding="utf-8")
        (self.root / "trial_spec.json").write_text(
            json.dumps({"units": list(self.units), "ledger": ledger}),
            encoding="utf-8")
        (self.root / "surface.json").write_text(
            json.dumps({u: list(PRIOR) for u in self.units}), encoding="utf-8")
        (self.root / "security" / "trial_runs").mkdir(parents=True)
        (self.root / "agents" / "handoffs").mkdir(parents=True)
        self.set_spec({})

    # -- the kill spec -----------------------------------------------------

    def set_spec(self, spec):
        (self.root / "kill_spec.json").write_text(
            json.dumps(spec), encoding="utf-8")

    # -- the three surfaces ------------------------------------------------

    def surface(self):
        """SURFACE 1 -- the operator's real record, read off disk."""
        return json.loads(
            (self.root / "surface.json").read_text(encoding="utf-8"))

    def prior_surface(self):
        return {u: list(PRIOR) for u in self.units}

    def journal_ids(self):
        return sorted(p.stem for p in
                      (self.root / "security" / "trial_runs").glob("*.json"))

    def journal_states(self, trial_id):
        """SURFACE 2 -- the durable record, read as bytes on disk rather than
        through the module that wrote it."""
        record = json.loads(
            (self.root / "security" / "trial_runs" / f"{trial_id}.json")
            .read_text(encoding="utf-8"))
        return {u["unit_id"]: u["state"] for u in record["units"]}

    def journal_temp_files(self):
        return sorted(p.name for p in
                      (self.root / "security" / "trial_runs").iterdir()
                      if p.name.startswith(".trial_journal."))

    def lock_files(self):
        return sorted(p.name for p in
                      (self.root / "security" / "trial_runs").iterdir()
                      if p.name.endswith(".lock"))

    def proofs(self):
        return sorted(p.name for p in (self.root / "agents" / "handoffs")
                      .glob("*.copy_run_proof.json"))

    def proof_temp_files(self):
        return sorted(p.name for p in (self.root / "agents" / "handoffs")
                      .iterdir() if p.name.startswith(".copy_run_proof."))

    def ledger_counts(self):
        path = self.root / "security" / "ledger" / "faultwindow.ledger.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8")).get("counts", {})

    # -- running -----------------------------------------------------------

    def _env(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.root)
        # Never leave bytecode behind in a project the next test rebuilds at the
        # same path family, and never let a stale cache answer for a source file.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def run_trial(self):
        return subprocess.run(
            [sys.executable, "drive_trial.py"], capture_output=True, text=True,
            cwd=str(self.root), env=self._env(), timeout=120)

    def run_recovery(self, trial_id):
        """SURFACE 3's producer -- the command in its PRODUCTION FORM, rendered by
        the shipped function and run from the project root with no flag the
        operator would have to understand."""
        command = trc.recovery_command(trial_id)
        self.case.assertNotIn(
            "--journal-dir", command,
            "the production invocation must carry no extra flag")
        argv = shlex.split(command)
        return subprocess.run(
            [sys.executable] + argv[1:], capture_output=True, text=True,
            cwd=str(self.root), env=self._env(), timeout=120)


class _FaultInjectionCase(unittest.TestCase):
    """The shared assertions. Every kill point goes through them."""

    UNITS = ("r1",)
    LEDGER = "memory"

    def setUp(self):
        self.proj = _Project(self, units=self.UNITS, ledger=self.LEDGER)

    # -- the kill ----------------------------------------------------------

    def kill_at(self, point, *, unit=None, nth=None, undo_noop=False,
                proc="trial"):
        """Run the real trial and kill it at `point`. Returns the CompletedProcess.

        Asserts the kill really happened: the status is the killswitch's own, not
        an exit code any product CLI uses, so a mis-aimed spec that let the
        process finish fails here rather than passing quietly.
        """
        spec = {"point": point, "proc": proc}
        if unit is not None:
            spec["unit"] = unit
        if nth is not None:
            spec["nth"] = nth
        if undo_noop:
            spec["undo_noop"] = True
        self.proj.set_spec(spec)
        result = self.proj.run_trial()
        self.assertEqual(
            result.returncode, KILL_STATUS,
            f"the process was meant to be KILLED at {point!r}; it exited "
            f"{result.returncode}. stdout={result.stdout!r} "
            f"stderr={result.stderr!r}")
        return result

    def run_to_completion(self, *, undo_noop=False):
        """Run the trial with nothing armed -- for the cases whose kill point is
        in the recovery process, which needs a journal in a driven state first."""
        spec = {"undo_noop": True} if undo_noop else {}
        self.proj.set_spec(spec)
        return self.proj.run_trial()

    def recovery_kill_at(self, point, trial_id, *, unit=None, nth=None,
                         undo_noop=False):
        """Kill the RECOVERY process at `point`."""
        spec = {"point": point, "proc": "recovery"}
        if unit is not None:
            spec["unit"] = unit
        if nth is not None:
            spec["nth"] = nth
        if undo_noop:
            spec["undo_noop"] = True
        self.proj.set_spec(spec)
        result = self.proj.run_recovery(trial_id)
        self.assertEqual(
            result.returncode, KILL_STATUS,
            f"the recovery process was meant to be KILLED at {point!r}; it "
            f"exited {result.returncode}. stdout={result.stdout!r} "
            f"stderr={result.stderr!r}")
        return result

    def the_only_trial(self):
        ids = self.proj.journal_ids()
        self.assertEqual(len(ids), 1,
                         f"expected exactly one journal on disk, found {ids}")
        return ids[0]

    # -- SURFACE 3: the operator-facing text and the exit code -------------

    def assertClaimMatchesSurface(self, result):
        """The truth check, anchored on the SURFACE and never on the journal.

        Whether "nothing is outstanding" is TRUE is a fact about the operator's
        record, so it is read from the surface file. The output is then required
        to claim exactly that, and the exit code is required to agree. A run that
        tells the operator nothing is outstanding while their record is still
        changed fails here whatever the journal says -- which is the failure mode
        this task exists to rule out, and the one this project has already paid
        for once.

        THE TWO DIRECTIONS ARE NOT SYMMETRIC, and the difference is worth being
        exact about. The safety-critical direction (surface changed => must say
        not-restored, must not say all-clear, must not exit 0) is absolute and
        holds for any run. The reverse (surface at prior => must say all-clear) is
        asserted here because every resume in this file CAN observe the surface; a
        run that could not observe would honestly report not-restored with the
        surface nonetheless at its prior state, since restoring without being able
        to confirm it is not a restore anyone may certify. That branch belongs to
        the recovery module's own suite, which owns it and pins both halves.
        """
        output = result.stdout + result.stderr
        at_prior = self.proj.surface() == self.proj.prior_surface()
        self.assertNotIn("Traceback", output,
                         "a non-technical operator reads this output")
        if at_prior:
            self.assertIn(
                tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, output,
                "the surface IS back at its prior state, so the operator must "
                f"be told so. output={output!r}")
            self.assertNotIn(tx.REFUSAL_MARKER_NOT_RESTORED, output)
            self.assertEqual(
                result.returncode, trc.EXIT_RESTORED,
                f"nothing is outstanding, so this must exit 0. output={output!r}")
        else:
            self.assertIn(
                tx.REFUSAL_MARKER_NOT_RESTORED, output,
                "the surface is NOT back at its prior state, so the operator "
                f"must be told that and nothing softer. output={output!r}")
            self.assertNotIn(
                tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, output,
                "FALSE SAFETY CLAIM: the operator was told nothing is "
                "outstanding while their record is still changed. "
                f"surface={self.proj.surface()!r} output={output!r}")
            self.assertNotEqual(
                result.returncode, trc.EXIT_RESTORED,
                "something IS outstanding, so the status must never read as "
                "success")
        return output

    def assertResumableCommandOffered(self, result, trial_id):
        output = result.stdout + result.stderr
        self.assertIn(
            trc.recovery_command(trial_id), output,
            "a blocking record with no command attached hands the operator a "
            f"verdict they cannot act on. output={output!r}")

    # -- the pass condition, all three surfaces at once -------------------

    def assertResumesToTerminal(self, trial_id, *, expect_states,
                                expect_surface, final_states=None,
                                final_surface=None, expect_ok=True):
        """SURFACES 1+2 at the instant of the kill, then the resume, then all
        three again."""
        self.assertEqual(self.proj.journal_states(trial_id), expect_states,
                         "the durable record at the instant of the kill")
        self.assertEqual(self.proj.surface(), expect_surface,
                         "the external surface at the instant of the kill")
        proofs_before_resume = self.proj.proofs()

        self.proj.set_spec({})          # the resume itself is not interfered with
        result = self.proj.run_recovery(trial_id)
        output = self.assertClaimMatchesSurface(result)

        if final_states is not None:
            self.assertEqual(self.proj.journal_states(trial_id), final_states)
        if final_surface is not None:
            self.assertEqual(self.proj.surface(), final_surface)
        if expect_ok:
            self.assertEqual(result.returncode, trc.EXIT_RESTORED, output)
            for unit_id, state in self.proj.journal_states(trial_id).items():
                self.assertIn(
                    state, (tj.STATE_PLANNED, tj.STATE_RESTORED_VERIFIED),
                    f"unit {unit_id} settled at {state!r}")
        else:
            self.assertEqual(result.returncode, trc.EXIT_RECOVERY_REQUIRED,
                             output)
            self.assertIn(tj.STATE_RECOVERY_REQUIRED,
                          self.proj.journal_states(trial_id).values())
            self.assertResumableCommandOffered(result, trial_id)
        # The resume must not PRODUCE a proof. Asserted as "no change" rather than
        # "none exists", because a kill after the proof was published leaves a
        # legitimate one the trial itself wrote, and demanding its absence would be
        # asserting the wrong fact.
        self.assertEqual(
            self.proj.proofs(), proofs_before_resume,
            "a recovery must never write a proof -- the apply-side observed "
            "evidence a proof carries was never in the durable record")
        return result

    def assertNothingWasMutatedAndNoJournalExists(self):
        """The legal shape of a kill BEFORE the write-ahead record exists: no
        durable record at all, and nothing touched. Distinguished from the
        forbidden shape (a mutation with nothing on disk naming it) by reading
        the surface."""
        self.assertEqual(self.proj.journal_ids(), [],
                         "no journal was published")
        self.assertEqual(
            self.proj.surface(), self.proj.prior_surface(),
            "NOTHING may have been mutated before a durable record exists -- a "
            "mutation with nothing on disk naming it is the unrecoverable state")
        self.assertEqual(self.proj.proofs(), [])


# ===========================================================================
# 3. THE WRITE-ONCE OPEN -- the plan and every capsule, before the first mutation
# ===========================================================================

class TheJournalOpenTests(_FaultInjectionCase):
    """Six kill instants inside the one atomic write that publishes the journal.

    Before the publish there is no journal -- and there must be no mutation
    either, which is the assertion that matters: the executor holds no units to
    apply until `open_trial_journal` returns.
    """

    def test_killed_before_the_temp_file_is_even_created(self):
        self.kill_at("journal.before_mkstemp", nth=1)
        self.assertNothingWasMutatedAndNoJournalExists()
        self.assertEqual(self.proj.journal_temp_files(), [])

    def test_killed_with_only_a_temp_file_on_disk(self):
        self.kill_at("journal.after_mkstemp", nth=1)
        self.assertNothingWasMutatedAndNoJournalExists()
        self.assertEqual(
            len(self.proj.journal_temp_files()), 1,
            "the half-written record is a dotfile with a .tmp suffix, so "
            "nothing looks for it as a journal")

    def test_the_temp_journal_a_crash_leaves_behind_is_never_committable(self):
        """A CRASH-ONLY artifact, and therefore one nothing could have checked
        before this battery existed.

        The leftover temp file is a partial trial journal, so it holds the same
        operator data the journal does -- the adapter's rendering of a record's
        PRIOR state. It has never existed on any disk until a process was killed
        mid-write, so its privacy coverage was latent-unverified rather than
        verified. It is covered, and by the stronger of the two available forms:
        the trial-journal directory is ignored WHOLESALE, unlike the trial proof,
        which needed a filename pattern because its own directory is a
        committed control-plane path.
        """
        self.kill_at("journal.after_mkstemp", nth=1)
        leftovers = self.proj.journal_temp_files()
        self.assertEqual(len(leftovers), 1, leftovers)
        template = (Path(__file__).resolve().parents[2] / "templates" / "root"
                    / "gitignore_template").read_text(encoding="utf-8")
        self.assertIn(
            "/security/trial_runs/", template.splitlines(),
            "the directory holding a crashed trial's partial record must be "
            "ignored as a DIRECTORY -- a *.json pattern would leave this "
            f"leftover ({leftovers[0]}) committable")

    def test_killed_before_the_contents_are_synced(self):
        self.kill_at("open.before_fsync")
        self.assertNothingWasMutatedAndNoJournalExists()

    def test_killed_after_the_contents_are_synced_before_the_publish(self):
        self.kill_at("open.after_fsync")
        self.assertNothingWasMutatedAndNoJournalExists()

    def test_killed_immediately_before_the_publish(self):
        self.kill_at("open.before_replace")
        self.assertNothingWasMutatedAndNoJournalExists()

    def test_killed_immediately_after_the_publish(self):
        self.kill_at("open.after_replace")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_PLANNED},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_PLANNED},
            final_surface=self.proj.prior_surface())

    def test_killed_before_the_directory_entry_is_synced(self):
        self.kill_at("open.before_dir_fsync")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_PLANNED},
            expect_surface=self.proj.prior_surface())

    def test_killed_after_the_directory_entry_is_synced(self):
        self.kill_at("open.after_dir_fsync")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_PLANNED},
            expect_surface=self.proj.prior_surface())


# ===========================================================================
# 4. THE APPLY-INTENT RECORD -- write-ahead means write-ahead
# ===========================================================================

class TheApplyIntentRecordTests(_FaultInjectionCase):
    """The most load-bearing boundary in the protocol.

    Killing at each instant inside this one atomic write answers, empirically,
    the question the whole journal exists for: can a mutation ever be issued
    before the record that authorizes it is published? Every instant before the
    `os.replace` must find the surface UNTOUCHED.
    """

    def test_killed_before_the_intent_record_is_synced(self):
        self.kill_at("apply_intent.before_fsync")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_PLANNED},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_PLANNED})

    def test_killed_after_the_intent_record_is_synced_before_the_publish(self):
        self.kill_at("apply_intent.after_fsync")
        trial_id = self.the_only_trial()
        self.assertEqual(
            self.proj.surface(), self.proj.prior_surface(),
            "no mutation may be issued before the intent record is PUBLISHED")
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_PLANNED},
            expect_surface=self.proj.prior_surface())

    def test_killed_immediately_before_the_intent_record_is_published(self):
        self.kill_at("apply_intent.before_replace")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_PLANNED},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_PLANNED})

    def test_a_killed_transition_leaves_the_prior_record_byte_intact(self):
        """The other half of the same instant: an interrupted write must not
        truncate what was already there."""
        self.kill_at("apply_intent.before_replace")
        trial_id = self.the_only_trial()
        loaded = tj.load_trial_journal(
            trial_id,
            journal_dir=str(self.proj.root / "security" / "trial_runs"))
        self.assertEqual(loaded.unit_states(), {"r1": tj.STATE_PLANNED},
                         "the prior record still validates, in full")

    def test_killed_immediately_after_the_intent_record_is_published(self):
        self.kill_at("apply_intent.after_replace")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_INTENT},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_before_the_intent_records_directory_entry_is_synced(self):
        self.kill_at("apply_intent.before_dir_fsync")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_INTENT},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_killed_after_the_intent_records_directory_entry_is_synced(self):
        self.kill_at("apply_intent.after_dir_fsync")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_INTENT},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_the_stale_lock_file_a_killed_process_leaves_blocks_nothing(self):
        """A kill inside the exclusive section leaves the lock FILE behind. The
        advisory lock itself is released by the operating system when the process
        dies, so the next process must not block on it -- and if it did, the
        `timeout` on every subprocess here turns the hang into a failure rather
        than a hung suite."""
        self.kill_at("apply_intent.before_replace")
        trial_id = self.the_only_trial()
        self.assertEqual(self.proj.lock_files(), [f"{trial_id}.json.lock"],
                         "the lock file outlives the process that took it")
        self.proj.set_spec({})
        result = self.proj.run_recovery(trial_id)
        self.assertEqual(result.returncode, trc.EXIT_RESTORED,
                         result.stdout + result.stderr)


# ===========================================================================
# 5. THE APPLY -- the ambiguous window, entered for real
# ===========================================================================

class TheApplyTests(_FaultInjectionCase):

    def test_killed_inside_apply_before_the_vendor_mutation(self):
        self.kill_at("apply.before_mutation")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_INTENT},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_inside_apply_after_the_vendor_mutation_landed(self):
        """THE ambiguous window: the mutation is live on the operator's record and
        nothing on disk can say whether it landed. The journal names the unit,
        which is the most that can honestly be said, and recovery converges."""
        self.kill_at("apply.after_mutation")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_INTENT},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_before_the_apply_confirmed_record_is_published(self):
        self.kill_at("apply_confirmed.before_replace")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_INTENT},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_after_the_apply_confirmed_record_is_published(self):
        self.kill_at("apply_confirmed.after_replace")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_CONFIRMED},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_after_the_apply_confirmed_directory_entry_is_synced(self):
        self.kill_at("apply_confirmed.after_dir_fsync")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_CONFIRMED},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_killed_inside_the_post_apply_observation_before_the_read(self):
        self.kill_at("verify1.before_read")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_CONFIRMED},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_inside_the_post_apply_observation_after_the_read(self):
        self.kill_at("verify1.after_read")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_CONFIRMED},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})


# ===========================================================================
# 6. THE REVERSAL -- the executor's own undo, and its write-ahead record
# ===========================================================================

class TheReversalTests(_FaultInjectionCase):

    def test_killed_before_the_undo_intent_record_is_published(self):
        self.kill_at("undo_intent.before_replace")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_APPLY_CONFIRMED},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_after_the_undo_intent_record_is_published(self):
        self.kill_at("undo_intent.after_replace")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_UNDO_INTENT},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_after_the_undo_intent_directory_entry_is_synced(self):
        self.kill_at("undo_intent.after_dir_fsync")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_UNDO_INTENT},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_killed_inside_undo_before_the_vendor_mutation(self):
        self.kill_at("undo.before_mutation")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_UNDO_INTENT},
            expect_surface={"r1": APPLIED},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_inside_undo_after_the_vendor_mutation(self):
        """The surface is back but nothing has observed it. The journal must NOT
        say the unit is settled -- that is the second forbidden shape."""
        self.kill_at("undo.after_mutation")
        trial_id = self.the_only_trial()
        self.assertNotEqual(
            self.proj.journal_states(trial_id)["r1"],
            tj.STATE_RESTORED_VERIFIED,
            "restoration was not OBSERVED, so it may not be recorded")
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_UNDO_INTENT},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED},
            final_surface=self.proj.prior_surface())

    def test_killed_inside_the_post_undo_observation_before_the_read(self):
        self.kill_at("verify2.before_read")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_UNDO_INTENT},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_killed_inside_the_post_undo_observation_after_the_read(self):
        self.kill_at("verify2.after_read")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_UNDO_INTENT},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_killed_before_the_restored_verified_record_is_published(self):
        self.kill_at("restored_verified.before_replace")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_UNDO_INTENT},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_killed_after_the_restored_verified_record_is_published(self):
        self.kill_at("restored_verified.after_replace")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_killed_after_the_restored_verified_directory_entry_is_synced(self):
        self.kill_at("restored_verified.after_dir_fsync")
        trial_id = self.the_only_trial()
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED},
            expect_surface=self.proj.prior_surface())


# ===========================================================================
# 7. THE BLOCKING RECORD -- killed around `recovery_required` itself
# ===========================================================================

class TheBlockingRecordTests(_FaultInjectionCase):
    """Reached with an undo that no-ops, so `verify_undo_restored` is False and
    the executor must write the blocking record. The surface here really is still
    changed, which makes this the one group where SURFACE 3's false-safety
    assertion has teeth in the dangerous direction."""

    def test_killed_before_the_blocking_record_is_published(self):
        self.kill_at("recovery_required.before_replace", undo_noop=True)
        trial_id = self.the_only_trial()
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_UNDO_INTENT})
        self.assertEqual(self.proj.surface(), {"r1": APPLIED})
        # The cause is gone for the resume, exactly as it is for an operator who
        # fixed what was wrong before re-running the command they were given.
        self.proj.set_spec({})
        result = self.proj.run_recovery(trial_id)
        self.assertClaimMatchesSurface(result)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})
        self.assertEqual(self.proj.surface(), self.proj.prior_surface())

    def test_killed_after_the_blocking_record_is_published(self):
        self.kill_at("recovery_required.after_replace", undo_noop=True)
        trial_id = self.the_only_trial()
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        self.assertEqual(self.proj.surface(), {"r1": APPLIED})
        self.proj.set_spec({})
        result = self.proj.run_recovery(trial_id)
        self.assertClaimMatchesSurface(result)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})

    def test_the_TRIALS_OWN_refusal_text_is_true_when_a_unit_is_left_changed(self):
        """The other producer of operator-facing text, and the reason this test
        exists at all.

        A killed process prints nothing, so every kill point above reaches the
        operator's eyes only through the RECOVERY command's output. That left the
        trial executor's own refusal -- the sentence an operator reads when the
        trial survives but a unit does not come back -- unasserted by this file. A
        mutation dropping the executor's safety post-condition therefore survived
        the whole battery: the run went on saying "nothing external is
        outstanding" about a unit durably changed on the operator's record, and
        nothing here noticed, because nothing here ever read that sentence.

        This is the state an operator lands in on the second attempt after a kill,
        so it is not a hypothetical branch: the trial runs to completion, the undo
        no-ops, and the surface really is still changed.
        """
        result = self.run_to_completion(undo_noop=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        trial_id = self.the_only_trial()
        summary = json.loads(result.stdout)
        self.assertFalse(summary["ok"])
        self.assertEqual(self.proj.surface(), {"r1": APPLIED},
                         "fixture precondition: the unit really is still changed")
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})

        refusal = summary["refusal"] or ""
        self.assertIn(
            tx.REFUSAL_MARKER_NOT_RESTORED, refusal,
            f"the trial must say the unit is not back. refusal={refusal!r}")
        self.assertNotIn(
            tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, refusal,
            "FALSE SAFETY CLAIM from the trial itself: the operator was told "
            "nothing is outstanding while the unit is durably changed on their "
            f"record. refusal={refusal!r}")
        self.assertIn(
            trc.recovery_command(trial_id), refusal,
            "the trial's refusal must name the repair, single-sourced from the "
            "module that performs it")
        self.assertEqual(self.proj.proofs(), [],
                         "no proof may be written for a trial that did not "
                         "bring its unit back")

        # And the command it named actually clears the state.
        self.proj.set_spec({})
        cleared = self.proj.run_recovery(trial_id)
        self.assertClaimMatchesSurface(cleared)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})

    def test_a_blocking_record_whose_cause_persists_stays_blocked_and_says_so(self):
        """The dangerous direction, end to end in the real project: the record is
        durable, the surface really is still changed, and the operator is told
        that and offered the identical command again."""
        self.kill_at("recovery_required.after_replace", undo_noop=True)
        trial_id = self.the_only_trial()
        self.proj.set_spec({"undo_noop": True})     # the cause persists
        result = self.proj.run_recovery(trial_id)
        self.assertEqual(self.proj.surface(), {"r1": APPLIED})
        self.assertClaimMatchesSurface(result)
        self.assertEqual(result.returncode, trc.EXIT_RECOVERY_REQUIRED)
        self.assertResumableCommandOffered(result, trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED},
                         "the state stays durable rather than being cleared")


# ===========================================================================
# 8. PROOF EMISSION -- after every unit is settled
# ===========================================================================

class TheProofEmissionTests(_FaultInjectionCase):
    """A kill during proof emission is the one class where nothing is outstanding
    on the operator's record and the trial still produced no evidence. The
    assertions therefore run in both directions: no half-written artifact may sit
    at the path acceptance reads from, and the operator must not be told anything
    is wrong with their data, because nothing is."""

    def test_killed_before_the_proof_temp_file_exists(self):
        self.kill_at("proof.before_mkstemp", nth=1)
        trial_id = self.the_only_trial()
        self.assertEqual(self.proj.proofs(), [])
        self.assertEqual(self.proj.proof_temp_files(), [])
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED},
            expect_surface=self.proj.prior_surface())

    def test_killed_with_only_a_proof_temp_file_on_disk(self):
        self.kill_at("proof.after_mkstemp", nth=1)
        trial_id = self.the_only_trial()
        self.assertEqual(
            self.proj.proofs(), [],
            "nothing may sit at the path acceptance reads from")
        temps = self.proj.proof_temp_files()
        self.assertEqual(len(temps), 1, temps)
        self.assertTrue(temps[0].endswith(".tmp"), temps)
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED},
            expect_surface=self.proj.prior_surface())

    def test_killed_before_the_proof_contents_are_synced(self):
        self.kill_at("proof.before_fsync")
        trial_id = self.the_only_trial()
        self.assertEqual(self.proj.proofs(), [])
        self.assertEqual(len(self.proj.proof_temp_files()), 1)
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED},
            expect_surface=self.proj.prior_surface())

    def test_killed_immediately_before_the_proof_is_published(self):
        self.kill_at("proof.before_replace")
        trial_id = self.the_only_trial()
        self.assertEqual(self.proj.proofs(), [])
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED},
            expect_surface=self.proj.prior_surface())

    def test_killed_immediately_after_the_proof_is_published(self):
        self.kill_at("proof.after_replace")
        trial_id = self.the_only_trial()
        self.assertEqual(self.proj.proofs(),
                         ["fixture_capability.copy_run_proof.json"])
        self.assertEqual(self.proj.proof_temp_files(), [])
        payload = json.loads(
            (self.proj.root / "agents" / "handoffs"
             / "fixture_capability.copy_run_proof.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "copy_run_proof-v1")
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_killed_after_the_proofs_directory_entry_is_synced(self):
        self.kill_at("proof.after_dir_fsync")
        trial_id = self.the_only_trial()
        self.assertEqual(self.proj.proofs(),
                         ["fixture_capability.copy_run_proof.json"])
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED})

    def test_a_published_proof_is_whole_and_never_a_torn_one(self):
        """What fault injection uniquely establishes about the proof: the artifact
        that appears at the acceptance path is COMPLETE.

        Deliberately not a re-run of the shipped validator. The producer already
        runs that validator over its own artifact and refuses to write anything it
        rejects, so schema conformance is structural there rather than a fact this
        file could add to. What only a kill can show is that a process death around
        the publish never leaves a half-written artifact at the path acceptance
        reads from -- so the assertion is on the required field set surviving
        whole, and on there being no leftover temp file masquerading as one.
        """
        from external_write.copy_run_proof import (
            COPY_RUN_PROOF_SCHEMA, _REQUIRED_FIELDS,
        )
        self.kill_at("proof.after_dir_fsync")
        trial_id = self.the_only_trial()
        payload = json.loads(
            (self.proj.root / "agents" / "handoffs"
             / "fixture_capability.copy_run_proof.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], COPY_RUN_PROOF_SCHEMA)
        self.assertEqual(
            sorted(set(_REQUIRED_FIELDS) - set(payload)), [],
            "the published artifact is missing required fields, so the publish "
            "was not atomic")
        self.assertEqual(self.proj.proof_temp_files(), [])
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED},
            expect_surface=self.proj.prior_surface())


# ===========================================================================
# 9. BEFORE ANY JOURNAL EXISTS -- provisioning and the blast-radius ledger
# ===========================================================================

class BeforeTheJournalExistsTests(_FaultInjectionCase):
    """Two external-call boundaries and one durable write happen BEFORE the
    journal is opened. A kill at any of them must leave nothing mutated -- and
    for the ledger, must leave the operator's consumed count truthful."""

    LEDGER = "persistent"

    def test_killed_while_provisioning_the_read_only_connection(self):
        self.kill_at("read_client.build")
        self.assertNothingWasMutatedAndNoJournalExists()
        self.assertEqual(
            self.proj.ledger_counts(), {},
            "the read side is resolved BEFORE authorization, so no "
            "blast-radius slot may have been consumed")

    def test_killed_while_provisioning_the_write_connection(self):
        self.kill_at("write_client.build")
        self.assertNothingWasMutatedAndNoJournalExists()
        self.assertEqual(
            self.proj.ledger_counts(), {"fixture_surface::" + _FIXTURE_OP_KIND: 1},
            "the write side is resolved AFTER the gate said yes, so the slot IS "
            "spent -- and the record of that must be truthful")

    def test_killed_before_the_ledger_reservation_is_published(self):
        self.kill_at("ledger.before_replace")
        self.assertNothingWasMutatedAndNoJournalExists()
        self.assertEqual(self.proj.ledger_counts(), {},
                         "an unpublished reservation consumed nothing")

    def test_killed_after_the_ledger_reservation_is_published(self):
        self.kill_at("ledger.after_replace")
        self.assertNothingWasMutatedAndNoJournalExists()
        self.assertEqual(
            self.proj.ledger_counts(),
            {"fixture_surface::" + _FIXTURE_OP_KIND: 1},
            "the reservation is durable, so the count must show it -- a cap that "
            "under-reports what was spent is the fail-open direction")

    def test_an_absent_journal_is_never_read_as_nothing_was_applied(self):
        """The fail-closed reading of the state these kills leave: there is no
        journal, so a recovery invocation against a guessed id must refuse rather
        than report an all-clear."""
        self.kill_at("write_client.build")
        self.proj.set_spec({})
        result = self.proj.run_recovery("trial-does-not-exist")
        self.assertEqual(result.returncode, trc.EXIT_RECOVERY_REQUIRED)
        output = result.stdout + result.stderr
        self.assertNotIn(tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, output)
        self.assertNotIn("Traceback", output)


# ===========================================================================
# 10. THE RECOVERY PROCESS'S OWN BOUNDARIES
# ===========================================================================

class TheRecoveryProcessTests(_FaultInjectionCase):
    """The repair is itself killable, and a repair that cannot survive being
    interrupted is not a repair. Every kill here is followed by re-running the
    IDENTICAL command, which is what an operator does."""

    def _killed_trial_in_the_ambiguous_window(self):
        self.kill_at("apply.after_mutation")
        trial_id = self.the_only_trial()
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_APPLY_INTENT})
        self.assertEqual(self.proj.surface(), {"r1": APPLIED})
        return trial_id

    def _resume_and_assert_settled(self, trial_id):
        self.proj.set_spec({})
        result = self.proj.run_recovery(trial_id)
        self.assertClaimMatchesSurface(result)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})
        self.assertEqual(self.proj.surface(), self.proj.prior_surface())
        self.assertEqual(self.proj.proofs(), [])
        return result

    def test_recovery_killed_while_provisioning_the_write_connection(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_write_client.build", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_APPLY_INTENT},
                         "nothing was recorded, because nothing was attempted")
        self.assertEqual(self.proj.surface(), {"r1": APPLIED})
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_while_provisioning_the_read_connection(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_read_client.build", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_APPLY_INTENT})
        self.assertEqual(self.proj.surface(), {"r1": APPLIED})
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_before_its_undo_intent_record_is_published(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_undo_intent.before_replace", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_APPLY_INTENT})
        self.assertEqual(self.proj.surface(), {"r1": APPLIED},
                         "no reversal may be issued before its own record is "
                         "published")
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_after_its_undo_intent_record_is_published(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_undo_intent.after_replace", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_UNDO_INTENT})
        self.assertEqual(self.proj.surface(), {"r1": APPLIED})
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_inside_undo_before_the_vendor_mutation(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_undo.before_mutation", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_UNDO_INTENT})
        self.assertEqual(self.proj.surface(), {"r1": APPLIED})
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_inside_undo_after_the_vendor_mutation(self):
        """The surface is back and nothing observed it. The record must not say
        settled, and re-running must establish it from an observation."""
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_undo.after_mutation", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_UNDO_INTENT})
        self.assertEqual(self.proj.surface(), self.proj.prior_surface())
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_inside_its_observation_before_the_read(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_verify1.before_read", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_UNDO_INTENT})
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_inside_its_observation_after_the_read(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_verify1.after_read", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_UNDO_INTENT})
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_before_its_restored_verified_record_is_published(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_restored_verified.before_replace", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_UNDO_INTENT},
                         "the settled state was not published, so the record "
                         "still says the unit may be outstanding")
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_after_its_restored_verified_record_is_published(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_restored_verified.after_replace", trial_id)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})
        self.assertEqual(self.proj.surface(), self.proj.prior_surface())
        result = self._resume_and_assert_settled(trial_id)
        self.assertEqual(result.returncode, trc.EXIT_RESTORED)

    def test_recovery_killed_before_its_blocking_record_is_published(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_recovery_required.before_replace", trial_id,
                              undo_noop=True)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_UNDO_INTENT})
        self.assertEqual(self.proj.surface(), {"r1": APPLIED},
                         "the no-op undo left the record changed")
        self._resume_and_assert_settled(trial_id)

    def test_recovery_killed_after_its_blocking_record_is_published(self):
        trial_id = self._killed_trial_in_the_ambiguous_window()
        self.recovery_kill_at("rec_recovery_required.after_replace", trial_id,
                              undo_noop=True)
        self.assertEqual(self.proj.journal_states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        self.assertEqual(self.proj.surface(), {"r1": APPLIED})
        self._resume_and_assert_settled(trial_id)


# ===========================================================================
# 11. MULTI-UNIT -- the boundary BETWEEN units, in both drivers
# ===========================================================================

class TheUnitBoundaryTests(_FaultInjectionCase):
    """A trial applies and reverses one unit before touching the next, so the
    boundary between units is a real kill point with a state no single-unit test
    can produce: an earlier unit settled, this one outstanding, later ones never
    touched."""

    UNITS = ("r1", "r2", "r3")

    def test_killed_mid_apply_on_the_SECOND_unit(self):
        self.kill_at("apply.after_mutation", unit="r2")
        trial_id = self.the_only_trial()
        self.assertEqual(
            self.proj.journal_states(trial_id),
            {"r1": tj.STATE_RESTORED_VERIFIED,
             "r2": tj.STATE_APPLY_INTENT,
             "r3": tj.STATE_PLANNED})
        self.assertEqual(self.proj.surface(),
                         {"r1": PRIOR, "r2": APPLIED, "r3": PRIOR})
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED,
                           "r2": tj.STATE_APPLY_INTENT,
                           "r3": tj.STATE_PLANNED},
            expect_surface={"r1": PRIOR, "r2": APPLIED, "r3": PRIOR},
            final_states={"r1": tj.STATE_RESTORED_VERIFIED,
                          "r2": tj.STATE_RESTORED_VERIFIED,
                          "r3": tj.STATE_PLANNED},
            final_surface=self.proj.prior_surface())

    def test_killed_between_the_second_and_third_unit(self):
        """`r3` is never touched, and a unit still recorded `planned` was provably
        never applied -- so recovery must not reverse it, which would be a write
        on a record the trial never touched."""
        self.kill_at("restored_verified.after_replace", unit="r2")
        trial_id = self.the_only_trial()
        self.assertEqual(
            self.proj.journal_states(trial_id),
            {"r1": tj.STATE_RESTORED_VERIFIED,
             "r2": tj.STATE_RESTORED_VERIFIED,
             "r3": tj.STATE_PLANNED})
        self.assertResumesToTerminal(
            trial_id,
            expect_states={"r1": tj.STATE_RESTORED_VERIFIED,
                           "r2": tj.STATE_RESTORED_VERIFIED,
                           "r3": tj.STATE_PLANNED},
            expect_surface=self.proj.prior_surface(),
            final_states={"r1": tj.STATE_RESTORED_VERIFIED,
                          "r2": tj.STATE_RESTORED_VERIFIED,
                          "r3": tj.STATE_PLANNED})

    def test_recovery_killed_between_two_units_it_was_driving(self):
        """Two units outstanding; the repair dies after settling the first. The
        second is still named, and re-running the identical command finishes."""
        self.kill_at("apply.after_mutation", unit="r2")
        trial_id = self.the_only_trial()
        # Put r1 back into a driven state by hand? No -- drive a real second
        # outstanding unit instead: r2 is outstanding, and r1 is already settled,
        # so kill recovery inside the reversal of r2 with r3 still planned.
        self.recovery_kill_at("rec_undo_intent.after_replace", trial_id,
                              unit="r2")
        self.assertEqual(
            self.proj.journal_states(trial_id),
            {"r1": tj.STATE_RESTORED_VERIFIED,
             "r2": tj.STATE_UNDO_INTENT,
             "r3": tj.STATE_PLANNED})
        self.proj.set_spec({})
        result = self.proj.run_recovery(trial_id)
        self.assertClaimMatchesSurface(result)
        self.assertEqual(
            self.proj.journal_states(trial_id),
            {"r1": tj.STATE_RESTORED_VERIFIED,
             "r2": tj.STATE_RESTORED_VERIFIED,
             "r3": tj.STATE_PLANNED})
        self.assertEqual(self.proj.surface(), self.proj.prior_surface())


# ===========================================================================
# 12. THE ENUMERATION ITSELF -- derived from the code, not from the plan
# ===========================================================================

class BoundaryEnumerationTests(unittest.TestCase):
    """The anti-drift half of this task.

    A report saying "I found N boundaries" is true on the day it is written. This
    re-derives the boundary set from the three modules' own ASTs on every run and
    requires the declaration above to match, and requires every declared boundary
    to have a kill point that this file actually uses. A later task that adds an
    `apply_one` call site, a `record_*` site or a second atomic writer fails here
    until it declares the boundary and kills at it.
    """

    # ------------------------------------------------------------------
    # The vocabulary. Drawn from the filesystem-MUTATING SURFACE of the
    # modules this code is allowed to import, NOT from the names it happens
    # to call today.
    #
    # The distinction is the whole point and it was learned the hard way: an
    # allowlist of observed usage is green-and-blind against any future writer
    # spelled differently. A complete second durable writer built from
    # `Path.write_text` + `os.rename` + `os.unlink` passed an earlier version of
    # this guard 8/8, because none of those three names was in use anywhere in
    # the protocol and so none of them was listed. Every name below is here
    # because the underlying module can mutate the filesystem with it, whether
    # or not this code has ever used it -- and
    # `test_a_second_durable_writer_BUILT_FROM_UNUSED_NAMES_is_caught` injects
    # exactly that writer and requires the derivation to catch it.
    # ------------------------------------------------------------------

    # Mutators reachable as a plain attribute or name call, wherever they appear.
    # `pathlib`'s writers are the reason this is name-based rather than
    # receiver-based: a `Path` arrives in a variable, so `some_path.write_text(...)`
    # has no import root to key on.
    FS_MUTATING_NAMES = frozenset({
        # os
        "replace", "rename", "renames", "remove", "unlink", "rmdir",
        "removedirs", "mkdir", "makedirs", "truncate", "ftruncate", "chmod",
        "fchmod", "lchmod", "chown", "fchown", "lchown", "link", "symlink",
        "utime", "mkfifo", "mknod", "write", "writev", "pwrite", "sendfile",
        "copy_file_range", "fsync", "fdatasync", "fdopen", "startfile",
        # tempfile
        "mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryFile",
        "SpooledTemporaryFile", "TemporaryDirectory",
        # shutil
        "copy", "copy2", "copyfile", "copyfileobj", "copymode", "copystat",
        "copytree", "move", "rmtree", "make_archive", "unpack_archive",
        # pathlib.Path writers
        "write_text", "write_bytes", "touch", "symlink_to", "hardlink_to",
        # file objects + json
        "writelines", "flush", "dump",
    })

    # Ordering primitives: they mutate nothing themselves but they are what makes
    # a mutation durable or exclusive, so a kill around them is a real instant.
    FS_ORDERING_NAMES = frozenset({"flock"})

    # The protocol's own durable-write entry points.
    PROTOCOL_PERSISTENCE_NAMES = frozenset({
        "_atomic_write_record", "_atomic_write_json", "open_trial_journal",
        "record_apply_intent", "record_apply_confirmed", "record_undo_intent",
        "record_restored_verified", "record_recovery_required",
    })

    # `open` / `os.open` are classified by MODE, not by name: the same call is a
    # read or a mutation depending on its arguments. This is what makes the lock
    # file's `open(..., "w")` a derived boundary while `read_record`'s
    # `open(path, encoding=...)` and `_fsync_directory`'s `os.open(dir, O_RDONLY)`
    # correctly are not.
    MODE_CLASSIFIED_NAMES = frozenset({"open"})
    _WRITE_MODE_CHARS = frozenset("wxa+")
    _WRITE_OPEN_FLAGS = frozenset({
        "O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND", "O_EXCL",
    })

    EXTERNAL_CALLEES = frozenset({
        "apply_one", "undo_one", "verify_one", "observe_unit",
        "resolve_write_client", "resolve_read_only_client",
        # `plan` is DERIVED so that its exclusion is a recorded judgment rather
        # than an absence a later reader cannot tell from a miss. See
        # BOUNDARIES_EXCLUDED_BY_CONTRACT.
        "plan",
    })

    # Modules whose members can touch the filesystem. Any call rooted at one of
    # these must be classified (below) -- that is the fail-closed half.
    FS_CAPABLE_ROOTS = frozenset({"os", "shutil", "tempfile", "json", "io",
                                  "pathlib"})

    # The READ-ONLY members of those modules that this code legitimately calls.
    # Declared POSITIVELY: a member in neither this set nor the mutating set is a
    # member nobody classified, and the test REFUSES rather than assuming it is
    # harmless.
    FS_READ_ONLY_MEMBERS = frozenset({
        "os.path.dirname", "os.path.abspath", "os.path.join", "os.path.exists",
        "os.path.basename", "os.path.isdir", "os.path.isfile",
        "os.path.normpath", "os.path.relpath", "os.path.split",
        "os.path.splitext", "os.getcwd", "os.close", "os.lstat", "os.stat",
        "os.fstat", "os.listdir", "os.scandir", "os.readlink", "os.fspath",
        "json.load", "json.loads", "json.dumps",
    })

    MODULES = ("trial_executor", "trial_journal", "trial_recovery")

    # ------------------------------------------------------------------
    # Derivation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dotted(func):
        """The dotted name of a call target when it is a pure attribute chain on
        a bare name (`os.path.dirname`), else None. Never guesses through a
        subscript, a call result or a variable."""
        parts = []
        node = func
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return None

    @staticmethod
    def _calls_with_innermost_scope(tree):
        """Every Call paired with its INNERMOST enclosing function, qualified with
        its parents (`_converge_unit._blocked`).

        Innermost rather than outermost, and qualified rather than bare, because
        both alternatives lose information the enumeration depends on: an
        outermost attribution would merge a nested call site with an outer one of
        the same callee into a single declared boundary, and a bare innermost name
        would not say where the nested function lives.
        """
        found = []

        def walk(node, scope):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    inner = f"{scope}.{child.name}" if scope != "<module>" \
                        else child.name
                    walk(child, inner)
                    continue
                if isinstance(child, ast.Call):
                    found.append((child, scope))
                walk(child, scope)

        walk(tree, "<module>")
        return found

    @classmethod
    def _open_is_a_write(cls, node, dotted):
        """Does this `open` / `os.open` call mutate the filesystem?"""
        if dotted == "os.open":
            flags = ast.dump(node.args[1]) if len(node.args) > 1 else ""
            return any(flag in flags for flag in cls._WRITE_OPEN_FLAGS)
        mode = None
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value
        for keyword in node.keywords:
            if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                mode = keyword.value.value
        if not isinstance(mode, str):
            return False        # no mode is "r" -- a read
        return bool(cls._WRITE_MODE_CHARS & frozenset(mode))

    @classmethod
    def _sources(cls):
        return [(module,
                 (_EXTERNAL_WRITE_DIR / f"{module}.py").read_text(
                     encoding="utf-8"))
                for module in cls.MODULES]

    @classmethod
    def _derive_persistence(cls, sources=None):
        """Every persistence boundary, derived from source text.

        Takes sources rather than reading them itself so the guard can be aimed at
        a PROBE -- a synthetic module carrying an injected writer -- and shown to
        catch it. A guard that can only ever be pointed at code that already
        passes is not a guard anyone has tested.
        """
        wanted = (cls.FS_MUTATING_NAMES | cls.FS_ORDERING_NAMES
                  | cls.PROTOCOL_PERSISTENCE_NAMES)
        found = set()
        for module, source in (sources if sources is not None
                               else cls._sources()):
            for node, scope in cls._calls_with_innermost_scope(
                    ast.parse(source)):
                func = node.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else func.id if isinstance(func, ast.Name) else None)
                if name is None:
                    continue
                if name in cls.MODE_CLASSIFIED_NAMES:
                    if not cls._open_is_a_write(node, cls._dotted(func)):
                        continue
                elif name not in wanted:
                    continue
                found.add(f"{module}:{scope}:{name}")
        return found

    @classmethod
    def _derive_external(cls, sources=None):
        found = set()
        for module, source in (sources if sources is not None
                               else cls._sources()):
            for node, scope in cls._calls_with_innermost_scope(
                    ast.parse(source)):
                func = node.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else func.id if isinstance(func, ast.Name) else None)
                if name in cls.EXTERNAL_CALLEES:
                    found.add(f"{module}:{scope}:{name}")
        return found

    def test_every_persistence_boundary_in_the_code_is_declared(self):
        derived = self._derive_persistence()
        self.assertEqual(
            derived, set(DECLARED_PERSISTENCE_BOUNDARIES),
            "the persistence boundaries in the code and the declared "
            "enumeration disagree. A boundary present in the code and absent "
            "here is one nothing kills at; the fix is to declare it AND add a "
            "kill point, not to widen this assertion.")

    def test_every_external_call_boundary_in_the_code_is_declared(self):
        derived = self._derive_external()
        self.assertEqual(
            derived, set(DECLARED_EXTERNAL_CALL_BOUNDARIES),
            "the external-call boundaries in the code and the declared "
            "enumeration disagree.")

    # ------------------------------------------------------------------
    # Proving the guard, rather than asserting that it guards
    # ------------------------------------------------------------------

    # A complete second durable writer, spelled with names the trial protocol
    # does not use ANYWHERE: `Path.write_text`, `os.rename`, `os.unlink`. This is
    # the construction that defeated the first version of this guard, kept here as
    # its permanent probe.
    _INJECTED_SECOND_WRITER = '''
import os
from pathlib import Path


def _shadow_publish(directory, payload):
    tmp = Path(directory) / ".shadow.tmp"
    tmp.write_text(payload, encoding="utf-8")
    os.rename(str(tmp), os.path.join(directory, "shadow.json"))
    if os.path.exists(str(tmp)):
        os.unlink(str(tmp))
'''

    def test_a_second_durable_writer_BUILT_FROM_UNUSED_NAMES_is_caught(self):
        """The guard's own falsification test, and the reason the vocabulary is
        drawn from the mutating SURFACE rather than from observed usage.

        `write_text`, `rename` and `unlink` appear nowhere in the trial protocol.
        Under a vocabulary listing only the names in use, this writer is invisible
        -- it adds three undeclared, unkilled-at persistence boundaries and the
        enumeration test stays green, which is exactly the green-and-blind shape
        the enumeration exists to prevent. Each of the three must be derived, and
        each must then fail the declaration match, since none is declared.
        """
        probe = [("trial_recovery",
                  (_EXTERNAL_WRITE_DIR / "trial_recovery.py").read_text(
                      encoding="utf-8") + self._INJECTED_SECOND_WRITER)]
        derived = self._derive_persistence(probe)
        for name in ("write_text", "rename", "unlink"):
            self.assertIn(
                f"trial_recovery:_shadow_publish:{name}", derived,
                f"an injected durable writer's {name!r} was NOT derived, so a "
                "future writer spelled this way would add an undeclared "
                "persistence boundary silently")
        self.assertTrue(
            derived - set(DECLARED_PERSISTENCE_BOUNDARIES),
            "the injected writer produced no undeclared boundary, so the "
            "declaration match could not have failed on it")

    def test_the_guard_catches_a_write_mode_open_and_ignores_a_read_one(self):
        """`open` is classified by MODE. Both directions, because a rule that
        fired on every `open` would be noise and one that fired on none would
        have missed the lock file this protocol really does create."""
        probe = [("probe", 'def w(p):\n'
                           '    open(p, "w").close()\n'
                           'def a(p):\n'
                           '    open(p, mode="a").close()\n'
                           'def r(p):\n'
                           '    open(p, encoding="utf-8").close()\n'
                           'def rr(p):\n'
                           '    open(p, "r").close()\n')]
        derived = self._derive_persistence(probe)
        self.assertIn("probe:w:open", derived)
        self.assertIn("probe:a:open", derived)
        self.assertNotIn("probe:r:open", derived)
        self.assertNotIn("probe:rr:open", derived)

    def test_the_guard_catches_a_write_flagged_os_open(self):
        """`os.open` is classified by its FLAGS, so the read-only directory handle
        the durability primitives take is not a boundary and a creating one is."""
        probe = [("probe", 'import os\n'
                           'def w(p):\n'
                           '    os.open(p, os.O_WRONLY | os.O_CREAT)\n'
                           'def r(p):\n'
                           '    os.open(p, os.O_RDONLY)\n')]
        derived = self._derive_persistence(probe)
        self.assertIn("probe:w:open", derived)
        self.assertNotIn("probe:r:open", derived)

    def test_a_call_on_a_filesystem_module_MUST_be_classified(self):
        """The fail-closed half, and the direction that closes the recall problem.

        The mutating-name list can never be provably exhaustive over every future
        library, so it is backed by a refusal: any call rooted at a module that
        CAN touch the filesystem must be classified as mutating or as read-only,
        both declared positively. A member in neither -- a newly-used `os.*` this
        file has never seen -- fails here rather than being assumed harmless,
        which is the same silence-must-refuse direction the protocol itself uses.
        """
        unclassified = []
        for module, source in self._sources():
            for node, scope in self._calls_with_innermost_scope(
                    ast.parse(source)):
                dotted = self._dotted(node.func)
                if dotted is None:
                    continue
                root = dotted.split(".")[0]
                if root not in self.FS_CAPABLE_ROOTS:
                    continue
                member = dotted.rsplit(".", 1)[-1]
                if (dotted in self.FS_READ_ONLY_MEMBERS
                        or member in self.FS_MUTATING_NAMES
                        or member in self.MODE_CLASSIFIED_NAMES):
                    continue
                unclassified.append(f"{module}:{scope}:{dotted}")
        self.assertEqual(
            sorted(unclassified), [],
            "these calls reach a module that can touch the filesystem and are "
            "classified as neither mutating nor read-only. Classify each one -- "
            "an unclassified filesystem call is one nothing can decide about, "
            "and defaulting it to harmless is the fail-open direction.")

    def test_that_fail_closed_check_REFUSES_an_unclassified_member(self):
        """And it really refuses: the same logic over a probe using an `os` member
        neither list carries."""
        probe = [("probe", "import os\ndef f(p):\n    os.pathconf(p, 'x')\n")]
        unclassified = []
        for module, source in probe:
            for node, scope in self._calls_with_innermost_scope(
                    ast.parse(source)):
                dotted = self._dotted(node.func)
                if dotted is None or dotted.split(".")[0] \
                        not in self.FS_CAPABLE_ROOTS:
                    continue
                member = dotted.rsplit(".", 1)[-1]
                if (dotted in self.FS_READ_ONLY_MEMBERS
                        or member in self.FS_MUTATING_NAMES
                        or member in self.MODE_CLASSIFIED_NAMES):
                    continue
                unclassified.append(f"{module}:{scope}:{dotted}")
        self.assertEqual(unclassified, ["probe:f:os.pathconf"])

    def test_the_attribution_is_INNERMOST_and_qualified(self):
        """A nested call site must not be merged into its outer function's.

        `record_recovery_required` really is called from `_blocked`, nested inside
        `_converge_unit`. An outermost attribution labels it `_converge_unit` and
        would collapse it with any outer call of the same callee into one declared
        boundary -- one boundary string covering two instants, with no way to tell
        from the enumeration that two exist.
        """
        derived = self._derive_persistence()
        self.assertIn(
            "trial_recovery:_converge_unit._blocked:record_recovery_required",
            derived)
        self.assertNotIn(
            "trial_recovery:_converge_unit:record_recovery_required", derived)
        probe = [("probe", "def outer():\n"
                           "    def inner():\n"
                           "        os.replace(1, 2)\n"
                           "    os.replace(3, 4)\n")]
        self.assertEqual(
            self._derive_persistence(probe),
            {"probe:outer.inner:replace", "probe:outer:replace"},
            "an outer and a nested call of the same callee are TWO boundaries")

    @staticmethod
    def _declared():
        return (set(DECLARED_PERSISTENCE_BOUNDARIES)
                | set(DECLARED_EXTERNAL_CALL_BOUNDARIES)
                | set(DECLARED_OFF_MODULE_BOUNDARIES))

    @staticmethod
    def _killed_at():
        covered = set()
        for boundaries in KILL_POINT_COVERAGE.values():
            covered.update(boundaries)
        return covered

    def test_every_boundary_is_killed_at_bracketed_excluded_or_untested(self):
        """The FOUR dispositions must PARTITION the declared set.

        A boundary in none of them is a boundary nobody decided about, which is
        the shape this project has shipped before: the gap is invisible because
        nothing names it. So a boundary added later lands in no group and fails
        here, rather than silently becoming untested.
        """
        killed = self._killed_at()
        bracketed = set(BOUNDARIES_BRACKETED_BY_KILLED_POINTS)
        untested = set(BOUNDARIES_NOT_KILL_TESTED)
        excluded = set(BOUNDARIES_EXCLUDED_BY_CONTRACT)
        declared = self._declared()
        groups = {"killed": killed, "bracketed": bracketed,
                  "untested": untested, "excluded": excluded}

        self.assertEqual(
            declared - (killed | bracketed | untested | excluded), set(),
            "these boundaries are declared and fall into NO disposition -- "
            "nothing kills at them, nothing brackets them, and nothing records "
            "them as untested or as excluded by contract")
        self.assertEqual(
            (killed | bracketed | untested | excluded) - declared, set(),
            "these are dispositioned and not declared")
        for first in groups:
            for second in groups:
                if first < second:
                    self.assertEqual(
                        groups[first] & groups[second], set(),
                        f"a boundary cannot be both {first} and {second} -- one "
                        "of the two claims is wrong")

    def test_every_excused_boundary_states_a_REASON(self):
        """"Not killed at" is only acceptable with a reason attached, and a blank
        one is the same as no reason."""
        for group in (BOUNDARIES_NOT_KILL_TESTED,
                      BOUNDARIES_BRACKETED_BY_KILLED_POINTS,
                      BOUNDARIES_EXCLUDED_BY_CONTRACT):
            for boundary, reason in group.items():
                self.assertTrue(
                    isinstance(reason, str) and len(reason.strip()) > 40,
                    f"{boundary} is excused with no substantive reason: "
                    f"{reason!r}")

    def test_the_untested_set_is_only_the_exception_only_cleanup_branch(self):
        """A bound on the excuse itself. Today exactly two boundaries are not
        kill-tested and both are the temp-file cleanup inside an `except`, which a
        kill structurally cannot enter. If that set ever grows to something a kill
        COULD reach, this fails and the growth has to be argued rather than
        appended to a dict.
        """
        self.assertEqual(
            sorted(BOUNDARIES_NOT_KILL_TESTED),
            ["trial_executor:_atomic_write_json:remove",
             "trial_journal:_atomic_write_record:remove"])

    def test_every_declared_kill_point_is_actually_exercised(self):
        """Read off this file's OWN ast: the literal points passed to the harness.

        A point declared in the coverage map and never used is exactly as much a
        gap as a boundary with no point, and the difference is invisible to a
        reader.
        """
        tree = ast.parse(_THIS_FILE.read_text(encoding="utf-8"))
        used = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else None)
            if name not in ("kill_at", "recovery_kill_at"):
                continue
            if node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                used.add(node.args[0].value)
        self.assertEqual(
            set(KILL_POINT_COVERAGE) - used, set(),
            "declared kill points that no test uses")
        self.assertEqual(
            used - set(KILL_POINT_COVERAGE), set(),
            "kill points used by a test and absent from the coverage map, so "
            "nothing records which boundary they cover")

    def test_the_kill_is_a_real_process_exit_and_never_an_exception(self):
        """The killswitch must terminate the process, not raise. An exception
        unwinds and runs cleanup handlers, which is what a crash does not do."""
        self.assertIn("os._exit", _KILLSWITCH_SOURCE)
        self.assertNotIn("raise ", _KILLSWITCH_SOURCE)
        self.assertNotIn("sys.exit", _KILLSWITCH_SOURCE)
        self.assertIn("killswitch.kill_if", _FIXTURE_ADAPTER_SOURCE)

    def test_the_fixture_adapter_declares_the_absolute_state_restore(self):
        """The whole convergence argument rests on the adapter's declared
        absolute-state restore. A fixture that did not declare it would be
        testing a protocol nobody may run."""
        self.assertIn("UNDO_IS_ABSOLUTE_STATE_RESTORE = True",
                      _FIXTURE_ADAPTER_SOURCE)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
