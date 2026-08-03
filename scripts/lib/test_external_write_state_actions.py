"""The State->Action registry, the durable-state scan, and the acknowledgement
command's own entrypoint.

Why this file exists
--------------------
Two blocking states in this package had a real, working exit that NO surface an
operator or their assistant reads ever named. A mechanism nobody can discover is
not reachable, so "the command exists" is not the bar: someone sitting in the
state has to be able to find the way out WITHOUT already knowing to look.

Three separate discovery problems, and the third is measured rather than argued:

  1. The acknowledgement of an unrepairable writer -- the one sanctioned exit from
     `needs_person` -- had no command at all, only a Python function.
  2. The recovery of an interrupted trial -- the one exit from `recovery_required`
     -- had a command, but only the trial's own refusal printed it.
  3. Process-kill fault injection measured that at 100% of trial-side kill points
     the killed process emits ZERO bytes on stdout and stderr, including kills
     that leave a live, unreversed mutation on the operator's real record. So the
     refusal that names the recovery command is printed by code the kill prevented
     from running, and the trial id survives only as a filename in a directory
     nothing reads. Discovery therefore has to come from a scan of DURABLE STATE,
     and may never depend on a killed process having printed anything.

What this file asserts, in one line each
----------------------------------------
  * every state that BLOCKS has at least one declared action with a real
    entrypoint and a post-condition, and the completeness check is a real gate --
    it quantifies over the two upstream vocabularies' own declared blocking sets,
    not over the registry's own contents;
  * a state that is terminal by OMISSION fails; a terminal state passes only when
    it is explicitly marked as an intentional disposition;
  * the two state vocabularies are namespaced, so a name that happens to collide
    across them cannot silently share an action;
  * the durable scan finds an interrupted trial from the files alone, joins on the
    trial id DECLARED INSIDE the record rather than trusting the filename, and
    fails closed on anything it cannot read;
  * the acknowledgement command exists, runs, and REFUSES exactly as it did before
    it was named -- naming it made it reachable, not cheaper.

Run:
  python3 -m unittest discover -s wizard/scripts/lib \\
      -p test_external_write_state_actions.py
"""

import ast
import json
import os
import re
import shlex
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

from external_write import scan                                # noqa: E402
from external_write import state_actions as sa                  # noqa: E402
from external_write import trial_journal as tj                  # noqa: E402
from external_write import trial_recovery as trc                # noqa: E402
from external_write import writer_acknowledgement as ack        # noqa: E402
from external_write import writer_ack_store as store            # noqa: E402
from external_write import writer_state_core as core            # noqa: E402
from external_write import zones                                # noqa: E402

MODULE = "state_actions.py"
QUEUE_REL = "agents/handoffs/pending_migrations.json"
WRITER = "agents/upkeep/runner.py"
CONFIRMATION = "Yes -- I know this one needs a person and I accept the risk."

_UNREPAIRABLE_SRC = '''"""Daily upkeep -- also delivers the operator's phone alert."""
import urllib.request
'''

_REBUILDABLE_SRC = '''"""A hand-rolled per-chunk bulk write loop."""
from external_write.adapters_thing import build_read_only_client
'''


def _entry_with_kinds(relpath, kinds):
    return {
        "mechanism_id": relpath.replace("/", "_").replace(".py", ""),
        "writer_relpath": relpath,
        "status": "pending",
        "paused_content_sha256": "0" * 64,
        "violations": [{"kind": k, "line": 2, "path": relpath} for k in kinds],
    }


class _Project:
    """A real project fixture at the real emitted relative paths."""

    def __init__(self, case):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, relpath, text):
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def queue(self, entries):
        self.write(QUEUE_REL, json.dumps(entries, indent=2))

    def journal_dir(self):
        return str(self.root / tj.DEFAULT_TRIAL_JOURNAL_DIR)

    def put_journal(self, trial_id, unit_states, *, op_kind="fixture.op",
                    declared_trial_id=None, raw=None):
        """Write a journal record straight to disk -- BYTES, not through the
        module that writes them, because the scan's whole job is to read what a
        killed process left behind."""
        d = self.root / tj.DEFAULT_TRIAL_JOURNAL_DIR
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{trial_id}.json"
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
            return path
        record = {
            "schema": tj.TRIAL_JOURNAL_SCHEMA,
            "trial_id": (declared_trial_id if declared_trial_id is not None
                         else trial_id),
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


def _module_ast():
    return ast.parse((_EXTERNAL_WRITE_DIR / MODULE).read_text(encoding="utf-8"))


# ===========================================================================
# 1. THE REGISTRY IS SEALED -- closed to operator and agent authorship
# ===========================================================================

class TheRegistryIsSealedTests(unittest.TestCase):
    """`SEALED_KERNEL`, and sealed means sealed: not operator-extensible and not
    agent-extensible. A registry that could be extended from disk would be a new
    trust surface, and the thing it would grant is the authority to tell an
    operator what to run."""

    def test_the_action_set_is_an_immutable_tuple(self):
        self.assertIsInstance(sa.ACTIONS, tuple)
        self.assertTrue(sa.ACTIONS)

    def test_every_action_record_is_frozen(self):
        for action in sa.ACTIONS:
            with self.subTest(action=action.action_id):
                with self.assertRaises(Exception):
                    action.actor = "somebody else"

    def test_the_declared_sets_are_immutable(self):
        self.assertIsInstance(sa.DECLARED_STATE_KEYS, frozenset)
        self.assertIsInstance(sa.GATED_STATE_KEYS, frozenset)
        with self.assertRaises(TypeError):
            sa.INTENTIONAL_DISPOSITIONS["anything"] = "anything"

    def test_the_module_exposes_no_way_to_add_an_action(self):
        """AST, not a text search: a function that mutates the registry is the
        whole difference between a sealed kernel and a trust surface."""
        names = {node.name for node in _module_ast().body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in sorted(names):
            with self.subTest(function=name):
                self.assertFalse(
                    name.startswith(("register", "add_", "extend", "install",
                                     "put_", "set_", "load_")),
                    f"{name!r} looks like a way to extend the registry")

    def test_the_module_reads_no_file_and_no_environment_variable(self):
        """The registry cannot be extended from disk or from the environment.
        Asserted structurally over the module's own source, because "we would
        never do that" is not a property."""
        tree = _module_ast()
        banned_calls = {"open", "eval", "exec", "compile", "__import__"}
        banned_attrs = {"environ", "getenv", "import_module", "loads", "load"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, banned_calls,
                                     "the registry must read nothing at runtime")
                if isinstance(node.func, ast.Attribute):
                    self.assertNotIn(
                        node.func.attr, banned_attrs,
                        "the registry must read nothing at runtime")
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"environ", "getenv"})

    def test_the_action_set_is_assigned_exactly_once_at_module_scope(self):
        assignments = 0
        for node in ast.walk(_module_ast()):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "ACTIONS":
                        assignments += 1
            if isinstance(node, ast.AnnAssign):
                if (isinstance(node.target, ast.Name)
                        and node.target.id == "ACTIONS"):
                    assignments += 1
        self.assertEqual(assignments, 1)


# ===========================================================================
# 2. THE COMPLETENESS GATE -- and it is a gate, not a tautology
# ===========================================================================

class EveryBlockingStateHasAWayOutTests(unittest.TestCase):
    """The gate quantifies over the two upstream vocabularies' OWN declared
    blocking sets (`writer_state_core.BLOCKING_WRITER_STATES` and
    `trial_journal.RECOVERY_DRIVEN_STATES`), never over the registry's contents.
    Derived from the actions it is checking, this assertion would be a tautology
    and a deleted action would pass it."""

    def test_the_gated_set_is_the_upstream_blocking_sets_and_nothing_else(self):
        expected = frozenset(
            [sa.writer_state_key(s) for s in core.BLOCKING_WRITER_STATES]
            + [sa.trial_unit_state_key(s) for s in tj.RECOVERY_DRIVEN_STATES])
        self.assertEqual(sa.GATED_STATE_KEYS, expected)

    def test_every_gated_state_has_at_least_one_action(self):
        self.assertEqual(sa.unactionable_gated_state_keys(), ())
        for key in sorted(sa.GATED_STATE_KEYS):
            with self.subTest(state=key):
                self.assertTrue(sa.actions_for_state(key))

    def test_no_declared_state_is_left_unclassified(self):
        """A state that is terminal by OMISSION is the bug. Every state in either
        vocabulary must be gated, or explicitly marked an intentional
        disposition -- being in neither is what this fails on."""
        self.assertEqual(sa.unclassified_state_keys(), ())

    def test_no_state_is_both_gated_and_declared_terminal(self):
        self.assertEqual(sa.doubly_classified_state_keys(), ())

    def test_no_action_lands_the_operator_in_a_dead_end(self):
        """An action's `expected_state` must itself either have an action or be a
        declared intentional disposition. An exit into a state with no exit is
        how this cut would open a third dead end while closing two."""
        self.assertEqual(sa.actions_landing_in_a_dead_end(), ())

    def test_every_action_declares_a_blocking_from_state(self):
        for action in sa.ACTIONS:
            for key in action.from_states:
                with self.subTest(action=action.action_id, state=key):
                    self.assertIn(key, sa.GATED_STATE_KEYS)

    def test_the_declared_vocabulary_covers_both_upstream_sources(self):
        """Derived from the declaring modules, so a state added to either one
        appears here (and then fails the classification test above) rather than
        being invisible."""
        writer = {sa.writer_state_key(v) for k, v in vars(core.WriterState).items()
                  if not k.startswith("_") and isinstance(v, str)}
        trial = {sa.trial_unit_state_key(s) for s in tj.TRIAL_UNIT_STATES}
        self.assertEqual(sa.DECLARED_STATE_KEYS, frozenset(writer | trial))

    def test_every_action_declares_all_six_fields_usefully(self):
        for action in sa.ACTIONS:
            with self.subTest(action=action.action_id):
                self.assertTrue(action.action_id.strip())
                self.assertTrue(action.from_states)
                self.assertIn(action.actor, sa.ACTORS)
                self.assertTrue(callable(action.command_builder))
                self.assertTrue(action.precondition.strip())
                self.assertIn(action.expected_state, sa.DECLARED_STATE_KEYS)

    def test_action_ids_are_unique(self):
        ids = [a.action_id for a in sa.ACTIONS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_action_names_an_entrypoint_that_ACTUALLY_EXISTS(self):
        """"Declared action with an executable entrypoint" -- checked by resolving
        the rendered command's script path against the shipped tree. A declared
        repair naming a file nobody ships is the failure this cut is closing, not a
        typo class."""
        for action in sa.ACTIONS:
            with self.subTest(action=action.action_id):
                argv = shlex.split(action.command_builder("some-subject"))
                self.assertEqual(argv[0], "python3", argv)
                script = _WIZARD / argv[1]
                self.assertTrue(script.is_file(),
                                f"{action.action_id} names {argv[1]}, which is "
                                "not a file this project ships")
                self.assertEqual(len(action.command_builder(
                    "some-subject").splitlines()), 1,
                    "a command that wraps is a paste hazard")


# ===========================================================================
# 3. NAMESPACING -- identity by declared domain, never by a bare state string
# ===========================================================================

class StateKeysAreNamespacedTests(unittest.TestCase):

    def test_the_two_vocabularies_are_disjoint_as_keys(self):
        writer = {sa.writer_state_key(v) for k, v in vars(core.WriterState).items()
                  if not k.startswith("_") and isinstance(v, str)}
        trial = {sa.trial_unit_state_key(s) for s in tj.TRIAL_UNIT_STATES}
        self.assertEqual(writer & trial, set())

    def test_a_bare_state_string_is_not_a_usable_key(self):
        """A raw `"needs_person"` must not resolve. Two vocabularies do not
        collide today; joining on the bare string is how they would."""
        with self.assertRaises(sa.StateActionError):
            sa.actions_for_state(core.WriterState.NEEDS_PERSON)
        with self.assertRaises(sa.StateActionError):
            sa.actions_for_state(tj.STATE_RECOVERY_REQUIRED)

    def test_an_unknown_domain_refuses(self):
        with self.assertRaises(sa.StateActionError):
            sa.state_key("some_other_domain", "needs_person")

    def test_an_unknown_key_refuses_rather_than_returning_nothing_to_do(self):
        with self.assertRaises(sa.StateActionError):
            sa.actions_for_state(sa.state_key(sa.DOMAIN_TRIAL_UNIT, "invented"))


# ===========================================================================
# 4. `recovery_required` IS FIRST CLASS, and the command is the shipped one
# ===========================================================================

class RecoveryRequiredIsFirstClassTests(unittest.TestCase):

    def setUp(self):
        self.key = sa.trial_unit_state_key(tj.STATE_RECOVERY_REQUIRED)

    def test_it_is_a_gated_state_with_an_action(self):
        self.assertIn(self.key, sa.GATED_STATE_KEYS)
        self.assertTrue(sa.actions_for_state(self.key))

    def test_its_action_renders_the_shipped_recovery_command(self):
        action, = sa.actions_for_state(self.key)
        self.assertEqual(action.command_builder("t-42"),
                         trc.recovery_command("t-42"))

    def test_every_recovery_driven_state_reaches_the_same_action(self):
        for state in tj.RECOVERY_DRIVEN_STATES:
            with self.subTest(state=state):
                actions = sa.actions_for_state(sa.trial_unit_state_key(state))
                self.assertEqual([a.action_id for a in actions],
                                 ["recover_interrupted_trial"])

    def test_its_post_condition_is_the_settled_state(self):
        action, = sa.actions_for_state(self.key)
        self.assertEqual(action.expected_state,
                         sa.trial_unit_state_key(tj.STATE_RESTORED_VERIFIED))

    def test_the_rendered_instruction_carries_the_command_verbatim(self):
        text = sa.instruction_for_state(self.key, "t-42")
        self.assertIn(trc.recovery_command("t-42"), text)
        self.assertNotIn("{command}", text)
        self.assertNotIn("{subject}", text)


# ===========================================================================
# 5. THE ACKNOWLEDGEMENT ACTION, and the command it names
# ===========================================================================

class TheAcknowledgementActionTests(unittest.TestCase):

    def setUp(self):
        self.key = sa.writer_state_key(core.WriterState.NEEDS_PERSON)

    def test_needs_person_has_the_acknowledgement_action(self):
        action, = sa.actions_for_state(self.key)
        self.assertEqual(action.action_id, "record_accepted_risk")
        self.assertEqual(action.actor, sa.ACTOR_OPERATOR)
        self.assertEqual(
            action.expected_state,
            sa.writer_state_key(core.WriterState.ACKNOWLEDGED_RISK))

    def test_the_rendered_command_is_the_modules_own(self):
        action, = sa.actions_for_state(self.key)
        self.assertEqual(action.command_builder(WRITER),
                         ack.acknowledgement_command(WRITER))

    def test_the_instruction_names_the_command_and_the_file(self):
        text = sa.instruction_for_state(self.key, WRITER)
        self.assertIn(ack.acknowledgement_command(WRITER), text)
        self.assertIn(WRITER, text)
        self.assertIn("cannot be fixed automatically and needs a person", text)

    def test_the_rebuildable_state_keeps_the_sentence_it_has_always_had(self):
        text = sa.instruction_for_state(
            sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE), WRITER)
        self.assertIn(
            f"an external-write bypass is unrepaired: `{WRITER}` -- rebuild it "
            "so it routes through the sanctioned bulk path", text)
        self.assertIn(scan.scan_command(WRITER), text)

    def test_that_sentence_has_exactly_one_home_in_the_package(self):
        """It used to be spelled in two modules. The registry binds the core's
        template; it does not re-spell it."""
        needle = "an external-write bypass is unrepaired"
        homes = sorted(p.name for p in _EXTERNAL_WRITE_DIR.glob("*.py")
                       if not p.name.startswith("test_")
                       and needle in p.read_text(encoding="utf-8"))
        self.assertEqual(homes, ["writer_state_core.py"], homes)

    def test_an_intentional_disposition_says_no_action_is_needed(self):
        for state in (core.WriterState.NON_LIVE, core.WriterState.RESOLVED,
                      core.WriterState.ACKNOWLEDGED_RISK):
            with self.subTest(state=state):
                text = sa.instruction_for_state(sa.writer_state_key(state),
                                                WRITER)
                self.assertIn("no action is needed", text)
                self.assertIn(WRITER, text)


class TheUnclassifiedRouteIsNotADeadEndTests(unittest.TestCase):
    """The branch a state added later would land on. Exercised directly, because
    a never-exercised fallback is a latent failure -- and this one is the only
    thing standing between a new state and an operator with nothing to do."""

    def test_a_state_nobody_classified_still_routes_to_a_person(self):
        text = sa.instruction_for_state(
            sa.state_key(sa.DOMAIN_TRIAL_UNIT, "invented_later"), "t-9")
        self.assertIn("ask your assistant", text.lower())
        self.assertIn("t-9", text)
        self.assertNotIn("no action is needed", text.lower())

    def test_a_DECLARED_state_with_no_handling_routes_to_a_person_too(self):
        """The other way into the same branch, driven separately: a state the
        registry DOES declare but neither actions nor dispositions. Mutation-proved
        by adding a state upstream, but the branch itself deserves its own test
        rather than sharing the undeclared-key one -- a fail-closed fallback nothing
        exercises is a latent failure, and this one is all that stands between a new
        state and an operator with nothing to do."""
        key = sa.state_key(sa.DOMAIN_TRIAL_UNIT, "declared_but_unhandled")
        original = sa.DECLARED_STATE_KEYS
        try:
            sa.DECLARED_STATE_KEYS = frozenset(original | {key})
            text = sa.instruction_for_state(key, "t-9")
        finally:
            sa.DECLARED_STATE_KEYS = original
        self.assertIn("ask your assistant", text.lower())
        self.assertNotIn("no action is needed", text.lower())

    def test_an_unreadable_record_routes_to_a_person_and_claims_nothing(self):
        text = sa.route_for_unidentified_record("security/trial_runs/x.json")
        self.assertIn("ask your assistant", text.lower())
        self.assertIn("security/trial_runs/x.json", text)
        self.assertNotIn("nothing is outstanding", text.lower())


# ===========================================================================
# 6. THE DURABLE-STATE SCAN -- what a killed process leaves behind
# ===========================================================================

class TheDurableScanTests(unittest.TestCase):
    """Reads the files a killed process left, never a stream it never wrote."""

    def setUp(self):
        self.p = _Project(self)

    def scan(self):
        return tj.scan_outstanding_trials(journal_dir=self.p.journal_dir())

    def test_an_absent_directory_is_not_an_outstanding_trial(self):
        """The fresh-project case, and it must NEVER fire: a check that fires on
        100% of deployments is the trap this package has corrected three times."""
        result = self.scan()
        self.assertEqual(result["trials"], [])
        self.assertEqual(result["unreadable"], [])
        self.assertIsNone(result["scan_error"])

    def test_an_empty_directory_is_not_an_outstanding_trial(self):
        (self.p.root / tj.DEFAULT_TRIAL_JOURNAL_DIR).mkdir(parents=True)
        self.assertEqual(self.scan()["trials"], [])

    def test_a_unit_in_each_driven_state_is_outstanding(self):
        for state in tj.RECOVERY_DRIVEN_STATES:
            with self.subTest(state=state):
                p = _Project(self)
                p.put_journal("t-1", {"r1": state})
                result = tj.scan_outstanding_trials(journal_dir=p.journal_dir())
                self.assertEqual(len(result["trials"]), 1, result)
                self.assertEqual(result["trials"][0]["trial_id"], "t-1")
                self.assertEqual(result["trials"][0]["outstanding_unit_ids"],
                                 ["r1"])
                self.assertEqual(result["trials"][0]["unit_states"],
                                 {"r1": state})

    def test_a_settled_trial_is_not_outstanding(self):
        self.p.put_journal("t-1", {"r1": tj.STATE_RESTORED_VERIFIED})
        self.assertEqual(self.scan()["trials"], [])

    def test_a_never_applied_unit_is_not_outstanding(self):
        self.p.put_journal("t-1", {"r1": tj.STATE_PLANNED})
        self.assertEqual(self.scan()["trials"], [])

    def test_a_mixed_trial_reports_only_the_outstanding_units(self):
        self.p.put_journal("t-1", {"a": tj.STATE_RESTORED_VERIFIED,
                                   "b": tj.STATE_APPLY_CONFIRMED,
                                   "c": tj.STATE_PLANNED})
        trial, = self.scan()["trials"]
        self.assertEqual(trial["outstanding_unit_ids"], ["b"])

    def test_a_malformed_record_is_reported_not_skipped(self):
        self.p.put_journal("t-1", {}, raw="{not json")
        result = self.scan()
        self.assertEqual(result["trials"], [])
        self.assertEqual(len(result["unreadable"]), 1, result)
        self.assertIn("t-1.json", result["unreadable"][0]["path"])
        self.assertTrue(result["unreadable"][0]["reason"])

    def test_a_record_whose_declared_id_disagrees_with_its_filename_is_refused(self):
        """The filename is a CANDIDATE, never the identity. Joining on the
        declared value is the rule; a disagreement is reported, never resolved by
        picking one."""
        self.p.put_journal("t-1", {"r1": tj.STATE_APPLY_INTENT},
                           declared_trial_id="t-2")
        result = self.scan()
        self.assertEqual(result["trials"], [])
        self.assertEqual(len(result["unreadable"]), 1, result)

    def test_a_temp_file_and_a_lock_file_are_not_trials(self):
        d = self.p.root / tj.DEFAULT_TRIAL_JOURNAL_DIR
        d.mkdir(parents=True)
        (d / ".trial_journal.abcd.json").write_text("{}", encoding="utf-8")
        (d / "t-1.json.lock").write_text("", encoding="utf-8")
        result = self.scan()
        self.assertEqual(result["trials"], [])
        self.assertEqual(result["unreadable"], [])

    def test_an_inaccessible_directory_fails_closed(self):
        d = self.p.root / tj.DEFAULT_TRIAL_JOURNAL_DIR
        d.mkdir(parents=True)
        self.p.put_journal("t-1", {"r1": tj.STATE_APPLY_INTENT})
        os.chmod(d, 0o000)
        self.addCleanup(os.chmod, d, 0o755)
        result = self.scan()
        self.assertIsNotNone(
            result["scan_error"],
            "an unreadable directory must never read as 'no trials'")

    def test_the_result_is_json_serializable_for_real(self):
        self.p.put_journal("t-1", {"r1": tj.STATE_UNDO_INTENT})
        round_tripped = json.loads(json.dumps(self.scan()))
        self.assertEqual(round_tripped["trials"][0]["trial_id"], "t-1")

    def test_trials_come_back_in_a_stable_order(self):
        self.p.put_journal("t-b", {"r1": tj.STATE_APPLY_INTENT})
        self.p.put_journal("t-a", {"r1": tj.STATE_APPLY_INTENT})
        self.assertEqual([t["trial_id"] for t in self.scan()["trials"]],
                         ["t-a", "t-b"])

    def test_the_scan_writes_nothing(self):
        """A read-only observer. A self-healing read path is a WRITE path, and
        this one runs against a record a crash left behind."""
        self.p.put_journal("t-1", {"r1": tj.STATE_APPLY_INTENT})
        d = self.p.root / tj.DEFAULT_TRIAL_JOURNAL_DIR
        before = {p.name: p.read_bytes() for p in d.iterdir()}
        self.scan()
        after = {p.name: p.read_bytes() for p in d.iterdir()}
        self.assertEqual(before, after)


class AStateNobodyClassifiedIsOutstandingTests(unittest.TestCase):
    """`outstanding_unit_ids` is exercised directly with a state the disposition
    map does not carry. The validated read path cannot produce one today, which
    is exactly why the branch needs its own test rather than a comment."""

    def test_an_unclassified_state_counts_as_outstanding(self):
        record = {"units": [{"unit_id": "r1", "state": "invented_later"}]}
        self.assertEqual(tj.outstanding_unit_ids(record), ("r1",))

    def test_a_driven_state_counts_as_outstanding(self):
        record = {"units": [{"unit_id": "r1", "state": tj.STATE_UNDO_INTENT}]}
        self.assertEqual(tj.outstanding_unit_ids(record), ("r1",))

    def test_a_settled_state_does_not(self):
        record = {"units": [{"unit_id": "r1",
                             "state": tj.STATE_RESTORED_VERIFIED}]}
        self.assertEqual(tj.outstanding_unit_ids(record), ())


# ===========================================================================
# 7. THE ACKNOWLEDGEMENT COMMAND ITSELF
# ===========================================================================

class TheAcknowledgementCommandTests(unittest.TestCase):

    def test_it_is_a_single_physical_line(self):
        command = ack.acknowledgement_command(WRITER)
        self.assertEqual(len(command.splitlines()), 1)
        self.assertNotIn("\r", command)

    def test_it_names_the_entrypoint_the_operator_actually_runs(self):
        command = ack.acknowledgement_command(WRITER)
        self.assertTrue(
            command.startswith(f"python3 {ack.ACKNOWLEDGEMENT_ENTRYPOINT_REL}"),
            command)
        self.assertEqual(Path(ack.ACKNOWLEDGEMENT_ENTRYPOINT_REL).name,
                         "writer_acknowledgement.py")
        self.assertTrue(
            (_WIZARD / ack.ACKNOWLEDGEMENT_ENTRYPOINT_REL).is_file(),
            "the rendered command must point at a file that exists")

    def test_a_path_with_a_space_is_quoted(self):
        command = ack.acknowledgement_command("agents/my writer.py")
        self.assertIn(shlex.quote("agents/my writer.py"), command)
        self.assertEqual(len(command.splitlines()), 1)

    def test_a_confirmation_with_a_newline_refuses_rather_than_wrapping(self):
        with self.assertRaises(ValueError):
            ack.acknowledgement_command(WRITER,
                                        operator_confirmation="yes\nplease")

    def test_the_placeholder_form_leaves_the_operators_words_to_the_operator(self):
        command = ack.acknowledgement_command(WRITER)
        self.assertIn("--operator-confirmation", command)
        self.assertIn("<", command)

    def test_the_rendered_command_parses_back_through_the_real_parser(self):
        argv = shlex.split(ack.acknowledgement_command(
            WRITER, operator_confirmation=CONFIRMATION))
        options, error = ack.parse_acknowledgement_args(argv[2:])
        self.assertIsNone(error, error)
        self.assertEqual(options[ack.FLAG_WRITER], WRITER)
        self.assertEqual(options[ack.FLAG_CONFIRMATION], CONFIRMATION)


class TheAcknowledgementArgParserDeniesByDefaultTests(unittest.TestCase):

    def test_an_unrecognized_flag_refuses(self):
        options, error = ack.parse_acknowledgement_args(["--force"])
        self.assertIsNone(options)
        self.assertIn("--force", error)

    def test_a_flag_with_no_value_refuses(self):
        options, error = ack.parse_acknowledgement_args([ack.FLAG_WRITER])
        self.assertIsNone(options)

    def test_a_missing_writer_refuses(self):
        options, error = ack.parse_acknowledgement_args(
            [ack.FLAG_CONFIRMATION, CONFIRMATION])
        self.assertIsNone(options)
        self.assertIn(ack.FLAG_WRITER, error)

    def test_a_missing_confirmation_refuses(self):
        options, error = ack.parse_acknowledgement_args(
            [ack.FLAG_WRITER, WRITER])
        self.assertIsNone(options)
        self.assertIn(ack.FLAG_CONFIRMATION, error)

    def test_a_blank_confirmation_refuses(self):
        options, error = ack.parse_acknowledgement_args(
            [ack.FLAG_WRITER, WRITER, ack.FLAG_CONFIRMATION, "   "])
        self.assertIsNone(options)


@unittest.skipUnless(Path(sys.executable).exists(), "no interpreter")
class TheAcknowledgementCommandActuallyRunsTests(unittest.TestCase):
    """The command is run as a real subprocess, from a project root, exactly as
    rendered. A command nothing ever executed is a command nobody has evidence
    works -- and this one is the exit from a blocking state."""

    def setUp(self):
        self.p = _Project(self)
        lib = self.p.root / "agents" / "lib" / "external_write"
        lib.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copytree(_EXTERNAL_WRITE_DIR, lib,
                        ignore=shutil.ignore_patterns("test_*.py",
                                                      "__pycache__"))
        (lib / "__init__.py").touch(exist_ok=True)
        (self.p.root / "agents" / "lib" / "__init__.py").touch(exist_ok=True)

    def _run(self, command):
        argv = shlex.split(command)
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable] + argv[1:], capture_output=True,
                              text=True, cwd=str(self.p.root), env=env,
                              timeout=120)

    def test_an_eligible_writer_is_acknowledged_by_the_rendered_command(self):
        self.p.write(WRITER, _UNREPAIRABLE_SRC)
        self.p.queue([_entry_with_kinds(WRITER, ["forbidden_import"])])

        result = self._run(ack.acknowledgement_command(
            WRITER, operator_confirmation=CONFIRMATION))

        self.assertEqual(result.returncode, 0,
                         f"{result.stdout!r} {result.stderr!r}")
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        active = store.active_acknowledgements(str(self.p.root))
        self.assertIn(WRITER, active)
        self.assertEqual(active[WRITER]["operator_confirmation"], CONFIRMATION)

    def test_the_same_command_REFUSES_a_rebuildable_writer(self):
        """Naming the route made it reachable, not cheaper. The eligibility guard
        is on the path the operator now has, not only on the Python function."""
        self.p.write(WRITER, _REBUILDABLE_SRC)
        self.p.queue([_entry_with_kinds(WRITER, ["adapter_module_import"])])

        result = self._run(ack.acknowledgement_command(
            WRITER, operator_confirmation=CONFIRMATION))

        self.assertEqual(result.returncode, 1,
                         f"{result.stdout!r} {result.stderr!r}")
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual(store.active_acknowledgements(str(self.p.root)), {})

    def test_a_writer_nothing_flagged_is_refused(self):
        self.p.write(WRITER, _UNREPAIRABLE_SRC)
        self.p.queue([])
        result = self._run(ack.acknowledgement_command(
            WRITER, operator_confirmation=CONFIRMATION))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(store.active_acknowledgements(str(self.p.root)), {})

    def test_the_entrypoint_goes_through_the_GUARDED_command_structurally(self):
        """AST over the entrypoint's own `__main__`: it must call the guarded
        command, and must never reach the store's write primitive directly. The
        behavioural half is the refusal above; this is the structural half, because
        "it happens to refuse today" and "it cannot record without the guard" are
        different properties."""
        tree = ast.parse((_EXTERNAL_WRITE_DIR / "writer_acknowledgement.py")
                         .read_text(encoding="utf-8"))
        main = [n for n in tree.body
                if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                and isinstance(n.test.left, ast.Name)
                and n.test.left.id == "__name__"]
        self.assertEqual(len(main), 1)
        called = {n.func.id for n in ast.walk(main[0])
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("acknowledge_writer", called)
        self.assertNotIn("put_acknowledgement_record", called,
                         "the entrypoint must never reach the write primitive "
                         "around the eligibility guard")

    def test_a_usage_error_exits_two_and_prints_the_usage(self):
        result = self._run(
            f"python3 {ack.ACKNOWLEDGEMENT_ENTRYPOINT_REL} --force yes")
        self.assertEqual(result.returncode, 2)
        self.assertIn(ack.FLAG_WRITER, result.stdout + result.stderr)


# ===========================================================================
# 8. ZONE MEMBERSHIP -- load-bearing, both directions
# ===========================================================================

class SealedKernelZoneMembershipTests(unittest.TestCase):

    def test_the_module_is_enrolled_as_sealed_kernel(self):
        self.assertIn(MODULE, zones.SEALED_KERNEL_MODULE_PATHS)

    def test_membership_is_load_bearing_and_not_decorative(self):
        """Scanned as CAPABILITY the module trips the sealed-kernel module
        boundary; scanned as SEALED_KERNEL it is clean. The KIND SET is the
        durable fact -- a count would go stale on an added annotation."""
        path = _EXTERNAL_WRITE_DIR / MODULE
        violations = scan.scan_paths([str(path)])
        self.assertEqual(violations, [], [str(v) for v in violations])

        without = frozenset(p for p in zones.SEALED_KERNEL_MODULE_PATHS
                            if p != MODULE)
        kinds = {v.kind for v in scan.scan_paths(
            [str(path)], allowed_root=str(_EXTERNAL_WRITE_DIR),
            sealed_kernel_paths=without)}
        self.assertTrue(kinds, "the membership must trip something")
        self.assertIn("sealed_kernel_import", kinds)

    def test_capability_zone_code_may_not_import_the_registry(self):
        self.assertNotIn(
            "state_actions", scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES,
            "the registry is what tells an operator what to run; a capability "
            "has no business authoring or reading that")

    def test_the_module_is_enrolled_in_the_emitted_lib_file_set(self):
        import agent_emitter
        self.assertIn(MODULE, agent_emitter._EXTERNAL_WRITE_LIB_FILES)


# ===========================================================================
# 9. THE ACCEPTANCE REFUSAL -- the surface that ADVERTISES the route
# ===========================================================================

class TheAcceptanceRefusalBindsTheEligibilityConstantTests(unittest.TestCase):
    """`operator_acceptance` split the blocking set for wording with an
    `else`-catch-all, and only one side of that split was ever told about the
    accept-the-risk route. It is the very surface that advertises that route, so a
    state added later would land on the permissive side -- told to "rebuild it" --
    by nobody having thought about it. It must bind the ONE eligibility constant.
    """

    def setUp(self):
        from external_write import operator_acceptance as oa
        self.source = (_EXTERNAL_WRITE_DIR
                       / "operator_acceptance.py").read_text(encoding="utf-8")
        self.oa = oa

    def test_the_refusal_path_binds_the_eligibility_constant_by_name(self):
        self.assertIn("ACKNOWLEDGEABLE_WRITER_STATES", self.source,
                      "the advertising surface must bind the same constant the "
                      "guard binds, not re-decide the question")

    def test_the_constant_has_exactly_one_declaration_in_the_package(self):
        declaring = sorted(
            p.name for p in _EXTERNAL_WRITE_DIR.glob("*.py")
            if not p.name.startswith("test_")
            and "ACKNOWLEDGEABLE_WRITER_STATES = " in p.read_text(encoding="utf-8"))
        self.assertEqual(declaring, ["writer_state_core.py"], declaring)

    def test_the_refusal_split_has_no_permissive_else_catch_all(self):
        """AST, because this is a question about code structure. The three-way
        classification must dispatch on positive membership; the branch a state
        nobody classified reaches must not be the one that names a repair."""
        tree = ast.parse(self.source)
        target = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "record_operator_acceptance"):
                target = node
        self.assertIsNotNone(target)
        found = False
        for node in ast.walk(target):
            if isinstance(node, ast.Compare) and any(
                    isinstance(op, ast.In) for op in node.ops):
                for comparator in node.comparators:
                    text = ast.dump(comparator)
                    if "ACKNOWLEDGEABLE_WRITER_STATES" in text:
                        found = True
        self.assertTrue(
            found,
            "the refusal must classify by POSITIVE membership in "
            "ACKNOWLEDGEABLE_WRITER_STATES")


# ===========================================================================
# 10. THE HEALTH SURFACE -- discovery from durable state
# ===========================================================================

class TheHealthSurfaceDiscoversAnInterruptedTrialTests(unittest.TestCase):
    """The third discovery obligation. A killed trial prints nothing at all, so
    the only thing left is the file it wrote -- and the health surface is what an
    agent reads at session start."""

    def setUp(self):
        from external_write import capability_health as ch
        self.ch = ch
        self.p = _Project(self)

    def status(self):
        return self.ch.overall_status(str(self.p.root))

    def test_a_project_with_no_trials_is_unaffected(self):
        status = self.status()
        self.assertFalse(status["interrupted_trial"]["outstanding"])
        self.assertEqual(status["interrupted_trial"]["trials"], [])
        self.assertTrue(status["normal_status_allowed"], status)

    def test_an_interrupted_trial_withholds_the_all_clear(self):
        self.p.put_journal("t-77", {"r1": tj.STATE_APPLY_CONFIRMED})
        status = self.status()
        self.assertTrue(status["interrupted_trial"]["outstanding"])
        self.assertFalse(
            status["normal_status_allowed"],
            "a unit that may still be changed on the operator's real record must "
            "never read as everything running normally")
        self.assertEqual(status["overall"], "red")

    def test_the_action_is_rendered_from_the_registry_with_the_real_trial_id(self):
        self.p.put_journal("t-77", {"r1": tj.STATE_UNDO_INTENT})
        trial, = self.status()["interrupted_trial"]["trials"]
        self.assertEqual(trial["trial_id"], "t-77")
        self.assertEqual(trial["outstanding_unit_ids"], ["r1"])
        self.assertIn(trc.recovery_command("t-77"), trial["action"])
        self.assertEqual(
            trial["action"],
            sa.instruction_for_state(
                sa.trial_unit_state_key(tj.STATE_UNDO_INTENT), "t-77"))

    def test_an_unreadable_record_is_surfaced_with_a_route_not_dropped(self):
        self.p.put_journal("t-77", {}, raw="{ not json")
        block = self.status()["interrupted_trial"]
        self.assertTrue(block["outstanding"])
        self.assertEqual(len(block["unreadable"]), 1, block)
        self.assertIn("ask your assistant",
                      block["unreadable"][0]["action"].lower())
        self.assertFalse(self.status()["normal_status_allowed"])

    def test_a_settled_trial_does_not_withhold_the_all_clear(self):
        self.p.put_journal("t-77", {"r1": tj.STATE_RESTORED_VERIFIED})
        status = self.status()
        self.assertFalse(status["interrupted_trial"]["outstanding"])
        self.assertTrue(status["normal_status_allowed"], status)

    def test_the_whole_status_object_survives_a_real_json_round_trip(self):
        self.p.put_journal("t-77", {"r1": tj.STATE_APPLY_INTENT})
        round_tripped = json.loads(json.dumps(self.status()))
        self.assertTrue(round_tripped["interrupted_trial"]["outstanding"])


class TheHealthSurfaceNamesTheWriterActionTests(unittest.TestCase):

    def setUp(self):
        from external_write import capability_health as ch
        self.ch = ch
        self.p = _Project(self)

    def test_a_needs_person_writer_gets_the_registrys_instruction(self):
        self.p.write(WRITER, _UNREPAIRABLE_SRC)
        self.p.queue([_entry_with_kinds(WRITER, ["forbidden_import"])])
        block = self.ch.overall_status(str(self.p.root))["open_external_write_bypass"]
        self.assertEqual(block["writer_states"][WRITER],
                         core.WriterState.NEEDS_PERSON)
        self.assertIn(ack.acknowledgement_command(WRITER),
                      block["actions"][WRITER])
        self.assertEqual(
            block["actions"][WRITER],
            sa.instruction_for_state(
                sa.writer_state_key(core.WriterState.NEEDS_PERSON), WRITER))

    def test_a_rebuildable_writer_gets_the_confirming_check(self):
        self.p.write(WRITER, _REBUILDABLE_SRC)
        self.p.queue([_entry_with_kinds(WRITER, ["adapter_module_import"])])
        block = self.ch.overall_status(str(self.p.root))["open_external_write_bypass"]
        self.assertIn(scan.scan_command(WRITER), block["actions"][WRITER])


class TheHealthCliAcceptsOverallAnywhereTests(unittest.TestCase):
    """`--overall` used to be recognized only as the FIRST argument, so the
    invocation the rebuild skill documents (`capability_health.py . --overall`)
    silently printed the per-capability list instead of the overall status. A
    discovery surface nothing reaches is not a discovery surface."""

    def setUp(self):
        self.p = _Project(self)
        import shutil
        lib = self.p.root / "agents" / "lib" / "external_write"
        lib.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_EXTERNAL_WRITE_DIR, lib,
                        ignore=shutil.ignore_patterns("test_*.py",
                                                      "__pycache__"))
        (lib / "__init__.py").touch(exist_ok=True)
        (self.p.root / "agents" / "lib" / "__init__.py").touch(exist_ok=True)

    def _run(self, *args):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "agents/lib/external_write/capability_health.py",
             *args], capture_output=True, text=True, cwd=str(self.p.root),
            env=env, timeout=120)

    def test_overall_first_returns_the_overall_object(self):
        result = self._run("--overall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("normal_status_allowed", json.loads(result.stdout))

    def test_overall_after_the_project_root_returns_the_overall_object(self):
        result = self._run(".", "--overall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("normal_status_allowed", json.loads(result.stdout),
                      "the documented invocation must reach the overall status")

    def test_the_interrupted_trial_reaches_the_operators_own_command(self):
        self.p.put_journal("t-77", {"r1": tj.STATE_APPLY_CONFIRMED})
        result = self._run(".", "--overall")
        status = json.loads(result.stdout)
        self.assertTrue(status["interrupted_trial"]["outstanding"])
        self.assertIn(trc.recovery_command("t-77"),
                      status["interrupted_trial"]["trials"][0]["action"])


# ===========================================================================
# 11. THE EMITTED SKILLS -- pinned to the registry's own renderers
# ===========================================================================

class TheEmittedSkillsNameTheCommandsTests(unittest.TestCase):
    """Markdown cannot call a function, so the pin runs the other way: the literal
    the skill carries must equal what the registry's own builder renders for a
    placeholder subject. If either entrypoint moves, the skill and the builder move
    together or this fails."""

    WRITER_PLACEHOLDER = "<the flagged file, exactly as the check named it>"
    TRIAL_PLACEHOLDER = "<trial-id-from-the-health-check>"

    def _skill(self, name):
        path = _WIZARD / "skills" / name
        self.assertTrue(path.is_file(), str(path))
        return path.read_text(encoding="utf-8")

    def test_the_rebuild_skill_names_the_acknowledgement_command(self):
        text = self._skill("rebuild-paused-capability.md")
        self.assertIn(ack.acknowledgement_command(self.WRITER_PLACEHOLDER),
                      text)

    def test_the_rebuild_skill_still_gates_that_route_on_needs_a_person(self):
        """Reachable, not cheaper: the skill must keep conditioning the route on
        the refusal saying the file needs a person."""
        text = self._skill("rebuild-paused-capability.md").lower()
        self.assertIn("cannot be fixed automatically", text)
        index_condition = text.index("cannot be fixed automatically")
        index_command = text.index("writer_acknowledgement.py")
        self.assertLess(index_condition, index_command,
                        "the condition must come before the command")

    def test_the_orientation_skill_names_the_recovery_command(self):
        text = self._skill("orientation.md")
        self.assertIn(trc.recovery_command(self.TRIAL_PLACEHOLDER), text)

    def test_the_orientation_skill_points_at_the_durable_discovery_field(self):
        text = self._skill("orientation.md")
        self.assertIn("interrupted_trial", text)
        self.assertIn("--overall", text)


# ===========================================================================
# 12. THE GATE BODIES THEMSELVES -- each one must fail when hollowed out
# ===========================================================================

class TheGateBodiesAreFalsifiableTests(unittest.TestCase):
    """The gates above prove the registry agrees with the two upstream
    vocabularies. These prove the GATES: each body is driven to a NON-EMPTY answer,
    so replacing it with `return ()` reds a test.

    Why this is not belt-and-braces. A review measured that all four bodies could be
    stubbed with the suite still green, and found a COMBINED mutation -- stub
    `unclassified_state_keys` AND add a state that is terminal by omission -- that
    went green and undetected. Terminal-by-omission is the one property this task's
    brief singled out, and it rested on the return value of a function nothing
    forced to compute anything. A gate that cannot fail is the fifth green-and-blind
    gate in this family.
    """

    def _patch(self, name, value):
        original = getattr(sa, name)
        setattr(sa, name, value)
        self.addCleanup(setattr, sa, name, original)

    def test_unactionable_gated_state_keys_reports_a_real_gap(self):
        key = sa.trial_unit_state_key(tj.STATE_PLANNED)   # declared, no action
        self._patch("GATED_STATE_KEYS", frozenset(sa.GATED_STATE_KEYS | {key}))
        self.assertIn(key, sa.unactionable_gated_state_keys())

    def test_unclassified_state_keys_reports_a_real_gap(self):
        key = sa.state_key(sa.DOMAIN_TRIAL_UNIT, "added_without_a_disposition")
        self._patch("DECLARED_STATE_KEYS",
                    frozenset(sa.DECLARED_STATE_KEYS | {key}))
        self.assertIn(key, sa.unclassified_state_keys())

    def test_doubly_classified_state_keys_reports_a_real_overlap(self):
        key = sa.writer_state_key(core.WriterState.RESOLVED)   # a disposition
        self.assertIn(key, sa.INTENTIONAL_DISPOSITIONS)
        self._patch("GATED_STATE_KEYS", frozenset(sa.GATED_STATE_KEYS | {key}))
        self.assertIn(key, sa.doubly_classified_state_keys())

    def test_actions_landing_in_a_dead_end_reports_a_real_dead_end(self):
        from types import MappingProxyType
        self._patch("INTENTIONAL_DISPOSITIONS", MappingProxyType({}))
        stuck = sa.actions_landing_in_a_dead_end()
        self.assertEqual(sorted(stuck),
                         sorted(a.action_id for a in sa.ACTIONS),
                         "with nothing declared settled, every action's "
                         "post-condition is a state with no exit")


class TheSamePropertiesComputedHereTests(unittest.TestCase):
    """A SECOND, independent path to the three properties whose gate bodies had
    none: the arithmetic is done in the test, over the module's own declared sets,
    so a hollowed-out gate body cannot hide a real violation.

    `test_every_gated_state_has_at_least_one_action` already had this shape (a
    subTest loop calling `actions_for_state`), which is exactly why it survived the
    review's combined mutation while the other three did not. These mirror it.
    """

    def test_every_declared_state_is_classified_computed_HERE(self):
        """THE terminal-by-omission assertion, without asking the module for the
        answer. A state added to either vocabulary and placed in neither the gated
        set nor the declared dispositions fails here even if
        `unclassified_state_keys` is replaced with `return ()`."""
        for key in sorted(sa.DECLARED_STATE_KEYS):
            with self.subTest(state=key):
                self.assertTrue(
                    key in sa.GATED_STATE_KEYS
                    or key in sa.INTENTIONAL_DISPOSITIONS,
                    f"{key} is terminal BY OMISSION -- it blocks nothing and "
                    "nobody wrote down why it needs no action")

    def test_nothing_is_doubly_classified_computed_HERE(self):
        self.assertTrue(
            sa.GATED_STATE_KEYS.isdisjoint(set(sa.INTENTIONAL_DISPOSITIONS)),
            "a state cannot both block and need no action")

    def test_no_action_lands_in_a_dead_end_computed_HERE(self):
        for action in sa.ACTIONS:
            with self.subTest(action=action.action_id):
                target = action.expected_state
                self.assertTrue(
                    target in sa.INTENTIONAL_DISPOSITIONS
                    or sa.actions_for_state(target),
                    f"{action.action_id} lands in {target}, which has no exit")


# ===========================================================================
# 13. ONE ANSWER PER OBJECT -- `descriptions` must never be state-blind-wrong
# ===========================================================================

class TheHealthSurfaceCarriesNoWrongAnswerTests(unittest.TestCase):
    """A review measured the same returned object carrying BOTH answers for a
    `needs_person` writer: `actions` named the acknowledgement route, and
    `descriptions` said "rebuild it" -- the one instruction that cannot work for a
    file no rebuild can rewrite -- while the docstring recommended `descriptions`.
    That is the two-independently-authored-copies divergence this cut recorded as a
    finding, sitting on one object, with the in-code guidance pointing at the wrong
    field."""

    def setUp(self):
        from external_write import capability_health as ch
        self.ch = ch
        self.p = _Project(self)

    def _bypass(self, src, kinds):
        self.p.write(WRITER, src)
        self.p.queue([_entry_with_kinds(WRITER, kinds)])
        return self.ch.overall_status(
            str(self.p.root))["open_external_write_bypass"]

    def test_the_docstring_names_the_registry_derived_field(self):
        doc = self.ch.overall_status.__doc__
        self.assertIn('open_external_write_bypass["actions"]', doc)

    def test_a_needs_person_writer_is_never_described_as_rebuildable(self):
        block = self._bypass(_UNREPAIRABLE_SRC, ["forbidden_import"])
        self.assertEqual(block["writer_states"][WRITER],
                         core.WriterState.NEEDS_PERSON)
        self.assertNotIn("rebuild it so it routes through the sanctioned bulk path",
                         block["descriptions"][WRITER],
                         "the one instruction that cannot work for this state")
        self.assertIn(ack.acknowledgement_command(WRITER),
                      block["descriptions"][WRITER])

    def test_a_rebuildable_writer_keeps_the_wording_it_has_always_had(self):
        block = self._bypass(_REBUILDABLE_SRC, ["adapter_module_import"])
        self.assertIn(
            f"an external-write bypass is unrepaired: `{WRITER}` -- rebuild it "
            "so it routes through the sanctioned bulk path",
            block["descriptions"][WRITER])

    def test_the_two_fields_cannot_diverge_for_a_bespoke_writer(self):
        """Derived from ONE source, so drift is not possible rather than merely
        unlikely. They stay distinct fields because for a NON-bypass entry
        `descriptions` carries that entry's own recorded next step and `actions`
        carries the way out of the writer's state -- see the test below."""
        for src, kinds in ((_UNREPAIRABLE_SRC, ["forbidden_import"]),
                           (_REBUILDABLE_SRC, ["adapter_module_import"])):
            with self.subTest(kinds=kinds):
                p = _Project(self)
                p.write(WRITER, src)
                p.queue([_entry_with_kinds(WRITER, kinds)])
                block = self.ch.overall_status(
                    str(p.root))["open_external_write_bypass"]
                self.assertEqual(block["descriptions"][WRITER],
                                 block["actions"][WRITER])

    def test_a_non_bypass_entry_still_speaks_in_its_OWN_words(self):
        """The kind-aware half, unchanged: this queue carries entries that are not
        bespoke writers at all, and describing one with the rebuild sentence tells
        the operator to do something impossible to a file that was never the
        problem."""
        queue_entry = {
            "mechanism_id": "upgrade_safety_check",
            "writer_relpath": "agents/handoffs/pending_migrations.json",
            "kind": "reconcile_incomplete",
            "status": "pending",
            "reason": "the upgrade safety check could not finish",
            "suggested_next_step": "Ask your assistant to run `wizard reconcile`.",
        }
        self.p.queue([queue_entry])
        block = self.ch.overall_status(
            str(self.p.root))["open_external_write_bypass"]
        rel = "agents/handoffs/pending_migrations.json"
        self.assertIn("wizard reconcile", block["descriptions"][rel])
        self.assertNotIn("rebuild it so it routes through the sanctioned bulk path",
                         block["descriptions"][rel])


# ===========================================================================
# 14. THE HEALTH CLI PARSES DENY-BY-DEFAULT
# ===========================================================================

class TheHealthCliRefusesAnUnrecognisedFlagTests(unittest.TestCase):
    """A review measured `--overal` (one keystroke) and `--json` both yielding `[]`
    and exit 0: a clean empty success from the one surface whose whole job is saying
    when something is outstanding. That is the silently-dropped-flag class this
    package has already shipped once, and the class the acknowledgement CLI in this
    same commit was given a strict parse for. This one had not been."""

    def setUp(self):
        import shutil
        self.p = _Project(self)
        lib = self.p.root / "agents" / "lib" / "external_write"
        lib.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_EXTERNAL_WRITE_DIR, lib,
                        ignore=shutil.ignore_patterns("test_*.py",
                                                      "__pycache__"))
        (lib / "__init__.py").touch(exist_ok=True)
        (self.p.root / "agents" / "lib" / "__init__.py").touch(exist_ok=True)

    def _run(self, *args):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "agents/lib/external_write/capability_health.py",
             *args], capture_output=True, text=True, cwd=str(self.p.root),
            env=env, timeout=120)

    def test_a_mistyped_overall_flag_never_returns_a_clean_empty_success(self):
        result = self._run(".", "--overal")
        self.assertNotEqual(
            result.returncode, 0,
            "a mistyped flag must never read as a successful report: "
            f"{result.stdout!r}")
        self.assertEqual(result.stdout, "",
                         "a refusal must print no report at all")
        self.assertIn("--overall", result.stderr)

    def test_an_unrecognised_flag_refuses_and_names_the_accepted_forms(self):
        result = self._run("--json")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--json", result.stderr)
        self.assertIn("--overall", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_second_project_root_refuses_rather_than_picking_one(self):
        result = self._run(".", "..")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_both_accepted_orderings_still_report(self):
        for args in ((".", "--overall"), ("--overall", "."), ("--overall",)):
            with self.subTest(args=args):
                result = self._run(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("normal_status_allowed", json.loads(result.stdout))

    def test_the_per_capability_form_still_reports(self):
        result = self._run(".")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])


# ===========================================================================
# 15. A DISCOVERED TRIAL ALWAYS CARRIES AN ACTIONABLE INSTRUCTION
# ===========================================================================

class ADiscoveredTrialNeverRendersAnEmptyActionTests(unittest.TestCase):
    """A discovered outstanding trial with an empty `action` is precisely the shape
    this cut exists to remove -- a blocking state the operator is told about and
    cannot act on. Asserted positively, and driven for the degenerate input that
    would otherwise produce it."""

    def setUp(self):
        from external_write import capability_health as ch
        self.ch = ch
        self.p = _Project(self)

    def test_a_real_discovered_trial_carries_a_command(self):
        self.p.put_journal("t-77", {"r1": tj.STATE_APPLY_INTENT})
        trial, = self.ch.overall_status(
            str(self.p.root))["interrupted_trial"]["trials"]
        self.assertTrue(trial["action"].strip())
        self.assertIn(trc.recovery_command("t-77"), trial["action"])

    def test_a_record_whose_units_do_not_resolve_still_routes_to_a_person(self):
        """The degenerate case: an outstanding unit id the state map does not cover.
        It cannot arise through the validated read today, which is why it is driven
        here directly -- the answer must be a route, never an empty string."""
        from external_write import trial_journal as real_tj
        original = real_tj.scan_outstanding_trials
        self.addCleanup(setattr, real_tj, "scan_outstanding_trials", original)
        real_tj.scan_outstanding_trials = lambda **kw: {
            "trials": [{"trial_id": "t-9", "path": "p", "op_kind": "k",
                        "outstanding_unit_ids": ["ghost"], "unit_states": {}}],
            "unreadable": [], "scan_error": None}
        trial, = self.ch.overall_status(
            str(self.p.root))["interrupted_trial"]["trials"]
        self.assertTrue(trial["action"].strip(),
                        "a discovered trial with no instruction is the dead end "
                        "this cut exists to remove")
        self.assertIn("ask your assistant", trial["action"].lower())


class TheScanReportsAMalformedUnitEntryPerRecordTests(unittest.TestCase):
    """A unit entry that is not an object cannot survive the validated read, so it
    can only arrive on a record this scan is already going to refuse. What matters
    is that it refuses THAT RECORD and keeps scanning, rather than aborting the
    whole sweep and losing every other trial with it."""

    def setUp(self):
        self.p = _Project(self)

    def test_a_malformed_unit_entry_is_reported_and_the_other_trials_survive(self):
        self.p.put_journal("t-good", {"r1": tj.STATE_APPLY_INTENT})
        d = self.p.root / tj.DEFAULT_TRIAL_JOURNAL_DIR
        (d / "t-bad.json").write_text(json.dumps({
            "schema": tj.TRIAL_JOURNAL_SCHEMA, "trial_id": "t-bad",
            "op_kind": "k", "units": ["not an object"]}), encoding="utf-8")

        result = tj.scan_outstanding_trials(journal_dir=str(d))

        self.assertEqual([t["trial_id"] for t in result["trials"]], ["t-good"],
                         "one bad record must not lose the others")
        self.assertEqual(len(result["unreadable"]), 1, result)
        self.assertIn("t-bad.json", result["unreadable"][0]["path"])
        self.assertIsNone(result["scan_error"])


# ===========================================================================
# 17. THE REPAIR SENTENCE IS AUTHORED ONCE, AND NO SURFACE STATE-BLINDLY
#     PRESCRIBES IT
#
# The registry removed the copies that existed. What remained was a surface that
# still PRESCRIBED the rebuild without knowing the writer's state -- the deepest
# layer's own entry description -- and a command layer that RE-SPELLED the repair
# clause because it cannot import the registry. Both are closed here: the
# description now DIAGNOSES without prescribing, and the command layer BINDS the
# one declaration instead of re-spelling it.
# ===========================================================================

class TheRepairSentenceIsAuthoredOnceTests(unittest.TestCase):

    #: The clause the registry's rebuild instruction ends with. Spelled here on
    #: purpose: a needle derived from the constant it is meant to pin would follow
    #: that constant anywhere and assert nothing.
    CLAUSE = "rebuild it so it routes through the sanctioned bulk path"

    def _production_sources(self):
        for path in sorted(_EXTERNAL_WRITE_DIR.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            yield path.name, path.read_text(encoding="utf-8")

    def test_the_repair_clause_has_exactly_one_home_in_the_package(self):
        """The property that makes the command layer's pinned exemption an
        exemption rather than a hole: there is ONE spelling of the repair, so the
        refusal and the registry's instruction cannot drift apart."""
        homes = sorted(name for name, src in self._production_sources()
                       if self.CLAUSE in src)
        self.assertEqual(homes, ["writer_state_core.py"], homes)

    def test_NO_action_instruction_has_a_second_author_in_the_package(self):
        """The two hand-written one-home pins above cover the two sentences that were
        already duplicated. This one is quantified over `ACTIONS`, so an action added
        later is covered without anyone remembering -- and it exists because
        `recover_interrupted_trial`'s instruction was pinned by nothing at all: it
        carries no repair verb and no spelled path, so the sentence could have been
        pasted into a second module and no text pin would have noticed.

        The permitted homes are the registry itself plus any module the registry
        provably reads a constant out of (today: the leaf layer's repair clause).
        Derived from the registry's own imports, so it is not a blessed-file list."""
        allowed = {"state_actions.py"}
        registry_src = (_EXTERNAL_WRITE_DIR / "state_actions.py").read_text(
            encoding="utf-8")
        for path in sorted(_EXTERNAL_WRITE_DIR.glob("*.py")):
            if path.name.startswith("test_") or path.name == "state_actions.py":
                continue
            if f"external_write.{path.stem}" in registry_src:
                allowed.add(path.name)

        sources = dict(self._production_sources())
        for action in sa.ACTIONS:
            fragments = [f for f in re.split(r"\{[^{}]*\}", action.instruction)
                         if len(f.strip()) >= 40]
            with self.subTest(action=action.action_id):
                self.assertTrue(fragments,
                                "an instruction with no substantial fixed fragment "
                                "cannot be pinned this way -- say so if that happens")
                homes = {name for name, src in sources.items()
                         if any(f in src for f in fragments)}
                self.assertTrue(
                    homes <= allowed,
                    "a second author of this action's instruction: {}".format(
                        sorted(homes - allowed)))

    def test_the_registrys_instruction_is_composed_from_that_one_declaration(self):
        self.assertIn(core.BYPASS_UNREPAIRED_REPAIR,
                      sa.instruction_for_state(
                          sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),
                          WRITER))
        self.assertEqual(core.BYPASS_UNREPAIRED_REPAIR, self.CLAUSE)
        self.assertIn(core.BYPASS_UNREPAIRED_DIAGNOSIS.format(relpath=WRITER),
                      sa.instruction_for_state(
                          sa.writer_state_key(core.WriterState.BLOCKING_LIVE_ENABLE),
                          WRITER))

    def test_the_entry_description_DIAGNOSES_a_bypass_and_prescribes_nothing(self):
        """It cannot know the writer's state -- it is the leaf layer, and it imports
        no sibling at all -- so prescribing was the defect. It described a file that
        needs a person as "rebuild it", which is the one instruction that cannot
        work for a file no rebuild of ours can rewrite. The diagnosis is true for
        every state; the repair is not, and the repair now comes from the registry
        only."""
        text = core.describe_blocking_entry(_entry_with_kinds(WRITER, ["forbidden_import"]))
        self.assertIn(WRITER, text)
        self.assertIn("external-write bypass is unrepaired", text)
        self.assertNotIn(self.CLAUSE, text,
                         "the leaf layer prescribed a repair it cannot know applies")
        self.assertNotIn("rebuild", text.lower())

    def test_a_non_bypass_entry_still_speaks_in_its_own_recorded_words(self):
        entry = {"mechanism_id": "m", "writer_relpath": QUEUE_REL,
                 "kind": "reconcile_incomplete", "status": "pending",
                 "suggested_next_step": "Ask your assistant to run `wizard reconcile`."}
        self.assertIn("wizard reconcile", core.describe_blocking_entry(entry))


class TheIneligibleRefusalBindsTheOneDeclarationTests(unittest.TestCase):
    """The command layer that records an accepted-risk decision refuses a writer in
    a state the decision does not apply to, and says why. It cannot render that from
    the registry (the registry imports this layer's own facade, and reaches the trial
    modules whose pre-existing cycle would then land inside the writer-state
    cluster's proved acyclicity closure), so the refusal's FRAMING is authored here
    and pinned as an exemption. What must NOT be authored here is the repair."""

    def _commands(self):
        from external_write import writer_commands
        return writer_commands

    def _production_sources(self):
        for path in sorted(_EXTERNAL_WRITE_DIR.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            yield path.name, path.read_text(encoding="utf-8")

    def test_the_refusal_contains_the_registrys_own_repair_clause(self):
        commands = self._commands()
        text = commands._INELIGIBLE_STATE_REASONS[
            core.WriterState.BLOCKING_LIVE_ENABLE].format(relpath=WRITER)
        self.assertIn(core.BYPASS_UNREPAIRED_REPAIR, text)
        self.assertIn(WRITER, text)

    def test_the_refusal_BINDS_the_clause_rather_than_re_spelling_it(self):
        """Structural, over the module's own source: no string literal in this
        module may contain the clause. A text search cannot answer this -- the
        module's docstring and comments discuss the clause at length."""
        source = (_EXTERNAL_WRITE_DIR / "writer_commands.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
        offenders = [node.lineno for node in ast.walk(tree)
                     if isinstance(node, ast.Constant)
                     and isinstance(node.value, str)
                     and id(node) not in docstrings
                     and core.BYPASS_UNREPAIRED_REPAIR in node.value]
        self.assertEqual(offenders, [],
                         "the repair clause is re-spelled here instead of bound "
                         "from its single declaration")
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertIn("BYPASS_UNREPAIRED_REPAIR", names,
                      "the refusal no longer binds the one declaration")

    def test_the_route_to_a_person_clause_ALSO_has_exactly_one_home(self):
        """The same remedy, applied to the clause this task originally left
        duplicated. It was spelled twice, BYTE-IDENTICALLY, in this one module -- once
        inside the ineligible-state map and once as the unrecognised-state reason --
        which is a plain re-spelling under "single source, never re-spelled", and the
        bind-plus-pin fix for the repair clause defeats the layering blocker by
        construction. There was no reason for the second copy to survive."""
        clause = ("ask your assistant to go through what the safety check recorded "
                  "for it with you")
        self.assertEqual(core.ROUTE_TO_A_PERSON_CLAUSE, clause)
        homes = sorted(name for name, src in self._production_sources()
                       if clause in src)
        self.assertEqual(homes, ["writer_state_core.py"], homes)

    def test_both_refusals_bind_that_clause_and_still_read_the_same(self):
        commands = self._commands()
        ineligible = commands._INELIGIBLE_STATE_REASONS[
            core.WriterState.BLOCKING_LIVE_ENABLE].format(relpath=WRITER)
        unrecognised = commands._UNRECOGNISED_STATE_REASON.format(relpath=WRITER)
        for text in (ineligible, unrecognised):
            self.assertIn(core.ROUTE_TO_A_PERSON_CLAUSE, text)
        self.assertIn(WRITER, unrecognised)
        self.assertIn("not in a state where accepting the risk", unrecognised)

    def test_the_registrys_own_route_is_deliberately_a_DIFFERENT_sentence(self):
        """Not everything that mentions a person is the same clause, and collapsing
        them would be wrong rather than tidy. The registry's route answers "this state
        has no recorded way out at all"; the command's answers "this state is not one
        a recorded decision applies to". Different claims, so they stay separate --
        and this asserts they are genuinely different rather than an oversight."""
        registry_route = sa.route_for_unclassified_state(WRITER)
        self.assertNotIn(core.ROUTE_TO_A_PERSON_CLAUSE, registry_route)
        self.assertIn("no recorded way out", registry_route)

    def test_the_refusal_still_refuses_and_records_nothing(self):
        """The behaviour the binding must not change."""
        p = _Project(self)
        p.write(WRITER, _REBUILDABLE_SRC)
        p.queue([_entry_with_kinds(WRITER, ["adapter_module_import"])])
        commands = self._commands()
        with self.assertRaises(store.WriterAcknowledgementError) as raised:
            commands.acknowledge_writer(str(p.root), WRITER,
                                        operator_confirmation=CONFIRMATION)
        message = str(raised.exception)
        self.assertIn("nothing was recorded", message)
        self.assertIn(core.BYPASS_UNREPAIRED_REPAIR, message)
        self.assertFalse((p.root / store.ACKNOWLEDGEMENTS_REL).exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
