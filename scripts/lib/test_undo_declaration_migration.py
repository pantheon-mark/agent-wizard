"""The clause-(c) declaration migration: deliver the trial-eligibility
absolute-state-undo declaration into an ALREADY-EMITTED adapter module.

Why this exists
---------------
Cut 1.9 Task 1 added a NEW adapter contract clause -- an adapter must DECLARE
that its ``undo_one`` restores absolute prior state before its operation kind
may undergo a journaled trial. Measurement during the Task 1 review found that
ZERO adapters anywhere declared it, so every operation kind was
trial-INELIGIBLE. A new contract clause with no migration is the F-VAL20-1
zero-caller shape exactly (a remediation nothing invokes), so the clause is
delivered through three channels that must agree:

  * the SHIPPED reference adapter declares it where it is provable from source
    (see test_external_write_adapters_gmail.py);
  * the EMITTER writes the declaration site into every newly scaffolded
    adapter (see test_capability_code_scaffold.py);
  * THIS migration writes it into adapters that already exist on disk, as a
    declared member of ``ADAPTER_MIGRATIONS`` -- the only way a migration can
    exist at all.

What this file pins
-------------------
  1. Placement obeys the MRO-ORDER rule ``adapter_registry.
     _resolve_undo_declaration`` enforces -- not "the registered class" and not
     "the first class in the file". A declaration authored ABOVE an OVERRIDING
     ``undo_one`` is SUPERSEDED at runtime, so a migration that writes it onto a
     base whose subclass overrides ``undo_one`` produces a file that LOOKS
     migrated and is still ineligible. Several tests exec the migrated source
     and put the real kernel resolver on it, rather than asserting on text.
  2. The inserted value is ``False``, never ``True``. Nothing static can know
     whether an operator's ``undo_one`` writes the recorded prior state or a
     compensating action, and a machine-written ``True`` at a gate that
     authorizes an external write would be a false declaration. This mirrors
     ``render_missing_evidence_predicate_stub``'s never-a-passing-stub rule.
  3. The attribute NAME is bound to the kernel's own constant by a cross-tree
     equality test, so a rename on either side fails here.

Run:  python3 -m unittest discover -s wizard/scripts/lib \\
          -p test_undo_declaration_migration.py
"""

import ast
import sys
import unittest
from pathlib import Path

_SCRIPTS_LIB = Path(__file__).resolve().parent
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
for _p in (str(_SCRIPTS_LIB), str(_AGENTS_LIB)):
    if _p not in sys.path:
        sys.path.insert(0, str(_p))

from adapter_migrations import ADAPTER_MIGRATIONS, MigrationContext  # noqa: E402
from external_write import adapter_registry  # noqa: E402
from undo_declaration_migration import (  # noqa: E402
    UNDO_DECLARATION_ATTR,
    UNDO_DECLARATION_DECLARED,
    UNDO_DECLARATION_MIGRATION_NAME,
    UNDO_DECLARATION_MISSING,
    UNDO_DECLARATION_SUPERSEDED_STATUS,
    UNDO_DECLARATION_UNDO_NOT_FOUND,
    plan_undo_declaration_migration,
    resolve_undo_declaration_site,
)

_CTX = MigrationContext(required_predicates=())


def _adapter(class_body, *, extra_classes="", registered="InboxAdapter",
             bases="", op_kind="inbox.labels.modify"):
    """A minimal operator-shaped adapter module. Deliberately NOT named after
    its capability's canonical id anywhere -- resolution joins on the DECLARED
    op_kind, never a filename."""
    return (
        "from external_write.adapter_registry import register_adapter\n"
        "\n"
        f"OP_KIND = {op_kind!r}\n"
        "\n"
        "\n"
        + extra_classes
        + f"class {registered}{bases}:\n"
        + class_body
        + "\n"
        f"register_adapter(OP_KIND, {registered}())\n"
    )


_UNDO_METHOD = (
    "    def undo_one(self, raw_client, unit):\n"
    "        return None\n"
    "\n"
)


def _exec_and_resolve(source, class_name):
    """Exec the source and put the REAL kernel resolver on the resulting class.

    Text assertions cannot answer an MRO-order question -- only the resolver that
    actually runs at registration can, and a fixture that diverged from the
    production shape is exactly what Task 1's own fix round had to correct.

    The module-scope registration lines are stripped before exec: they exist for
    the AST resolver to read, and running the REAL ``register_adapter`` would
    require these minimal fixtures to implement the whole Adapter protocol, which
    has nothing to do with what is under test here.
    """
    body = "".join(
        line for line in source.splitlines(keepends=True)
        if not line.startswith("register_adapter(")
        and not line.startswith("from external_write.adapter_registry import"))
    namespace: dict = {}
    exec(compile(body, "<migrated>", "exec"), namespace)  # noqa: S102
    return adapter_registry._resolve_undo_declaration(namespace[class_name])


class TheAttributeNameIsBoundToTheKernelConstant(unittest.TestCase):
    """The most-shipped defect in this codebase is a re-spelled literal. The
    build-side toolkit tree and the emitted-lib tree are separate roots of trust
    and neither imports the other at module scope (the same reason
    ``contracts.RISK_CLASSES`` duplicates ``dependency_projection.RISK_CLASSES``
    behind a cross-tree equality test), so the duplication is guarded HERE."""

    def test_the_migration_uses_the_kernels_own_spelling(self):
        self.assertEqual(UNDO_DECLARATION_ATTR,
                         adapter_registry.UNDO_IDEMPOTENCY_DECLARATION_ATTR)


class TheMigrationIsADeclaredSetMember(unittest.TestCase):
    """The declared-migration-set standing rule: a remediation must be a declared
    member of a set some real flow iterates, never a function a caller has to
    remember to call."""

    def test_it_is_a_member_of_the_declared_set(self):
        self.assertIn(UNDO_DECLARATION_MIGRATION_NAME,
                      [m.name for m in ADAPTER_MIGRATIONS])

    def test_the_member_runs_this_modules_transform(self):
        member = next(m for m in ADAPTER_MIGRATIONS
                      if m.name == UNDO_DECLARATION_MIGRATION_NAME)
        source = _adapter(_UNDO_METHOD)
        self.assertEqual(member.plan(source, _CTX).source,
                         plan_undo_declaration_migration(source, _CTX).source)


class PlacementObeysTheMroOrderRule(unittest.TestCase):

    def test_declaration_lands_on_the_class_that_defines_undo_one(self):
        result = plan_undo_declaration_migration(_adapter(_UNDO_METHOD), _CTX)
        self.assertTrue(result.changed, result.reason)
        self.assertIs(_exec_and_resolve(result.source, "InboxAdapter"), False)

    def test_declaration_lands_on_an_in_module_BASE_that_defines_undo_one(self):
        """``d_decl == d_undo``: the base defines undo_one and the subclass
        overrides nothing, so declaring on the base is honoured at runtime."""
        source = _adapter(
            "    def apply_one(self, raw_client, unit):\n        return None\n",
            extra_classes=("class BaseAdapter:\n" + _UNDO_METHOD + "\n"),
            registered="InboxAdapter", bases="(BaseAdapter)")
        result = plan_undo_declaration_migration(source, _CTX)
        self.assertTrue(result.changed, result.reason)
        self.assertIn("BaseAdapter", result.reason)
        self.assertIs(_exec_and_resolve(result.source, "InboxAdapter"), False)

    def test_declaration_lands_on_the_SUBCLASS_when_it_overrides_undo_one(self):
        """THE TRAP. A base declares the clause; the subclass replaces
        ``undo_one`` below it, so the base's claim describes code that will not
        run and the kernel reports SUPERSEDED. The migration must re-declare on
        the overriding class -- writing it onto the base again would produce a
        file that looks migrated and is still ineligible."""
        source = _adapter(
            _UNDO_METHOD,
            extra_classes=("class BaseAdapter:\n"
                           f"    {UNDO_DECLARATION_ATTR} = True\n"
                           + _UNDO_METHOD + "\n"),
            registered="InboxAdapter", bases="(BaseAdapter)")
        self.assertIs(_exec_and_resolve(source, "InboxAdapter"),
                      adapter_registry.UNDO_DECLARATION_SUPERSEDED,
                      "fixture precondition: the unmigrated shape must be "
                      "SUPERSEDED, or this test proves nothing")
        result = plan_undo_declaration_migration(source, _CTX)
        self.assertTrue(result.changed, result.reason)
        self.assertIs(_exec_and_resolve(result.source, "InboxAdapter"), False,
                      "the re-declaration must be resolvable, not superseded")

    def test_a_subclass_declaring_for_an_inherited_undo_one_is_left_alone(self):
        """``d_decl < d_undo`` is legitimate: the declaring author is vouching
        for code that already existed. Re-inserting would shadow a real
        declaration -- possibly a True one -- with False."""
        source = _adapter(
            f"    {UNDO_DECLARATION_ATTR} = True\n"
            "    def apply_one(self, raw_client, unit):\n        return None\n",
            extra_classes=("class BaseAdapter:\n" + _UNDO_METHOD + "\n"),
            registered="InboxAdapter", bases="(BaseAdapter)")
        result = plan_undo_declaration_migration(source, _CTX)
        self.assertFalse(result.changed, result.reason)
        self.assertTrue(result.benign, result.reason)
        self.assertEqual(result.source, source)
        self.assertIs(_exec_and_resolve(source, "InboxAdapter"), True)

    def test_every_registered_class_in_a_multi_registration_module_is_covered(self):
        """``adapters_gmail.py``'s shape -- several classes, several
        registrations. A per-module "did anything change" check would pass with
        only the first class done (the F-1 defect, in a new place)."""
        source = (
            "from external_write.adapter_registry import register_adapter\n"
            "\n"
            "OP_A = 'a.op'\n"
            "OP_B = 'b.op'\n"
            "\n"
            "\n"
            "class AAdapter:\n" + _UNDO_METHOD + "\n"
            "class BAdapter:\n" + _UNDO_METHOD + "\n"
            "register_adapter(OP_A, AAdapter())\n"
            "register_adapter(OP_B, BAdapter())\n")
        result = plan_undo_declaration_migration(source, _CTX)
        self.assertTrue(result.changed, result.reason)
        for class_name in ("AAdapter", "BAdapter"):
            with self.subTest(class_name=class_name):
                self.assertIs(_exec_and_resolve(result.source, class_name), False)

    def test_running_the_migration_twice_changes_nothing_the_second_time(self):
        once = plan_undo_declaration_migration(_adapter(_UNDO_METHOD), _CTX)
        twice = plan_undo_declaration_migration(once.source, _CTX)
        self.assertFalse(twice.changed, twice.reason)
        self.assertTrue(twice.benign, twice.reason)
        self.assertEqual(twice.source, once.source)


class TheInsertedValueIsNeverAPassingDeclaration(unittest.TestCase):

    def test_the_inserted_declaration_is_False(self):
        result = plan_undo_declaration_migration(_adapter(_UNDO_METHOD), _CTX)
        self.assertIn(f"{UNDO_DECLARATION_ATTR} = False", result.source)
        self.assertNotIn(f"{UNDO_DECLARATION_ATTR} = True", result.source)

    def test_the_migrated_adapter_is_still_REFUSED_a_trial(self):
        """The whole point: delivering the declaration SITE is not delivering
        consent. The gate must still refuse until a human sets it to True."""
        result = plan_undo_declaration_migration(_adapter(_UNDO_METHOD), _CTX)
        self.assertIs(_exec_and_resolve(result.source, "InboxAdapter"), False,
                      "False is refused by trial_eligibility clause (c) -- "
                      "silence and False both mean 'not vouched for'")

    def test_the_inserted_comment_tells_a_human_what_to_check(self):
        result = plan_undo_declaration_migration(_adapter(_UNDO_METHOD), _CTX)
        inserted = result.source[len(_adapter(_UNDO_METHOD).split("\n")[0]):]
        self.assertIn("prior state", inserted.lower())
        self.assertIn("undo_one", inserted)


class RefusesRatherThanGuesses(unittest.TestCase):

    def test_unparseable_source_is_left_untouched_and_not_benign(self):
        source = "class Broken(:\n"
        result = plan_undo_declaration_migration(source, _CTX)
        self.assertFalse(result.changed)
        self.assertFalse(result.benign)
        self.assertEqual(result.source, source)

    def test_a_module_registering_nothing_is_left_untouched(self):
        source = "OP_KIND = 'x'\n"
        result = plan_undo_declaration_migration(source, _CTX)
        self.assertFalse(result.changed)
        self.assertEqual(result.source, source)

    def test_no_in_module_undo_one_is_a_BENIGN_no_op(self):
        """Deliberately benign, not a refusal. ``register_adapter`` captures
        ``cls.undo_one`` unconditionally, so a registered adapter with no
        ``undo_one`` anywhere in its hierarchy cannot even import -- an
        adapter with none in THIS module inherits it from a base this static
        pass may not follow. Blocking the whole project on that would be the
        over-firing guard the capability-declared scope-correction warns about; the
        fail-closed keystone is the post-condition, which is quantified over
        capability-declared op_kinds only."""
        source = _adapter(
            "    def apply_one(self, raw_client, unit):\n        return None\n")
        result = plan_undo_declaration_migration(source, _CTX)
        self.assertFalse(result.changed)
        self.assertTrue(result.benign, result.reason)
        self.assertEqual(result.source, source)

    def test_an_unresolvable_registration_is_never_guessed_at(self):
        source = (
            "from external_write.adapter_registry import register_adapter\n"
            "\n"
            "OP_KIND = 'x.op'\n"
            "\n"
            "\n"
            "def make_adapter():\n"
            "    return None\n"
            "\n"
            "\n"
            "register_adapter(OP_KIND, make_adapter())\n")
        result = plan_undo_declaration_migration(source, _CTX)
        self.assertFalse(result.changed)
        self.assertFalse(result.benign)
        self.assertEqual(result.source, source)


class TheStaticResolverMatchesTheKernelRule(unittest.TestCase):
    """The migration and the conformance post-condition MUST resolve the
    declaration the same way -- detection and insertion disagreeing about which
    class they mean is the exact F-1 defect. Both call this one resolver."""

    def _site(self, source, class_name="InboxAdapter"):
        return resolve_undo_declaration_site(ast.parse(source), class_name)

    def test_missing_when_nothing_declares_it(self):
        site = self._site(_adapter(_UNDO_METHOD))
        self.assertEqual(site.status, UNDO_DECLARATION_MISSING)
        self.assertEqual(site.undo_defining_class, "InboxAdapter")
        self.assertIsNone(site.declaring_class)

    def test_declared_on_the_same_class(self):
        site = self._site(_adapter(
            f"    {UNDO_DECLARATION_ATTR} = True\n" + _UNDO_METHOD))
        self.assertEqual(site.status, UNDO_DECLARATION_DECLARED)
        self.assertEqual(site.declaring_class, "InboxAdapter")

    def test_superseded_when_declared_above_an_overriding_undo_one(self):
        site = self._site(_adapter(
            _UNDO_METHOD,
            extra_classes=("class BaseAdapter:\n"
                           f"    {UNDO_DECLARATION_ATTR} = True\n"
                           + _UNDO_METHOD + "\n"),
            registered="InboxAdapter", bases="(BaseAdapter)"))
        self.assertEqual(site.status, UNDO_DECLARATION_SUPERSEDED_STATUS)
        self.assertEqual(site.undo_defining_class, "InboxAdapter")
        self.assertEqual(site.declaring_class, "BaseAdapter")

    def test_undo_not_found_when_no_class_in_the_module_defines_it(self):
        site = self._site(_adapter(
            "    def apply_one(self, raw_client, unit):\n        return None\n"))
        self.assertEqual(site.status, UNDO_DECLARATION_UNDO_NOT_FOUND)

    def test_an_annotated_declaration_counts(self):
        """``UNDO_IS_ABSOLUTE_STATE_RESTORE: bool = True`` is the same
        declaration. Matching only ``ast.Assign`` would silently report a real
        declaration as missing and the migration would shadow it."""
        site = self._site(_adapter(
            f"    {UNDO_DECLARATION_ATTR}: bool = True\n" + _UNDO_METHOD))
        self.assertEqual(site.status, UNDO_DECLARATION_DECLARED)

    def test_the_static_resolver_agrees_with_the_kernel_on_every_shape(self):
        """Cross-check: for each shape, the static verdict and the RUNTIME
        verdict must agree. A static approximation that drifts from the rule
        actually enforced at registration is worse than no check."""
        shapes = {
            UNDO_DECLARATION_MISSING: _adapter(_UNDO_METHOD),
            UNDO_DECLARATION_DECLARED: _adapter(
                f"    {UNDO_DECLARATION_ATTR} = True\n" + _UNDO_METHOD),
            UNDO_DECLARATION_SUPERSEDED_STATUS: _adapter(
                _UNDO_METHOD,
                extra_classes=("class BaseAdapter:\n"
                               f"    {UNDO_DECLARATION_ATTR} = True\n"
                               + _UNDO_METHOD + "\n"),
                registered="InboxAdapter", bases="(BaseAdapter)"),
        }
        expected_runtime = {
            UNDO_DECLARATION_MISSING: None,
            UNDO_DECLARATION_DECLARED: True,
            UNDO_DECLARATION_SUPERSEDED_STATUS:
                adapter_registry.UNDO_DECLARATION_SUPERSEDED,
        }
        for status, source in shapes.items():
            with self.subTest(status=status):
                self.assertEqual(self._site(source).status, status)
                self.assertIs(_exec_and_resolve(source, "InboxAdapter"),
                              expected_runtime[status])


if __name__ == "__main__":
    unittest.main()
