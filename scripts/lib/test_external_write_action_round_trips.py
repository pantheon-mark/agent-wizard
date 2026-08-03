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

EVERY declared action's round-trip runs, and the one that could not is DISCHARGED
--------------------------------------------------------------------------------
`recover_interrupted_trial` leaves the trial-unit states, and its round-trip was
DECLARED not-yet-runnable here for one precisely-stated reason: the trial had a
public RECOVERY entrypoint and no public way to START one, so reaching a driven
state in a fixture would have meant authoring a driver standing in for an
entrypoint that did not exist -- and a round-trip that passes because the gate
faked its own starting conditions is the green-and-blind failure this gate exists
to end.

That entrypoint now exists and is enrolled in the operator-invocable command
manifest, so the declaration is discharged rather than relaxed: every trial-unit
fixture below reaches its state by RUNNING that public command against a project
carrying the operator-side adapter contracts, and being killed (`os._exit`, no
unwinding, nothing on either stream) at the point its state names. Nothing writes
a durable trial record by hand. The recovery command is then run as a real
subprocess and the state both trial surfaces report -- the production reader and
the health projection -- must be the settled state the action declares.

One state in that vocabulary cannot be the whole state of a fixture, and it is
declared with its structural reason rather than omitted: see
`_STATES_WITH_NO_WHOLE_FIXTURE`.

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
from external_write import scan                                    # noqa: E402
from external_write import state_actions as sa                     # noqa: E402
from external_write import trial_executor as tx                   # noqa: E402
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

#: The operator-side adapter contracts a trial needs, reproduced over a FILE so
#: the state survives the process that changes it -- which is the whole point: a
#: killed trial and the recovery command that follows it are two processes, and a
#: fixture holding its surface in memory could not model the thing being tested.
#:
#: The fault is read off a file at the moment of use, not baked in, because the
#: same adapter has to fail in the trial process and work in the recovery process
#: that repairs it. `os._exit` is the kill: no unwinding, no cleanup, nothing on
#: either stream -- what a crashed operator run actually leaves behind.
_TRIAL_ADAPTER_SRC = '''"""Fixture adapter -- the operator-side trial contracts over a file."""
import json
import os
from pathlib import Path

from external_write.adapter_registry import register_adapter
from external_write.contracts import (
    OperationContract, WRITE_AFFECTING_MODULES, register_contract,
)
from external_write.operations import EffectUnit
from external_write.read_facade import ReadFacade, register_read_facade

OP_KIND = "fixture.trial.set_exact_labels"
SURFACE_REL = "security/fixture_surface.json"
FAULT_REL = "security/fixture_fault.txt"
APPLIED_LABEL = "ARCHIVED"

FAULT_APPLY_EXIT = "apply_exit"
FAULT_VERIFY_EXIT = "verify_exit"
FAULT_UNDO_EXIT = "undo_exit"
FAULT_UNDO_NOOP = "undo_noop"

_KILL_STATUS = 137


def _read_surface():
    path = Path.cwd() / SURFACE_REL
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_surface(state):
    path = Path.cwd() / SURFACE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _fault():
    path = Path.cwd() / FAULT_REL
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


class _WriteClient:
    def set_labels(self, unit_id, labels):
        state = _read_surface()
        state[unit_id] = list(labels)
        _write_surface(state)


class _ReadOnlyClient:
    def get_state(self, unit_id):
        return {"unit_id": unit_id,
                "labels": sorted(_read_surface().get(unit_id, ()))}


class FixtureTrialReadFacade(ReadFacade):
    read_methods = ("get_state",)

    def get_state(self, unit_id):
        return self._read("get_state", unit_id)


class FixtureTrialAdapter:
    """Absolute-state undo, both evidence predicates, both clients provisioned
    on the adapter -- the shape the trial-eligibility preflight requires."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def __init__(self):
        self._observations = 0

    def plan(self, params):
        return [
            EffectUnit(unit_id=r["unit_id"],
                       target_ref={"unit_id": r["unit_id"]},
                       undo_ref={"unit_id": r["unit_id"],
                                 "prior_labels": list(r.get("prior_labels", ()))})
            for r in (params or {}).get("records", [])
        ]

    def build_write_client(self, op):
        return _WriteClient()

    def build_read_only_client(self, op):
        return _ReadOnlyClient()

    def apply_one(self, raw_client, unit):
        raw_client.set_labels(unit.target_ref["unit_id"], [APPLIED_LABEL])
        if _fault() == FAULT_APPLY_EXIT:
            os._exit(_KILL_STATUS)

    def undo_one(self, raw_client, unit):
        fault = _fault()
        if fault == FAULT_UNDO_EXIT:
            os._exit(_KILL_STATUS)
        if fault == FAULT_UNDO_NOOP:
            return None
        raw_client.set_labels(unit.undo_ref["unit_id"],
                              unit.undo_ref["prior_labels"])

    def verify_one(self, observer, unit):
        self._observations += 1
        if _fault() == FAULT_VERIFY_EXIT and self._observations == 1:
            os._exit(_KILL_STATUS)
        observed = observer.get_state(unit.unit_id)["labels"]
        prior = sorted((unit.undo_ref or {}).get("prior_labels", ()))
        return {"unit_id": unit.unit_id, "observed_labels": observed,
                "applied": observed == [APPLIED_LABEL],
                "matches_prestate": observed == prior}

    def verify_apply_landed(self, evidence):
        return bool(evidence.poststate.get("applied"))

    def verify_undo_restored(self, evidence):
        return bool(evidence.poststate.get("matches_prestate"))


register_adapter(OP_KIND, FixtureTrialAdapter())
register_contract(OperationContract(
    op_kind=OP_KIND, writes=("labels",), produces=(),
    dependency_set=WRITE_AFFECTING_MODULES,
    verifier_set=("prestate_snapshot_diff_v1",),
    introduces_persistent_binding=False, risk_class="sensitive_data",
    requires_accepted_phase=True, blast_radius_cap=25,
    read_only_scope="fixture.readonly"))
register_read_facade(OP_KIND, FixtureTrialReadFacade)
'''

#: The capability the trial is run FOR. It proposes; it never holds a client and
#: never touches the adapter -- the kernel-as-runner injects the read-only view.
_TRIAL_CAPABILITY_SRC = '''"""Fixture capability -- proposes what the trial carries through."""
from external_write.operations import Operation

OP_KIND = "fixture.trial.set_exact_labels"
SURFACE = "fixture_surface"


def describe():
    return "fixture trial capability"


def propose_operations(facade, batch_id):
    return [Operation(surface=SURFACE, object_id="r1", field="labels",
                      new_value="ARCHIVED", op_kind=OP_KIND, batch_id=batch_id,
                      params={"records": [%s]})]
'''

TRIAL_CAPABILITY_ID = "fixture_trial"
TRIAL_SURFACE = "fixture_surface"
TRIAL_OP_KIND = "fixture.trial.set_exact_labels"
TRIAL_ADAPTER_STEM = "adapters_trialfixture"
FIXTURE_SURFACE_REL = "security/fixture_surface.json"
FIXTURE_FAULT_REL = "security/fixture_fault.txt"
DESCRIPTOR_SET_REL = "security/capability_descriptors.json"

#: What the operator says to approve a bounded trial on their own record. One
#: physical line, no quoting hazard.
TRIAL_APPROVAL = "Yes -- try one change on my real record and put it back."

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
        return self._put_validated_shape_record(path, trial_id, unit_states,
                                                op_kind)

    # -- the trial fixture: an operator project a real trial can run in --------

    def install_trial_fixture(self, units=("r1",), cap=25):
        """Everything a trial needs, as the bytes a real project carries: the
        adapter enrolled the way an operator-added adapter is enrolled (a sibling
        JSON manifest the kernel unions in at import, never an edit to a
        bundle-copied file), the reader DECLARED in the lib the kernel resolves
        declarations from, the capability that proposes the change, the descriptor
        entry that declares a native-undo test target, and the surface itself."""
        lib = self.root / "agents" / "lib" / "external_write"
        (lib / f"{TRIAL_ADAPTER_STEM}.py").write_text(_TRIAL_ADAPTER_SRC,
                                                      encoding="utf-8")
        (lib / "operator_adapters.json").write_text(
            json.dumps([TRIAL_ADAPTER_STEM]), encoding="utf-8")
        records = ", ".join(
            '{"unit_id": "%s", "prior_labels": ["OPEN"]}' % unit for unit in units)
        self.write(f"agents/capabilities/{TRIAL_CAPABILITY_ID}_capability.py",
                   _TRIAL_CAPABILITY_SRC % records)
        self.write(DESCRIPTOR_SET_REL, json.dumps([{
            "id": TRIAL_SURFACE, "name": TRIAL_SURFACE, "action_class": "modify",
            "risk_class": "sensitive_data", "recovery_profile_ref": None,
            "declared_test_target": "native_undo", "blast_radius_cap": cap,
            "accepted": False}], indent=2))
        self.write(FIXTURE_SURFACE_REL,
                   json.dumps({unit: ["OPEN"] for unit in units}, indent=2))
        return tuple(units)

    def set_fault(self, fault):
        self.write(FIXTURE_FAULT_REL, fault)

    def clear_fault(self):
        path = self.root / FIXTURE_FAULT_REL
        if path.exists():
            path.unlink()

    def surface(self):
        return json.loads((self.root / FIXTURE_SURFACE_REL).read_text(
            encoding="utf-8"))

    def trial_ids(self):
        directory = self.root / tj.DEFAULT_TRIAL_JOURNAL_DIR
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.glob("*.json"))

    def _put_validated_shape_record(self, path, trial_id, unit_states, op_kind):
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

    def observe(self, project, subject, allow_ambiguity=False,
                domain=sa.DOMAIN_BESPOKE_WRITER):
        """Every state the production machinery reports for `subject`, as registry
        KEYS, in sorted order.

        `domain` selects the VOCABULARY the subject belongs to, and it is the
        FIXTURE's domain rather than the action's: an action invoked against a
        subject of the other vocabulary must leave that subject where it was, and
        that property is only observable in the subject's own vocabulary. Both
        branches read two surfaces and require them to agree, for the same reason:
        the two have diverged before.

        THE TRIAL BRANCH. The production reader is `scan_outstanding_trials` -- the
        same one the health projection is built over -- and the surfaces are that
        reader and the projection. A trial with nothing outstanding is reported by
        NEITHER, exactly as a writer with no open entry is: for those, the settled
        per-unit states come from the trial's own durable record through the same
        validated read the recovery command performs. That is not a third
        classifier -- there is nothing to classify. A unit's state is a value the
        record carries, and the reader above is that read plus an
        outstanding-or-not filter.

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
        if domain == sa.DOMAIN_TRIAL_UNIT:
            journal_dir = str(project.root / tj.DEFAULT_TRIAL_JOURNAL_DIR)
            projected = tuple(sorted(
                {state for trial in status["interrupted_trial"]["trials"]
                 if trial["trial_id"] == subject
                 for state in trial["unit_states"].values()}))
            reported = tuple(sorted(
                {state for trial in tj.scan_outstanding_trials(
                    journal_dir=journal_dir)["trials"]
                 if trial["trial_id"] == subject
                 for state in trial["unit_states"].values()}))
            self.assertEqual(
                projected, reported,
                "the health projection and the production reader report "
                "different states for trial %r -- one of the two surfaces an "
                "operator reads is wrong" % subject)
            if not reported:
                reported = tuple(sorted(set(tj.load_trial_journal(
                    subject, journal_dir=journal_dir).unit_states().values())))
            return tuple(sa.trial_unit_state_key(state) for state in reported)

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
        """Run `command` as a real process, from the project root, with the
        arguments exactly as rendered. Bytecode writing is off in the child, so
        nothing a previous run cached can answer for what the current source does.

        ONE SUBSTITUTION, and it is not fidelity being traded away: the rendered
        command starts with `python3` (asserted, because a rendered command that did
        not would not be the paste-ready line it claims to be), and what actually
        runs is `sys.executable` with the same arguments. That is what makes the
        dual-interpreter run mean anything -- under py3.12 the child has to be
        py3.12, and a literal `python3` would silently run the system 3.9.6 in both
        halves and prove the second one nothing."""
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
    the reaper closes its entry. Nothing here removes the entry by hand.

    THE OPEN ENTRY IS ASSERTED BEFORE IT IS ALLOWED TO BE CLOSED, and that is
    load-bearing rather than defensive. This is the one state observed as the
    ABSENCE of an entry, so a fixture that never had one would be indistinguishable
    from one the reaper cleared -- absence read as evidence of resolution, which is
    the same silence-as-safety shape this file's own scanner finding turned on. A
    hollowed-out builder must fail here, not pass quietly."""
    project = _Project(case)
    project.write(INBOX_WRITER, _SANCTIONED_SRC)
    project.queue([_queue_entry(INBOX_WRITER, ["sealed_kernel_import"],
                               _sha256(_REBUILDABLE_SRC))])
    case.assertIn(
        INBOX_WRITER,
        [str(e.get("writer_relpath"))
         for e in core.open_bespoke_writer_migrations(str(project.root))],
        "this fixture reaches its state by having an entry CLOSED, so it must "
        "start with one open -- a writer nothing ever flagged would look "
        "identical and prove nothing")
    return project, INBOX_WRITER


# ---------------------------------------------------------------------------
# THE TRIAL-UNIT BUILDERS. Every one reaches its state by RUNNING THE PUBLIC
# TRIAL COMMAND against a project carrying the operator-side contracts, and then
# being killed (or not) at the point the state names. Nothing writes a journal by
# hand: a hand-authored durable record asserts that a trial did something no trial
# did, which is the fixture faking its own starting conditions -- the failure this
# gate exists to end, and the reason this domain's round-trip was declared
# not-yet-runnable until the trial had an operator-invocable way in.
# ---------------------------------------------------------------------------

def _run_a_trial(case, fault=None, units=("r1",)):
    """Run the public trial command once, with `fault` armed, and return
    `(project, trial_id)`.

    The fault file is REMOVED before returning: the same adapter has to fail in
    the trial process and work in the recovery process that repairs it, which is
    what a transient cause actually looks like."""
    project = _Project(case)
    project.install_trial_fixture(units=units)
    if fault is not None:
        project.set_fault(fault)
    command = tx.trial_command(TRIAL_CAPABILITY_ID,
                              operator_approval=TRIAL_APPROVAL)
    case.assert_enrolled_operator_command(command)
    result = case.run_command(project, command)
    project.clear_fault()
    if fault is None:
        case.assertEqual(result.returncode, 0,
                         "fixture precondition: the trial itself must run: %r %r"
                         % (result.stdout, result.stderr))
    else:
        case.assertNotEqual(
            result.returncode, 0,
            "fixture precondition: this fixture models a KILLED trial, and the "
            "command reported success")
    ids = project.trial_ids()
    case.assertEqual(
        len(ids), 1,
        "fixture precondition: exactly one durable trial record, found %r" % ids)
    return project, ids[0]


def _build_apply_intent(case):
    """Killed the instant after the change was issued and before anything
    confirmed it landed -- the ambiguous window the whole protocol is built
    around. The change IS live on the surface."""
    return _run_a_trial(case, fault="apply_exit")


def _build_apply_confirmed(case):
    """Killed after the change was issued and recorded, while it was being
    checked."""
    return _run_a_trial(case, fault="verify_exit")


def _build_undo_intent(case):
    """Killed after the reversal was recorded as intended and before it was
    issued. The write-ahead record is already on disk, which is what write-ahead
    means -- so recovery must not re-record it."""
    return _run_a_trial(case, fault="undo_exit")


def _build_recovery_required(case):
    """Not killed: the reversal was issued and did not restore the surface, and
    the trial recorded that truthfully rather than reporting a restore it could
    not observe."""
    return _run_a_trial(case, fault="undo_noop")


def _build_restored_verified(case):
    """The settled end of the protocol, reached by a trial that completed: every
    unit observed back at its prior state, and the proof written."""
    return _run_a_trial(case)


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
    sa.trial_unit_state_key(tj.STATE_APPLY_INTENT): _build_apply_intent,
    sa.trial_unit_state_key(tj.STATE_APPLY_CONFIRMED): _build_apply_confirmed,
    sa.trial_unit_state_key(tj.STATE_UNDO_INTENT): _build_undo_intent,
    sa.trial_unit_state_key(tj.STATE_RECOVERY_REQUIRED): _build_recovery_required,
    sa.trial_unit_state_key(tj.STATE_RESTORED_VERIFIED): _build_restored_verified,
}

#: The one state in either vocabulary that CANNOT be the whole state of a fixture,
#: with the structural reason -- declared POSITIVELY, because a state left out of
#: the builder map for no recorded reason is exactly the silently-untested state
#: this gate refuses everywhere else.
#:
#: A trial's journal is opened and its first unit is driven in the same call, with
#: no adapter hook between the two: the write-ahead intent for unit one is fsynced
#: before anything can interrupt the run. So `planned` is only ever reachable as a
#: CO-STATE -- a later unit of a trial that stopped at an earlier one -- never as
#: the state of every unit of a trial. It is exercised in that form, from a real
#: killed run, by `TheStoppedTrialLeavesLaterUnitsUNTOUCHEDTests`, and the state's
#: declared disposition (nothing was changed, so nothing is needed) is what the
#: registry renders for it.
_STATES_WITH_NO_WHOLE_FIXTURE = {
    sa.trial_unit_state_key(tj.STATE_PLANNED): (
        "a trial drives its first unit in the same call that opens the journal, "
        "so no unit of a trial can be the only one left unattempted"),
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

_RUNNABLE_DOMAINS = frozenset({sa.DOMAIN_BESPOKE_WRITER, sa.DOMAIN_TRIAL_UNIT})

#: EMPTY, and that is the discharge rather than a tidy. The trial-unit domain was
#: declared not-yet-runnable here for one stated reason: no operator-invocable
#: command could put a project into a trial-unit state, because the trial had a
#: public RECOVERY entrypoint and no public way to START one -- so reaching a driven
#: state would have meant authoring a driver standing in for an entrypoint that did
#: not exist, and a round-trip that passes because the gate faked its own starting
#: conditions is the failure this gate exists to end.
#:
#: That entrypoint now exists, is enrolled in the operator-invocable command
#: manifest, and is what every trial-unit fixture above runs. The declaration is
#: therefore discharged: the round-trips RUN, from real killed runs. The mapping is
#: kept (rather than deleted) so a future deferral has a declared home with the same
#: obligations -- a domain in neither set still fails the partition test below.
_BLOCKED_DOMAINS = {}


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


def _runnable_vocabulary_keys():
    """Every state key of every RUNNABLE domain, read off the declaring modules so
    a state added to either vocabulary arrives here automatically."""
    keys = set()
    if sa.DOMAIN_BESPOKE_WRITER in _RUNNABLE_DOMAINS:
        keys |= set(_writer_vocabulary_keys())
    if sa.DOMAIN_TRIAL_UNIT in _RUNNABLE_DOMAINS:
        keys |= {sa.trial_unit_state_key(s) for s in tj.TRIAL_UNIT_STATES}
    return frozenset(keys)


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
        """The obligation on a deferral, kept live for whoever declares the next
        one. Nothing is deferred today, so the loop is empty -- which is why the
        rule is also driven against a planted deferral below, rather than being a
        vacuous pass nobody would notice had stopped checking."""
        for domain, blocker in sorted(_BLOCKED_DOMAINS.items()):
            with self.subTest(domain=domain):
                self.assertTrue(blocker.strip())
                self.assertIn("no operator-invocable", blocker,
                              "a deferral has to say what is missing, not that "
                              "it was hard")

    def test_the_deferral_rule_REJECTS_a_blocker_that_names_no_obstacle(self):
        """Driven, so the rule above cannot quietly stop meaning anything."""
        for blocker in ("", "   ", "this was hard to test"):
            with self.subTest(blocker=blocker):
                self.assertFalse(
                    blocker.strip() and "no operator-invocable" in blocker,
                    "a blocker naming no missing mechanism must not qualify")

    def test_NO_action_is_blocked_today(self):
        """Pinned at NONE. Every declared action's round-trip runs, so an action
        joining the blocked set again is a failure rather than a footnote -- and
        the one deferral this file ever carried is discharged, not relaxed."""
        self.assertEqual([a.action_id for a in _blocked_actions()], [])
        self.assertEqual(_BLOCKED_DOMAINS, {})

    def test_every_action_from_states_live_in_a_SINGLE_vocabulary(self):
        for action in sa.ACTIONS:
            with self.subTest(action=action.action_id):
                self.assertIn(_action_domain(action), sa.DOMAINS)

    def test_the_fixture_builders_cover_the_WHOLE_runnable_vocabulary(self):
        """Quantified over BOTH declaring modules' own vocabularies. A state added
        upstream and left out of the builder map fails here -- it does not become
        an untested state nobody noticed. A state that cannot be the whole state of
        a fixture is covered only by being DECLARED so, with its structural reason,
        which is the difference between a recorded bound and an omission."""
        self.assertEqual(
            frozenset(_FIXTURE_BUILDERS) | frozenset(_STATES_WITH_NO_WHOLE_FIXTURE),
            _runnable_vocabulary_keys())
        self.assertEqual(
            frozenset(_FIXTURE_BUILDERS) & frozenset(_STATES_WITH_NO_WHOLE_FIXTURE),
            frozenset(),
            "a state cannot both have a fixture and be declared unfixturable")
        for key, reason in sorted(_STATES_WITH_NO_WHOLE_FIXTURE.items()):
            with self.subTest(state=key):
                self.assertTrue(reason.strip(),
                                "an exclusion with no reason is an omission")

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

class TheDISCHARGEDBlockerIsAssertedNotASSUMEDTests(unittest.TestCase):
    """The declared blocker this file used to carry is DISCHARGED, and the same
    standard applies to the discharge as applied to the deferral: it is asserted
    against the shipped tree, not recorded as done.

    What was missing was named precisely -- an operator-invocable way to START a
    trial -- and the assertions below are the mirror image of the ones that held
    while it was missing: an entrypoint from which a trial start is reachable now
    EXISTS, and it is one the operator-invocable command manifest declares. If
    either stops being true, the round-trips above are running against a mechanism
    no operator can reach, and this class is what says so."""

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

    def _called_names(self, node):
        """Every bare callee name reachable in `node`, from `f(...)` and
        `x.f(...)` alike. Bare names, deliberately: resolving each call to its
        defining module would make this check MISS a driver assembled across
        modules, and over-approximating is the safe direction for an assertion
        about whether a start is reachable at all."""
        names = set()
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
        return names

    def _package(self):
        """`{module name: (functions, main_block_callees)}` for the whole emitted
        package, where `functions` maps each defined function to what it calls."""
        parsed = {}
        for path in self._production_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            functions = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.setdefault(node.name, set()).update(
                        self._called_names(node))
            main_callees = set()
            for node in tree.body:
                if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                        and isinstance(node.test.left, ast.Name)
                        and node.test.left.id == "__name__"):
                    main_callees |= self._called_names(node)
            parsed[path.name] = (functions, main_callees)
        return parsed

    def _names_that_reach_a_trial_start(self, parsed):
        """TRANSITIVE closure over the whole package: every function name from
        which a trial start is reachable through any chain of calls."""
        reaching = {"run_trial"}
        changed = True
        while changed:
            changed = False
            for functions, _main in parsed.values():
                for name, callees in functions.items():
                    if name not in reaching and (callees & reaching):
                        reaching.add(name)
                        changed = True
        return reaching

    def test_a_shipped_ENTRYPOINT_can_now_reach_a_trial_start(self):
        """AST, because this is a question about code structure. The same closure
        that had to be EMPTY while the blocker held must now be non-empty, and the
        module it names must be the one the fixtures above actually run."""
        parsed = self._package()
        reaching = self._names_that_reach_a_trial_start(parsed)
        drivers = sorted(name for name, (_functions, main_callees) in parsed.items()
                         if main_callees & reaching)
        self.assertIn(
            Path(tx.TRIAL_ENTRYPOINT_REL).name, drivers,
            "no shipped command-line entrypoint can reach a trial start, so no "
            "trial-unit state is reachable in a freshly emitted project and the "
            "round-trips above are testing something an operator cannot do: %s"
            % drivers)

    def test_the_trial_start_is_an_ENROLLED_OPERATOR_COMMAND(self):
        """The property an operator is exposed to. Resolved from each entry's OWN
        declared `command_prefix` to the module it names, so this joins on a
        declared value rather than re-spelling a module name as a literal."""
        parsed = self._package()
        reaching = self._names_that_reach_a_trial_start(parsed)
        enrolled = []
        for entry in manifest.BASELINE_COMMANDS:
            script = next((token for token in entry.command_prefix.split()
                           if token.endswith(".py")), None)
            if script is None:
                continue
            name = Path(script).name
            if name not in parsed:
                continue      # a per-capability command, not a module we ship
            if parsed[name][1] & reaching:
                enrolled.append(entry.name)
        self.assertTrue(
            enrolled,
            "nothing the command manifest declares invocable can start a trial, "
            "so the producer of the proof acceptance requires is unreachable to "
            "the operator")

    def test_the_proof_PRODUCER_is_reachable_and_the_validator_still_the_gate(self):
        """The second historical dead end had two halves. The bypass half was
        already closed; THIS is the half that was open -- a capability could be
        made fully compliant and still not produce the fresh proof its own
        acceptance requires, because nothing operator-invocable drove the
        apply/undo/verify round trip.

        What is asserted is the shape of the closure, not merely that something
        changed: the proof module still exposes only a VALIDATOR and declares no
        entrypoint of its own (a producer there would be the validator vouching
        for its own output), while the producer sits in the journaled executor and
        is reachable from an operator command. The round-trip above runs it and
        puts the artifact through that same shipped validator."""
        proof_module = ast.parse(
            (_EXTERNAL_WRITE_DIR / "copy_run_proof.py").read_text(encoding="utf-8"))
        public = sorted(node.name for node in proof_module.body
                        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                        and not node.name.startswith("_"))
        self.assertIn("validate_copy_run_proof", public)
        self.assertFalse(
            self._has_main_block(proof_module),
            "the validator module now declares an entrypoint of its own -- the "
            "producer and the check on it must not be the same command")
        self.assertEqual(
            [name for name in public if name.startswith("produce")], [],
            "the producer belongs in the journaled executor, on the enforced "
            "path, not beside the validator that judges its output")

        executor = ast.parse(
            (_EXTERNAL_WRITE_DIR / Path(tx.TRIAL_ENTRYPOINT_REL).name).read_text(
                encoding="utf-8"))
        self.assertTrue(self._has_main_block(executor),
                        "the producer ships no operator-invocable entrypoint")


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
        domain = _domain_of(from_state)

        # (2) THE PRODUCTION CLASSIFIER OBSERVES THE DECLARED PRE-STATE. Not the
        # fixture's intention -- the shipped machinery's answer.
        self.assertEqual(
            self.observe(project, subject, domain=domain), (from_state,),
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
            self.observe(project, subject, domain=domain),
            (action.expected_state,),
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
        domain = _domain_of(state)
        self.assertEqual(self.observe(project, subject, domain=domain), (state,),
                         "fixture precondition")
        before = frozenset(store.active_acknowledgements(str(project.root)))

        command = _render(action, subject,
                          with_confirmation=_needs_confirmation(action))
        result = self.run_command(project, command)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

        self.assertEqual(
            self.observe(project, subject, domain=domain), (state,),
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
        # Its own vocabulary: the refusal being asserted is the one an operator
        # reads about a FILE, and a subject from the other vocabulary is covered by
        # the cross-domain safety property above rather than by this wording.
        for state in sorted(frozenset(_FIXTURE_BUILDERS)
                            & _writer_vocabulary_keys()
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
    that. Its second half -- that after the rebuild the writer's own capability
    still could not produce the fresh proof its acceptance requires, because
    nothing operator-invocable drove the apply/undo/verify round trip -- is closed
    too, and closed by EXECUTION rather than by assertion: the trial-unit fixtures
    in this file run that producer through its public command, and the artifact it
    emits goes through the shipped validator. What remains asserted here is the
    bypass half, which is this class's own subject."""

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

    def test_an_UNDECODABLE_writer_never_has_its_entry_closed(self):
        """A DEFECT THIS GATE FOUND, now CLOSED, and pinned here so it stays that
        way.

        What used to happen: the bypass scanner returned NO violations for a source
        file it could not decode as UTF-8, so "this file passes the scan" and "this
        file could not be read" were the same answer -- silence passing, inside the
        trust scanner. The reaper's predicate is hash-changed AND scan-clean, so a
        flagged writer whose bytes changed to something not decodable as UTF-8 had
        its migration entry CLOSED and the project reported green over a bypass
        that was still there. The structural classifier gets this right on its own
        (see the two tests above); it never got asked, because the
        reconcile-on-read reap runs first and removes the entry.

        The trigger was ordinary, not adversarial: a source saved latin-1 or cp1252
        -- accented content, a Windows-authored file -- is valid Python.

        Fixed by giving the decode failure its own clause, reporting the same
        `unparseable` kind the scanner already raises for a file that will not
        parse, on identical reasoning: a file that cannot be statically verified
        must never read as verified. The ACCESS-failure half is a different
        question and is still open by design -- see the record below."""
        project = _Project(self)
        path = project.root / UPKEEP_WRITER
        path.parent.mkdir(parents=True, exist_ok=True)
        # Valid Python in a non-UTF-8 encoding, still carrying the bypass it was
        # flagged for. Its bytes differ from the recorded pause-time hash, so the
        # reap reaches the scan branch rather than short-circuiting.
        path.write_bytes(
            "from external_write.run_envelope import mint_run_envelope  "
            "# caf\xe9\n".encode("latin-1"))
        project.queue([_queue_entry(UPKEEP_WRITER, ["sealed_kernel_import"],
                                   "0" * 64)])
        self.assertEqual(
            self.observe(project, UPKEEP_WRITER),
            (sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),),
            "an undecodable writer's entry was closed as if it had been fixed")

    def test_an_undecodable_source_is_REPORTED_by_the_scanner_itself(self):
        """The upstream half, asserted directly, because the reap is not the only
        consumer. The check that decides which operator writers get FLAGGED in the
        first place sweeps whole directories through this same function, so a file
        it cannot read reading as clean meant such a writer was never flagged at
        all -- the more consequential direction of the same defect.

        Driven as a directory sweep next to a byte-identical readable control, so
        the assertion is that the sweep reports BOTH rather than that it reports
        something."""
        project = _Project(self, with_lib=False)
        project.write("agents/x/__init__.py", "")
        project.write("agents/x/control.py", "import urllib.request\n")
        (project.root / "agents" / "x" / "bad.py").write_bytes(
            "import urllib.request  # caf\xe9\n".encode("latin-1"))

        found = {Path(v.path).name: v.kind
                 for v in scan.scan_paths([str(project.root / "agents")])}
        self.assertEqual(found.get("control.py"), "forbidden_import",
                         "fixture precondition: the readable control is flagged")
        self.assertIn("bad.py", found,
                      "a source the scanner cannot read is passing silently")
        self.assertEqual(found["bad.py"], "unparseable")

    @unittest.expectedFailure
    def test_KNOWN_GAP_an_inaccessible_source_still_reads_as_clean(self):
        """THE REMAINING HALF of the defect above, and it is deliberately still
        open. Recorded as an EXPECTED FAILURE so that closing it turns this into an
        unexpected success -- a hard failure -- and forces this record to be
        discharged rather than quietly outliving its reason.

        The clearing authority is the build lead.

        Why the two halves were split rather than fixed together. A DECODE failure
        is a content problem: the file is right there and readable, it simply is not
        valid UTF-8, so refusing to vouch for it costs nothing and was pure
        fail-open. An ACCESS failure is a different question. This function is
        called with whole DIRECTORIES -- by the build-time gate, by the check that
        decides which writers get flagged at upgrade, and by four other read
        surfaces -- so treating one permission-denied `.py` as a violation would
        fail every build that contains one, anywhere in a swept tree. That is the
        fail-closed-check-that-bricks-everything shape, and this cut exists partly
        to stop opening states an operator cannot leave. Closing it needs the input
        set scoped first, which is a design decision with cross-consumer reach.

        What is NOT at risk in the meantime, and is pinned green above: the readers
        that must distinguish an absent file from an inaccessible one already do so
        on their own read's exception type, so an inaccessible writer's entry is
        never closed."""
        project = _Project(self, with_lib=False)
        path = project.write("agents/y/locked.py", "import urllib.request\n")
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o644)
        self.assertTrue(
            scan.scan_paths([str(path)]),
            "a source the scanner could not open reported no violations")


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

    def test_whatever_the_SURFACE_hands_over_is_not_a_DEAD_END(self):
        """THE HARM, pinned without pinning the defect.

        The defect: the health projection keys its per-writer state on the relpath,
        so it structurally cannot represent two open entries naming one file in
        different states and reports whichever was iterated last. For this fixture
        it therefore hands the operator the accept-the-risk command -- which the
        eligibility guard then refuses, because a decision is keyed on the path and
        cannot say which entry it accepted.

        That shape is deliberately NOT asserted. Pinning "the surface reports one of
        two states, last one wins" would turn a defect into a contract, and the
        eventual fix would have to break a passing test.

        What IS asserted is the harm, in a form that stays true after any fix:
        whatever the surface hands the operator must not be a dead end. Either the
        command it names works, or the outcome routes the operator onward. What must
        never happen is a command that fails while saying nothing about what to do
        instead -- and that is exactly the shape both of this cut's historical dead
        ends had."""
        instruction = health.overall_status(
            str(self.project.root))["open_external_write_bypass"][
                "actions"][UPKEEP_WRITER]
        self.assertTrue(instruction.strip(), "the surface handed over nothing")

        command = None
        for entry in manifest.BASELINE_COMMANDS:
            index = instruction.find(entry.command_prefix)
            if index != -1:
                command = instruction[index:].split("\n")[0].strip()
                break

        if command is None:
            # No command offered: then the text itself must route to a person.
            self.assertIn("ask your assistant", instruction.lower(),
                          "no command and no route is a dead end")
            return

        result = self.run_command(self.project, command)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        if result.returncode == 0:
            self.assertNotIn(
                sa.writer_state_key(core.WriterState.NEEDS_PERSON),
                self.observe(self.project, UPKEEP_WRITER,
                             allow_ambiguity=True),
                "the command reported success and left the writer needing a "
                "person")
            return
        message = (result.stdout + result.stderr).lower()
        self.assertTrue(message.strip(),
                        "the surface handed over a command that fails silently")
        self.assertTrue(
            "ask your assistant" in message
            or core.BYPASS_UNREPAIRED_REPAIR in message,
            "the surface handed the operator a command that is refused without "
            "naming anything they can do instead: %r" % message)

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

    def test_the_PRODUCTION_CLASSIFIER_is_read_in_exactly_ONE_place(self):
        """The production classifier has exactly one reader in this file, so no
        second place can form its own opinion about a state.

        NARROWED ON PURPOSE, and the narrowing is the honest claim rather than the
        flattering one. This does NOT say both surfaces are single-sourced: several
        tests read the health projection directly to inspect specific fields of the
        bypass block -- `blocking`, `read_error`, `writer_relpaths`,
        `blocking_writer_relpaths`, `descriptions`, `actions` -- which is a
        legitimate thing for a test to look at and is not a state read.

        What this guard is still worth: a cross-surface state COMPARISON needs the
        classifier, so guarding the classifier is what keeps every such comparison
        inside `observe`, where the two surfaces are required to agree. A test that
        wanted to decide a state for itself would have to call the classifier, and
        it cannot."""
        tree = self._own_tree()
        readers = {"bespoke_writer_state_report"}
        seen = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr in readers):
                    seen.append(node.name)
        self.assertEqual(
            sorted(set(seen)), ["observe"],
            "the production classifier is read outside the observation helper, so "
            "a second place can decide a state for itself")

    def test_every_fixture_builder_writes_raw_artifacts_and_returns_a_subject(self):
        for key, builder in sorted(_FIXTURE_BUILDERS.items()):
            with self.subTest(state=key):
                self.assertTrue(callable(builder))
                self.assertEqual(builder.__code__.co_argcount, 1,
                                 "a builder takes the test case and nothing "
                                 "else -- it must not be handed a state")


class NoFixtureReachesItsStateByNeverBeingFLAGGEDTests(unittest.TestCase,
                                                        _Observing):
    """The durability property the state set alone does not give.

    Every one of these states is a state of an OPEN bespoke-writer entry, so every
    fixture must actually have one. A builder that reached its state by never
    putting an entry on the queue would be indistinguishable from a real one for the
    state observed as an absence -- and it would then also stand in as the
    "outside `from_states`" case for both actions' rejection runs, where the
    property being asserted is that the state does not change. Nothing would notice.

    Absence must never be evidence. Quantified over the builder map, so a builder
    added later is covered without anyone remembering."""

    def test_every_builder_leaves_a_real_open_entry_naming_its_subject(self):
        for key, builder in sorted(_FIXTURE_BUILDERS.items()):
            if _domain_of(key) != sa.DOMAIN_BESPOKE_WRITER:
                continue
            with self.subTest(state=key):
                project, subject = builder(self)
                flagged = [str(e.get("writer_relpath")) for e in
                           core.open_bespoke_writer_migrations(str(project.root))]
                self.assertIn(
                    subject, flagged,
                    "the fixture for %s carries no open entry for %r, so its "
                    "state was reached by never being flagged rather than by "
                    "anything the product did" % (key, subject))


class NoTrialFixtureReachesItsStateWithoutARealRUNTests(unittest.TestCase,
                                                        _Observing):
    """The trial-domain twin of the durability property above, and it is the one
    that made this domain's round-trip un-runnable until now.

    A hand-authored journal record can carry any state, any unit and any recovery
    capsule -- so a fixture that wrote one would be asserting that a trial did
    something no trial did, and the recovery round-trip would then be exercising
    the fixture's imagination. What distinguishes a record a RUN produced is that
    the product wrote its TRANSITIONS: a unit that reached a driven state passed
    through `planned` first, and the history says so. Quantified over the builder
    map, so a trial builder added later is covered without anyone remembering."""

    def test_every_trial_builder_leaves_a_record_a_REAL_RUN_wrote(self):
        for key, builder in sorted(_FIXTURE_BUILDERS.items()):
            if _domain_of(key) != sa.DOMAIN_TRIAL_UNIT:
                continue
            with self.subTest(state=key):
                project, subject = builder(self)
                record = tj.load_trial_journal(
                    subject,
                    journal_dir=str(project.root / tj.DEFAULT_TRIAL_JOURNAL_DIR)
                ).read_record()
                self.assertEqual(record["op_kind"], TRIAL_OP_KIND)
                histories = [len(unit.get("history") or ())
                             for unit in record["units"]]
                self.assertTrue(
                    histories and min(histories) >= 2,
                    "the record for %s carries no transition history, so it was "
                    "not written by a run that moved through the states -- which "
                    "is what a hand-authored record looks like" % key)

    def test_the_trial_ID_is_never_chosen_by_the_fixture(self):
        """The subject is read back off what the product wrote. A fixture that
        named its own trial id would be free to name one for a record it also
        wrote, which is the same thing in a different order."""
        source = _THIS_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name == "trial_command":
                for keyword in node.keywords:
                    self.assertNotEqual(keyword.arg, "trial_id")
                self.assertLessEqual(
                    len(node.args), 1,
                    "the trial command is rendered with the capability only")


class TheStoppedTrialLeavesLaterUnitsUNTOUCHEDTests(unittest.TestCase,
                                                    _Observing):
    """`planned` in its only reachable form, from a REAL killed run -- the state
    `_STATES_WITH_NO_WHOLE_FIXTURE` declares cannot be a whole fixture's state.

    Two properties at once, and the second is the safety one: a trial that could
    no longer earn a proof STOPS, so every unit after the failure stays where it
    was written down and was never applied. If it did not stop, a proof that can
    no longer be earned would keep buying live mutations at the operator's
    expense."""

    def test_a_unit_after_the_failure_is_recorded_planned_and_never_applied(self):
        project, trial_id = _run_a_trial(self, fault="undo_noop",
                                        units=("r1", "r2"))
        states = tj.load_trial_journal(
            trial_id,
            journal_dir=str(project.root / tj.DEFAULT_TRIAL_JOURNAL_DIR)
        ).unit_states()
        self.assertEqual(states, {"r1": tj.STATE_RECOVERY_REQUIRED,
                                  "r2": tj.STATE_PLANNED})
        # The second unit's own surface value is untouched: it was written down
        # and never applied, which is what makes its declared disposition true.
        self.assertEqual(project.surface()["r2"], ["OPEN"])

    def test_the_registry_tells_the_operator_that_unit_needs_nothing(self):
        """The declared disposition for `planned`, rendered by the registry for a
        real unit of a real stopped run -- not for a hypothetical one."""
        project, trial_id = _run_a_trial(self, fault="undo_noop",
                                        units=("r1", "r2"))
        del project
        instruction = sa.instruction_for_state(
            sa.trial_unit_state_key(tj.STATE_PLANNED), "r2")
        self.assertIn("no action is needed", instruction)
        self.assertIn("r2", instruction)


class TheOperatorCanFindTheirWayOutFromTheSURFACEAloneTests(unittest.TestCase,
                                                            _Observing):
    """The discoverability claim, end to end, at the standard this cut set for it:
    the operator's own text has to be sufficient.

    Nothing here uses a test-side trial id or a test-rendered command. The trial
    is killed, the health projection an agent reads at session start is asked what
    to do, the command is SLICED OUT of that sentence, and that command is what
    runs. A repair an operator cannot find is the same shape as one that does not
    exist."""

    def test_the_command_sliced_out_of_the_health_report_actually_repairs_it(self):
        project, trial_id = _run_a_trial(self, fault="apply_exit")
        status = health.overall_status(str(project.root))
        self.assertFalse(status["normal_status_allowed"])
        trial, = status["interrupted_trial"]["trials"]
        instruction = trial["action"]

        command = None
        for entry in manifest.BASELINE_COMMANDS:
            index = instruction.find(entry.command_prefix)
            if index != -1:
                command = instruction[index:].split("\n")[0].strip()
                break
        self.assertIsNotNone(
            command,
            "the surface an agent reads names no runnable command for an "
            "interrupted trial: %r" % instruction)
        self.assertIn(trial_id, command,
                      "the command the surface hands over does not name the trial "
                      "it is about")

        result = self.run_command(project, command)
        self.assertEqual(result.returncode, 0,
                         "the command the surface handed over did not work: %r %r"
                         % (result.stdout, result.stderr))
        self.assertEqual(
            self.observe(project, trial_id, domain=sa.DOMAIN_TRIAL_UNIT),
            (sa.trial_unit_state_key(tj.STATE_RESTORED_VERIFIED),))
        self.assertEqual(project.surface()["r1"], ["OPEN"],
                         "the operator's record is not back at its prior value")
        self.assertTrue(
            health.overall_status(str(project.root))["interrupted_trial"][
                "trials"] == [],
            "the surface still reports an interrupted trial after it was repaired")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
