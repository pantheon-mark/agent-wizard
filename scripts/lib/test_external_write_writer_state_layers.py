"""The writer-state cluster's LAYERING — that the four layers form a DAG, and that
the bottom one can compute a writer's structural state with no knowledge that
operator acknowledgements exist at all.

Why this file exists
--------------------
The bespoke-writer machinery grew as two modules that imported each other, both
lazily, in opposite directions: the state module reached for the active
acknowledgement records so it could label an entry `acknowledged_risk`, and the
acknowledgement writer reached back for the open-entry list so it could refuse to
record a decision about a file nothing had flagged. Two lazy imports hide a cycle
well -- neither one fails at import time, so nothing in the suite noticed -- but a
cycle is what makes the eligibility rule impossible to tighten: any check the
acknowledgement side wants to make about a writer's STATE has to come from the
module that is already asking it about acknowledgements.

The split is four layers:

    writer_state_core     structural state: the WriterState vocabulary, the open
                          bespoke-writer queue, and the classification that
                          depends on nothing but the queue entry and the writer
                          file. Imports NO sibling in this package.
    writer_ack_store      the acknowledgement records: persistence, the
                          hash-validity rule, and the write primitive. Imports NO
                          sibling in this package.
    _ext_write_state      the state SERVICE: combines the two -- structural state
                          plus the operator's recorded decisions -- and keeps the
                          reap and the advisory owner derivation.
    writer_commands       the operator-invocable commands: validate through the
                          core, write through the store.

Two properties, and they are NOT the same property
--------------------------------------------------
1. The graph is ACYCLIC. `ImportGraphAcyclicityTests` proves it over the real
   module sources, following function-scope imports as well as module-scope ones,
   because the cycle this split removes was spelled entirely in function-scope
   imports. The graph is AST-static -- the ceiling this whole package states for
   itself -- so it cannot follow a dynamic import; that hole is closed for these
   modules specifically by `test_no_module_in_the_cluster_reaches_a_sibling_
   dynamically` rather than merely disclosed.

2. Structural classification consults NO acknowledgement state.
   `StructuralStateIsAcknowledgementBlindTests` proves it separately, because an
   acyclic graph does not imply it: a perfectly acyclic core could read the
   acknowledgement file directly, or take the active set as an argument, and the
   graph would still be a DAG. This is the property a later refactor is most
   likely to break -- reaching for the acknowledged set "just to save a pass"
   inside the core is the obvious shortcut -- so it is asserted behaviourally
   (the core's answer does not move when a valid acknowledgement lands on disk)
   and not only structurally.

Scope note on the acyclicity assertion
--------------------------------------
The assertion is over the subgraph REACHABLE FROM this cluster, not the whole
package. That is deliberate and it is not a loophole: the closure from these
modules is small and fully checked, while the package at large carries four
older, unrelated two-module cycles that predate this cluster and that no task
here is chartered to touch (they are named in `test_the_scope_of_this_assertion_
is_recorded_honestly` so the narrowing is a recorded fact rather than a silent
one). Widening the assertion to the package would make this file red for reasons
that have nothing to do with the layering it guards.

Run:
  python3 -m unittest discover -s wizard/scripts/lib \\
      -p test_external_write_writer_state_layers.py
"""

import ast
import hashlib
import json
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

from external_write import _ext_write_state as service        # noqa: E402
from external_write import scan                               # noqa: E402
from external_write import writer_ack_store as store          # noqa: E402
from external_write import writer_acknowledgement as facade   # noqa: E402
from external_write import writer_commands as commands        # noqa: E402
from external_write import writer_state_core as core          # noqa: E402
from external_write import zones                              # noqa: E402

CORE = "writer_state_core"
STORE = "writer_ack_store"
SERVICE = "_ext_write_state"
COMMANDS = "writer_commands"
FACADE = "writer_acknowledgement"

#: The layers whose job is acknowledgements. The core may reach none of them.
ACK_LAYER_MODULES = frozenset({STORE, COMMANDS, FACADE})

#: Roots of the cluster whose reachable subgraph must be acyclic.
CLUSTER_ROOTS = (CORE, STORE, SERVICE, COMMANDS, FACADE)

#: Two-module cycles that already existed elsewhere in this package before this
#: cluster was split, none of them reachable from it. Recorded so the scoping of
#: the acyclicity assertion above is an explicit, checkable fact.
PREEXISTING_CYCLES_ELSEWHERE = (
    ("capability_health", "lifecycle_state"),
    ("effects_manifest", "proof_hash"),
    ("lifecycle_state", "operator_acceptance"),
    ("trial_executor", "trial_recovery"),
)


# ---------------------------------------------------------------------------
# The import graph, read from the real sources by AST -- never a text search,
# and never `import`-and-introspect (a lazy import inside a function body is
# invisible to introspection until that branch runs, and the cycle this file
# guards against was spelled exactly that way).
# ---------------------------------------------------------------------------

def _sibling_imports(tree):
    """Every `external_write` SIBLING this module imports, at ANY depth -- module
    scope, function scope, inside a `try`, inside a branch. All four forms:
    `import external_write.x`, `from external_write import x`,
    `from external_write.x import y`, and the relative `from . import x` /
    `from .x import y`."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if "external_write" in parts:
                    i = parts.index("external_write")
                    if i + 1 < len(parts):
                        found.add(parts[i + 1])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    found.add(node.module.split(".")[0])
                else:
                    found.update(a.name for a in node.names)
            elif node.module:
                parts = node.module.split(".")
                if "external_write" in parts:
                    i = parts.index("external_write")
                    if i + 1 < len(parts):
                        found.add(parts[i + 1])
                    else:
                        found.update(a.name for a in node.names)
    return found


def _package_graph():
    """`module -> set(sibling modules it imports)` over every production module in
    the emitted package, derived from the real tree. A module that will not parse
    is a FAILURE of this guard, never a silent skip."""
    trees = {}
    for path in sorted(_EXTERNAL_WRITE_DIR.glob("*.py")):
        if path.name.startswith("test_") or path.name == "__init__.py":
            continue
        trees[path.stem] = ast.parse(path.read_text(encoding="utf-8"))
    return ({name: {e for e in _sibling_imports(tree) if e in trees}
             for name, tree in trees.items()}, trees)


def _closure(graph, roots):
    seen = set(roots)
    stack = list(roots)
    while stack:
        for nxt in graph.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _cycles(graph, nodes):
    """Every simple cycle inside the induced subgraph over `nodes`, each
    normalised to start at its smallest member so the same cycle is reported
    once."""
    found = set()

    def walk(node, path, visited):
        for nxt in sorted(graph.get(node, ())):
            if nxt not in nodes:
                continue
            if nxt in path:
                cyc = tuple(path[path.index(nxt):])
                pivot = min(range(len(cyc)), key=lambda j: cyc[j])
                found.add(cyc[pivot:] + cyc[:pivot])
            elif nxt not in visited:
                visited.add(nxt)
                walk(nxt, path + [nxt], visited)

    for start in sorted(nodes):
        walk(start, [start], {start})
    return found


class ImportGraphAcyclicityTests(unittest.TestCase):

    def setUp(self):
        self.graph, self.trees = _package_graph()

    def test_every_layer_module_exists(self):
        for name in CLUSTER_ROOTS:
            self.assertIn(name, self.graph, f"{name}.py is not in the emitted package")

    def test_the_cluster_subgraph_is_acyclic(self):
        """THE assertion. Over the real sources, following lazy imports."""
        nodes = _closure(self.graph, CLUSTER_ROOTS)
        found = _cycles(self.graph, nodes)
        self.assertEqual(
            found, set(),
            "the writer-state cluster's import graph must be acyclic; found: "
            + "; ".join(" -> ".join(c) + " -> " + c[0] for c in sorted(found)))

    def test_the_scope_of_this_assertion_is_recorded_honestly(self):
        """The narrowing above is a fact about the package, not an escape hatch:
        the four older cycles it excludes must genuinely still exist AND must
        genuinely be unreachable from this cluster. If one of them is ever fixed,
        this test fails and the exclusion is deleted rather than left to rot."""
        nodes = _closure(self.graph, CLUSTER_ROOTS)
        for a, b in PREEXISTING_CYCLES_ELSEWHERE:
            self.assertIn(b, self.graph.get(a, set()),
                          f"{a} -> {b} no longer exists; drop it from the list")
            self.assertIn(a, self.graph.get(b, set()),
                          f"{b} -> {a} no longer exists; drop it from the list")
            self.assertNotIn(
                a, nodes,
                f"{a} became reachable from the writer-state cluster, so this "
                "file's scoping no longer holds and the assertion must widen")

    def test_no_module_in_the_cluster_reaches_a_sibling_dynamically(self):
        """The graph above is AST-static, so it follows `import` and `from ... import`
        and nothing else. `importlib.import_module(f"external_write.{stem}")` or
        `__import__(...)` would be a real edge it cannot see -- and two modules
        elsewhere in this package legitimately do exactly that with a runtime-variable
        stem, so the limit is not hypothetical.

        Rather than disclose the ceiling and leave it open, this closes it WITHIN the
        scope of the assertion: no module reachable from this cluster may reach a
        sibling by any dynamic mechanism, so for these modules the static graph is the
        whole graph. It says nothing about the rest of the package, which is where the
        two legitimate dynamic importers live."""
        offenders = {}
        for name in sorted(_closure(self.graph, CLUSTER_ROOTS)):
            for node in ast.walk(self.trees[name]):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (isinstance(func, ast.Name) and func.id == "__import__") or (
                        isinstance(func, ast.Attribute)
                        and func.attr in ("import_module", "spec_from_file_location")):
                    offenders.setdefault(name, []).append(node.lineno)
        self.assertEqual(
            offenders, {},
            "a dynamic import inside the writer-state cluster would be an import "
            "edge this file's graph cannot see")

    def test_the_core_imports_no_sibling_at_all(self):
        """The core is a LEAF. Not "imports no acknowledgement module" -- imports
        nothing from this package, so there is no route by which a later edit
        gives it a sibling dependency without showing up here."""
        self.assertEqual(_sibling_imports(self.trees[CORE]), set())

    def test_the_store_imports_no_sibling_at_all(self):
        self.assertEqual(_sibling_imports(self.trees[STORE]), set())

    def test_the_commands_layer_reaches_the_core_and_the_store_and_not_the_service(self):
        imports = _sibling_imports(self.trees[COMMANDS])
        self.assertIn(CORE, imports, "commands must validate through the core")
        self.assertIn(STORE, imports, "commands must write through the store")
        self.assertNotIn(
            SERVICE, _closure(self.graph, [COMMANDS]),
            "the commands layer must not depend on the state service -- that "
            "edge is the one that closed the original cycle")

    def test_the_service_combines_the_core_and_the_store_directly(self):
        imports = _sibling_imports(self.trees[SERVICE])
        self.assertIn(CORE, imports)
        self.assertIn(STORE, imports)
        self.assertNotIn(
            FACADE, _closure(self.graph, [SERVICE]),
            "the service must reach acknowledgement records through the store, "
            "not through the compatibility facade")


# ---------------------------------------------------------------------------
# The load-bearing property, asserted on its own.
# ---------------------------------------------------------------------------

QUEUE_REL = "agents/handoffs/pending_migrations.json"
WRITER = "agents/upkeep/runner.py"
CONFIRMATION = "Yes -- I understand this one cannot be fixed automatically and I accept the risk."

_UNREPAIRABLE_SRC = '''"""Daily upkeep -- also delivers the operator's phone alert."""
import urllib.request
'''


class _Project:
    """A real project fixture at the real emitted relative paths."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def close(self):
        self._tmp.cleanup()

    def write(self, relpath, text):
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def write_bytes(self, relpath, raw):
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        return p

    def queue(self, entries):
        self.write(QUEUE_REL, json.dumps(entries, indent=2))

    def root_str(self):
        return str(self.root)


def _needs_person_entry(relpath=WRITER):
    """A queue entry whose recorded violation kind no remediator of ours covers,
    which is what makes its structural state `needs_person`."""
    return {
        "mechanism_id": "agents_upkeep_runner",
        "writer_relpath": relpath,
        "status": "pending",
        "paused_content_sha256": "0" * 64,
        "violations": [{"kind": "forbidden_import", "line": 2, "path": relpath}],
    }


class StructuralStateIsAcknowledgementBlindTests(unittest.TestCase):
    """Proved behaviourally, because the import-graph test does not imply it."""

    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)
        self.p.write(WRITER, _UNREPAIRABLE_SRC)
        self.p.queue([_needs_person_entry()])

    def _entry(self):
        return core.open_bespoke_writer_migrations(self.p.root_str())[0]

    def test_a_valid_acknowledgement_does_not_move_the_structural_state(self):
        """THE load-bearing assertion. The same entry, the same file, the only
        difference being a valid acknowledgement on disk -- and the core's answer
        is byte-identical. The service's answer moves; the core's must not."""
        before = core.structural_classification(self.p.root_str(), self._entry())
        self.assertEqual(before.state, core.WriterState.NEEDS_PERSON)

        commands.acknowledge_writer(self.p.root_str(), WRITER,
                                   operator_confirmation=CONFIRMATION)
        self.assertTrue(store.active_acknowledgements(self.p.root_str()),
                        "the fixture must actually have recorded one")

        after = core.structural_classification(self.p.root_str(), self._entry())
        self.assertEqual(after, before,
                         "structural classification consulted acknowledgement state")

    def test_the_service_by_contrast_does_move(self):
        """The companion of the test above: if the service did not move either,
        the pair would pass while the whole exit was dead."""
        self.assertEqual(
            service.classify_bespoke_writer_entry(self.p.root_str(), self._entry()),
            service.WriterState.NEEDS_PERSON)
        commands.acknowledge_writer(self.p.root_str(), WRITER,
                                   operator_confirmation=CONFIRMATION)
        self.assertEqual(
            service.classify_bespoke_writer_entry(self.p.root_str(), self._entry()),
            service.WriterState.ACKNOWLEDGED_RISK)

    def test_the_core_never_emits_a_state_it_could_not_have_derived_structurally(self):
        """`acknowledged_risk` and `resolved` are in the core's VOCABULARY -- the
        report buckets and the upgrade notice both pin the full set -- but the core
        can never produce either: one needs a recorded human decision and the other
        is the reaper's. Asserted over every entry shape that reaches the core."""
        cases = [
            _needs_person_entry(),
            dict(_needs_person_entry(), violations=[{"kind": "sealed_kernel_import"}]),
            dict(_needs_person_entry(), violations=[]),
            dict(_needs_person_entry(), writer_relpath=""),
            dict(_needs_person_entry(), writer_relpath="agents/gone/missing.py"),
            _needs_person_entry(relpath="tests/test_thing.py"),
        ]
        self.p.write("tests/test_thing.py",
                     "import unittest\n\n\nclass T(unittest.TestCase):\n    pass\n")
        for entry in cases:
            with self.subTest(entry=entry.get("writer_relpath")):
                got = core.structural_classification(self.p.root_str(), entry).state
                self.assertNotIn(got, (core.WriterState.ACKNOWLEDGED_RISK,
                                       core.WriterState.RESOLVED))

    def test_the_cores_source_names_no_acknowledgement_symbol_or_path(self):
        """Anti-drift over the AST, not the text: a later edit cannot reach the
        records by `importlib`, by re-spelling the store's relative path, or by
        naming one of its functions. The state VOCABULARY is exempt by
        construction -- this checks symbols and paths, never the English word,
        because `WriterState.ACKNOWLEDGED_RISK` legitimately lives here."""
        tree = ast.parse((_EXTERNAL_WRITE_DIR / f"{CORE}.py").read_text(encoding="utf-8"))
        banned_names = {"active_acknowledgements", "acknowledge_writer",
                        "put_acknowledgement_record", "require_writer_content_hash",
                        "ACKNOWLEDGEMENTS_REL", "ACKNOWLEDGEMENT_SCHEMA",
                        "WriterAcknowledgementError"}
        banned_strings = {store.ACKNOWLEDGEMENTS_REL, STORE, COMMANDS, FACADE}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, banned_names)
            elif isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, banned_names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                for banned in banned_strings:
                    self.assertNotIn(banned, node.value,
                                     f"the core names {banned!r}")

    def test_structural_classification_takes_no_acknowledged_argument(self):
        """The other way the property dies: keep the core acyclic but let a caller
        pass the active set in. Then the core is still 'blind' by import and fully
        sighted in practice."""
        import inspect
        params = set(inspect.signature(core.structural_classification).parameters)
        self.assertEqual(params, {"project_root", "entry"})


class AcknowledgementPreconditionTests(unittest.TestCase):
    """The service applies the acknowledgement only where it applied before: to a
    writer whose source the core could actually read. A file that reads as BYTES
    (so it can carry a matching hash) but not as UTF-8 TEXT is the case that
    separates the two, and it must stay blocking."""

    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)

    def test_a_writer_whose_source_is_not_readable_text_is_never_acknowledged(self):
        raw = b'"""upkeep"""\nimport urllib.request\n# \xff\xfe not utf-8\n'
        self.p.write_bytes(WRITER, raw)
        self.p.queue([_needs_person_entry()])
        entry = core.open_bespoke_writer_migrations(self.p.root_str())[0]

        self.assertFalse(
            core.structural_classification(self.p.root_str(), entry).source_readable)
        self.assertEqual(
            service.classify_bespoke_writer_entry(
                self.p.root_str(), entry, acknowledged={WRITER}),
            service.WriterState.BLOCKING_LIVE_ENABLE,
            "an acknowledgement must not un-block a writer whose source the "
            "classifier could not read")

    def test_an_empty_relpath_is_never_acknowledged_either(self):
        entry = dict(_needs_person_entry(), writer_relpath="")
        self.assertEqual(
            service.classify_bespoke_writer_entry(
                self.p.root_str(), entry, acknowledged={""}),
            service.WriterState.BLOCKING_LIVE_ENABLE)


class CommandRefusalOrderTests(unittest.TestCase):
    """Splitting the command across two layers made the ORDER of its four refusals
    a thing that could silently change. It must not: what the operator reads when
    their confirmation is unusable cannot depend on whether the file happened to be
    flagged, or they get told to go and look at a file when the real problem was
    their own paste. Pinned in both directions."""

    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)
        self.p.write(WRITER, _UNREPAIRABLE_SRC)
        self.p.write("agents/other/thing.py", "x = 1\n")
        self.p.queue([_needs_person_entry()])

    def _refusal(self, relpath, confirmation):
        with self.assertRaises(store.WriterAcknowledgementError) as raised:
            commands.acknowledge_writer(self.p.root_str(), relpath,
                                        operator_confirmation=confirmation)
        return str(raised.exception)

    def test_a_blank_confirmation_is_reported_before_eligibility(self):
        self.assertIn("in your own words",
                      self._refusal("agents/other/thing.py", "   "))

    def test_a_split_confirmation_is_reported_before_eligibility(self):
        self.assertIn("split across lines",
                      self._refusal("agents/other/thing.py", "Yes I accept\nthe risk"))

    def test_an_unreadable_writer_is_reported_before_eligibility(self):
        self.assertIn("could not be read",
                      self._refusal("agents/gone/missing.py", CONFIRMATION))

    def test_a_readable_unflagged_writer_reports_the_eligibility_refusal(self):
        self.assertIn("not currently flagged",
                      self._refusal("agents/other/thing.py", CONFIRMATION))

    def test_an_unreadable_queue_is_never_reported_as_not_flagged(self):
        """Fail-closed: a corrupt queue must not present as "this file is not
        flagged", which reads to the operator as "nothing to do here"."""
        self.p.write(QUEUE_REL, "{not json")
        with self.assertRaises(core.ExternalWriteStateReadError):
            commands.acknowledge_writer(self.p.root_str(), WRITER,
                                        operator_confirmation=CONFIRMATION)


# ---------------------------------------------------------------------------
# Behaviour preservation: the names every existing consumer reaches for are the
# SAME OBJECTS after the split, not equal copies.
# ---------------------------------------------------------------------------

class PublicSurfaceIdentityTests(unittest.TestCase):
    """Identity, not equality: a re-declared `WriterState` with the same five
    strings would compare equal field-by-field and would be a second source of
    the vocabulary -- exactly what "single source, never re-spelled" forbids."""

    def test_the_service_re_exports_the_cores_objects(self):
        for name in ("WriterState", "ExternalWriteStateReadError",
                     "REMEDIABLE_VIOLATION_KINDS", "BLOCKING_WRITER_STATES",
                     "MIGRATION_QUEUE_REL", "open_bespoke_writer_migrations",
                     "open_bespoke_writer_relpaths", "is_bypass_writer_entry",
                     "describe_blocking_entry"):
            with self.subTest(name=name):
                self.assertIs(getattr(service, name), getattr(core, name))

    def test_the_facade_re_exports_the_store_and_command_objects(self):
        self.assertIs(facade.active_acknowledgements, store.active_acknowledgements)
        self.assertIs(facade.WriterAcknowledgementError, store.WriterAcknowledgementError)
        self.assertIs(facade.ACKNOWLEDGEMENTS_REL, store.ACKNOWLEDGEMENTS_REL)
        self.assertIs(facade.ACKNOWLEDGEMENT_SCHEMA, store.ACKNOWLEDGEMENT_SCHEMA)
        self.assertIs(facade.acknowledge_writer, commands.acknowledge_writer)

    def test_there_is_exactly_one_writer_state_class_in_the_package(self):
        """Derived from the real sources: only the core may DECLARE the
        vocabulary. Every other module binds it."""
        declaring = []
        for path in sorted(_EXTERNAL_WRITE_DIR.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.ClassDef) and node.name == "WriterState":
                    declaring.append(path.name)
        self.assertEqual(declaring, [f"{CORE}.py"])

    def test_the_acknowledgement_path_is_spelled_in_exactly_one_module(self):
        spelling = []
        for path in sorted(_EXTERNAL_WRITE_DIR.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and node.value == store.ACKNOWLEDGEMENTS_REL):
                    spelling.append(path.name)
                    break
        self.assertEqual(spelling, [f"{STORE}.py"])


# ---------------------------------------------------------------------------
# The new modules must physically reach an operator project, and must be zoned.
# ---------------------------------------------------------------------------

class EnrollmentAndZoneTests(unittest.TestCase):

    NEW_MODULES = (CORE, STORE, COMMANDS)

    def test_each_new_module_is_enrolled_in_the_emitted_lib_file_list(self):
        import agent_emitter
        for name in self.NEW_MODULES:
            with self.subTest(module=name):
                self.assertIn(f"{name}.py", agent_emitter._EXTERNAL_WRITE_LIB_FILES,
                              "an unenrolled module is silently absent from every "
                              "generated project, and the service imports it at "
                              "module scope -- a raw ModuleNotFoundError at import "
                              "time for the completion gate and the health read")

    def test_each_new_module_is_zoned_sealed_kernel(self):
        for name in self.NEW_MODULES:
            with self.subTest(module=name):
                self.assertIn(f"{name}.py", zones.SEALED_KERNEL_MODULE_PATHS)
                self.assertEqual(
                    zones.classify_zone(_EXTERNAL_WRITE_DIR / f"{name}.py",
                                        _EXTERNAL_WRITE_DIR),
                    zones.Zone.SEALED_KERNEL)

    def test_each_new_module_scans_clean(self):
        for name in self.NEW_MODULES:
            with self.subTest(module=name):
                self.assertEqual(
                    scan.scan_paths([_EXTERNAL_WRITE_DIR / f"{name}.py"],
                                    allowed_root=_EXTERNAL_WRITE_DIR), [])

    def test_the_commands_layers_membership_is_load_bearing_not_decorative(self):
        """The counterfactual, for the one new module that genuinely needs the
        exemption: without the entry its ordinary kernel wiring is flagged. The
        other two import no sibling, so they have no counterfactual to assert --
        their entries are zone DECLARATIONS, which is what keeps a later sibling
        import from silently changing their classification."""
        without = frozenset(zones.SEALED_KERNEL_MODULE_PATHS) - {f"{COMMANDS}.py"}
        kinds = {v.kind for v in scan.scan_paths(
            [_EXTERNAL_WRITE_DIR / f"{COMMANDS}.py"],
            allowed_root=_EXTERNAL_WRITE_DIR, sealed_kernel_paths=without)}
        self.assertEqual(kinds, {"sealed_kernel_import"})

    def test_membership_does_not_let_capability_code_import_any_of_them(self):
        for name in self.NEW_MODULES:
            with self.subTest(module=name):
                self.assertNotIn(name, scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES)


if __name__ == "__main__":
    unittest.main()
