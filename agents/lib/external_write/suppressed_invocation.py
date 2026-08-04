"""The durable record of an entrypoint pause guard FIRING.

What this is for
----------------
When an upgrade finds that one of your own scripts changes something outside this
project without going through the safety check, it does not edit your script. It
puts a small guard at the top of the wrapper that runs it. From then on, invoking
that wrapper prints ``paused pending migration`` and stops before any of the
script's own work.

That part worked. What did not work is that nobody found out. Every scheduled
entry sends its output to a log file (``>> ...log 2>&1``), so the guard's message
went into a file nobody reads. On a real project this ran nine times over nine
days -- nine scheduled jobs that silently did not happen -- and the person
operating it learned nothing until someone went looking for an unrelated reason.

This module is what the guard now calls when it fires, so that the firing survives
on disk instead of only in a log: one record per paused mechanism under
``.wizard/suppressed-invocations/``, carrying when it first happened, when it last
happened, how many times, and which read-only outputs (a digest, an alert, a
backup) the upgrade found reason to think went dark with it -- or that it could not
establish that either way. The session-start health surface reads those records and
withholds its "everything is running normally" signal while any of them is still
live.

WHAT THIS ESTABLISHES -- and, precisely, what it does not
---------------------------------------------------------
Written out plainly because the value of the count depends entirely on reading it
in the terms it is recorded in.

ESTABLISHED
  The wrapper was invoked and the guard fired: the record is written from INSIDE
  the guard, ahead of its exit. An actual invocation is what proves a run was due,
  which is why this needs no schedule model, no list of expected outputs and no
  liveness monitor -- and why the guard itself was not moved or changed to make
  this work.

NOT ESTABLISHED BY THE ABSENCE OF A RECORD
  Stated first because it is the inference a reader will reach for. No record does
  NOT mean nothing was suppressed. Recording is best-effort by construction: the
  guard cannot be allowed to depend on it (see below), so a missing ``python3``, an
  unwritable directory or a refusal here all leave the run stopped and unrecorded.
  Separately, the guard's own location arithmetic relies on ``dirname`` being
  resolvable, so an environment without it does not reach this program at all.
  A record is positive evidence; its absence is not evidence of the negative.

``suppressed_count`` IS
  the number of times a wrapper invocation was stopped by the guard. One per
  invocation, and that part is measured: it is what this program does.

  A hand invocation counts -- also measured; nothing here distinguishes who
  invoked the wrapper.

  REASONING, NOT MEASUREMENT, and flagged as such: a scheduler that re-ran the same
  due run would presumably count twice, since each attempt is another invocation.
  No live scheduler retry has been observed for this, so treat it as an expectation
  rather than an established fact. It is not load-bearing today: the guard's exit
  status is unchanged (0), so nothing here gives a scheduler a reason to retry.

``suppressed_count`` IS NOT
  the number of scheduled runs that were due, and it is not a count of anything
  the schedule says. Treat it as the number of times someone or something tried to
  run this and was stopped.

THIS DOES NOT DETECT
  an output that went missing for any other reason; a scheduler that never fired
  at all; or a run that completed successfully and silently left one of its
  outputs out. None of those involve the guard, and nothing here reports on them.

THE CEILING
  This proves the guard fired. It does not establish that anybody saw it. The
  record is on disk and the health surface reports it; whether it is read is
  outside anything here. The enforcement ceiling of this whole package is
  build-time checks plus a person approving -- a recorder called from a shell
  guard is not a runtime sandbox and nothing here should be read as one.

SCOPE: THE ENTRYPOINT GUARD, AND ONLY IT
  There is a second, differently-shaped event that also says "paused pending
  migration": the runtime write gate refusing one gated operation for a paused
  mechanism. That is not this. This module counts the ENTRYPOINT WRAPPER guard
  stopping a whole invocation, which is a strictly different fact -- a whole run
  that did not happen, versus one write that was refused inside a run that did.
  Nothing here counts the second kind, and a reader should never have to guess
  which one a number refers to.

How it is called, and why it is built the way it is
---------------------------------------------------
The guard calls this as a plain subprocess::

    python3 <project>/agents/lib/external_write/suppressed_invocation.py record \\
      --mechanism-id <id> --entrypoint <relpath> --project-root <dir> \\
      --pause-state <path>

Three properties follow from the environment that call happens in, and each one is
a deliberate constraint rather than a style choice:

  STDLIB ONLY, AND NOTHING FROM THIS PACKAGE. The guard runs under the
  scheduler's environment, not an activated virtualenv, so ``python3`` may be a
  different interpreter than the project's -- or absent. An import chain that can
  fail is a count silently never recorded, so this module imports nothing beyond
  the standard library and nothing at all from ``external_write``.

  IT CANNOT DECIDE WHETHER THE PAUSED WORK RUNS. The guard's ``exit 0`` is its
  own statement, unconditional, and does not depend on this program's exit status
  (which is why the guard also neutralises that status with ``|| :`` -- under
  ``sh -e`` a nonzero exit here would otherwise abort the wrapper before the exit
  ran). Failing here loses a count. It can never let a paused script run.

  ITS WAIT FOR THE LOCK IS BOUNDED. A read-modify-write of a shared counter needs a
  lock, and a lock held by another invocation must not turn into an indefinite
  wait: the guard has already stopped the payload by this point, so a hang here
  would hang the scheduled job rather than endanger anything. The wait is capped at
  ``LOCK_WAIT_SECONDS`` and exhausting it REFUSES -- an unlocked read-modify-write
  would lose counts, and under-reporting is the one direction this module exists to
  prevent. Disclosed bound, because "bounded" is a stronger word than what is
  built: it is the WAIT that is capped, not the program. An individual filesystem
  call that itself blocks indefinitely -- a stalled network mount under the
  project -- is not bounded by anything here.

Two states this module refuses rather than guesses
--------------------------------------------------
  A MALFORMED OR FOREIGN RECORD. An existing record that will not parse, or one
  declaring a different ``mechanism_id`` than the file it was loaded as, is
  refused and left byte-for-byte as it is. Starting a fresh count over it would
  turn nine suppressed runs into one -- silently under-reporting the exact harm
  this exists to surface -- and rewriting it would destroy the evidence of
  whatever produced it.

  AN INACCESSIBLE RECORD. Absent and unreadable are different facts and are never
  conflated: ``os.stat`` distinguishes them, ``FileNotFoundError`` is the only
  genuinely-absent signal, and any other error refuses. An unreadable record is
  not "never suppressed".

Where the entangled-output labels come from
-------------------------------------------
The upgrade already looks for signs that the paused entrypoint is ALSO the thing
that produces read-only output you rely on, and names what it found. Those labels
are recorded on the pause-state record the guard points this program at, and are
carried onto the event here.

Their bound comes with them, and is not narrowed on the way through: the upstream
signal is TEXTUAL, not semantic -- read/report-shaped words in the paused file's own
source -- so a label means the upgrade found reason to think that output is affected,
never that it observed it stop. Deliberately broad in that direction: a false label
only says "paused too" about something that was fine, while a false silence is a
continuity promise nobody checked.

Deny-by-default, exactly as the upgrade notice treats it: ``entangled`` and
``unknown`` are handled IDENTICALLY, and only a positively-verified separate
read-only entrypoint reads as safe. ``unknown`` never renders as "no entangled
outputs" -- silence is not evidence of absence -- and a determination is never
weakened by a later read that could not establish it (see
``_merge_entanglement``).
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

try:  # POSIX advisory locking. Absent on non-POSIX platforms.
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - non-POSIX only
    _fcntl = None


# ---------------------------------------------------------------------------
# Surface + schema
#
# THE SINGLE HOME of the events directory. Every consumer imports this name; a
# re-spelled literal is how the writer and the reader of one mechanism come to
# disagree about where the record lives.
#
# Note what is deliberately NOT here: the paused-mechanisms directory. That value
# is already spelled in several places across the build/emitted boundary under a
# deliberate duplicated-by-value discipline, and this module adds no further
# spelling of it -- the guard hands over the pause-state path it built from the
# build-side constant, and the health surface passes its own.
# ---------------------------------------------------------------------------

SUPPRESSED_INVOCATIONS_DIR_REL = ".wizard/suppressed-invocations"

SUPPRESSED_INVOCATION_SCHEMA = "suppressed-invocation-v1"

#: Determination values for ``known_entangled_outputs``. Three, not two: "we did
#: not establish it" is its own answer and must never collapse into either of the
#: other two.
ENTANGLEMENT_ENTANGLED = "entangled"
ENTANGLEMENT_UNKNOWN = "unknown"
ENTANGLEMENT_SEPARATE_VERIFIED = "separate_verified"

#: Fail-closed ordering. A determination is only ever replaced by one at least as
#: strong; an unrecognised value ranks with the strongest, so a value added later
#: cannot silently weaken a record by nobody having classified it here.
_ENTANGLEMENT_RANK = {
    ENTANGLEMENT_SEPARATE_VERIFIED: 0,
    ENTANGLEMENT_UNKNOWN: 1,
    ENTANGLEMENT_ENTANGLED: 2,
}
_UNRECOGNISED_RANK = 2

#: How long a recorder waits for another invocation's lock before refusing. The
#: payload is already stopped by this point, so the cost of this bound is a lost
#: count and the cost of NOT bounding it is a hung scheduled job.
LOCK_WAIT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.02

_TEMP_RECORD_PREFIX = ".suppressed_invocation."
_LOCK_SUFFIX = ".lock"

EXIT_RECORDED = 0
EXIT_BAD_ARGS = 2
EXIT_NOT_RECORDED = 3


class SuppressedInvocationError(Exception):
    """Raised for anything this module refuses rather than guesses at.

    An exception rather than a quiet fallback: every case it covers is one where
    the alternative is a number that under-reports how much work silently did not
    happen, and a number nobody can tell is wrong is worse than a refusal
    somebody can see.
    """


# ---------------------------------------------------------------------------
# Paths and identity
# ---------------------------------------------------------------------------

def _validated_mechanism_id(mechanism_id: Any) -> str:
    """Return ``mechanism_id`` unchanged if it is safe to use as a filename stem;
    raise otherwise.

    VALIDATES, never sanitizes. Rewriting an unsafe id would map two distinct
    mechanisms onto one record, and the second would then overwrite the first's
    count -- from the filesystem's point of view they would be the same mechanism.

    THE RULE IS "ONE ORDINARY, NON-HIDDEN PATH COMPONENT" -- not an alphanumeric
    allowlist, and the difference was a real reach defect. This originally copied the
    trial journal's charset (``alnum`` plus ``-_.``), which is right for a
    machine-GENERATED id and wrong for this one: a mechanism id is DERIVED from the
    operator's own filename (``_migration_identity`` returns the relpath stem), so
    ``scripts/Daily Report.py`` yields ``Daily Report`` and an apostrophe yields
    ``o'brien``. Both are perfectly ordinary filenames, both were refused here, and
    the refusal was invisible: the upgrade reported the tripwire installed while
    every invocation recorded nothing. A space in a filename is entirely plausible
    for the non-technical operator this is built for.

    So what is checked is what actually matters for a filename stem, stated as
    positive structural properties rather than as a list of characters to fear:

      * it is exactly ONE path component (``basename`` of it is itself), so it can
        never traverse out of the records directory;
      * it is not ``.`` or ``..``, which are path components rather than names;
      * it does not begin with ``.`` -- a durable record is not a hidden file;
      * it carries no leading or trailing whitespace, which would make two visually
        identical ids distinct;
      * it carries no control characters, which no legitimate derived id has and
        which would corrupt any line-oriented reading of the record.
    """
    if not (isinstance(mechanism_id, str) and mechanism_id):
        raise SuppressedInvocationError(
            f"a mechanism id must be a non-empty string; got {mechanism_id!r}")
    if mechanism_id in (".", ".."):
        raise SuppressedInvocationError(
            f"the mechanism id {mechanism_id!r} is a path component, not an id")
    if mechanism_id.startswith("."):
        raise SuppressedInvocationError(
            f"the mechanism id {mechanism_id!r} may not begin with '.' -- this is "
            "a durable record, not a hidden file")
    if os.path.basename(mechanism_id) != mechanism_id:
        raise SuppressedInvocationError(
            f"the mechanism id {mechanism_id!r} is not a single name -- it contains "
            "a path separator, so a record keyed on it could be written outside the "
            "records directory. The id is NOT rewritten to fit.")
    if mechanism_id != mechanism_id.strip():
        raise SuppressedInvocationError(
            f"the mechanism id {mechanism_id!r} has leading or trailing whitespace, "
            "which would make two ids that look identical distinct. The id is NOT "
            "trimmed to fit, because trimming two different ids onto one filename "
            "would let one mechanism overwrite another's record.")
    control = sorted({ch for ch in mechanism_id
                      if ord(ch) < 0x20 or ord(ch) == 0x7F})
    if control:
        raise SuppressedInvocationError(
            f"the mechanism id {mechanism_id!r} contains control character(s) "
            f"{[hex(ord(c)) for c in control]}, which no derived id has and which "
            "would corrupt any line-oriented reading of the record. The id is NOT "
            "rewritten to fit.")
    return mechanism_id


def mechanism_id_refusal(mechanism_id: Any) -> Optional[str]:
    """``None`` if a record can be kept for ``mechanism_id``; the plain-language
    reason it cannot, otherwise.

    THE SAME rule as ``_validated_mechanism_id``, asked as a question instead of
    enforced -- one implementation, not two. It exists so the pass that installs a
    tripwire can find out BEFORE claiming success that this mechanism will be able
    to record: an id this refuses would otherwise be reported as ``upgraded`` while
    every invocation of that wrapper silently recorded nothing, which is this task's
    own defect reproduced inside its own fix.
    """
    try:
        _validated_mechanism_id(mechanism_id)
    except SuppressedInvocationError as exc:
        return str(exc)
    return None


def events_dir(project_root: Any) -> str:
    return os.path.join(str(project_root), SUPPRESSED_INVOCATIONS_DIR_REL)


def event_path(project_root: Any, mechanism_id: str) -> str:
    return os.path.join(events_dir(project_root),
                        f"{_validated_mechanism_id(mechanism_id)}.json")


def lock_path(project_root: Any, mechanism_id: str) -> str:
    return os.path.join(events_dir(project_root),
                        f"{_validated_mechanism_id(mechanism_id)}{_LOCK_SUFFIX}")


# ---------------------------------------------------------------------------
# The entangled read-output determination
# ---------------------------------------------------------------------------

def read_outputs_may_be_suppressed(determination: Any) -> bool:
    """True when the read-only outputs of this entrypoint may have gone dark with
    it -- the ONE place that decision is made.

    ``entangled`` and ``unknown`` both answer True, deliberately and identically:
    a continuity claim is only ever made on positive verification of a separate
    read-only entrypoint, so "we could not check" fails toward "treat it as
    paused too". An unrecognised value answers True for the same reason.
    """
    return _ENTANGLEMENT_RANK.get(str(determination),
                                  _UNRECOGNISED_RANK) > _ENTANGLEMENT_RANK[
        ENTANGLEMENT_SEPARATE_VERIFIED]


def _entanglement(determination: str, labels: Optional[List[str]] = None
                  ) -> Dict[str, Any]:
    return {"determination": determination, "labels": list(labels or ())}


def read_entanglement(pause_state_path: Optional[str]) -> Dict[str, Any]:
    """The entangled-read-output determination for a paused mechanism, read off
    the pause-state record the guard points here.

    Every failure to establish it -- no path given, absent file, unreadable file,
    unparseable content, unexpected shape -- answers ``unknown``, which the one
    classifier above treats exactly like ``entangled``. This function never
    raises: a missing determination must cost a label, never a count.
    """
    if not pause_state_path:
        return _entanglement(ENTANGLEMENT_UNKNOWN)
    try:
        with open(str(pause_state_path), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return _entanglement(ENTANGLEMENT_UNKNOWN)
    if not isinstance(data, dict):
        return _entanglement(ENTANGLEMENT_UNKNOWN)
    carries = data.get("carries_read_outputs")
    raw_labels = data.get("entangled_read_outputs")
    labels = ([str(x) for x in raw_labels] if isinstance(raw_labels, list) else [])
    if carries is True:
        return _entanglement(ENTANGLEMENT_ENTANGLED, labels)
    companion = data.get("separate_readonly_entrypoint")
    if carries is False and isinstance(companion, str) and companion.strip():
        # The ONLY case that reads as safe, and only on a positively-named
        # companion: `False` on its own is not a continuity claim.
        return _entanglement(ENTANGLEMENT_SEPARATE_VERIFIED)
    return _entanglement(ENTANGLEMENT_UNKNOWN)


def _merge_entanglement(existing: Any, fresh: Dict[str, Any]) -> Dict[str, Any]:
    """Combine a recorded determination with a fresh one, never downgrading.

    Monotonic toward "may be dark": once labels are known, a later read that could
    not establish them must not erase them, and a positively-verified companion
    must not survive a later read that could no longer verify it. Both directions
    are the same rule -- a determination is only ever replaced by one at least as
    strong.
    """
    if not isinstance(existing, dict):
        return dict(fresh)
    old_det = str(existing.get("determination", ENTANGLEMENT_UNKNOWN))
    new_det = str(fresh.get("determination", ENTANGLEMENT_UNKNOWN))
    old_rank = _ENTANGLEMENT_RANK.get(old_det, _UNRECOGNISED_RANK)
    new_rank = _ENTANGLEMENT_RANK.get(new_det, _UNRECOGNISED_RANK)
    determination = old_det if old_rank >= new_rank else new_det
    raw_old = existing.get("labels")
    labels: List[str] = [str(x) for x in raw_old] if isinstance(raw_old, list) else []
    for label in fresh.get("labels") or ():
        if str(label) not in labels:
            labels.append(str(label))
    return _entanglement(determination, labels)


# ---------------------------------------------------------------------------
# Durability primitives
#
# The temp-file + fsync + atomic-replace + directory-fsync pattern, and the
# POSIX advisory lock around a read-modify-write, are the same primitives this
# package already carries in `trial_journal`, `lifecycle_state`,
# `_ext_write_state` and `run_envelope`. They are re-implemented here rather than
# imported for the reason given in the module docstring: this program must run
# under whatever `python3` a scheduler hands it, with no import chain that can
# fail. The PRIMITIVES are reused; no existing SCHEMA is overloaded with the new
# fact -- the pause-state record, the migration queue and the run envelopes are
# left exactly as they are.
# ---------------------------------------------------------------------------

def _now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fsync_directory(directory: str) -> None:
    """fsync the DIRECTORY entry, so the ``os.replace`` that published the record
    is itself durable: the rename is a directory-entry change and an fsync of the
    file does not cover it."""
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _atomic_write_event(path: str, record: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=True,
                      allow_nan=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=_TEMP_RECORD_PREFIX, suffix=".tmp",
                              dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_directory(directory)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


@contextmanager
def _exclusive(path: str) -> Iterator[None]:
    """Serialize a read-modify-write against every other invocation recording the
    same mechanism, with a BOUNDED wait.

    Fails closed when POSIX advisory locking is unavailable, and fails closed when
    the bound is exhausted: an unlocked read-modify-write can lose an update, and
    a lost update here is a suppressed run that nothing on disk records -- the
    exact under-reporting this module exists to prevent.
    """
    if _fcntl is None:  # pragma: no cover - non-POSIX only
        raise SuppressedInvocationError(
            "refusing to update the suppressed-invocation record without a "
            "cross-process lock: POSIX fcntl.flock is unavailable on this "
            "platform, so two invocations in the same moment could lose a count.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                _fcntl.flock(lock_file.fileno(),
                             _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                    raise
                if time.monotonic() >= deadline:
                    raise SuppressedInvocationError(
                        "another invocation has held the suppressed-invocation "
                        f"record for {LOCK_WAIT_SECONDS:g}s; refusing to update it "
                        "unlocked rather than waiting longer, because the paused "
                        "work is already stopped and a longer wait would hold up "
                        "the scheduled job instead.")
                time.sleep(_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Reading an existing record
# ---------------------------------------------------------------------------

def _validated_event(raw: Any, mechanism_id: str, path: str) -> Dict[str, Any]:
    def bad(detail: str) -> SuppressedInvocationError:
        return SuppressedInvocationError(
            f"the suppressed-invocation record at {path!r} {detail}. It is left "
            "exactly as it is: starting a fresh count over it would under-report "
            "how many runs were stopped, and rewriting it would destroy whatever "
            "evidence it holds.")

    if not isinstance(raw, dict):
        raise bad(f"is a {type(raw).__name__}, not a record")
    if raw.get("schema") != SUPPRESSED_INVOCATION_SCHEMA:
        raise bad(f"declares schema {raw.get('schema')!r}, not "
                  f"{SUPPRESSED_INVOCATION_SCHEMA!r}")
    declared = raw.get("mechanism_id")
    if declared != mechanism_id:
        # Identity is the DECLARED value; the filename is only a candidate. A
        # disagreement is reported, never resolved by picking one of the two.
        raise bad(f"declares mechanism_id {declared!r} but was loaded as "
                  f"{mechanism_id!r}")
    count = raw.get("suppressed_count")
    if not (isinstance(count, int) and not isinstance(count, bool) and count >= 0):
        raise bad(f"carries suppressed_count {count!r}, which is not a count")
    for key in ("first_suppressed_at", "last_suppressed_at", "entrypoint_relpath"):
        if not isinstance(raw.get(key), str):
            raise bad(f"carries {key} {raw.get(key)!r}, which is not a string")
    if not isinstance(raw.get("known_entangled_outputs"), dict):
        raise bad("carries no known_entangled_outputs object")
    return raw


def _read_existing_event(path: str, mechanism_id: str) -> Optional[Dict[str, Any]]:
    """The record already on disk, or ``None`` if there genuinely is not one.

    ABSENT IS NOT INACCESSIBLE. ``os.stat`` rather than ``os.path.exists`` or
    ``is_file``, which answer False for both: a permission error swallowed as
    absence would read as "never suppressed", which is the one answer that must
    never be reachable by accident here.
    """
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SuppressedInvocationError(
            f"the suppressed-invocation record at {path!r} exists but could not be "
            f"examined ({exc.strerror or exc!r}), so it is not possible to tell how "
            "many runs have already been stopped. This is not the same as never "
            "having been suppressed, and it is not treated as such.")
    if not stat.S_ISREG(st.st_mode):
        raise SuppressedInvocationError(
            f"{path!r} is where this mechanism's suppressed-invocation record "
            "belongs, but it is not a regular file.")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise SuppressedInvocationError(
            f"the suppressed-invocation record at {path!r} could not be read "
            f"({exc.strerror or exc!r}). An unreadable record is not an empty one.")
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise SuppressedInvocationError(
            f"the suppressed-invocation record at {path!r} could not be parsed "
            f"({exc}). It is left exactly as it is rather than being replaced with "
            "a fresh count of one, which would report nine stopped runs as one.")
    return _validated_event(raw, mechanism_id, path)


# ---------------------------------------------------------------------------
# The write path -- what the guard calls
# ---------------------------------------------------------------------------

def record_suppressed_invocation(
    *,
    project_root: Any,
    mechanism_id: str,
    entrypoint_relpath: str,
    pause_state_path: Optional[str] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Record that ``entrypoint_relpath``'s pause guard stopped one invocation.

    Returns the record as written. Raises ``SuppressedInvocationError`` for
    anything it refuses; the caller in the guard neutralises that, and the guard's
    own unconditional ``exit 0`` is what keeps the paused work stopped either way.
    """
    mid = _validated_mechanism_id(mechanism_id)
    relpath = str(entrypoint_relpath or "").strip()
    if not relpath:
        raise SuppressedInvocationError(
            "an entrypoint relpath is required: a record that cannot name the "
            "wrapper that was stopped is not actionable by anyone reading it")
    path = event_path(project_root, mid)
    fresh = read_entanglement(pause_state_path)
    stamp = now or _now_iso_z()
    with _exclusive(lock_path(project_root, mid)):
        existing = _read_existing_event(path, mid)
        if existing is None:
            record: Dict[str, Any] = {
                "schema": SUPPRESSED_INVOCATION_SCHEMA,
                "mechanism_id": mid,
                "entrypoint_relpath": relpath,
                "first_suppressed_at": stamp,
                "last_suppressed_at": stamp,
                "suppressed_count": 1,
                "known_entangled_outputs": fresh,
            }
        else:
            record = dict(existing)
            record["entrypoint_relpath"] = relpath
            record["last_suppressed_at"] = stamp
            record["suppressed_count"] = int(existing["suppressed_count"]) + 1
            record["known_entangled_outputs"] = _merge_entanglement(
                existing.get("known_entangled_outputs"), fresh)
        _atomic_write_event(path, record)
    return record


# ---------------------------------------------------------------------------
# The read path -- what the health surface calls. READ-ONLY.
# ---------------------------------------------------------------------------

def scan_suppressed_invocation_events(*, directory: Optional[str] = None
                                      ) -> Dict[str, Any]:
    """Every suppressed-invocation record on disk.

    Returns a plain, JSON-serializable dict::

        {"events":     [{<the record>, "path": ...}, ...],
         "unreadable": [{"path", "reason"}, ...],
         "scan_error": None or a plain-language reason}

    STRICTLY READ-ONLY, and that is load-bearing rather than incidental. The
    session-start health command this feeds does self-heal other state as it
    reads. It must not do anything of the kind here: this is the surface most
    likely to be the first thing that observes suppression, and if observing it
    reaped, cleared or "converged" the record, then the act of looking would
    destroy the evidence of the harm. Nine suppressed runs erased by the first
    person to check is strictly worse than nine nobody noticed. Nothing in this
    function writes, creates a directory, or removes anything.

    ABSENT IS NOT INACCESSIBLE. A project where no guard has ever fired has no
    directory at all, and that is the overwhelmingly common case -- including every
    fresh build -- so it must report nothing rather than fire on every deployment.
    A directory that EXISTS and cannot be read is the opposite: nothing can be
    established about it, so it sets ``scan_error``. ``os.stat`` distinguishes the
    two; ``os.path.isdir`` answers False for both.

    IDENTITY IS THE DECLARED VALUE. A filename is a candidate id; each record is
    validated against the name it was loaded as and a disagreement lands in
    ``unreadable`` rather than being resolved by picking one.
    """
    target = directory
    result: Dict[str, Any] = {"events": [], "unreadable": [], "scan_error": None}
    if not target:
        result["scan_error"] = (
            "no location was given for the record of stopped runs, so it is not "
            "possible to tell whether any scheduled work has been stopped")
        return result

    try:
        mode = os.stat(target).st_mode
    except FileNotFoundError:
        # No guard has ever fired here. Nothing stopped, nothing to say.
        return result
    except OSError as exc:
        result["scan_error"] = (
            f"the record of stopped runs at {target!r} could not be examined "
            f"({exc.strerror or exc!r}), so it is not possible to tell whether any "
            "scheduled work is being stopped without you being told")
        return result
    if not stat.S_ISDIR(mode):
        result["scan_error"] = (
            f"{target!r} is where the record of stopped runs belongs, but it is "
            "not a folder, so it is not possible to tell whether any scheduled "
            "work is being stopped without you being told")
        return result

    try:
        names = sorted(os.listdir(target))
    except OSError as exc:
        result["scan_error"] = (
            f"the record of stopped runs at {target!r} could not be listed "
            f"({exc.strerror or exc!r}), so it is not possible to tell whether any "
            "scheduled work is being stopped without you being told")
        return result

    for name in names:
        if name.startswith(_TEMP_RECORD_PREFIX) or name.endswith(_LOCK_SUFFIX):
            continue
        if not name.endswith(".json"):
            continue
        path = os.path.join(target, name)
        candidate_id = name[: -len(".json")]
        # Everything derived from this record is inside the try: a record whose
        # shape defeats any step is reported UNREADABLE and the sweep continues,
        # so one malformed file cannot take every other mechanism's
        # discoverability with it.
        try:
            record = _read_existing_event(path, _validated_mechanism_id(candidate_id))
            if record is None:  # pragma: no cover - raced deletion
                continue
            entry = dict(record)
            entry["path"] = path
        except Exception as exc:  # noqa: BLE001 -- reported, never swallowed.
            result["unreadable"].append({"path": path, "reason": str(exc)})
            continue
        result["events"].append(entry)
    result["events"].sort(key=lambda e: str(e["mechanism_id"]))
    return result


# ---------------------------------------------------------------------------
# CLI -- the guard's caller
#
# Exit codes are honest and deliberately NOT swallowed here: the guard is what
# neutralises them (`|| :`), because that is the layer whose `exit 0` must stay
# unconditional. A recorder that reported success on failure would make the log
# line -- the one thing a person already reading the log would see -- a lie.
# ---------------------------------------------------------------------------

_CLI_RECORD = "record"


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="suppressed_invocation.py",
        description=("record that an entrypoint's pause guard stopped one "
                     "invocation before any of the script's own work ran"))
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    rec = sub.add_parser(_CLI_RECORD, help="record one stopped invocation")
    rec.add_argument("--mechanism-id", required=True)
    rec.add_argument("--entrypoint", required=True)
    rec.add_argument("--project-root", required=True)
    rec.add_argument("--pause-state", default=None)
    return parser


def _emit(payload: Dict[str, Any]) -> None:
    """One structured line on stderr, and NOTHING on stdout.

    Stderr is a convenience for somebody already reading the log that swallowed
    this message for nine days -- never the delivery. The delivery is the durable
    record and the health surface that reads it. Stdout belongs to the wrapper.
    """
    sys.stderr.write(json.dumps(payload, sort_keys=True) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))
    try:
        record = record_suppressed_invocation(
            project_root=args.project_root,
            mechanism_id=args.mechanism_id,
            entrypoint_relpath=args.entrypoint,
            pause_state_path=args.pause_state,
        )
    except Exception as exc:  # noqa: BLE001 -- reported, never swallowed.
        _emit({
            "schema": SUPPRESSED_INVOCATION_SCHEMA,
            "event": "suppressed_invocation_not_recorded",
            "mechanism_id": args.mechanism_id,
            "entrypoint_relpath": args.entrypoint,
            "reason": str(exc),
        })
        return EXIT_NOT_RECORDED
    _emit({
        "schema": SUPPRESSED_INVOCATION_SCHEMA,
        "event": "suppressed_invocation",
        "mechanism_id": record["mechanism_id"],
        "entrypoint_relpath": record["entrypoint_relpath"],
        "first_suppressed_at": record["first_suppressed_at"],
        "last_suppressed_at": record["last_suppressed_at"],
        "suppressed_count": record["suppressed_count"],
        "known_entangled_outputs": record["known_entangled_outputs"],
        "record": event_path(args.project_root, record["mechanism_id"]),
    })
    return EXIT_RECORDED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
