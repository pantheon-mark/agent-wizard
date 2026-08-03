"""THE BEHAVIOURAL CONFORMANCE GATE over the State->Action registry: every
declared way out of a state is EXECUTED against a real project in that state, and
the state the production machinery then OBSERVES must be the one the action
declared.

What this gate is, and exactly what it does not claim
----------------------------------------------------
It is a CONFORMANCE gate, not a semantic-correctness oracle. It proves that an
action achieves the transition it declares -- run this command, from this state,
and the machinery afterwards reports that state. It does NOT prove the declared
transition is the RIGHT advice for the operator: whether "accept the risk" is the
right thing to tell someone about this particular file is a judgement no static or
behavioural check can make, and this gate does not pretend to make it. That
residual is irreducible at this project's standing enforcement ceiling
(build-time + operator-as-approver, never a runtime or OS sandbox) and it is far
smaller than the alternative, which is what this package shipped four times over:
a declared instruction that was never once executed, so nobody knew whether it
worked at all.

Why it exists, stated as the bet it is
--------------------------------------
Four consecutive rounds of work on the same defect family each added a permanent
gate, and every one of them was green and blind to the very next instance of its
own class. The reason was always the same: each gate depended on some fixture
happening to exercise the offending line. The previous round's answer was to make
its gate STATIC -- it fires when someone WRITES the defect. This one is the
complementary half: it is BEHAVIOURAL. A declared action with no passing
round-trip is a build failure, so an instruction can no longer be shipped
unexecuted.

The eight properties this file is built to hold, and the way each one could
otherwise have made this gate theatre
--------------------------------------------------------------------------------
1. RAW PROJECT ARTIFACTS ONLY, never an injected state object. Every fixture
   below writes a queue file, a writer file, a capability module, a durable trial
   record -- the bytes a real project carries -- and then ASKS the production
   classifier what state that is. A fixture that handed the classifier a
   pre-built state record would be testing the fixture, not the product. Asserted
   structurally over this module's own source, not merely intended
   (`ThisGateNeverInjectsAStateTests`).
2. THE PRODUCTION CLASSIFIER OBSERVES THE PRE-STATE, before anything is invoked.
   Not "the fixture meant this to be needs_person" -- the shipped classifier says
   so, or the round-trip does not start.
3. THE PUBLIC OPERATOR-FACING COMMAND IS WHAT RUNS, never an internal helper. The
   command is rendered by the registry's own builder, checked to be enrolled in
   the operator-invocable command manifest, and executed as a real subprocess from
   the project root -- which is how the operator runs it.
4. BOTH SURFACES ARE RE-READ: the production classifier AND the health projection
   an agent reads at session start. Two surfaces, because they have diverged
   before, and because a right answer on one of them next to a wrong answer on the
   other is how an operator gets told to do something impossible.
5. REJECTION FROM EVERY STATE OUTSIDE `from_states`, enumerated from the state
   vocabulary itself rather than hand-picked, so a state added upstream is covered
   without anyone remembering. The property asserted is the safety one: an action
   performed from a state it does not declare must leave the subject exactly where
   it was.
6. THE TWO HISTORICAL DEAD ENDS ARE REPRODUCED, sanitized. One is the writer whose
   only sanctioned exit no emitted surface named, so it was leavable only by
   someone who already knew to look. The other is the writer that could be made
   fully compliant and still could not produce the proof its own acceptance
   requires. The first is closed and its closure is executed here. The second is
   half closed, and the half that remains is named, grounded and made falsifiable
   rather than left to be rediscovered.
7. DEGENERATE STATE IS DRIVEN, not assumed away: a malformed queue, an unreadable
   queue, a content change after a decision was recorded, a writer that only LOOKS
   unused, and two open items naming one file in different states.
8. THE GATE IS FALSIFIABLE. Each body that could be hollowed out is driven to a
   non-empty answer, and the known-bad mutations this gate exists to catch are
   recorded in the report that accompanies it.

How a post-state is OBSERVED, including the one state no classifier returns
--------------------------------------------------------------------------
`_Observing.observe` is the only place in this file that reads a state. It runs the
health projection first -- which is the real session-start read path, and which
self-heals before reporting, exactly as an operator session does -- then the
production classifier, and refuses to proceed if the two disagree.

`resolved` needs saying out loud: NOTHING classifies a writer into it. The reaper
is the single authority on whether a writer is resolved, and what the reaper does
is REMOVE the entry. So the observable form of that state is the absence of any
open entry for a subject that had one, and that is what `observe` reports. A second
resolution rule implemented here would be a second authority over one fact, which
is the duplicated-inference defect this package refuses everywhere else.

One action's round-trip cannot run yet, and it is declared rather than skipped
-----------------------------------------------------------------------------
`recover_interrupted_trial` leaves the trial-unit states. Its command is real,
public, enrolled and covered end to end by the trial recovery suite. What does not
exist is an operator-invocable way to START a trial, so a trial-unit state is not
reachable in a freshly emitted project through any sanctioned path -- the fixture
would have to author a driver script standing in for the entrypoint that is still
to be built, and a round-trip that passes only because the gate faked its own
starting conditions is precisely the green-and-blind failure this gate exists to
end. So the action is DECLARED blocked, with its blocker named, and the blocker is
itself asserted to still hold: the moment an operator-invocable trial driver
lands, `TheBlockerIsAssertedNotAssumedTests` goes red and the declaration must be
discharged. The observable half of that domain -- that the production reader sees
each driven state in a durable record a killed process leaves behind -- is
exercised here anyway, to keep the deferral as narrow as it can honestly be.

Enforcement ceiling (disclosure): build-time. Executing a repair in a fixture
proves the repair works; it does not police the operator's project at runtime, and
nothing in this file could.

Run:
  python3 -m unittest discover -s wizard/scripts/lib \\
      -p test_external_write_action_round_trips.py
"""

import ast
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_WIZARD = Path(__file__).resolve().parents[2]
_AGENTS_LIB = _WIZARD / "agents" / "lib"
_EXTERNAL_WRITE_DIR = _AGENTS_LIB / "external_write"
if str(_AGENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENTS_LIB))
if str(_WIZARD / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(_WIZARD / "scripts" / "lib"))

from external_write import _ext_write_state as service            # noqa: E402
from external_write import capability_health as health            # noqa: E402
from external_write import command_manifest as manifest           # noqa: E402
from external_write import state_actions as sa                     # noqa: E402
from external_write import trial_journal as tj                     # noqa: E402
from external_write import writer_ack_store as store               # noqa: E402
from external_write import writer_state_core as core               # noqa: E402

_THIS_FILE = Path(__file__).resolve()

QUEUE_REL = "agents/handoffs/pending_migrations.json"

#: What the operator says. One physical line, no apostrophe-quoting hazard.
CONFIRMATION = "Yes -- I know this one needs a person and I accept the risk."


# ---------------------------------------------------------------------------
# RAW SOURCES. Each one is operator-shaped code, written to disk as bytes. None
# of them carries a state; the production classifier decides what state they are.
# ---------------------------------------------------------------------------

#: The upkeep writer's real shape: notification delivery entangled with the write
#: loop, so it records a violation kind our own remediation does not cover. This
#: is the sanitized reproduction of the writer whose only exit no surface named.
_UNREPAIRABLE_SRC = '''"""Daily upkeep -- also delivers the operator's phone alert."""
import urllib.request


def notify(message):
    urllib.request.urlopen("https://example.invalid/notify", data=message)
'''

#: A hand-rolled per-chunk bulk write loop: every violation it records is one our
#: own remediator covers, which is what makes it rebuildable. This is the sanitized
#: reproduction of the writer that could be made compliant.
_REBUILDABLE_SRC = '''"""Hand-rolled per-chunk bulk writer -- bypasses the sanctioned path."""
from external_write.run_envelope import mint_run_envelope


def run_all(chunks):
    return [mint_run_envelope(chunk) for chunk in chunks]
'''

#: The same writer AFTER the rebuild: it routes through the sanctioned bulk path
#: and passes the real scan. This is the assistant's work, not a command's.
_SANCTIONED_SRC = '''"""Migrated -- routes the bulk write through the sanctioned path."""
from external_write.capability_api import run_sanctioned_bulk


def run_all(facade, batch_id, operations):
    return run_sanctioned_bulk(facade, batch_id, operations)
'''

#: A test module. Whether it is actually unused is not decided by its name -- the
#: classifier requires three signals and this source supplies two of them.
_TEST_MODULE_SRC = '''"""Helpers exercised only by the upkeep test suite."""
import unittest


class UpkeepHelperTests(unittest.TestCase):

    def test_nothing_in_the_running_system_calls_this(self):
        self.assertTrue(True)
'''

#: The harness capability. It exists so the project has a capability at all, which
#: is what puts the reconcile-on-read self-heal (and therefore the reaper) on the
#: health projection's real path. Nothing about the writer states depends on it --
#: the block it participates in is attribution-free by design.
_HARNESS_CAPABILITY_SRC = '''"""Harness capability -- exists so reconcile-on-read has something to resolve."""

OP_KIND = "delete_record"


def describe():
    return "harness ready"


def propose_operations(facade, batch_id):
    return []
'''

HARNESS_CAPABILITY_ID = "harness"

#: Writer relpaths, chosen to match the shapes the two historical dead ends had.
UPKEEP_WRITER = "agents/upkeep/runner.py"
INBOX_WRITER = "agents/inbox/runner.py"
TEST_WRITER = "agents/upkeep/test_upkeep_helpers.py"


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _queue_entry(relpath, kinds, paused_content_sha256, mechanism_id=None):
    """One pending-migrations entry, in the shape the upgrade reconcile records:
    a relpath-derived mechanism id, no owning-capability field, the pause-time
    content hash, and the violation KINDS the scanner recorded. It carries no
    state -- the state is computed from these bytes plus the file on disk."""
    return {
        "mechanism_id": (mechanism_id if mechanism_id is not None
                         else relpath.replace("/", "_").replace(".py", "")),
        "writer_relpath": relpath,
        "entrypoint_relpath": None,
        "status": "pending",
        "reason": "flagged non-conformant with the external-write gate on upgrade",
        "paused_content_sha256": paused_content_sha256,
        "violations": [{"kind": kind, "line": 2, "path": relpath}
                       for kind in kinds],
    }


class _Project:
    """A real operator project on disk, at the real emitted relative paths, with
    the emitted lib copied in so a rendered command can be run from the project
    root exactly as the operator runs it."""

    def __init__(self, case, with_lib=True):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.write("agents/capabilities/%s_capability.py" % HARNESS_CAPABILITY_ID,
                   _HARNESS_CAPABILITY_SRC)
        if with_lib:
            lib = self.root / "agents" / "lib" / "external_write"
            lib.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(_EXTERNAL_WRITE_DIR, lib,
                            ignore=shutil.ignore_patterns("test_*.py",
                                                          "__pycache__"))
            (lib / "__init__.py").touch(exist_ok=True)
            (self.root / "agents" / "lib" / "__init__.py").touch(exist_ok=True)

    def write(self, relpath, text):
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def queue(self, entries):
        self.write(QUEUE_REL, json.dumps(entries, indent=2))

    def raw_queue(self, text):
        self.write(QUEUE_REL, text)

    def put_trial_record(self, trial_id, unit_states, op_kind="fixture.op",
                         raw=None):
        """A durable trial record written straight to disk as BYTES -- not through
        the module that writes them, because what this reads is what a killed
        process left behind, and a killed process emits nothing at all."""
        directory = self.root / tj.DEFAULT_TRIAL_JOURNAL_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ("%s.json" % trial_id)
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
            return path
        record = {
            "schema": tj.TRIAL_JOURNAL_SCHEMA,
            "trial_id": trial_id,
            "op_kind": op_kind,
            "units": [
                {
                    "unit_id": unit_id,
                    "state": state,
                    "history": [{"state": state, "at": "2026-01-01T00:00:00Z"}],
                    "recovery_capsule": {
                        tj.CAPSULE_KEY_SCHEMA: tj.RECOVERY_CAPSULE_SCHEMA,
                        tj.CAPSULE_KEY_UNIT_ID: unit_id,
                        tj.CAPSULE_KEY_OP_KIND: op_kind,
                        tj.CAPSULE_KEY_TARGET_REF: json.dumps({"id": unit_id}),
                        tj.CAPSULE_KEY_UNDO_REF: json.dumps({"to": "prior"}),
                    },
                }
                for unit_id, state in sorted(unit_states.items())
            ],
        }
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# THE OBSERVATION. The only place in this file that reads a state.
# ---------------------------------------------------------------------------

class _Observing:
    """Mixin carrying the observation and the command runner.

    Both are deliberately in ONE place: a second way to read a state, or a second
    way to invoke a command, is a second thing that has to agree with the first,
    and that is the shape of this package's worst defects."""

    def observe(self, project, subject, allow_ambiguity=False):
        """Every state the production machinery reports for `subject`, as registry
        KEYS, in sorted order.

        Reads BOTH surfaces, in the order a real session reads them: the health
        projection first (it is the session-start read path, and it self-heals
        before reporting), then the production classifier over the queue. The two
        must agree; a disagreement is reported here rather than resolved, because
        the whole reason there are two is that they have diverged before.

        An empty answer for a subject means no open entry names it. For a subject
        that HAD one, that is the observable form of `resolved`: the reaper is the
        single authority on resolution and what it does is remove the entry. This
        function does not re-derive that predicate -- it reports the absence.

        `allow_ambiguity` relaxes only the cross-surface agreement check, and only
        for the case that provokes it: the health projection keys its per-writer
        state map on the relpath, so it structurally cannot represent two open
        entries naming one file in different states. That case has its own tests,
        which assert the safety properties rather than the agreement.
        """
        status = health.overall_status(str(project.root))
        block = status["open_external_write_bypass"]
        health_states = tuple(sorted(
            {state for relpath, state in block["writer_states"].items()
             if relpath == subject}))

        report = service.bespoke_writer_state_report(str(project.root))
        classifier_states = tuple(sorted(
            {state for state, entries in report.items() for entry in entries
             if str(entry.get("writer_relpath")) == subject}))

        if not allow_ambiguity:
            self.assertEqual(
                health_states, classifier_states,
                "the health projection and the production classifier report "
                "different states for %r -- one of the two surfaces an operator "
                "reads is wrong" % subject)

        if not classifier_states:
            return (sa.writer_state_key(core.WriterState.RESOLVED),)
        return tuple(sa.writer_state_key(state) for state in classifier_states)

    def run_command(self, project, command):
        """Run `command` as the operator runs it: as a real process, from the
        project root, exactly as rendered. Bytecode writing is off, so nothing a
        previous run cached can answer for what the current source does."""
        argv = shlex.split(command)
        self.assertEqual(argv[0], "python3", command)
        self.assertEqual(len(command.splitlines()), 1,
                         "a command that wraps is a paste hazard")
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable] + argv[1:], capture_output=True,
                              text=True, cwd=str(project.root),
                              env=environment, timeout=300)

    def assert_enrolled_operator_command(self, command):
        """The command must be one the operator-invocable command manifest
        declares. Joined on the manifest's own declared prefix -- not on the
        script's filename, and not on where the file happens to live."""
        matches = [entry for entry in manifest.BASELINE_COMMANDS
                   if command.startswith(entry.command_prefix)]
        self.assertTrue(
            matches,
            "%r is not an enrolled operator-invocable command; a round-trip that "
            "ran an internal helper would prove nothing about what an operator "
            "can actually do" % command)
        return matches[0]


# ---------------------------------------------------------------------------
# THE FIXTURE BUILDERS -- one per state in the round-trippable vocabulary.
# Every one writes raw artifacts and NONE of them names a state on the artifact.
# ---------------------------------------------------------------------------

def _build_needs_person(case):
    """A writer recording a violation kind our own remediation does not cover."""
    project = _Project(case)
    project.write(UPKEEP_WRITER, _UNREPAIRABLE_SRC)
    project.queue([_queue_entry(UPKEEP_WRITER, ["forbidden_import"],
                               _sha256(_UNREPAIRABLE_SRC))])
    return project, UPKEEP_WRITER


def _build_blocking_live_enable(case):
    """A hand-rolled write loop whose every recorded violation our own remediator
    covers. Its content hash matches the recorded pause-time hash, so it is
    unchanged since it was flagged and the reaper leaves it alone."""
    project = _Project(case)
    project.write(INBOX_WRITER, _REBUILDABLE_SRC)
    project.queue([_queue_entry(INBOX_WRITER, ["sealed_kernel_import"],
                               _sha256(_REBUILDABLE_SRC))])
    return project, INBOX_WRITER


def _build_non_live(case):
    """A test module that nothing in the running system names."""
    project = _Project(case)
    project.write(TEST_WRITER, _TEST_MODULE_SRC)
    project.queue([_queue_entry(TEST_WRITER, ["sealed_kernel_import"],
                               _sha256(_TEST_MODULE_SRC))])
    return project, TEST_WRITER


def _build_acknowledged_risk(case):
    """Built by RUNNING the real public command against a real needs-person
    project -- never by writing a decision record by hand. A hand-written record
    would make this fixture the thing under test."""
    project, subject = _build_needs_person(case)
    action = _action("record_accepted_risk")
    result = case.run_command(project, action.command_builder(
        subject, operator_confirmation=CONFIRMATION))
    case.assertEqual(result.returncode, 0,
                     "fixture precondition: %r %r" % (result.stdout,
                                                      result.stderr))
    return project, subject


def _build_resolved(case):
    """The rebuilt writer: it routes through the sanctioned path, its content
    differs from the recorded pause-time hash, and it passes the real scan -- so
    the reaper closes its entry. Nothing here removes the entry by hand."""
    project = _Project(case)
    project.write(INBOX_WRITER, _SANCTIONED_SRC)
    project.queue([_queue_entry(INBOX_WRITER, ["sealed_kernel_import"],
                               _sha256(_REBUILDABLE_SRC))])
    return project, INBOX_WRITER


#: State key -> the builder that puts a real project into it. Checked below to
#: cover the ENTIRE round-trippable vocabulary: a state added upstream and left out
#: of this map fails the gate rather than being silently untested.
_FIXTURE_BUILDERS = {
    sa.writer_state_key(core.WriterState.NEEDS_PERSON): _build_needs_person,
    sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE):
        _build_blocking_live_enable,
    sa.writer_state_key(core.WriterState.NON_LIVE): _build_non_live,
    sa.writer_state_key(core.WriterState.ACKNOWLEDGED_RISK):
        _build_acknowledged_risk,
    sa.writer_state_key(core.WriterState.RESOLVED): _build_resolved,
}


# ---------------------------------------------------------------------------
# WHAT THE ACTOR DOES that is not the command.
#
# Derived from the registry's own `actor` field, not hand-picked: an action whose
# actor is the ASSISTANT is one where the work happens outside the command and the
# command CONFIRMS it, so such an action MUST declare that work here. An action
# whose actor is the OPERATOR is one the command itself performs, so it must NOT.
# Both directions are asserted.
# ---------------------------------------------------------------------------

def _rebuild_the_writer(project, subject):
    """The assistant's half of the rebuild: rewrite the writer so it routes
    through the sanctioned bulk path. Code authoring -- which is exactly why this
    action's actor is the assistant and its command only confirms the result."""
    project.write(subject, _SANCTIONED_SRC)


_ACTOR_WORK = {
    "rebuild_onto_the_sanctioned_path": _rebuild_the_writer,
}


# ---------------------------------------------------------------------------
# THE DECLARED PARTITION OF THE REGISTRY'S DOMAINS.
#
# A positive declaration: a domain is either round-trippable here, or blocked with
# a named blocker. A domain in neither fails the gate -- silence refuses.
# ---------------------------------------------------------------------------

_RUNNABLE_DOMAINS = frozenset({sa.DOMAIN_BESPOKE_WRITER})

_BLOCKED_DOMAINS = {
    sa.DOMAIN_TRIAL_UNIT: (
        "no operator-invocable command can put a project into a trial-unit state: "
        "the trial has a public RECOVERY entrypoint but no public way to START "
        "one, so reaching a driven state in a fixture would mean authoring a "
        "driver script standing in for the entrypoint that is still to be built. "
        "A round-trip that passes because the gate faked its own starting "
        "conditions is the failure this gate exists to end, so this action's "
        "round-trip is DECLARED not-yet-runnable instead. The blocker is asserted "
        "to still hold, so this declaration cannot outlive it."),
}


def _domain_of(state_key):
    """The domain half of a registry key, split on the registry's OWN declared
    separator and checked against its OWN declared domain list -- never inferred
    from anything incidental."""
    domain = state_key.split(sa.KEY_SEPARATOR, 1)[0]
    if domain not in sa.DOMAINS:
        raise AssertionError("%r does not start with a declared domain" % state_key)
    return domain


def _action(action_id):
    for action in sa.ACTIONS:
        if action.action_id == action_id:
            return action
    raise AssertionError("no action %r in the registry" % action_id)


def _action_domain(action):
    domains = {_domain_of(key) for key in action.from_states}
    if len(domains) != 1:
        raise AssertionError(
            "action %r spans domains %s; a round-trip has to know which "
            "vocabulary the subject belongs to" % (action.action_id,
                                                   sorted(domains)))
    return next(iter(domains))


def _runnable_actions():
    return tuple(action for action in sa.ACTIONS
                 if _action_domain(action) in _RUNNABLE_DOMAINS)


def _blocked_actions():
    return tuple(action for action in sa.ACTIONS
                 if _action_domain(action) in _BLOCKED_DOMAINS)


def _writer_vocabulary_keys():
    """The bespoke-writer vocabulary as keys, read off the declaring class rather
    than listed here, so a state added to it arrives automatically."""
    return frozenset(
        sa.writer_state_key(value) for name, value in vars(core.WriterState).items()
        if not name.startswith("_") and isinstance(value, str))


def _render(action, subject, with_confirmation=False):
    """The command, from the registry's own builder. The accepted-risk builder
    takes the operator's words as a keyword; every other builder takes the subject
    alone, so the shape is decided by whether the caller has words to supply."""
    if with_confirmation:
        return action.command_builder(subject,
                                      operator_confirmation=CONFIRMATION)
    return action.command_builder(subject)


def _needs_confirmation(action):
    """True iff this action's command carries the operator's own words. Read off
    the ACTOR field: only an action the operator themself performs can carry what
    they said, and the command's own renderer refuses to invent it."""
    return action.actor == sa.ACTOR_OPERATOR and (
        _action_domain(action) == sa.DOMAIN_BESPOKE_WRITER)


# ===========================================================================
# 1. EVERY DECLARED ACTION IS ACCOUNTED FOR -- nothing passes by default
# ===========================================================================

class EveryDeclaredActionIsAccountedForTests(unittest.TestCase):
    """The completeness half. A declared action is either round-tripped below or
    declared blocked with a named blocker; there is no third option, and an action
    added later lands in neither and fails here."""

    def test_every_declared_action_is_either_round_tripped_or_declared_blocked(self):
        accounted = {a.action_id for a in _runnable_actions()} | {
            a.action_id for a in _blocked_actions()}
        self.assertEqual(accounted, {a.action_id for a in sa.ACTIONS},
                         "an action in neither set is an instruction this gate "
                         "never executes")

    def test_the_registrys_domains_are_PARTITIONED_into_runnable_and_blocked(self):
        self.assertEqual(_RUNNABLE_DOMAINS | frozenset(_BLOCKED_DOMAINS),
                         frozenset(sa.DOMAINS),
                         "a domain in neither set would be silently untested")
        self.assertEqual(_RUNNABLE_DOMAINS & frozenset(_BLOCKED_DOMAINS),
                         frozenset(),
                         "a domain cannot be both runnable and blocked")

    def test_every_blocked_domain_states_a_blocker_that_names_the_obstacle(self):
        for domain, blocker in sorted(_BLOCKED_DOMAINS.items()):
            with self.subTest(domain=domain):
                self.assertTrue(blocker.strip())
                self.assertIn("no operator-invocable", blocker,
                              "a deferral has to say what is missing, not that "
                              "it was hard")

    def test_exactly_one_action_is_blocked_today(self):
        """Pinned at ONE, so a second action quietly joining the blocked set is a
        failure rather than a footnote."""
        self.assertEqual([a.action_id for a in _blocked_actions()],
                         ["recover_interrupted_trial"])

    def test_every_action_from_states_live_in_a_SINGLE_vocabulary(self):
        for action in sa.ACTIONS:
            with self.subTest(action=action.action_id):
                self.assertIn(_action_domain(action), sa.DOMAINS)

    def test_the_fixture_builders_cover_the_WHOLE_runnable_vocabulary(self):
        """Quantified over the declaring class's own vocabulary. A state added
        upstream and left out of the builder map fails here -- it does not become
        an untested state nobody noticed."""
        self.assertEqual(frozenset(_FIXTURE_BUILDERS), _writer_vocabulary_keys())

    def test_an_assistant_action_declares_its_actor_work_and_an_operator_one_does_not(self):
        """Derived from the registry's `actor` field. An assistant action means the
        work is code authoring the command only confirms, so the round-trip has to
        do that work; an operator action is performed BY the command, so declaring
        work for it would mean the round-trip did the command's job for it."""
        for action in _runnable_actions():
            with self.subTest(action=action.action_id):
                if action.actor == sa.ACTOR_ASSISTANT:
                    self.assertIn(action.action_id, _ACTOR_WORK)
                else:
                    self.assertNotIn(action.action_id, _ACTOR_WORK)

    def test_the_declared_actor_work_names_only_real_actions(self):
        self.assertTrue(
            set(_ACTOR_WORK) <= {a.action_id for a in sa.ACTIONS},
            "actor work declared for an action that does not exist")


# ===========================================================================
# 2. THE BLOCKER IS ASSERTED, NOT ASSUMED
# ===========================================================================

class TheBlockerIsAssertedNotAssumedTests(unittest.TestCase):
    """The declared blocker above is only honest while it is TRUE. These assert it
    against the shipped tree, so the moment an operator-invocable trial driver
    lands, this class goes red and the blocked declaration must be discharged
    rather than quietly outliving its own reason."""

    def _production_modules(self):
        for path in sorted(_EXTERNAL_WRITE_DIR.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            yield path

    def _has_main_block(self, tree):
        return any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            for node in tree.body)

    def _calls(self, tree, function_name):
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute) else None)
            if name == function_name:
                found.append(node.lineno)
        return found

    def test_no_shipped_entrypoint_can_START_a_trial(self):
        """AST, because this is a question about code structure: a module that
        both declares a command-line entrypoint AND drives a trial would BE the
        operator-invocable trial driver whose absence is the declared blocker."""
        drivers = []
        for path in self._production_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if self._has_main_block(tree) and self._calls(tree, "run_trial"):
                drivers.append(path.name)
        self.assertEqual(
            drivers, [],
            "an operator-invocable trial driver now exists (%s) -- the blocked "
            "round-trip declaration for the trial domain is discharged and must "
            "be replaced with a real round-trip" % drivers)

    def test_the_command_manifest_enrolls_no_trial_driver(self):
        """The other half of the same question, joined on the manifest's own
        declared prefixes rather than on any filename."""
        for entry in manifest.BASELINE_COMMANDS:
            with self.subTest(command=entry.name):
                self.assertNotIn("trial_executor", entry.command_prefix)

    def test_the_acceptance_PROOF_half_still_has_no_producer_either(self):
        """The second historical dead end had two halves. The bypass half is closed
        and executed in this file; this is the half that is not. The proof module
        exposes a VALIDATOR and nothing that produces a proof, and it declares no
        entrypoint -- so a writer that has been made fully compliant still cannot
        produce the fresh proof its own acceptance requires. Grounded on the
        shipped source rather than recalled."""
        path = _EXTERNAL_WRITE_DIR / "copy_run_proof.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        public = sorted(node.name for node in tree.body
                        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                        and not node.name.startswith("_"))
        self.assertIn("validate_copy_run_proof", public)
        self.assertFalse(
            self._has_main_block(tree),
            "the proof module now declares an entrypoint -- revisit the declared "
            "residual, it may be discharged")
        self.assertEqual(
            [name for name in public if name.startswith("produce")], [],
            "a proof producer now exists -- the declared residual is discharged "
            "and this assertion must be replaced with a real round-trip")


# ===========================================================================
# 3. THE ROUND TRIP -- the OBSERVED post-state equals the DECLARED one
# ===========================================================================

class TheDeclaredTransitionActuallyHappensTests(unittest.TestCase, _Observing):
    """The gate. For every runnable action, for every state it declares it leaves:
    build a real project the production classifier reports IS in that state, run
    the PUBLIC command, and assert the state both surfaces then report is the one
    the action declared.

    This is the conformance claim and the whole of it. It does not assert the
    declared transition is good advice -- see this module's docstring."""

    def test_every_action_achieves_its_declared_transition_from_every_from_state(self):
        exercised = []
        for action in _runnable_actions():
            for from_state in action.from_states:
                with self.subTest(action=action.action_id, from_state=from_state):
                    self._round_trip(action, from_state)
                    exercised.append((action.action_id, from_state))
        self.assertTrue(exercised, "no round-trip ran at all")
        # Every from_state of every runnable action was covered -- computed here
        # rather than trusted, so a loop that silently skipped one fails.
        self.assertEqual(
            sorted(exercised),
            sorted((a.action_id, s) for a in _runnable_actions()
                   for s in a.from_states))

    def _round_trip(self, action, from_state):
        builder = _FIXTURE_BUILDERS[from_state]
        project, subject = builder(self)

        # (2) THE PRODUCTION CLASSIFIER OBSERVES THE DECLARED PRE-STATE. Not the
        # fixture's intention -- the shipped machinery's answer.
        self.assertEqual(
            self.observe(project, subject), (from_state,),
            "the fixture is not in the state the action declares it leaves, so "
            "the round-trip would prove nothing")

        # The actor's own work, when the command CONFIRMS rather than performs.
        work = _ACTOR_WORK.get(action.action_id)
        if work is not None:
            work(project, subject)

        # (3) THE PUBLIC OPERATOR-FACING COMMAND, enrolled and executed.
        command = _render(action, subject,
                          with_confirmation=_needs_confirmation(action))
        self.assert_enrolled_operator_command(command)
        result = self.run_command(project, command)
        self.assertEqual(
            result.returncode, 0,
            "the declared way out of %s did not succeed: stdout=%r stderr=%r"
            % (from_state, result.stdout, result.stderr))
        self.assertNotIn("Traceback", result.stdout + result.stderr,
                         "a non-technical operator reads this output")

        # (4) RE-READ THROUGH BOTH SURFACES, and the observed state must be the
        # declared post-condition.
        self.assertEqual(
            self.observe(project, subject), (action.expected_state,),
            "action %r declares it establishes %s, and it did not"
            % (action.action_id, action.expected_state))

    def test_the_rendered_command_of_every_action_is_an_enrolled_operator_command(self):
        """Including the blocked one: its command is real and public, which is
        what makes the blocker narrow -- what is missing is the way IN, not the
        way out."""
        for action in sa.ACTIONS:
            with self.subTest(action=action.action_id):
                entry = self.assert_enrolled_operator_command(
                    _render(action, "some-subject"))
                self.assertTrue(entry.name.strip())

    def test_the_post_state_of_every_runnable_action_is_a_SETTLED_state(self):
        """A round-trip that landed in another blocking state would be an exit
        into a state that still needs an exit. Computed here over the registry's
        own declared dispositions, not asked of the registry's gate body."""
        for action in _runnable_actions():
            with self.subTest(action=action.action_id):
                self.assertIn(action.expected_state,
                              sa.INTENTIONAL_DISPOSITIONS,
                              "%r lands somewhere that is not declared settled"
                              % action.action_id)


# ===========================================================================
# 4. REJECTION FROM EVERY STATE OUTSIDE `from_states`
# ===========================================================================

class AnActionDoesNothingFromAStateItDoesNotDeclareTests(unittest.TestCase,
                                                          _Observing):
    """Enumerated from the state vocabulary itself, so a state added upstream is
    covered without anyone remembering to add a case.

    The property asserted is the SAFETY one, and it is uniform: an action invoked
    from a state it does not declare must leave the subject exactly where it was.
    That is deliberately not phrased as "the command exits non-zero". One of these
    commands is a read-only confirming check that legitimately succeeds without
    changing anything, and another is idempotent when re-run from the very state it
    establishes. Keying on the exit code would force a hand-written table of
    expected outcomes -- a second declaration of the authorization question, which
    is the shape of this package's worst defects. Keying on the observed state is
    derived entirely from the registry."""

    def test_no_action_moves_a_subject_from_a_state_it_does_not_declare(self):
        exercised = []
        for action in _runnable_actions():
            outside = sorted(frozenset(_FIXTURE_BUILDERS)
                             - frozenset(action.from_states))
            self.assertTrue(outside, "every state is a from_state; nothing to test")
            for state in outside:
                with self.subTest(action=action.action_id, state=state):
                    self._refuses_to_move(action, state)
                    exercised.append((action.action_id, state))
        self.assertEqual(
            sorted(exercised),
            sorted((a.action_id, s) for a in _runnable_actions()
                   for s in (frozenset(_FIXTURE_BUILDERS)
                             - frozenset(a.from_states))))

    def _refuses_to_move(self, action, state):
        project, subject = _FIXTURE_BUILDERS[state](self)
        self.assertEqual(self.observe(project, subject), (state,),
                         "fixture precondition")
        before = frozenset(store.active_acknowledgements(str(project.root)))

        command = _render(action, subject,
                          with_confirmation=_needs_confirmation(action))
        result = self.run_command(project, command)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

        self.assertEqual(
            self.observe(project, subject), (state,),
            "action %r moved a subject out of %s, which it does not declare it "
            "leaves" % (action.action_id, state))

        after = frozenset(store.active_acknowledgements(str(project.root)))
        self.assertEqual(
            before, after,
            "action %r created or removed a recorded operator decision for a "
            "subject in %s -- consent recorded for a state the decision does not "
            "apply to is inert, but it must never be WRITTEN" % (action.action_id,
                                                                 state))

    def test_the_refusals_the_operator_reads_are_never_a_dead_end(self):
        """A refusal that names nothing leaves the operator exactly where the two
        historical dead ends left them."""
        action = _action("record_accepted_risk")
        for state in sorted(frozenset(_FIXTURE_BUILDERS)
                            - frozenset(action.from_states)):
            with self.subTest(state=state):
                project, subject = _FIXTURE_BUILDERS[state](self)
                result = self.run_command(
                    project, _render(action, subject, with_confirmation=True))
                if result.returncode == 0:
                    continue     # idempotent re-record into its own post-state
                message = result.stdout + result.stderr
                self.assertTrue(message.strip(), "a silent refusal")
                self.assertIn("nothing was recorded", message)


# ===========================================================================
# 5. THE TWO HISTORICAL DEAD ENDS, REPRODUCED
# ===========================================================================

class TheWriterWhoseOnlyExitNoSurfaceNamedTests(unittest.TestCase, _Observing):
    """The first dead end, sanitized: a real operator writer that the safety check
    found needs a person -- notification delivery entangled with its write loop,
    which no remediator of ours rewrites. Its only sanctioned exit was a recorded
    operator decision, and that decision existed only as a Python function: no
    surface an operator or their assistant reads ever named it, so the state was
    leavable only by someone who already knew to look. That is the same shape as a
    state with no exit at all."""

    def setUp(self):
        self.project, self.subject = _build_needs_person(self)

    def test_the_surface_an_agent_reads_at_session_start_NAMES_the_exit(self):
        block = health.overall_status(
            str(self.project.root))["open_external_write_bypass"]
        self.assertEqual(block["writer_states"][self.subject],
                         core.WriterState.NEEDS_PERSON)
        expected = _render(_action("record_accepted_risk"), self.subject)
        self.assertIn(expected, block["actions"][self.subject],
                      "the field an agent is told to relay does not carry the "
                      "command that leaves this state")
        self.assertIn(expected, block["descriptions"][self.subject],
                      "the two operator-facing fields carry different answers")

    def test_the_surface_never_tells_this_writer_to_rebuild_itself(self):
        """The instruction that cannot work for a file no rebuild of ours can
        rewrite. Both fields, because one of them used to carry it while the other
        carried the route that works."""
        block = health.overall_status(
            str(self.project.root))["open_external_write_bypass"]
        for field in ("actions", "descriptions"):
            with self.subTest(field=field):
                self.assertNotIn(core.BYPASS_UNREPAIRED_REPAIR,
                                 block[field][self.subject])

    def test_running_the_named_command_ACTUALLY_clears_the_state(self):
        command = _render(_action("record_accepted_risk"), self.subject,
                          with_confirmation=True)
        result = self.run_command(self.project, command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.observe(self.project, self.subject),
            (sa.writer_state_key(core.WriterState.ACKNOWLEDGED_RISK),))
        recorded = store.active_acknowledgements(str(self.project.root))
        self.assertEqual(recorded[self.subject]["operator_confirmation"],
                         CONFIRMATION,
                         "the record must carry the operator's own words")

    def test_the_decision_is_HASH_BOUND_and_the_state_returns_when_the_file_changes(self):
        """The post-state is not permanent, and the disposition sentence promises
        exactly that. A decision that survived a content change would be consent
        to code the operator never saw."""
        self.run_command(self.project,
                         _render(_action("record_accepted_risk"), self.subject,
                                 with_confirmation=True))
        self.assertEqual(
            self.observe(self.project, self.subject),
            (sa.writer_state_key(core.WriterState.ACKNOWLEDGED_RISK),))

        self.project.write(self.subject,
                           _UNREPAIRABLE_SRC + "\n# the operator edited this\n")

        self.assertEqual(
            self.observe(self.project, self.subject),
            (sa.writer_state_key(core.WriterState.NEEDS_PERSON),),
            "the recorded decision outlived the bytes it was taken about")
        self.assertEqual(store.active_acknowledgements(str(self.project.root)),
                         {})

    def test_the_all_clear_is_withheld_even_after_the_decision_is_recorded(self):
        """Not blocking must never mean invisible: an accepted risk stops holding
        live-enable back and still withholds "everything is running normally"."""
        self.run_command(self.project,
                         _render(_action("record_accepted_risk"), self.subject,
                                 with_confirmation=True))
        status = health.overall_status(str(self.project.root))
        self.assertFalse(status["normal_status_allowed"], status)
        self.assertIn(self.subject,
                      status["open_external_write_bypass"]["writer_relpaths"])
        self.assertNotIn(
            self.subject,
            status["open_external_write_bypass"]["blocking_writer_relpaths"])


class ARecordedDecisionIsNeverHONOUREDForARebuildableWriterTests(
        unittest.TestCase, _Observing):
    """The historical defect that made the eligibility rule necessary, reproduced
    from RAW ARTIFACTS ALONE.

    What happened: the state service tested the recorded decision FIRST, ahead of
    every other state, and the command gated only on there being an open entry. A
    decision recorded against a fully REBUILDABLE writer therefore took it out of
    the blocking set, so the rebuild never had to happen -- with the operator's
    entirely genuine consent, which is why no consent check could have caught it.
    The consent was real; the QUESTION was wrong.

    Reproducing that needs a VALID decision on a writer that is rebuildable, and
    this gets there without forging anything: the operator records a decision about
    a writer the check found needs a person, and a later re-scan records a different
    set of violation kinds for the same file -- every one of them now covered by our
    own remediator. The writer's BYTES never change, so the operator's decision is
    still hash-valid and still on file. It simply must stop applying.

    This is the one shape a round-trip cannot reach on its own, because a decision
    for an ineligible writer cannot be created through the public command at all.
    It is reachable through the queue, which is an ordinary project artifact the
    upgrade reconcile rewrites."""

    def setUp(self):
        self.project, self.subject = _build_needs_person(self)
        result = self.run_command(
            self.project, _render(_action("record_accepted_risk"), self.subject,
                                  with_confirmation=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.observe(self.project, self.subject),
            (sa.writer_state_key(core.WriterState.ACKNOWLEDGED_RISK),),
            "fixture precondition: a real, recorded decision")

    def _rescan_records_remediable_kinds(self):
        """The same file, re-scanned, recording only kinds our own remediator
        covers. The writer's bytes are untouched, so the decision stays valid."""
        self.project.queue([_queue_entry(self.subject, ["sealed_kernel_import"],
                                        _sha256(_UNREPAIRABLE_SRC))])

    def test_the_decision_stops_applying_once_the_writer_is_rebuildable(self):
        self._rescan_records_remediable_kinds()
        self.assertEqual(
            self.observe(self.project, self.subject),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),),
            "a recorded decision released a writer whose every violation our own "
            "remediator covers, so its rebuild never had to happen")

    def test_the_decision_is_still_on_file_and_simply_NOT_honoured(self):
        """It is not deleted, revoked or hidden -- the operator said what they
        said. It is INERT for this state, which is a different thing, and the
        difference matters because deleting it would be rewriting their words."""
        self._rescan_records_remediable_kinds()
        self.assertIn(self.subject,
                      store.active_acknowledgements(str(self.project.root)),
                      "the record was destroyed rather than left unapplied")

    def test_the_writer_goes_back_to_HOLDING_LIVE_ENABLE_BACK(self):
        self._rescan_records_remediable_kinds()
        status = health.overall_status(str(self.project.root))
        block = status["open_external_write_bypass"]
        self.assertIn(self.subject, block["blocking_writer_relpaths"])
        self.assertFalse(status["normal_status_allowed"])

    def test_the_surface_then_names_the_REBUILD_and_not_the_decision(self):
        self._rescan_records_remediable_kinds()
        block = health.overall_status(
            str(self.project.root))["open_external_write_bypass"]
        self.assertIn(core.BYPASS_UNREPAIRED_REPAIR, block["actions"][self.subject])
        self.assertNotIn("no action is needed",
                         block["actions"][self.subject].lower(),
                         "an operator whose rebuild is still owed was told there "
                         "was nothing to do")


class TheCompliantWriterThatCouldNotProveItCompliesTests(unittest.TestCase,
                                                          _Observing):
    """The second dead end, sanitized: a hand-rolled bulk write loop that CAN be
    made fully compliant. Every violation recorded against it is one our own
    remediator covers, so the rebuild genuinely clears it -- and this file executes
    that. What it also records, and grounds, is the half that is still open: after
    the rebuild the writer's own capability still cannot produce the fresh proof
    its acceptance requires, because nothing operator-invocable drives the
    apply-undo-verify round-trip that would produce one. The bypass terminates
    correctly; the acceptance path still terminates."""

    def setUp(self):
        self.project, self.subject = _build_blocking_live_enable(self)

    def test_the_surface_tells_this_writer_to_rebuild_and_names_the_check(self):
        block = health.overall_status(
            str(self.project.root))["open_external_write_bypass"]
        self.assertEqual(block["writer_states"][self.subject],
                         core.WriterState.BLOCKING_LIVE_ENABLE)
        self.assertIn(core.BYPASS_UNREPAIRED_REPAIR,
                      block["actions"][self.subject])
        self.assertIn(_render(_action("rebuild_onto_the_sanctioned_path"),
                              self.subject),
                      block["actions"][self.subject])

    def test_the_rebuilt_writer_passes_the_confirming_check_and_its_entry_CLOSES(self):
        _rebuild_the_writer(self.project, self.subject)
        result = self.run_command(
            self.project,
            _render(_action("rebuild_onto_the_sanctioned_path"), self.subject))
        self.assertEqual(result.returncode, 0,
                         "the check the entry clears on does not pass: %r %r"
                         % (result.stdout, result.stderr))
        self.assertEqual(
            self.observe(self.project, self.subject),
            (sa.writer_state_key(core.WriterState.RESOLVED),))
        self.assertEqual(
            json.loads((self.project.root / QUEUE_REL).read_text(
                encoding="utf-8")), [],
            "the entry was not closed, so the writer is still held back")

    def test_an_edit_that_does_not_migrate_it_does_NOT_close_the_entry(self):
        """The safety-critical direction of the same predicate: a changed hash
        alone must never close an entry. Without this, a cosmetic edit would look
        like a rebuild."""
        self.project.write(self.subject,
                           _REBUILDABLE_SRC + "\n# tweaked, still a bypass\n")
        result = self.run_command(
            self.project,
            _render(_action("rebuild_onto_the_sanctioned_path"), self.subject))
        self.assertNotEqual(result.returncode, 0,
                            "the confirming check passed a writer that is still "
                            "a bypass")
        self.assertEqual(
            self.observe(self.project, self.subject),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),))


# ===========================================================================
# 6. DEGENERATE, AMBIGUOUS AND UNREADABLE STATE
# ===========================================================================

class MalformedAndUnreadableStateNeverReadsAsAWayOutTests(unittest.TestCase,
                                                          _Observing):
    """A read failure must never present as "this file is not flagged" and refuse
    for the wrong reason, nor as a clean bill of health."""

    def test_a_malformed_queue_refuses_the_command_and_withholds_the_all_clear(self):
        project = _Project(self)
        project.write(UPKEEP_WRITER, _UNREPAIRABLE_SRC)
        project.raw_queue("{ not json")

        status = health.overall_status(str(project.root))
        block = status["open_external_write_bypass"]
        self.assertTrue(block["read_error"])
        self.assertTrue(block["blocking"])
        self.assertFalse(status["normal_status_allowed"])

        result = self.run_command(
            project, _render(_action("record_accepted_risk"), UPKEEP_WRITER,
                             with_confirmation=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertIn("could not be read", result.stdout + result.stderr)
        self.assertFalse((project.root / store.ACKNOWLEDGEMENTS_REL).exists())

    def test_an_UNREADABLE_queue_is_distinguished_from_an_absent_one(self):
        project = _Project(self)
        project.write(UPKEEP_WRITER, _UNREPAIRABLE_SRC)
        path = project.write(QUEUE_REL, json.dumps(
            [_queue_entry(UPKEEP_WRITER, ["forbidden_import"],
                          _sha256(_UNREPAIRABLE_SRC))]))
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o644)

        status = health.overall_status(str(project.root))
        self.assertTrue(status["open_external_write_bypass"]["read_error"])
        self.assertFalse(status["normal_status_allowed"])

        result = self.run_command(
            project, _render(_action("record_accepted_risk"), UPKEEP_WRITER,
                             with_confirmation=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((project.root / store.ACKNOWLEDGEMENTS_REL).exists())

    def test_an_ABSENT_queue_is_a_normal_input_and_fires_nothing(self):
        """The fresh-project case. A check that fires on every deployment is worse
        than no check, and this package has corrected that trap more than once."""
        project = _Project(self)
        status = health.overall_status(str(project.root))
        self.assertFalse(status["open_external_write_bypass"]["read_error"])
        self.assertFalse(status["open_external_write_bypass"]["blocking"])
        self.assertTrue(status["normal_status_allowed"], status)

    def test_a_writer_whose_FILE_is_unreadable_stays_blocking(self):
        """A file that reads as bytes but not as text is unclassifiable, and an
        unclassifiable writer must never be granted a non-blocking state. Driven
        with the entry's recorded pause-time hash matching the file, which is the
        case where the classifier is the one that answers."""
        project = _Project(self)
        path = project.root / UPKEEP_WRITER
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"\xff\xfe not decodable as utf-8 \x00"
        path.write_bytes(payload)
        project.queue([_queue_entry(
            UPKEEP_WRITER, ["forbidden_import"],
            hashlib.sha256(payload).hexdigest())])
        self.assertEqual(
            self.observe(project, UPKEEP_WRITER),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),))

    def test_an_INACCESSIBLE_writer_never_has_its_entry_closed(self):
        """Present but inaccessible is not "no longer exists". Distinguished by
        the read's own exception type, and this direction is correct today."""
        project = _Project(self)
        path = project.write(UPKEEP_WRITER, _REBUILDABLE_SRC)
        project.queue([_queue_entry(UPKEEP_WRITER, ["sealed_kernel_import"],
                                   "0" * 64)])
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o644)
        self.assertEqual(
            self.observe(project, UPKEEP_WRITER),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),),
            "an unverifiable writer was granted a non-blocking state")

    @unittest.expectedFailure
    def test_KNOWN_DEFECT_an_undecodable_writer_has_its_entry_closed(self):
        """A DEFECT THIS GATE FOUND, recorded here so it cannot be lost, and
        deliberately recorded as an EXPECTED FAILURE so that fixing it turns this
        into an unexpected success and forces this record to be discharged.

        NOT this task's to fix, and a naive fix is dangerous -- see the report that
        accompanies this file. The clearing authority is the build lead.

        What happens: the bypass scanner returns NO violations for a source file it
        cannot decode as UTF-8, so "the file passes the scan" and "the file could
        not be read" are the same answer. The reaper's predicate is
        hash-changed AND scan-clean, so a flagged writer whose bytes change to
        something not decodable as UTF-8 has its migration entry CLOSED, and the
        project reports green over a bypass that is still there. The structural
        classifier gets this right on its own (see the two tests above); it never
        gets asked, because the reconcile-on-read reap runs first and removes the
        entry.

        The scanner's own comment, two lines below the branch responsible, says an
        unparseable file "cannot be statically verified safe" and must be treated
        as a violation "so the build does not pass blind". The read-failure branch
        immediately above it does the opposite.
        """
        project = _Project(self)
        path = project.root / UPKEEP_WRITER
        path.parent.mkdir(parents=True, exist_ok=True)
        # Valid Python in a non-UTF-8 encoding -- not adversarial, just a file
        # saved as latin-1. Its bytes differ from the recorded pause-time hash.
        path.write_bytes("X = 'caf\xe9'\n".encode("latin-1"))
        project.queue([_queue_entry(UPKEEP_WRITER, ["sealed_kernel_import"],
                                   "0" * 64)])
        self.assertEqual(
            self.observe(project, UPKEEP_WRITER),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),),
            "an undecodable writer's entry was closed as if it had been fixed")


class DuplicateAndMixedEntriesNamingOneFileTests(unittest.TestCase, _Observing):
    """Two open items naming one file, in DIFFERENT states. The queue guarantees
    no relpath uniqueness and two entries can record different violations, so this
    is reachable -- and a decision is keyed on the PATH, so it cannot say which of
    them it accepted."""

    def setUp(self):
        self.project = _Project(self)
        self.project.write(UPKEEP_WRITER, _UNREPAIRABLE_SRC)
        self.project.queue([
            _queue_entry(UPKEEP_WRITER, ["forbidden_import"],
                         _sha256(_UNREPAIRABLE_SRC), mechanism_id="first"),
            _queue_entry(UPKEEP_WRITER, ["sealed_kernel_import"],
                         _sha256(_UNREPAIRABLE_SRC), mechanism_id="second"),
        ])

    def test_the_production_classifier_reports_BOTH_states(self):
        self.assertEqual(
            self.observe(self.project, UPKEEP_WRITER, allow_ambiguity=True),
            tuple(sorted((
                sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),
                sa.writer_state_key(core.WriterState.NEEDS_PERSON)))))

    def test_the_command_REFUSES_rather_than_picking_one(self):
        result = self.run_command(
            self.project, _render(_action("record_accepted_risk"), UPKEEP_WRITER,
                                  with_confirmation=True))
        self.assertNotEqual(result.returncode, 0)
        message = result.stdout + result.stderr
        self.assertIn("more than one open item names", message)
        self.assertEqual(store.active_acknowledgements(str(self.project.root)),
                         {})

    def test_both_entries_still_hold_live_enable_back(self):
        status = health.overall_status(str(self.project.root))
        block = status["open_external_write_bypass"]
        self.assertTrue(block["blocking"])
        self.assertIn(UPKEEP_WRITER, block["blocking_writer_relpaths"])
        self.assertFalse(status["normal_status_allowed"])

    def test_two_entries_naming_DIFFERENT_files_are_each_answered_separately(self):
        """The ordinary multi-entry case, which must keep working: distinct
        relpaths in distinct states each get their own state and their own way
        out."""
        project = _Project(self)
        project.write(UPKEEP_WRITER, _UNREPAIRABLE_SRC)
        project.write(INBOX_WRITER, _REBUILDABLE_SRC)
        project.queue([
            _queue_entry(UPKEEP_WRITER, ["forbidden_import"],
                         _sha256(_UNREPAIRABLE_SRC)),
            _queue_entry(INBOX_WRITER, ["sealed_kernel_import"],
                         _sha256(_REBUILDABLE_SRC)),
        ])
        self.assertEqual(
            self.observe(project, UPKEEP_WRITER),
            (sa.writer_state_key(core.WriterState.NEEDS_PERSON),))
        self.assertEqual(
            self.observe(project, INBOX_WRITER),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),))
        block = health.overall_status(
            str(project.root))["open_external_write_bypass"]
        self.assertNotEqual(block["actions"][UPKEEP_WRITER],
                            block["actions"][INBOX_WRITER],
                            "two writers in different states were handed the "
                            "same instruction")

    def test_a_non_dict_entry_on_the_queue_does_not_lose_the_real_one(self):
        project = _Project(self)
        project.write(UPKEEP_WRITER, _UNREPAIRABLE_SRC)
        project.queue(["not an entry", None,
                       _queue_entry(UPKEEP_WRITER, ["forbidden_import"],
                                    _sha256(_UNREPAIRABLE_SRC))])
        self.assertEqual(
            self.observe(project, UPKEEP_WRITER),
            (sa.writer_state_key(core.WriterState.NEEDS_PERSON),))


class NonLiveNeedsAREALAbsenceOfReferencesTests(unittest.TestCase, _Observing):
    """`non_live` is the one non-blocking structural state, so the signals that
    grant it are the ones worth attacking. A name is not evidence."""

    def _project(self):
        project = _Project(self)
        project.write(TEST_WRITER, _TEST_MODULE_SRC)
        project.queue([_queue_entry(TEST_WRITER, ["sealed_kernel_import"],
                                   _sha256(_TEST_MODULE_SRC))])
        return project

    def test_an_unreferenced_test_module_is_not_live(self):
        self.assertEqual(
            self.observe(self._project(), TEST_WRITER),
            (sa.writer_state_key(core.WriterState.NON_LIVE),))

    def test_a_DECLARED_INVOCATION_SURFACE_naming_it_disqualifies_that(self):
        project = self._project()
        project.write("agents/roster.md",
                      "| upkeep | runs agents/upkeep/test_upkeep_helpers.py |\n")
        self.assertEqual(
            self.observe(project, TEST_WRITER),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),))

    def test_a_REAL_IMPORT_from_non_test_code_disqualifies_it_too(self):
        project = self._project()
        project.write("agents/upkeep/driver.py",
                      "import test_upkeep_helpers\n\n\ndef main():\n"
                      "    return test_upkeep_helpers\n")
        self.assertEqual(
            self.observe(project, TEST_WRITER),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),))

    def test_a_module_named_like_a_test_but_WITHOUT_test_structure_is_not_granted_it(self):
        project = _Project(self)
        project.write(TEST_WRITER,
                      '"""Named like a test; no test framework in it at all."""\n'
                      "\n\ndef helper():\n    return 1\n")
        project.queue([_queue_entry(
            TEST_WRITER, ["sealed_kernel_import"],
            _sha256('"""Named like a test; no test framework in it at all."""\n'
                    "\n\ndef helper():\n    return 1\n"))])
        self.assertEqual(
            self.observe(project, TEST_WRITER),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),))


class TheBlockedDomainsOBSERVABLEHalfStillRunsTests(unittest.TestCase):
    """The deferral is kept as narrow as it honestly can be. What cannot run is
    reaching a trial-unit state through a sanctioned path and then driving the
    reversal. What CAN run, and does here, is the observation half: the production
    reader sees each driven state in the durable record a killed process leaves
    behind, and the health projection hands back the registry's own command for it.

    This is not a substitute for the round-trip and is not counted as one."""

    def setUp(self):
        self.project = _Project(self, with_lib=False)

    def _scan(self):
        return tj.scan_outstanding_trials(
            journal_dir=str(self.project.root / tj.DEFAULT_TRIAL_JOURNAL_DIR))

    def test_the_production_reader_sees_every_driven_state_from_disk_alone(self):
        for state in sorted(tj.RECOVERY_DRIVEN_STATES):
            with self.subTest(state=state):
                project = _Project(self, with_lib=False)
                project.put_trial_record("t-1", {"r1": state})
                result = tj.scan_outstanding_trials(
                    journal_dir=str(project.root
                                    / tj.DEFAULT_TRIAL_JOURNAL_DIR))
                self.assertEqual(
                    [t["trial_id"] for t in result["trials"]], ["t-1"])
                self.assertEqual(result["trials"][0]["unit_states"], {"r1": state})

    def test_the_health_projection_hands_back_the_registrys_own_command(self):
        self.project.put_trial_record("t-77", {"r1": tj.STATE_APPLY_CONFIRMED})
        status = health.overall_status(str(self.project.root))
        trial, = status["interrupted_trial"]["trials"]
        self.assertFalse(status["normal_status_allowed"])
        self.assertEqual(
            trial["action"],
            sa.instruction_for_state(
                sa.trial_unit_state_key(tj.STATE_APPLY_CONFIRMED), "t-77"))
        self.assertIn(_render(_action("recover_interrupted_trial"), "t-77"),
                      trial["action"])

    def test_an_unreadable_record_routes_to_a_person_and_claims_nothing(self):
        self.project.put_trial_record("t-77", {}, raw="{ not json")
        status = health.overall_status(str(self.project.root))
        block = status["interrupted_trial"]
        self.assertTrue(block["outstanding"])
        self.assertEqual(len(block["unreadable"]), 1, block)
        self.assertIn("ask your assistant",
                      block["unreadable"][0]["action"].lower())
        self.assertFalse(status["normal_status_allowed"])

    def test_a_record_whose_declared_id_disagrees_with_its_filename_is_refused(self):
        """Joined on the DECLARED value. The filename is a candidate, never the
        identity."""
        directory = self.project.root / tj.DEFAULT_TRIAL_JOURNAL_DIR
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "t-1.json").write_text(json.dumps({
            "schema": tj.TRIAL_JOURNAL_SCHEMA, "trial_id": "t-2",
            "op_kind": "fixture.op",
            "units": [{"unit_id": "r1", "state": tj.STATE_APPLY_INTENT}]}),
            encoding="utf-8")
        result = self._scan()
        self.assertEqual(result["trials"], [])
        self.assertEqual(len(result["unreadable"]), 1, result)


# ===========================================================================
# 7. THE GATE'S OWN BODIES ARE FALSIFIABLE
# ===========================================================================

class TwoWaysOutOfONEStateIntoTwoSETTLEDStatesIsReportedTests(unittest.TestCase):
    """The cross-check the round-trip alone cannot make.

    A round-trip proves an action reaches the state it declares. It cannot notice
    that a state has acquired a SECOND declared way out landing in a different
    settled state -- because each round-trip would pass on its own. That
    combination is the exact historical defect: a rebuildable writer given a
    consent-recording exit as well as a rebuild, so recording consent took it out
    of the blocking set and the rebuild never had to happen, with the operator's
    entirely genuine consent. No consent check could have caught it, because the
    consent was real and the QUESTION was wrong.

    Computed here over the registry's own declared sets, and driven to a non-empty
    answer below so the body cannot be hollowed out."""

    def _states_with_two_settled_exits(self, actions):
        by_state = {}
        for action in actions:
            for key in action.from_states:
                by_state.setdefault(key, set()).add(action.expected_state)
        return tuple(sorted(
            key for key, targets in by_state.items()
            if len({t for t in targets if t in sa.INTENTIONAL_DISPOSITIONS}) > 1))

    def test_no_state_today_has_two_ways_out_into_two_settled_states(self):
        self.assertEqual(self._states_with_two_settled_exits(sa.ACTIONS), ())

    def test_the_check_REPORTS_such_a_state_when_one_exists(self):
        """Driven with a second exit added to a state that already has one. A gate
        body nothing forces to compute anything is the fifth green-and-blind gate
        in this family."""
        blocking = sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE)
        rebuild = _action("rebuild_onto_the_sanctioned_path")
        accept = _action("record_accepted_risk")
        widened = sa.StateAction(
            action_id=accept.action_id,
            from_states=accept.from_states + (blocking,),
            actor=accept.actor,
            command_builder=accept.command_builder,
            precondition=accept.precondition,
            expected_state=accept.expected_state,
            instruction=accept.instruction)
        self.assertIn(blocking,
                      self._states_with_two_settled_exits((rebuild, widened)))


class ThisGateNeverInjectsAStateTests(unittest.TestCase):
    """The single most likely way this gate could be theatre: a fixture that hands
    the classifier a pre-built state instead of raw artifacts. Asserted
    structurally over this file's own source, because "we would never do that" is
    not a property."""

    def _own_tree(self):
        return ast.parse(_THIS_FILE.read_text(encoding="utf-8"))

    def test_the_gate_never_names_the_classifiers_own_state_record(self):
        names = {node.id for node in ast.walk(self._own_tree())
                 if isinstance(node, ast.Name)}
        attributes = {node.attr for node in ast.walk(self._own_tree())
                      if isinstance(node, ast.Attribute)}
        for forbidden in ("StructuralClassification", "structural_classification",
                          "classify_bespoke_writer_entry"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names | attributes,
                                 "a fixture that constructs or drives the "
                                 "classifier directly is testing itself")

    def test_the_gate_never_writes_a_decision_record_by_hand(self):
        attributes = {node.attr for node in ast.walk(self._own_tree())
                      if isinstance(node, ast.Attribute)}
        self.assertNotIn("put_acknowledgement_record", attributes,
                         "a hand-written consent record would make the fixture, "
                         "not the command, the thing under test")

    def test_the_two_surfaces_are_read_in_exactly_ONE_place(self):
        """A second reader is a second thing that has to agree. Both surface calls
        must live inside the observation helper."""
        tree = self._own_tree()
        readers = {"bespoke_writer_state_report"}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr in readers):
                    self.assertEqual(
                        node.name, "observe",
                        "%r reads the production classifier directly; every "
                        "state read must go through the observation helper"
                        % node.name)

    def test_every_fixture_builder_writes_raw_artifacts_and_returns_a_subject(self):
        for key, builder in sorted(_FIXTURE_BUILDERS.items()):
            with self.subTest(state=key):
                self.assertTrue(callable(builder))
                self.assertEqual(builder.__code__.co_argcount, 1,
                                 "a builder takes the test case and nothing "
                                 "else -- it must not be handed a state")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
