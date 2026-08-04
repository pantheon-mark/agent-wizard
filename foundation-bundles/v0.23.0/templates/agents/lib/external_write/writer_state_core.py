"""Structural state of an open bespoke-writer entry -- the bottom layer of the
writer-state machinery, and a LEAF: it imports no sibling in this package.

What "structural" means here
----------------------------
Everything about a flagged writer that is decidable from two inputs alone: the
queue entry the upgrade reconcile recorded, and the writer file on disk. Whether
the writer exists, whether it is a test module nothing invokes, and whether the
violation kinds recorded against it are ones our own remediation covers. Nothing
in this module reads, writes, or names any record of a human decision about a
writer; the layer above combines this state with those records.

That blindness is the point, not an accident of the current call graph. It is what
lets the layer that RECORDS a decision ask this one for a writer's state without
the two modules importing each other -- which they used to, in both directions,
each lazily, so neither import ever failed and nothing noticed. A cycle there is
what made the decision-recording rule impossible to tighten: any check it wanted
to make about a writer's state had to come from the module already asking it about
decisions. See `test_external_write_writer_state_layers.py` for the pair of
assertions that hold the split in place -- one that the graph is acyclic, and a
separate one that classification here does not consult that state, because the
first does not imply the second.

Why this module exists at all
-----------------------------
An operator project's pending-migration queue
(``agents/handoffs/pending_migrations.json``) can carry a "bespoke writer" entry: a
hand-rolled per-chunk write loop that bypasses the sanctioned, gated bulk write
path (``run_sanctioned_bulk``) and was flagged non-conformant on upgrade. Such an
entry is keyed on a RELPATH-DERIVED ``mechanism_id`` with NO owning-capability
field -- so the id-keyed safety views were once structurally BLIND to it: a project
with an OPEN bypass reported green/done anyway.

This module defines the ONE canonical predicate those views consume to close that
hole with a coarse, fail-closed, PROJECT-WIDE block: safety must NOT depend on
attributing the writer back to a capability (that attribution is a separate,
advisory-only concern) -- the mere EXISTENCE of any open bespoke-writer entry makes
the whole project non-green.

What a "bespoke writer" entry IS
--------------------------------
An entry in the pending-migrations queue where ``writer_relpath`` is set
(non-null, non-empty) AND ``status == "pending"``. A canonical-capability
migration entry has ``writer_relpath is None`` (see
``upgrade_reconcile._append_migration_request`` / the ``MechanismReport`` schema)
and is NOT a bespoke writer -- it is already covered by the id-keyed views and must
never trip this block (no over-firing).

Fail-closed contract (deliberate)
----------------------------------
* A genuinely ABSENT queue file is a NORMAL, non-error input: there is nothing
  queued, so there is no open bypass -> returns ``[]``. "Absent" and "unreadable"
  are never conflated (the same distinction every other reader in this package
  draws).
* An EXISTING-but-unreadable/malformed queue file (an ``OSError`` other than
  ``FileNotFoundError``, invalid JSON, or a top-level shape that is not a JSON
  array) must NEVER silently collapse to "no open entries" and thus a false green
  -- doing so is exactly the failure mode this predicate exists to close. It RAISES
  ``ExternalWriteStateReadError``; every caller treats that raise as NON-GREEN
  (blocking), never as a clean bill of health.
* A non-dict individual entry is skipped (it cannot carry a ``writer_relpath`` to
  act on) -- per-entry tolerance mirrors ``capability_health._is_pending_
  migration``; only the top-level structural failures above raise.

Enforcement ceiling (disclosure): this is build-time + operator-as-approver
enforcement, NOT a runtime/OS sandbox -- the same ceiling every module in this
package discloses. This module reports a state; the gate/health views that consume
it are what decline to say "done"/"normal".

Zoning note: this module is listed in ``zones.SEALED_KERNEL_MODULE_PATHS``. That
is a zone DECLARATION, not an exemption it currently needs -- it imports no sibling
here, constructs no credential, names no adapter and never calls
``run_operation``, so it passes every check on its own merits today. It is listed
because it IS kernel machinery, and leaving that to be inferred from "it happens
not to import a sibling right now" is precisely the infer-identity-from-incidental-
structure mistake this package refuses elsewhere. Membership grants NO capability
the right to import this module (that allowlist is the independent
``scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES`` set).

Stdlib only -- no third-party dependencies, and no first-party ones either.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List, NamedTuple

# Duplicated-by-value from lifecycle_state.MIGRATION_QUEUE_REL /
# capability_health.MIGRATION_QUEUE_REL / upgrade_reconcile.MIGRATION_QUEUE_REL
# (never imported across the build/runtime boundary -- same discipline as every
# other path constant in this package).
MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"


class ExternalWriteStateReadError(Exception):
    """The pending-migrations queue EXISTS but could not be read/parsed. Raised
    (never swallowed) so a read failure can never present as "no open bypass"
    (a false green). Callers treat this as NON-GREEN, exactly like a confirmed
    open bypass -- fail-closed."""


def read_migration_queue(project_root: str) -> List[Any]:
    """The full, parsed pending-migrations queue (every entry, whatever its
    shape) under ``project_root`` -- the single fail-closed reader every consumer
    of this state goes through, in this module and in the state service above it.

    Absent queue file -> ``[]`` (nothing queued; a NORMAL non-error input).
    Existing-but-unreadable/malformed/non-array -> raises
    ``ExternalWriteStateReadError`` (fail-closed; see module docstring) -- never a
    misleading empty list on a read failure."""
    path = Path(project_root) / MIGRATION_QUEUE_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ExternalWriteStateReadError(
            f"pending-migrations queue {path} exists but could not be read: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ExternalWriteStateReadError(
            f"pending-migrations queue {path} exists but is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ExternalWriteStateReadError(
            f"pending-migrations queue {path} exists but is not a JSON array")
    return data


def is_open_bespoke_writer_entry(entry: Any) -> bool:
    """The ONE canonical per-entry predicate: True iff ``entry`` is an OPEN
    bespoke-writer entry -- a dict whose ``writer_relpath`` is set (non-null,
    non-empty) AND whose ``status`` equals ``"pending"``.

    A non-dict individual entry is skipped (it cannot carry a ``writer_relpath``
    to act on). "set (non-null)" per the contract; an empty string is
    degenerate/not a real relpath and is treated as unset. Any other non-null
    value counts (fail-closed: an odd-shaped-but-present ``writer_relpath`` still
    blocks). A canonical-capability migration entry has ``writer_relpath is None``
    and is deliberately NOT a bespoke writer (no over-firing)."""
    if not isinstance(entry, dict):
        return False
    writer_relpath = entry.get("writer_relpath")
    if writer_relpath is None or writer_relpath == "":
        return False
    return entry.get("status") == "pending"


def open_bespoke_writer_migrations(project_root: str) -> List[Dict[str, Any]]:
    """Return the list of OPEN bespoke-writer migration entries under
    ``project_root`` -- every entry in ``agents/handoffs/pending_migrations.json``
    whose ``writer_relpath`` is set (non-null, non-empty) AND whose ``status``
    equals ``"pending"`` (see ``is_open_bespoke_writer_entry``).

    This is the ONE canonical definition of "is there an open external-write
    bypass in this project" -- attribution-free (it deliberately ignores
    ``mechanism_id`` / any owning-capability field) and reused by every safety
    view, never re-implemented per caller.

    Absent queue file -> ``[]`` (nothing queued). Existing-but-unreadable/
    malformed -> raises ``ExternalWriteStateReadError`` (fail-closed; see module
    docstring). Never returns a misleading empty list on a read failure."""
    return [e for e in read_migration_queue(project_root)
            if is_open_bespoke_writer_entry(e)]


def open_bespoke_writer_relpaths(project_root: str) -> List[str]:
    """Convenience projection over ``open_bespoke_writer_migrations``: the sorted,
    de-duplicated ``writer_relpath`` string(s) of every open bespoke-writer entry
    -- the plain-language "fix this file" list a gate/health view names to the
    operator. Raises ``ExternalWriteStateReadError`` on an unreadable queue, same
    fail-closed contract as the predicate it derives from."""
    return sorted({
        str(e.get("writer_relpath"))
        for e in open_bespoke_writer_migrations(project_root)
    })


# ---------------------------------------------------------------------------
# Deterministic STATE CLASSES over the open bespoke-writer set.
#
# The coarse, attribution-free presence-of-violation gate WORKED and is NOT undone
# here: ``open_bespoke_writer_migrations`` above is untouched and remains the
# single attribution-free definition of "is there an open external-write bypass".
# What a real-operator validation found is that making EVERY open entry block
# EVERYTHING means one unrepairable writer bricks acceptance project-wide,
# permanently, with no operator-reachable exit -- the gate's own "never block the
# REPAIR" principle holding locally and failing globally.
#
# THE DECIDABILITY MOVE. "Does a reachable remediation exist?" is undecidable in
# general -- proving a behaviour-preserving rewrite to scan-clean code exists is
# exactly the semantic judgement the coarse gate exists to keep out (both
# cross-vendor advisors independently rejected asking it). So we do not ask it. We
# ask a question we CAN answer: does OUR OWN deterministic remediator cover every
# violation recorded on this entry? That is decidable, because we know what our
# remediator does. It keys on the scanner's recorded violation KINDS, which the
# reconcile already persists on each entry.
#
# DELIBERATE DEVIATION FROM ADVISOR OUTPUT -- DO NOT "SIMPLIFY" BACK.
# gpt-5.5's proposed table listed ``needs_person`` as NON-blocking. That silently
# re-opens the acceptance-goes-green-around-a-live-writer false green. Here
# NEEDS_PERSON REMAINS BLOCKING; its only sanctioned exit is an explicit,
# hash-bound operator decision recorded by a layer above this one -- a recorded
# human decision, never a classifier's silent judgement. Guarded by
# test_writer_state_classes.test_needs_person_without_acknowledgement_is_blocking.
# ---------------------------------------------------------------------------

class WriterState:
    """The five states an open bespoke-writer entry can be in. Plain string
    constants (not an Enum) so they serialize into health/report JSON directly,
    matching how every other typed signal in this package is surfaced.

    This class is the SINGLE declaration of the vocabulary; the state service and
    the upgrade-notice renderer both bind these values rather than re-spelling
    them. Two of the five are deliberately NOT producible here:
    ``ACKNOWLEDGED_RISK`` needs a recorded human decision, which is a layer above,
    and ``RESOLVED`` is the reaper's. Declaring a name is not the same as reading
    the state behind it -- see ``structural_classification``."""

    BLOCKING_LIVE_ENABLE = "blocking_live_enable"
    NEEDS_PERSON = "needs_person"
    NON_LIVE = "non_live"
    ACKNOWLEDGED_RISK = "acknowledged_risk"
    RESOLVED = "resolved"   # reserved: emitted by the REAPER, never by classification


#: Violation kinds OUR OWN remediation covers. The rebuild flow rewrites a
#: bespoke writer onto the sanctioned bulk path, and the kernel-runner injection
#: removes the capability's reason to name a client/adapter at all -- between them
#: these five kinds are mechanically fixable. Verified against all 7 real estate
#: entries 2026-07-25: agents/inbox/runner.py and scripts/finish_estate_cleanup.py
#: record only kinds from this set (correctly BLOCKING -- we can fix them), while
#: agents/upkeep/runner.py additionally records ``forbidden_import`` (correctly
#: NEEDS_PERSON -- entangled urllib notification delivery, which no remediator of
#: ours rewrites).
REMEDIABLE_VIOLATION_KINDS = frozenset({
    "adapter_module_import",
    "adapter_registry_reference",
    "sealed_kernel_import",
    "raw_run_operation_reference",
    "credential_provider_reference",
})

#: Declared invocation surfaces -- the places the running system says what it
#: actually invokes. Used only to DISQUALIFY a non_live classification, never to
#: grant one.
_LIVE_SURFACE_RELPATHS = (
    "agents/cron/cron_config.md",
    "agents/roster.md",
)

#: Directory names that are never operator code and never an invocation
#: surface: vendored dependencies, VCS internals, and derived caches. Excluded
#: from the reference scan entirely. (Real estate case 2026-07-25: `.venv`
#: carried third-party pycparser modules that are INTENTIONALLY unparseable,
#: and scanning them fail-closed every non_live classification in the project.)
#:
#: PUBLIC, and deliberately so: it is the package's ONE answer to "which
#: directories are not this project's own code", and the bypass scanner's
#: whole-project consent sweep bounds its input with the same set rather than
#: keeping a second copy that has to be kept in step. Exporting it does not
#: cost this module its leaf status -- a name read out of here is not an import
#: made from here.
NON_PROJECT_DIRS = frozenset({
    ".venv", "venv", ".git", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", "site-packages", "build", "dist",
})


def _recorded_violation_kinds(entry: Dict[str, Any]) -> set:
    """The set of violation ``kind`` strings recorded on ``entry`` by the
    reconcile at pause time. Unknown/odd shapes contribute a sentinel that is
    NOT in ``REMEDIABLE_VIOLATION_KINDS``, so anything unrecognised fails
    closed toward NEEDS_PERSON rather than toward "we can fix it"."""
    kinds = set()
    for v in entry.get("violations") or []:
        if isinstance(v, dict):
            kind = v.get("kind") or v.get("rule")
            kinds.add(str(kind) if kind else "__unrecognised__")
        else:
            kinds.add("__unrecognised__")
    return kinds


def _matches_test_naming(writer_relpath: str) -> bool:
    """Signal 1 of 3 for non_live: unittest discovery naming."""
    stem = Path(writer_relpath).name
    return stem.startswith("test_") or stem.endswith("_test.py")


def _has_test_structure(source_text: str) -> bool:
    """Signal 2 of 3 for non_live: the module actually contains test-framework
    structure -- a ``unittest``/``pytest`` import AND either a TestCase-shaped
    class or a ``test_*`` function. AST-parsed, never a text grep, so a mere
    mention in a string or comment does not qualify. Unparseable -> False
    (fail-closed: an unparseable module is never granted non_live)."""
    try:
        tree = ast.parse(source_text)
    except (SyntaxError, ValueError):
        return False

    imports_framework = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] in ("unittest", "pytest") for a in node.names):
                imports_framework = True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in ("unittest", "pytest"):
                imports_framework = True
    if not imports_framework:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                if name == "TestCase":
                    return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                return True
    return False


def _referenced_by_live_surface(root: Path, writer_relpath: str) -> bool:
    """Signal 3 of 3 for non_live (inverted): is this writer named by anything
    the running system actually invokes? True DISQUALIFIES non_live.

    Checks the declared invocation surfaces (cron config / roster) and any
    non-test Python module in the project that names this writer's relpath or
    module stem. Any read failure returns True (fail-closed: unverifiable means
    we must not grant the non-blocking classification)."""
    stem = Path(writer_relpath).stem

    # Declared invocation surfaces are prose/tables, not code -- a textual
    # match is the only available signal and the right one there.
    for rel in _LIVE_SURFACE_RELPATHS:
        p = root / rel
        try:
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8")
        except OSError:
            return True
        if writer_relpath in text or stem in text:
            return True

    # Python modules are parsed, never grepped. A COMMENT mentioning the module
    # is NOT an invocation (real estate case: agents/inbox/runner.py carries
    # `# Header / From parsing (pure -- see test_inbox_runner.py)`), whereas an
    # import or a string literal naming it IS. The AST gives exactly that
    # discrimination for free: comments are absent from the tree, string
    # literals are not. A text grep here would be the same infer-from-
    # incidental-structure defect class.
    try:
        candidates = list(root.rglob("*.py"))
    except OSError:
        return True
    for p in candidates:
        try:
            rel_posix = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel_posix == writer_relpath:
            continue
        if _matches_test_naming(rel_posix):
            continue          # a test referencing a test does not make it live
        if "/lib/external_write/" in "/" + rel_posix:
            continue          # the sealed kernel is not an invocation surface
        parts = set(Path(rel_posix).parts)
        if parts & NON_PROJECT_DIRS:
            continue          # vendored/derived trees are not invocation surfaces.
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return True       # unreadable -> cannot verify -> fail closed.
        # Cheap, over-inclusive PRE-FILTER: a file that never mentions this
        # writer cannot reference it, so it is irrelevant and is never parsed.
        # Without this, one unparseable file ANYWHERE would disqualify every
        # non_live classification -- the same "one bad file bricks everything"
        # fault this machinery exists to fix.
        if writer_relpath not in text and stem not in text:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return True       # mentions it but unparseable -> fail closed.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.split(".")[-1] == stem for a in node.names):
                    return True
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.split(".")[-1] == stem or any(a.name == stem for a in node.names):
                    return True
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if writer_relpath in node.value or node.value.strip() == stem:
                    return True
    return False


class StructuralClassification(NamedTuple):
    """What ``structural_classification`` decided, plus the one fact the layer
    above needs from the SAME read in order to combine it correctly.

    ``state``            -- a ``WriterState``, always one of BLOCKING_LIVE_ENABLE
                            / NON_LIVE / NEEDS_PERSON.
    ``source_readable``  -- whether this classification actually got to look at
                            the writer's source text. False means there was no
                            usable relpath, or the file was absent, inaccessible,
                            or not decodable as UTF-8 text.

    ``source_readable`` is carried rather than re-derived because it is a
    precondition the layer above must respect and a second read to answer it
    would be a second implementation of the same question -- and could disagree
    with this one on a file that changed in between."""

    state: str
    source_readable: bool


def structural_classification(project_root: str,
                              entry: Dict[str, Any]) -> StructuralClassification:
    """Classify ONE open bespoke-writer ``entry`` from its recorded contents and
    its writer file alone.

    Deterministic and fail-closed: every path that cannot positively establish a
    non-blocking state yields ``BLOCKING_LIVE_ENABLE``. Precedence:

      1. no usable ``writer_relpath``  -> BLOCKING_LIVE_ENABLE, source unreadable
      2. writer source unreadable      -> BLOCKING_LIVE_ENABLE, source unreadable
      3. test module, unreferenced     -> NON_LIVE   (3 signals, all required)
      4. any non-remediable violation  -> NEEDS_PERSON  (STILL BLOCKING)
      5. otherwise                     -> BLOCKING_LIVE_ENABLE

    Step 2 is deliberately NOT "absent -> RESOLVED". ``reap_resolved_writer_
    migrations`` is the SINGLE authority on whether a writer is resolved -- it owns
    the full predicate (absent OR hash-changed-AND-scan-clean) and it REMOVES the
    entry. A second, weaker resolution rule here would be two authorities over one
    fact: exactly the duplicated-inference defect class this package guards
    against, and it would silently un-block an entry the reaper has not cleared. So
    an unreadable/absent writer simply falls through to fail-closed BLOCKING;
    reconcile-on-read runs the reaper moments later and the entry disappears
    properly. (Caught by ``test_open_bespoke_bypass_refuses_live_enable_with_no_
    partial_state``, whose fixture has no writer file on disk -- that keystone
    regression test found this.) An INACCESSIBLE-but-present writer is likewise
    never RESOLVED: absent and inaccessible are distinguished via the read's own
    exception type, never ``os.path.exists``/``is_file``, which conflate the two.

    This function takes NO set of prior human decisions and consults none. That is
    asserted directly, and separately from the import graph, because an acyclic
    module that took the decisions as an argument would satisfy the graph and
    defeat the point."""
    root = Path(project_root)
    writer_relpath = str(entry.get("writer_relpath") or "")
    if not writer_relpath:
        return StructuralClassification(WriterState.BLOCKING_LIVE_ENABLE, False)

    writer_path = root / writer_relpath
    try:
        source_text = writer_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return StructuralClassification(WriterState.BLOCKING_LIVE_ENABLE, False)

    if (_matches_test_naming(writer_relpath)
            and _has_test_structure(source_text)
            and not _referenced_by_live_surface(root, writer_relpath)):
        return StructuralClassification(WriterState.NON_LIVE, True)

    kinds = _recorded_violation_kinds(entry)
    if not kinds:
        # nothing recorded -> unprovable -> block.
        return StructuralClassification(WriterState.BLOCKING_LIVE_ENABLE, True)
    if kinds - REMEDIABLE_VIOLATION_KINDS:
        return StructuralClassification(WriterState.NEEDS_PERSON, True)
    return StructuralClassification(WriterState.BLOCKING_LIVE_ENABLE, True)


#: The states that hold back live-enable. NEEDS_PERSON is deliberately here --
#: see the section header. Only an explicit, recorded operator decision moves an
#: entry out of it, and that decision is applied a layer above.
BLOCKING_WRITER_STATES = frozenset({
    WriterState.BLOCKING_LIVE_ENABLE,
    WriterState.NEEDS_PERSON,
})


#: The states from which a RECORDED HUMAN DECISION is the exit -- exactly one, and
#: deliberately spelled as the one-element POSITIVE set rather than as a check
#: against the states that refuse.
#:
#: This is the SINGLE declaration of that authorization rule. Both layers above
#: bind it: the command layer refuses to record a decision about a writer that is
#: not in one of these states, and the state service applies a recorded decision
#: only to an entry in one of them. Neither of those two is sufficient on its own,
#: which is precisely why the rule may not be spelled twice -- "two paths that must
#: agree" is the shape this package's worst defects have taken.
#:
#: WHY IT IS A POSITIVE SET. The rule used to be neither of those things: the
#: command gated on membership in the OPEN set and the service tested the record
#: FIRST, ahead of every other state. Between them, a decision recorded against a
#: fully REBUILDABLE writer took it out of the blocking set, so the rebuild never
#: had to happen -- with the operator's entirely genuine consent, which is why no
#: consent check could have caught it. Spelled as a denylist of the states that
#: refuse, a state added to the vocabulary later would land on the permissive side
#: by nobody having thought about it; spelled positively, silence refuses.
#:
#: WHY needs_person AND NOTHING ELSE. It is the one state whose exit a person IS.
#: A ``blocking_live_enable`` writer has a mechanical exit -- every violation
#: recorded against it is one our own remediator covers, so the rebuild flow
#: genuinely clears it -- and accepting the risk instead would simply skip that
#: rebuild. A ``non_live`` writer is already out of the blocking set, so a decision
#: would release nothing while putting an audit record on file about a non-event.
#: The remaining two states are not reachable from ``structural_classification`` at
#: all: ``acknowledged_risk`` needs the very decision being authorized, and
#: ``resolved`` is the reaper's.
#:
#: Enforcement ceiling, restated because this constant sits at an authorization
#: boundary: build-time + operator-as-approver. Refusing to record a decision does
#: not disable anything at runtime, and recording one does not switch anything on.
ACKNOWLEDGEABLE_WRITER_STATES = frozenset({
    WriterState.NEEDS_PERSON,
})


#: Entry ``kind`` values that describe a real unrepaired external-write bypass in
#: an operator-authored writer file -- the ONLY case the bypass DIAGNOSIS below
#: actually fits. The bespoke-writer bypass entries this machinery was originally
#: built for carry NO ``kind`` field at all (see
#: ``upgrade_reconcile._append_migration_request``, build-side); a missing kind is
#: treated the same as membership here (see ``is_bypass_writer_entry``), so today's
#: only real bypass entries keep the wording they have always had. This set exists
#: for a future writer that wants to opt an explicitly-kinded entry INTO bypass
#: wording on purpose.
_BYPASS_WRITER_KINDS = frozenset({"external_write_bypass"})


def is_bypass_writer_entry(entry: Dict[str, Any]) -> bool:
    """True iff ``entry`` is a real, unrepaired external-write bypass in an
    operator-authored writer file -- the only entry shape the bypass diagnosis
    below actually describes.

    This queue (``agents/handoffs/pending_migrations.json``) is shared by every
    remediation this package's siblings record, not only bypass writers -- an
    entry can equally record a fact that has nothing to do with a hand-rolled
    write path (for example, that a safety check itself could not finish). Those
    entries are still real and still block (see ``open_bespoke_writer_migrations``
    / ``blocking_bespoke_writer_migrations``, both attribution- and kind-free by
    design), but they must not be DESCRIBED as a bypass writer, because neither the
    diagnosis nor the repair the state->action registry renders for one applies to
    them.

    It is also what every caller must consult BEFORE asking the registry for a way
    out: the registry answers for a writer's state, and an entry that is not a
    writer at all has no writer state to answer for.
    """
    kind = entry.get("kind")
    return kind is None or kind in _BYPASS_WRITER_KINDS


#: WHAT WAS FOUND, with no repair in it. True of an unrepaired bespoke-writer
#: bypass in EVERY state it can be in, which is exactly why it is separated from
#: the repair below: this module is the deepest layer of the writer-state cluster
#: and imports no sibling at all, so it cannot know which repair applies. It used
#: to prescribe one anyway -- see ``describe_blocking_entry``.
BYPASS_UNREPAIRED_DIAGNOSIS = "an external-write bypass is unrepaired: `{relpath}`"

#: THE REPAIR, and the ONE spelling of it in this package. Two surfaces need this
#: clause and cannot both render it from the state->action registry: the registry
#: renders it for every state-keyed surface, and the accepted-risk command layer
#: cannot import the registry at all (the registry imports that layer's own facade,
#: and reaches the trial modules whose pre-existing cycle would then land inside
#: the writer-state cluster's proved acyclicity closure). So the clause is declared
#: HERE -- the only module both of them already import, and one that imports no
#: sibling itself -- and both BIND it. Two independently-authored copies of the same
#: operator-facing guidance is a recorded finding in this package, and the copies
#: drifted; one declaration is what makes that impossible rather than unlikely.
#:
#: Carries NO placeholder, so it can be concatenated into either consumer's own
#: sentence without either of them knowing the other's field names.
BYPASS_UNREPAIRED_REPAIR = (
    "rebuild it so it routes through the sanctioned bulk path")

#: Diagnosis + repair, as the registry composes it. ``{relpath}`` is the only
#: field: a consumer that needs the template rather than the finished sentence
#: formats it with ``relpath="{subject}"`` and gets the template back with the
#: registry's own placeholder in place -- no re-spelling.
BYPASS_UNREPAIRED_TEMPLATE = (
    BYPASS_UNREPAIRED_DIAGNOSIS + " -- " + BYPASS_UNREPAIRED_REPAIR)

#: THE ROUTE TO A PERSON, for a writer the accepted-risk decision does not apply to.
#: Declared here for the same reason as the repair clause above and by the same
#: remedy: the command layer needs it in two of its own refusals -- one for a state
#: the decision is not the exit from, one for a state it has no sentence for at all
#: -- and it spelled the clause twice, byte-identically, in one module. One
#: declaration, both sites bind it.
#:
#: Deliberately NOT the same sentence as the state->action registry's own
#: route-to-a-person, which answers a different question: the registry's is for a
#: state it has no recorded way out of AT ALL, this one is for a state that has a way
#: out which simply is not "accept the risk". Collapsing them would be wrong rather
#: than tidy, and a test asserts they stay different.
#:
#: Carries no placeholder, so either consumer concatenates it into its own sentence.
ROUTE_TO_A_PERSON_CLAUSE = (
    "ask your assistant to go through what the safety check recorded for it with you")


def describe_blocking_entry(entry: Dict[str, Any]) -> str:
    """One plain-language sentence DESCRIBING one open blocking entry. It says what
    was found; it never says what to do about it.

    A bypass entry (``is_bypass_writer_entry``) gets the diagnosis and nothing more.
    It used to get the repair as well, and that was the defect: this module computes
    a writer's STRUCTURAL state and deliberately knows nothing else, so the sentence
    it produced was blind to which state the writer was actually in. A file the
    safety check found needs a person was told to rebuild itself -- the one
    instruction that cannot work for a file no rebuild of ours can rewrite. The
    repair depends on the state, so it is rendered from the state->action registry,
    which is the one place that knows both. This function's job is the half that is
    true in every state.

    Every other kind speaks for itself, because this queue carries facts that are
    not bypasses at all -- describing those with the bypass wording tells the
    operator to do something impossible to a file that was never the problem
    (rebuilding ``agents/handoffs/pending_migrations.json`` itself is meaningless;
    it is the queue, not a writer). That recorded next step is authored where the
    entry is written, which is the one thing the registry cannot know.

    Blocking is unaffected by any of this: what an entry BLOCKS is decided without
    consulting its kind, and only what the operator READS is chosen here.
    """
    if is_bypass_writer_entry(entry):
        relpath = str(entry.get("writer_relpath"))
        return BYPASS_UNREPAIRED_DIAGNOSIS.format(relpath=relpath)
    next_step = entry.get("suggested_next_step") or entry.get("reason")
    if not next_step:
        relpath = str(entry.get("writer_relpath"))
        next_step = f"this project has an open item to review at `{relpath}`"
    return str(next_step)
