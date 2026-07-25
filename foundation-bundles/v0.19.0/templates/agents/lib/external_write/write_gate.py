"""The deterministic pre-write gate: the runtime-enforcement heart of the safety
substrate.

`run_operation` (adapters.py) is the single chokepoint every external write passes through.
This module supplies the deterministic gate it runs BEFORE anything touches the
surface, making the design's core invariant mechanically true:

    No high-risk external action may run unless it is covered by a descriptor-declared,
    ACCEPTED phase — and until accepted, only against the declared test target (copy /
    bounded_sample / dry_run / native_undo), never live. An accepted phase authorizes only
    the declared bounded-test actions during build/supervised — it is NOT blanket live
    authorization.

THE OVERRIDING PROPERTY is fail-safe everywhere: a missing input (absent target signal,
absent/unreadable/malformed descriptor set, unknown/unclassified risk) must NEVER open the
gate. Every branch below defaults to refuse.

Design points settled from the code:

  * Target signal — an explicit, machine-readable `target` argument threaded through
    run_operation, whose test-target vocabulary REUSES dependency_projection.TEST_TARGETS and
    whose copy value reuses copy_run_proof's copy-surface convention: an Operation whose
    surface is COPY_SURFACE ("copy_surface") is implicitly a copy target even with no explicit
    target. A declared test target is honored ONLY when the op physically targets a recognized
    test/copy surface (is_test_surface); a test-target claim on a live surface is refused (I1),
    because the target string is a caller assertion and the write lands on op.surface.
    For a gated op an ABSENT target (no arg + a non-copy surface) fails safe to refuse
    — the gate never defaults to live. Extending the Operation record was rejected: its
    canonical_repr / digest is hash-bound (broker receipts key off it) and a target is an
    execution-context signal, not part of the operation's approved identity.

  * Blast-radius counter — an injected in-memory InvocationLedger keyed on the capability
    (surface::op_kind). The "window" is the ledger instance's lifetime, owned by the caller
    (per-session / per-batch). For a live irreversible op an ABSENT ledger fails safe to
    refuse (the cap cannot be enforced without a counter). Recording happens at gate-permit
    time; over-counting on a later refusal is the SAFE direction for a blast-radius cap.

Vocabulary constants below are duplicated from wizard/scripts/lib/dependency_projection.py
(external_write cannot import the build-side tree, a deliberate boundary) and pinned equal by cross-tree
tests in test_external_write_write_gate.py, exactly as contracts.RISK_CLASSES is.

Stdlib only — no third-party dependencies.
"""

import json
import os
import stat as _stat
import tempfile
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

try:  # POSIX advisory file locking (mac/Linux — the operator-project target).
    import fcntl as _fcntl
except Exception:  # pragma: no cover - non-POSIX fallback (no cross-process lock)
    _fcntl = None

from external_write.operations import Operation, Result
from external_write.contracts import OperationContract, get_contract


# ---------------------------------------------------------------------------
# Vocabulary (duplicated from dependency_projection.py; cross-tree-tested)
# ---------------------------------------------------------------------------

# The one risk class the gate must NEVER reach by silent fallback (design §4.5): an explicit
# read_only_local classification skips the gate; an ABSENT/unknown one never resolves here.
READ_ONLY_LOCAL = "read_only_local"

# An absent/unrecognized risk_class resolves to the MOST-protected class, never the safe
# one. Mirrors dependency_projection.FAIL_SAFE_RISK_CLASS / resolve_risk_class().
FAIL_SAFE_RISK_CLASS = "irreversible_external"

# The classes the gate treats as high-risk: acceptance + test-target required. Everything in the
# risk vocabulary except read_only_local (never gated) and reversible_external (already gated by
# the broker + copy_run_proof; the seeded status ops live here and stay ungated by this module).
GATED_RISK_CLASSES = frozenset({
    "irreversible_external", "standing_automation", "sensitive_data",
})

# The declared-test-target vocabulary (design §4.5/§4.7/§5.1), reused verbatim from
# dependency_projection.TEST_TARGETS. A gated op may run against any of these before acceptance.
TEST_TARGETS = frozenset({"copy", "bounded_sample", "dry_run", "native_undo"})

# TEST_TARGETS splits into
# two safety classes by LIVE BLAST RADIUS, not by the word "test" — a bounded live sample is a
# subset of the LIVE resource and cannot be made safe by surface separation the way copy is.
# The two classes below partition TEST_TARGETS EXACTLY (pinned by a test in
# test_external_write_write_gate.py) so a future test-target string can never silently default
# into the wrong safety class.
#
#   ISOLATED_TEST_TARGETS   — no live blast radius at all. `copy` is surface-based
#     (COPY_SURFACE, descriptor-independent) — unchanged/byte-identical. `dry_run` permits
#     unconditionally at THIS gate; that permit is SAFE only because a separate adapter
#     guarantees dry_run never reaches client.write (the gate authorizes the intent, the
#     adapter enforces no-mutation) — see evaluate_write_gate below.
#   LIVE_BOUNDED_TEST_TARGETS — a REAL live write to a bounded subset of the live resource
#     (perform-then-revert for native_undo; a bounded live sample for bounded_sample). These
#     are NOT surface-isolated, so they run the SAME live-enforcement funnel as an accepted
#     live write (recovery floor + mandatory cap + ledger) — the only relaxation vs. the
#     accepted live path is dropping the `accepted: true` requirement (a DECLARED capability
#     whose declared_test_target exactly matches suffices; see _declared_entry below).
ISOLATED_TEST_TARGETS = frozenset({"copy", "dry_run"})
LIVE_BOUNDED_TEST_TARGETS = frozenset({"bounded_sample", "native_undo"})

# The explicit live-target signal. A gated op must carry target=LIVE_TARGET affirmatively to
# even attempt a live write — it can never reach live by omission.
LIVE_TARGET = "live"

# copy_run_proof's copy-surface convention (copy_run_proof._synthetic_op). An Operation on this
# surface is inherently a copy target. Reusing it is why this module introduces no parallel mechanism.
COPY_SURFACE = "copy_surface"

# The recognized bounded/copy/test surfaces (I1): physical surfaces a write can land on WITHOUT
# reaching the operator's live record. A declared test target (copy/bounded_sample/dry_run/
# native_undo) is a caller ASSERTION about intent; it is honored only when the op physically
# targets one of these surfaces — otherwise a caller could pass target="copy" on a live surface
# and the write would still hit the live record. The sole convention today is copy_run_proof's
# COPY_SURFACE; a real bounded_sample / dry_run surface is a future concern and must be added here
# EXPLICITLY (never inferred), exactly like the vocabulary constants above.
TEST_SURFACES = frozenset({COPY_SURFACE})


def is_test_surface(surface: Any) -> bool:
    """True iff `surface` is a recognized bounded/copy/test surface — one a write cannot use to
    reach the operator's live record. Deterministic and fail-safe: an unrecognized surface is
    NOT a test surface, so a claimed test target on it is refused (I1)."""
    return surface in TEST_SURFACES


# ---------------------------------------------------------------------------
# System clock — the single source of any date this module writes
# ---------------------------------------------------------------------------

def system_clock() -> datetime:
    """Return the current UTC time from the system clock. The gate NEVER accepts a
    model-authored / passed-in 'today' string; every timestamp it writes originates here.
    Injectable in run_operation via `clock=` for deterministic tests. Reusable by any future
    module that needs the same clock discipline."""
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime) -> str:
    """ISO-8601 UTC with Z suffix (matches the receipt/broker timestamp format)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Fail-safe descriptor-set loader
# ---------------------------------------------------------------------------

# The project-root-relative path to the ONE descriptor-set file every emitted
# writes-back system carries (security/capability_descriptors.json). It holds the FULL
# descriptor set — every declared descriptor, `accepted` flags varying — not only the accepted
# ones; the prior name (ACCEPTED_DESCRIPTOR_SET_PATH) misled at a trust surface. BOTH gates read
# this SAME file: this module (write_gate, runtime) filters on `accepted: true` + surface match;
# the build-time coverage gate (coverage_gate.py) ignores `accepted` entirely and checks only
# DECLARATION. The loader's `open(path)` resolves against cwd — both the coverage-gate CLI and
# agent invocations run from the operator project root (see coverage_gate.py's CLI docstring and
# the project's operating rule that agents run from project root), so this project-root-relative
# path resolves correctly from either caller.
DESCRIPTOR_SET_PATH: Optional[str] = "security/capability_descriptors.json"

# The project-root-relative directory holding the persistent, per-run
# blast-radius ledgers (one JSON file per ledger_window_id — see
# PersistentInvocationLedger). Disk-first + audit convention, resolved against
# cwd exactly like DESCRIPTOR_SET_PATH (agents run from the operator project
# root). Fail-safe: an absent ledger file reads as zero consumed, not an open
# gate — see PersistentInvocationLedger._read_counts.
DEFAULT_LEDGER_DIR = "security/invocation_ledgers"

# The project-root-relative directory the emitted upgrade-reconcile step
# (wizard/scripts/lib/upgrade_reconcile.py, build-side) writes per-mechanism
# pause-state JSON into (F-55 B2). BUILD<->RUNTIME VALUE CONTRACT: that module
# defines its own PAUSED_MECHANISMS_DIR_REL constant with this SAME string
# value -- it WRITES the markers, this module READS them, and neither can
# import the other (upgrade_reconcile.py is a build-side script; this module
# is emitted into the operator runtime and must not import the build-side
# tree). The two constants are pinned equal BY VALUE in
# test_external_write_write_gate.py (a cross-tree test, run from
# wizard/scripts/lib, which CAN import both modules) -- never let them drift
# independently. Resolved against cwd exactly like DESCRIPTOR_SET_PATH /
# DEFAULT_LEDGER_DIR above (agents run from the operator project root).
PAUSED_MECHANISMS_DIR = ".wizard/paused-mechanisms"


def load_descriptor_set(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load the machine-readable descriptor set (the render_descriptor_registry_json shape: a
    JSON array of entries with id/name/action_class/risk_class/recovery_profile_ref/
    declared_test_target/blast_radius_cap/accepted). Holds the FULL set — every declared
    descriptor, `accepted` flags varying; write_gate filters on `accepted: true` (+ surface
    match) below, the build-time coverage gate ignores `accepted` entirely.

    FAIL-SAFE by construction: any missing input — no path configured, absent file, unreadable
    file, malformed JSON, or a non-array payload — returns [] (nothing accepted/declared), so a
    live gated op is refused. It NEVER raises and NEVER treats an unreadable set as permissive."""
    if path is None:
        path = DESCRIPTOR_SET_PATH
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return data


def _load_paused_op_kinds(paused_root: str) -> Optional[frozenset]:
    """(F-55 B2; corrected by the xvendor Fix A stat-based check) Load the
    UNION of ``paused_op_kinds`` across every ``*.json`` marker file directly
    under ``paused_root``.

    Returns:
      * ``frozenset()`` (empty) when ``paused_root`` is genuinely ABSENT
        (``os.stat`` raises ``FileNotFoundError``), or exists as a directory
        but contains no ``*.json`` files at all. No new denial: byte-identical
        to the prior (pre-F-55-B2) behavior.
      * the UNION frozenset of every marker's ``paused_op_kinds`` list when
        every marker present parses cleanly.
      * ``None`` -- the FAIL-CLOSED signal -- when ``paused_root`` EXISTS but
        is INACCESSIBLE (``os.stat`` raises any ``OSError`` other than
        ``FileNotFoundError`` -- e.g. permission-denied), when a NON-DIRECTORY
        sits at that path, when the directory EXISTS but cannot be listed
        (e.g. a permission-denied ``os.listdir`` failure), or when ANY
        ``*.json`` file in the directory is unreadable, is not valid JSON, is
        not a JSON object, or carries a ``paused_op_kinds`` value that is not
        a list of strings. A missing ``paused_op_kinds`` KEY (e.g. an existing
        B1 ``entrypoint_paused`` state file, which never carries this field)
        is NOT malformed -- it contributes the empty list, same as an absent
        key entirely. The caller MUST treat ``None`` as "the true paused set
        cannot be computed" and refuse the write in front of it: an
        inaccessible/corrupt/unlistable marker directory could be hiding a
        real pause for exactly the op_kind about to run, so ONE unreadable
        marker -- or an inaccessible/non-directory/unlistable path -- anywhere
        in this check is enough to refuse EVERY write reaching it (never just
        the op_kind the corrupt file happens to name) -- matching this
        module's "every branch defaults to refuse" posture. An
        existing-but-INACCESSIBLE or existing-but-UNLISTABLE path is
        unreadable markers, not an absent directory: it must NOT be conflated
        with the genuinely-absent case above, which is the only one that is
        safe to permit through.

    Fix A (xvendor trust-surface finding): the prior implementation used
    ``os.path.isdir(paused_root)`` to decide "absent vs. present", but
    ``os.path.isdir`` INTERNALLY SWALLOWS ``PermissionError``/``OSError`` and
    returns ``False`` on any stat failure -- so an EXISTING-but-UNREADABLE
    marker directory (a marker naming the op_kind about to run could be
    hiding inside it) was indistinguishable from a genuinely-absent one and
    fell through to the permissive "absent" branch: a fail-OPEN hole. This
    stat-based check distinguishes the two: ``FileNotFoundError`` from
    ``os.stat`` is the ONLY genuinely-absent signal; every other ``OSError``
    (including a swallowed-by-isdir permission failure) and every
    non-directory result at that path fail closed (``None``).
    """
    # These checks are DELIBERATELY split into separate try/except blocks (not
    # one try wrapping everything): a `FileNotFoundError` from `os.stat` means
    # the path genuinely isn't there (safe to permit through as "absent"),
    # but ANY OTHER `OSError` from `stat` (e.g. permission-denied -- which
    # `os.path.isdir` would have swallowed into a bare `False`), a
    # non-directory at that path, or a `listdir` that then raises `OSError`,
    # is an EXISTING, UNREADABLE/WRONG-SHAPE marker set -- that must fail
    # closed (`None`), never be conflated with the absent case.
    try:
        st = os.stat(paused_root)
    except FileNotFoundError:
        return frozenset()
    except OSError:
        # Exists but could not be stat'd (e.g. permission-denied) -- fail
        # closed. This is exactly the case `os.path.isdir` used to swallow.
        return None
    if not _stat.S_ISDIR(st.st_mode):
        # A non-directory sits at this path -- something is wrong; never
        # treat it like "absent".
        return None
    try:
        names = sorted(n for n in os.listdir(paused_root) if n.endswith(".json"))
    except OSError:
        # The directory EXISTS but could not be listed -- unreadable markers,
        # not an absent directory. Fail closed: a marker naming the op_kind
        # about to run could be hiding behind this listing failure.
        return None

    union: set = set()
    for name in names:
        path = os.path.join(paused_root, name)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        kinds = data.get("paused_op_kinds", [])
        if kinds is None:
            kinds = []
        if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds):
            return None
        union.update(kinds)
    return frozenset(union)


# ---------------------------------------------------------------------------
# Blast-radius invocation ledger (deterministic counter, outside the LLM)
# ---------------------------------------------------------------------------

# The outcome of an atomic reserve-under-cap (I-1). ``reserved`` is True iff the
# slots were consumed; ``consumed_before`` is the authoritative count for the key
# BEFORE this reservation; ``refusal`` is None on success, or a machine-readable
# cause when refused ("cap" — would exceed the cap; "lock_unavailable" — no
# cross-process lock, so an atomic reserve cannot be guaranteed, fail-closed I-2).
ReserveOutcome = namedtuple("ReserveOutcome", ["reserved", "consumed_before", "refusal"])


class InvocationLedger:
    """A simple in-memory invocation counter — the deterministic blast-radius window.

    The window is this instance's lifetime: the caller owns it (a per-session or per-batch
    ledger gives a per-session / per-batch window). Keyed on the capability (surface::op_kind).
    Deliberately below the LLM: no model text can move these counts."""

    def __init__(self) -> None:
        self._counts: Dict[str, int] = {}

    def count(self, key: str) -> int:
        return self._counts.get(key, 0)

    def record(self, key: str, n: int = 1) -> None:
        """Consume `n` slots for `key` (the window is bounded in UNITS, not
        invocations). Defaults to 1 so every call site that predates unit-aware
        counting — one invocation, one slot — is unaffected."""
        self._counts[key] = self.count(key) + n

    def reserve(self, key: str, n: int, cap: int) -> ReserveOutcome:
        """Atomically check-and-consume ``n`` slots for ``key`` iff doing so would
        NOT exceed ``cap`` (I-1). Single-process/in-memory, so the check and the
        increment are trivially one critical section. Returns a ``ReserveOutcome``:
        on success the slots are consumed and ``reserved`` is True; if it would
        exceed the cap, NOTHING is consumed and ``refusal`` is "cap"."""
        consumed = self.count(key)
        if consumed + n > cap:
            return ReserveOutcome(False, consumed, "cap")
        self._counts[key] = consumed + n
        return ReserveOutcome(True, consumed, None)


class PersistentInvocationLedger:
    """The blast-radius counter, PERSISTED TO DISK and keyed by the run's
    ``ledger_window_id`` — the Task 4 (v0.12.0 Slice 1, design §1) fix for F-39.

    F-39 (the defect): a bulk driver built a FRESH in-memory ``InvocationLedger``
    per chunk, so the accumulated blast-radius count reset to zero each chunk and
    the cap never accumulated across a session. This class makes the count
    DISK-AUTHORITATIVE: it lives in one JSON file per ``ledger_window_id``, so
    constructing a fresh ledger object per chunk (or after a restart / a
    regenerated loop) re-reads the SAME accumulated count — the window cannot be
    reset. The ``ledger_window_id`` is DERIVED by the caller from the verified
    RunEnvelope identity (never a mutable trusted field); this class only
    persists counts under it.

    Interface-compatible with ``InvocationLedger`` (``count`` / ``record``), so
    ``evaluate_write_gate`` consumes it with no change: the only difference is
    LIFETIME + persistence + key, exactly as the design specifies. Within one
    window the counts are still keyed by ``surface::op_kind`` (the gate's
    ``_ledger_key``), unchanged.

    I2 (atomic ledger): every mutation (``record`` and the atomic ``reserve``)
    is a read-modify-write performed under an EXCLUSIVE advisory file lock
    (``fcntl.flock`` on a per-window lock file) and committed with an atomic
    temp-file + ``os.replace``. Two concurrent runners therefore cannot lose an
    update. Cap enforcement goes through ``reserve``, which performs the cap
    CHECK and the increment inside the SAME critical section (I-1) — so the
    check-then-consume TOCTOU that let two runners double-spend the last slot is
    closed. If the advisory lock is unavailable (non-POSIX ``_fcntl is None``),
    both ``record`` and ``reserve`` FAIL CLOSED rather than proceed unlocked
    (I-2) — an unlocked consume is never the safe direction for a cap.

    Fail-safe: an absent ledger file means zero consumed (nothing spent yet) —
    NOT a permissive open gate. The gate's own fail-safe (an ABSENT ``cap_ledger``
    argument refuses a live gated op) is unchanged and orthogonal: this class is
    a ledger that exists, with a count of zero until something is recorded."""

    SCHEMA = "invocation_ledger-v1"

    def __init__(self, ledger_window_id: str, *, ledger_dir: Optional[str] = None) -> None:
        if not (isinstance(ledger_window_id, str) and ledger_window_id):
            raise ValueError("ledger_window_id must be a non-empty string")
        self._window_id = ledger_window_id
        self._dir = ledger_dir if ledger_dir else DEFAULT_LEDGER_DIR
        # Filenames are derived from the window id (already a hex digest in
        # normal use); sanitize defensively so an unexpected value can never
        # escape the ledger directory.
        safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_"
                       for ch in ledger_window_id)
        self._path = os.path.join(self._dir, f"{safe}.ledger.json")
        self._lock_path = self._path + ".lock"

    @property
    def path(self) -> str:
        return self._path

    @property
    def ledger_window_id(self) -> str:
        return self._window_id

    def _read_counts(self) -> Dict[str, int]:
        """Read the authoritative counts from disk. Fail-safe: a missing /
        unreadable / malformed file reads as an empty (all-zero) ledger — never
        raises, never invents a non-zero count."""
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        counts = data.get("counts")
        if not isinstance(counts, dict):
            return {}
        out: Dict[str, int] = {}
        for k, v in counts.items():
            if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool):
                out[k] = v
        return out

    def _atomic_write_counts(self, counts: Dict[str, int]) -> None:
        os.makedirs(self._dir, exist_ok=True)
        payload = {"schema": self.SCHEMA, "ledger_window_id": self._window_id,
                   "counts": counts}
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        fd, tmp = tempfile.mkstemp(prefix=".invocation_ledger.", suffix=".tmp",
                                   dir=self._dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise

    def count(self, key: str) -> int:
        """The authoritative consumed-unit count for ``key`` in this window,
        read fresh from disk every call (the disk is the single source of
        truth — no cached in-process count that a fresh instance could miss)."""
        return self._read_counts().get(key, 0)

    def record(self, key: str, n: int = 1) -> None:
        """Consume ``n`` slots for ``key`` atomically: acquire the exclusive
        per-window lock, read the current disk count, add ``n``, and commit via
        an atomic replace, then release. Serializes concurrent runners so no
        update is lost and the cap cannot be double-spent (I2).

        I-2 (fail-closed): if the POSIX advisory lock is unavailable
        (``_fcntl is None``), this REFUSES rather than proceeding through an
        unlocked read-modify-write — an unlocked consume can lose an update /
        double-spend, which is never the safe direction for a blast-radius cap."""
        if _fcntl is None:
            raise RuntimeError(
                "blast-radius ledger refuses to record without a cross-process "
                "lock: POSIX fcntl.flock is unavailable on this platform, so an "
                "atomic update cannot be guaranteed (fail-closed, I-2)")
        os.makedirs(self._dir, exist_ok=True)
        with open(self._lock_path, "w", encoding="utf-8") as lock_file:
            _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_EX)
            try:
                counts = self._read_counts()
                counts[key] = counts.get(key, 0) + n
                self._atomic_write_counts(counts)
            finally:
                _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_UN)

    def reserve(self, key: str, n: int, cap: int) -> ReserveOutcome:
        """Atomically reserve ``n`` slots for ``key`` under ``cap`` — the I-1 fix
        for the check-then-consume TOCTOU. The read of the current count, the
        cap check, and the increment all happen INSIDE ONE exclusive-lock
        critical section, so two concurrent runners can never both observe the
        same headroom and both consume it (the double-spend the old lockless
        ``count`` + separate ``record`` allowed). If the reservation would exceed
        the cap, NOTHING is written and ``refusal`` is "cap".

        I-2 (fail-closed): if the advisory lock is unavailable (``_fcntl is
        None``), REFUSE with ``refusal`` == "lock_unavailable" — never fall back
        to an unlocked reserve, which could double-spend the cap."""
        if _fcntl is None:
            return ReserveOutcome(False, self.count(key), "lock_unavailable")
        os.makedirs(self._dir, exist_ok=True)
        with open(self._lock_path, "w", encoding="utf-8") as lock_file:
            _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_EX)
            try:
                counts = self._read_counts()
                consumed = counts.get(key, 0)
                if consumed + n > cap:
                    return ReserveOutcome(False, consumed, "cap")
                counts[key] = consumed + n
                self._atomic_write_counts(counts)
                return ReserveOutcome(True, consumed, None)
            finally:
                _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Gate decision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GateDecision:
    """Outcome of the pre-write gate.

    permitted: True iff the op may proceed to receipt validation + write.
    refusal:   the Result to return immediately when not permitted (never None if not permitted).
    audit:     a dict to merge into the final 'written' Result.detail on success (e.g. the
               irreversibility acknowledgement); None for ops that write no audit record.
    """
    permitted: bool
    refusal: Optional[Result] = None
    audit: Optional[Dict[str, Any]] = None


_PERMIT = GateDecision(permitted=True)


def _refuse(reason: str, **extra: Any) -> GateDecision:
    detail: Dict[str, Any] = {"reason": reason, "gate": "write_gate_v1"}
    detail.update(extra)
    return GateDecision(permitted=False, refusal=Result(status="refused", detail=detail))


def _effective_risk_class(contract: Optional[OperationContract]) -> str:
    """An op with no contract, or a contract whose risk_class is not in the known
    vocabulary, resolves to the MOST-protected class — never read_only_local by omission."""
    if contract is None:
        return FAIL_SAFE_RISK_CLASS
    rc = contract.risk_class
    known = GATED_RISK_CLASSES | {READ_ONLY_LOCAL, "reversible_external"}
    if isinstance(rc, str) and rc in known:
        return rc
    return FAIL_SAFE_RISK_CLASS


def _resolve_target(op: Operation, target: Optional[str]) -> Optional[str]:
    """Resolve the machine-readable target signal. Reuses copy_run_proof's copy-surface
    convention (surface==COPY_SURFACE => implicit 'copy'). Returns None when the signal is
    ABSENT (no explicit arg and not a copy surface) — the caller fails that safe to refuse."""
    if op.surface == COPY_SURFACE:
        return "copy"
    return target


def _covering_entry(descriptor_set: Sequence[Dict[str, Any]], op: Operation,
                    risk_class: str) -> Optional[Dict[str, Any]]:
    """Return the first accepted descriptor entry that COVERS this op, or None.

    Covering requires all of: accepted is exactly True; the entry's capability id or name
    matches the op's surface (the deterministic op->capability join); and the entry's declared
    risk_class equals the op's effective risk_class (an acceptance recorded at a different risk
    level does not cover). Anything short of a full match => not covered => refuse live."""
    for e in descriptor_set:
        if not isinstance(e, dict):
            continue
        if e.get("accepted") is not True:
            continue
        if e.get("id") != op.surface and e.get("name") != op.surface:
            continue
        if e.get("risk_class") != risk_class:
            continue
        return e
    return None


def _declared_entry(descriptor_set: Sequence[Dict[str, Any]], op: Operation, risk_class: str,
                    target: str) -> Optional[Dict[str, Any]]:
    """Return the first DECLARED descriptor entry that covers this op for a LIVE_BOUNDED test
    `target`, or None. Distinct from `_covering_entry` (that function is left byte-unchanged;
    this is a separate lookup, not a conditional weakening of it — leaking the accepted-live
    path would be a drift risk).

    Same surface/risk-class join as `_covering_entry` (op's capability id/name match; declared
    risk_class equals the op's effective risk_class), but:
      (a) does NOT require `accepted` — a LIVE_BOUNDED write is exactly the PRE-acceptance
          mechanism (a declared capability, not an accepted one).
      (b) additionally requires `e.get("declared_test_target") == target` EXACTLY.
          `declared_test_target` is a single validated string (not a collection) — an entry
          declared for 'copy' does not cover a 'bounded_sample' request, and vice versa."""
    for e in descriptor_set:
        if not isinstance(e, dict):
            continue
        if e.get("id") != op.surface and e.get("name") != op.surface:
            continue
        if e.get("risk_class") != risk_class:
            continue
        if e.get("declared_test_target") != target:
            continue
        return e
    return None


def _effective_cap(contract: Optional[OperationContract],
                   covering: Optional[Dict[str, Any]]) -> Optional[int]:
    """Effective blast-radius cap = the SMALLEST of the caps present (the per-capability
    descriptor cap may override the contract default DOWNWARD, never upward). Returns
    None only when neither a contract cap nor a descriptor cap is set."""
    caps: List[int] = []
    if contract is not None and isinstance(contract.blast_radius_cap, int) \
            and not isinstance(contract.blast_radius_cap, bool):
        caps.append(contract.blast_radius_cap)
    if covering is not None:
        dc = covering.get("blast_radius_cap")
        if isinstance(dc, int) and not isinstance(dc, bool):
            caps.append(dc)
    return min(caps) if caps else None


def _ledger_key(op: Operation) -> str:
    return f"{op.surface}::{op.op_kind}"


def resolve_effective_cap(op: Operation,
                          descriptor_set: Optional[Sequence[Dict[str, Any]]] = None) -> Optional[int]:
    """Public accessor: the effective blast-radius cap for `op` — the contract's
    default `blast_radius_cap`, overridden DOWNWARD by matching descriptor entries'
    caps if any are present (same "smallest of the caps present" rule as
    `_effective_cap`, used internally by the live-enforcement funnel below).

    Adapter dispatch (adapters.py) reuses this to count a registered adapter's
    planned `len(effect_units)` against the SAME cap value the invocation-level gate
    would use — independently of, and BEFORE, that per-invocation ledger enforcement,
    which counts one Operation as one slot regardless of how many effect units it
    fans out to (the fan-out gap this exists to close).

    Matching is lenient on purpose: it considers EVERY descriptor entry whose
    id/name matches op.surface and whose risk_class matches op's effective risk
    class, WITHOUT requiring `accepted` or a declared_test_target match — a cap
    value is not an authorization decision, so it is not gated the way
    `_covering_entry`/`_declared_entry` are. Fail-safe: if more than one entry
    matches, the SMALLEST cap across ALL of them wins (never the first match) —
    the same "smallest cap wins" convention `_effective_cap` establishes for the
    contract-vs-single-entry case, applied here across every matching entry so a
    too-permissive cap can never be silently selected. Returns None only when
    neither a contract cap nor any matching descriptor cap is configured."""
    contract = get_contract(op.op_kind)
    risk_class = _effective_risk_class(contract)
    ds = load_descriptor_set() if descriptor_set is None else descriptor_set
    matches: List[Dict[str, Any]] = []
    for e in ds:
        if not isinstance(e, dict):
            continue
        if e.get("id") != op.surface and e.get("name") != op.surface:
            continue
        if e.get("risk_class") != risk_class:
            continue
        matches.append(e)
    if not matches:
        return _effective_cap(contract, None)
    caps = [c for c in (_effective_cap(contract, e) for e in matches) if c is not None]
    return min(caps) if caps else None


def _enforce_live_funnel(op: Operation, risk_class: str, contract: Optional[OperationContract],
                         entry: Dict[str, Any], cap_ledger: Optional[InvocationLedger],
                         clock: Any, n_units: int = 1) -> GateDecision:
    """The SHARED live-enforcement funnel: the recovery floor, the mandatory
    blast-radius cap + ledger, and the irreversibility audit. Called by BOTH the LIVE path
    (`entry` from `_covering_entry`, accepted required) and the LIVE_BOUNDED path (`entry` from
    `_declared_entry`, accepted NOT required) — the only difference between the two callers is
    which lookup produced `entry`; every live bound past that point is identical (constraint:
    the LIVE_BOUNDED relaxation vs. LIVE drops ONLY `accepted:true`). Duplicating this logic
    across two branches was rejected as a drift risk.

    n_units: the number of discrete effect units THIS operation plans to apply — 1 for
    the legacy field-write path and every existing caller (default, backward-compatible), or
    `len(adapter.plan(op.params))` for a registered adapter (adapters.py hoists that pure
    plan() call above the gate to compute it). The window this function enforces is bounded in
    UNITS across the ledger's lifetime, not in invocation count: a single multi-unit operation
    consumes `n_units` slots, so a session of many multi-unit invocations cannot slip past the
    cap by counting each invocation as one slot regardless of its fan-out (the per-op cap
    stays independent and unchanged — this is the separate AGGREGATE bound)."""
    # Recovery floor — NON-GRADUATING for standing_automation: a live standing_automation
    # op requires a recovery profile on its entry, and NO autonomy/maturity signal can waive it
    # (there is no such parameter on this gate — the floor is structural, not narrated).
    if risk_class == "standing_automation":
        ref = entry.get("recovery_profile_ref")
        if not (isinstance(ref, str) and ref.strip()):
            return _refuse(
                "live standing_automation refused: the non-graduating recovery floor is not "
                "satisfied — the entry declares no recovery_profile_ref (a backup/recover "
                "path). Maturity graduates supervision, never this safety net.",
                op_kind=op.op_kind, risk_class=risk_class)

    # Blast-radius cap — deterministic, outside the LLM. MANDATORY for every
    # gated risk class on a live OR live-bounded write, not only irreversible_external — an
    # unbounded gated live write (live or live-bounded) is never permitted.
    effective_cap = _effective_cap(contract, entry)
    if effective_cap is None:
        return _refuse(
            "live gated op refused: no blast-radius cap could be determined (neither a "
            "contract default nor a per-capability descriptor cap). An unbounded gated live "
            "write is never permitted.",
            op_kind=op.op_kind, risk_class=risk_class)
    if cap_ledger is None:
        return _refuse(
            "live gated op refused: no invocation ledger supplied, so the blast-radius cap "
            f"({effective_cap}) cannot be enforced. Refusing rather than running an untracked "
            "gated action.",
            op_kind=op.op_kind, risk_class=risk_class, blast_radius_cap=effective_cap)
    key = _ledger_key(op)
    # I-1: the cap CHECK and the consume are ONE atomic reserve-under-cap — never
    # a lockless ``count`` read followed by a separate ``record``. Two concurrent
    # runners can no longer both observe the same headroom and both consume it
    # (the double-spend TOCTOU). The reserve refuses WITHOUT incrementing when it
    # would exceed the cap, and fails closed if the lock is unavailable (I-2).
    outcome = cap_ledger.reserve(key, n_units, effective_cap)
    if not outcome.reserved:
        if outcome.refusal == "lock_unavailable":
            return _refuse(
                "live gated op refused: the blast-radius ledger's cross-process lock is "
                "unavailable on this platform, so an atomic reserve-under-cap cannot be "
                "guaranteed. Refusing rather than risking a double-spend of the cap "
                f"({effective_cap}) through an unlocked consume.",
                op_kind=op.op_kind, risk_class=risk_class, blast_radius_cap=effective_cap)
        consumed = outcome.consumed_before
        return _refuse(
            f"live gated op refused: blast-radius cap of {effective_cap} reached for this "
            "capability in the current window — the window is bounded in UNITS, not "
            f"invocations: {consumed} unit(s) already consumed in this window, this operation "
            f"plans {n_units} more, which would bring the total to {consumed + n_units}, "
            f"exceeding the cap of {effective_cap}.",
            op_kind=op.op_kind, risk_class=risk_class, blast_radius_cap=effective_cap,
            n_units=n_units, units_consumed_before=consumed)
    units_consumed_after = outcome.consumed_before + n_units

    # Per design §4.7: a live irreversible action writes an explicit, clock-stamped
    # "this cannot be reversed" acknowledgement. The timestamp comes from the clock, NEVER
    # a passed-in string.
    audit: Optional[Dict[str, Any]] = None
    if risk_class == FAIL_SAFE_RISK_CLASS:
        audit = {
            "irreversibility_acknowledgement": {
                "reversible": False,
                "note": "This action cannot be reversed.",
                "op_kind": op.op_kind,
                "blast_radius_cap": effective_cap,
                # units_consumed_in_window (renamed from invocation_index): the
                # CUMULATIVE unit count consumed in this window so far, post-reserve — no
                # longer an invocation index, since one operation can consume many units.
                # Taken from the atomic reserve's own before-count + n_units (not a
                # fresh disk read, which a concurrent runner could have moved).
                "units_consumed_in_window": units_consumed_after,
                "recorded_at": _iso_z(clock()),
            }
        }

    return GateDecision(permitted=True, audit=audit)


def evaluate_write_gate(op: Operation, *, target: Optional[str] = None,
                        descriptor_set: Optional[Sequence[Dict[str, Any]]] = None,
                        cap_ledger: Optional[InvocationLedger] = None,
                        clock: Optional[Any] = None,
                        n_units: int = 1,
                        paused_root: Optional[str] = None) -> GateDecision:
    """The deterministic pre-write gate. Returns a GateDecision; the caller returns the refusal
    immediately when not permitted, and merges `audit` into the success Result otherwise.

    n_units (default 1): the number of discrete effect units the calling operation plans
    to apply — threaded straight into `_enforce_live_funnel`'s unit-aware window. Defaults to 1
    so every existing direct caller (field-write ops, and every test/caller that predates this
    unit-aware window) is unaffected: 1 unit consumes exactly 1 window slot, byte-identical to
    the prior per-invocation behavior.

    paused_root (F-55 B2, default None => PAUSED_MECHANISMS_DIR): the directory of
    per-mechanism pause-state JSON markers the emitted upgrade-reconcile step writes. Checked
    immediately after the read_only_local short-circuit (step 2 below) and before every other
    branch, so it covers every WRITE path — gated (copy/dry_run/bounded_sample/native_undo/live)
    AND the ungated reversible_external path — while a pure local read (step 2) can never be
    blocked by a write-pause or by a corrupt marker. SCOPE (disclosed, do not overclaim): this is
    a runtime check on the SANCTIONED external-write route only
    (run_enveloped_operation -> run_operation -> evaluate_write_gate). A caller reaching the
    adapter layer directly (_run_adapter_operation / an Adapter's own apply_one) bypasses this
    marker entirely — closing THAT bypass is a BUILD-TIME job (scan.py's CAPABILITY-zone bans),
    never this runtime check; see test_external_write_write_gate.py's boundary-documenting test.

    Order (each step fails safe):
      1. Resolve the contract + effective risk class (fail-safe classification).
      2. read_only_local => never trips (design §4.5): permit untouched.
      2.5. Paused op_kind deny-branch (F-55 B2): any op_kind named in the union of every
           readable paused-mechanisms marker's `paused_op_kinds` => refuse ("... is paused
           pending migration ..."). Any marker present but unreadable/malformed/wrong-shape =>
           refuse fail-closed (the true paused set cannot be computed). No markers / absent dir
           => fall through unchanged (byte-identical to pre-F-55-B2 behavior).
      3. Not gated (reversible_external, ungated) => permit untouched (byte-identical to the ungated path).
      4. Gated => resolve target: absent => refuse. Otherwise the resolved target falls into
         exactly one of three classes:
           - ISOLATED_TEST_TARGETS ('copy', 'dry_run') — no live blast radius. 'copy' permits
             only on a recognized test/copy surface (I1), else refuses; 'dry_run' permits
             unconditionally (no surface/cap/ledger/acceptance requirement — safe only because
             the adapter guarantees no client.write under dry_run).
           - LIVE_BOUNDED_TEST_TARGETS ('bounded_sample', 'native_undo') — a real live write to
             a bounded subset of the live resource. Requires a DECLARED (not necessarily
             accepted) descriptor entry whose declared_test_target exactly matches, then runs
             the SAME live-enforcement funnel as an accepted live write (recovery floor +
             mandatory blast-radius cap + ledger).
           - LIVE_TARGET ('live') — requires a covering ACCEPTED descriptor entry, then the
             same live-enforcement funnel.
         Any other resolved value => refuse (unrecognized target).
    """
    if clock is None:
        clock = system_clock

    contract = get_contract(op.op_kind)
    risk_class = _effective_risk_class(contract)

    # (2) read_only_local NEVER trips — but ONLY when explicitly classified so (an absent
    # risk_class resolved to FAIL_SAFE_RISK_CLASS above, so it can never reach this branch).
    if risk_class == READ_ONLY_LOCAL:
        return _PERMIT

    # (2.5) F-55 B2 — paused op_kind deny-branch. Deliberately placed HERE: after the
    # read_only_local short-circuit (a write-pause, and a fail-closed refusal on a corrupt
    # marker, must NEVER block a pure local read) and BEFORE the `gated` computation below, so
    # every WRITE path — every gated class (copy/dry_run/bounded_sample/native_undo/live) AND
    # the ungated reversible_external path — still passes through this check (they all fall
    # through to here). SCOPE: this is enforced only on the SANCTIONED route
    # (run_enveloped_operation -> run_operation -> evaluate_write_gate); a caller reaching the
    # adapter layer directly bypasses it — that bypass is closed at BUILD time by scan.py, not
    # here (see this module's docstring for the full disclosure).
    resolved_paused_root = paused_root if paused_root is not None else PAUSED_MECHANISMS_DIR
    paused_op_kinds = _load_paused_op_kinds(resolved_paused_root)
    if paused_op_kinds is None:
        return _refuse(
            "gated operation refused: a paused-mechanisms marker exists but could not be read "
            "(unreadable, malformed JSON, or the wrong shape) — the true set of paused op_kinds "
            "cannot be computed, so this write is refused rather than risk missing an active "
            "pause",
            op_kind=op.op_kind)
    if op.op_kind in paused_op_kinds:
        return _refuse(
            f"gated operation refused: op_kind {op.op_kind!r} is paused pending migration "
            "(run the rebuild-paused-capability flow to repair and re-accept it before it "
            "runs live again)",
            op_kind=op.op_kind, paused=True)

    # (3) Is this op gated at all?  Unknown/uncovered writer (no contract) is gated;
    # any GATED_RISK_CLASSES member is gated; an explicit requires_accepted_phase is gated.
    gated = (
        contract is None
        or risk_class in GATED_RISK_CLASSES
        or bool(getattr(contract, "requires_accepted_phase", False))
    )
    if not gated:
        return _PERMIT

    # (4) Gated path — target resolution first.
    resolved = _resolve_target(op, target)
    if resolved is None:
        return _refuse(
            "gated operation refused: no target signal — a high-risk op must declare its "
            "target (a declared test target, or an affirmative live target); it never "
            "defaults to live",
            op_kind=op.op_kind, risk_class=risk_class)

    if resolved in ISOLATED_TEST_TARGETS:
        if resolved == "copy":
            # I1 (unchanged/byte-identical): a declared 'copy' target is a caller ASSERTION;
            # it is honored ONLY when the op's surface is a recognized test/copy surface. A
            # copy claimed on a live (non-test) surface must NOT permit — client.write would
            # otherwise hit the live record. Fail-safe: bind the target claim to where the
            # write physically lands.
            if not is_test_surface(op.surface):
                return _refuse(
                    f"gated operation refused: target {resolved!r} is a declared test target "
                    f"but the surface {op.surface!r} is not a recognized test/copy surface — a "
                    "test-target claim on a live surface is never honored (the write would hit "
                    "the live record). Route the operation to a copy/bounded test surface, or "
                    "declare the affirmative live target and satisfy the accepted-phase gate.",
                    op_kind=op.op_kind, risk_class=risk_class, surface=op.surface)
            # Copy against a recognized test/copy surface — always allowed, acceptance-
            # independent, no live blast radius, so no cap and no ledger required.
            return _PERMIT

        # resolved == "dry_run": permit UNCONDITIONALLY — no surface, cap, ledger, or
        # acceptance requirement. This permit is SAFE ONLY because a separate task's adapter
        # (run_operation) guarantees a dry_run op never reaches client.write: THIS gate
        # authorizes the intent, the ADAPTER enforces no-mutation. If that adapter guarantee
        # were ever removed, this unconditional permit would become a live-write hole.
        return _PERMIT

    if resolved in LIVE_BOUNDED_TEST_TARGETS:
        # A REAL live write to a bounded subset of the live resource (perform-then-revert for
        # native_undo; a bounded live sample for bounded_sample) — NOT surface-isolated, so it
        # runs the SAME live-enforcement funnel as an accepted live write. The only relaxation
        # vs. the accepted live path is dropping `accepted: true`: a DECLARED capability whose
        # declared_test_target exactly matches `resolved` suffices (accepted not required).
        ds = load_descriptor_set() if descriptor_set is None else descriptor_set
        declared = _declared_entry(ds, op, risk_class, resolved)
        if declared is None:
            return _refuse(
                f"gated operation refused: capability not DECLARED for test target {resolved!r} "
                "— a LIVE_BOUNDED write requires a descriptor entry whose declared_test_target "
                f"exactly matches {resolved!r} at risk_class {risk_class!r} (acceptance is NOT "
                "required pre-acceptance, but a DECLARATION is).",
                op_kind=op.op_kind, risk_class=risk_class)
        return _enforce_live_funnel(op, risk_class, contract, declared, cap_ledger, clock,
                                    n_units=n_units)

    if resolved != LIVE_TARGET:
        return _refuse(
            f"gated operation refused: unrecognized target {resolved!r}; must be {LIVE_TARGET!r} "
            f"or a declared test target ({sorted(TEST_TARGETS)})",
            op_kind=op.op_kind)

    # resolved == LIVE_TARGET — require a covering ACCEPTED descriptor phase.
    ds = load_descriptor_set() if descriptor_set is None else descriptor_set
    covering = _covering_entry(ds, op, risk_class)
    if covering is None:
        return _refuse(
            "live target refused: no covering ACCEPTED descriptor phase for this capability at "
            f"risk_class {risk_class!r} — run against the declared test target until a covering "
            "phase is accepted; an accepted phase authorizes only the declared bounded-test "
            "actions, never blanket live mutation",
            op_kind=op.op_kind, risk_class=risk_class)

    return _enforce_live_funnel(op, risk_class, contract, covering, cap_ledger, clock,
                                n_units=n_units)
