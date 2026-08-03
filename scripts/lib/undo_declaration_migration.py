"""Deterministic delivery of the trial-eligibility contract clause (c) --
the absolute-state-undo DECLARATION -- into an adapter module that already
exists on disk (Cut 1.9 / Task 1b).

The clause
----------
Cut 1.9 Task 1 added a NEW adapter contract clause: for an operation kind to be
eligible for a journaled TRIAL (``apply -> verify -> undo -> verify-restored``,
the only thing that can produce the ``copy_run_proof`` operator acceptance
requires), the registered adapter must DECLARE that its ``undo_one`` writes the
recorded PRIOR state rather than a relative compensating action. After a crash
the trial journal can only say the apply was INTENDED, so the recovery path runs
``undo_one`` without knowing whether the mutation landed and may run it more
than once; an absolute-state restore converges under both conditions and a
compensating action does not. Silence is REFUSED -- never treated as consent.

Why a migration exists at all
-----------------------------
Measurement during the Task 1 review found that ZERO adapters anywhere declared
the clause, so every operation kind -- including both live estate ones -- was
trial-ineligible and no acceptance could complete. A new contract clause with no
migration is exactly the F-VAL20-1 shape the declared-migration-set decision
closed (a correct, tested remediation nothing invoked), and that decision's
standing rule is that a remediation mechanism must be a DECLARED MEMBER of a set
some real flow iterates, never a function a caller has to remember to call. So
this transform is registered in
``adapter_migrations.ADAPTER_MIGRATIONS`` and the upgrade engine iterates it;
there is no other way to reach it.

What it writes, and what it deliberately does NOT write
-------------------------------------------------------
It writes the declaration SITE with the value ``False``, never ``True``.

Nothing static -- and nothing in the kernel either -- can know whether an
operator's ``undo_one`` restores the recorded prior state or deletes what it
created. That is a property of the vendor call it makes. A machine-written
``True`` would be a FALSE DECLARATION at a gate that authorizes an external
write, which is the one thing this whole clause exists to prevent. ``False`` and
absence are treated identically by the preflight (both REFUSE), so this changes
no verdict; what it changes is that the clause now exists, in the operator's own
file, at the exact class a human has to look at, with a comment naming what to
check. This mirrors ``capability_code_scaffold.
render_missing_evidence_predicate_stub``'s never-a-passing-stub rule exactly.

Placement is an MRO-ORDER question, not a "which class is registered" question
------------------------------------------------------------------------------
``adapter_registry._resolve_undo_declaration`` honours a declaration only when it
was authored AT OR BELOW the class that defines ``undo_one`` (``d_decl <=
d_undo`` in MRO order). A declaration authored ABOVE an OVERRIDING ``undo_one``
is SUPERSEDED, because a base's claim cannot describe an implementation written
after it. So writing the declaration onto "the registered class", or onto "the
first class in the file", produces files that LOOK migrated and are still
ineligible. This module resolves the class that actually DEFINES ``undo_one``
(walking in-module bases) and writes there -- and the same resolver
(:func:`resolve_undo_declaration_site`) is what the conformance post-condition in
``upgrade_reconcile.py`` reads, so detection and insertion can never disagree
about which class they mean. That disagreement, between a detector and an
inserter, is the exact F-1 shared-resolver defect.

Reuse, not invention
--------------------
Target-class resolution is the EXISTING registration-aware AST resolver
(``capability_code_scaffold.resolve_registered_adapter_classes`` +
``has_register_adapter_call``), and insertion is the same duplicate-safe
``end_lineno`` text splice ``insert_missing_evidence_predicate_stubs`` already
uses. A second resolver would be the defect, not the fix.

Disclosed bounds
----------------
  * The static ancestry walk follows only bases DEFINED IN THE SAME MODULE. An
    out-of-module base is unprovable without importing operator code, which this
    never does, for the reason established when that rule was corrected: the
    toolkit runs under a different interpreter than the operator's virtualenv,
    and operator adapters import vendor SDKs this process has no reason to have.
    A module with no resolvable ``undo_one`` is a BENIGN no-op here, not a
    refusal -- blocking every project whose adapter inherits ``undo_one`` from
    elsewhere would be the over-firing guard the capability-declared
    scope-correction warns about. The fail-closed keystone is the conformance
    post-condition, which is quantified over CAPABILITY-DECLARED op_kinds only.
  * The linearization is depth-first over ``bases``, which matches Python's MRO
    for the single-inheritance shape every emitted and observed adapter uses. For
    an exotic diamond it is an approximation; the runtime rule remains
    authoritative and the post-condition re-checks the end state on every
    upgrade.
  * Enforcement ceiling UNCHANGED: build-time plus operator-as-approver. This is
    not a runtime sandbox. A hand-edit can set the declaration to ``True``
    falsely, exactly as it could always mis-implement ``undo_one``; that surfaces
    as a trial whose restoration cannot be verified, never as a silent pass.

Stdlib only. Build-side toolkit code -- ships with the engine via ``wizard
self-update``, never into the operator project's emitted lib.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from adapter_migrations import MigrationContext, TransformResult
from capability_code_scaffold import (
    has_register_adapter_call, resolve_registered_adapter_classes,
)

#: The CLASS-attribute name an adapter declares the clause with.
#:
#: Mirrored VERBATIM from ``external_write.adapter_registry.
#: UNDO_IDEMPOTENCY_DECLARATION_ATTR``. The build-side toolkit tree and the
#: emitted-lib tree are separate roots of trust and neither imports the other at
#: module scope -- the same constraint that makes ``contracts.RISK_CLASSES``
#: duplicate ``dependency_projection.RISK_CLASSES``. So this duplication is
#: guarded by a CROSS-TREE EQUALITY TEST (``test_undo_declaration_migration.
#: TheAttributeNameIsBoundToTheKernelConstant``), which fails if either side is
#: renamed without the other. Every consumer on this side of the boundary reads
#: this constant; a re-spelled literal is this codebase's most-shipped defect.
UNDO_DECLARATION_ATTR = "UNDO_IS_ABSOLUTE_STATE_RESTORE"

#: The method the declaration makes a claim ABOUT. Mirrored from
#: ``adapter_registry._UNDO_METHOD_ATTR`` under the same cross-tree rule.
UNDO_METHOD_NAME = "undo_one"

#: The declared migration's stable, operator-visible name. Recorded on every
#: queue entry and refusal reason, so an outcome can always be traced back.
UNDO_DECLARATION_MIGRATION_NAME = "undo_absolute_state_declaration"

# ---------------------------------------------------------------------------
# The four possible static verdicts. Named constants rather than bare strings
# because BOTH this migration and the conformance post-condition branch on them,
# and the two must never drift apart.
# ---------------------------------------------------------------------------

#: A declaration is authored at or below the class defining ``undo_one`` --
#: honoured at runtime. (Says nothing about its VALUE: ``False`` is a declaration
#: and is still refused a trial by the preflight.)
UNDO_DECLARATION_DECLARED = "declared"
#: A declaration exists in the hierarchy, but an OVERRIDING ``undo_one`` was
#: defined below it, so the runtime reports
#: ``adapter_registry.UNDO_DECLARATION_SUPERSEDED``. The repair is to re-declare
#: on the overriding class -- NOT to add a declaration that is already there.
UNDO_DECLARATION_SUPERSEDED_STATUS = "superseded"
#: ``undo_one`` is defined in this module's hierarchy and nothing declares the
#: clause anywhere at or below it.
UNDO_DECLARATION_MISSING = "missing"
#: No class in this module's in-module hierarchy defines ``undo_one`` at all, so
#: there is nothing here for the clause to describe and nothing to place it next
#: to. Never guessed at.
UNDO_DECLARATION_UNDO_NOT_FOUND = "undo_not_found"


@dataclass(frozen=True)
class UndoDeclarationSite:
    """Where a class's clause-(c) declaration is, in MRO terms.

    ``undo_defining_class`` is the class whose OWN body defines ``undo_one`` --
    the class a declaration must sit at or below. ``declaring_class`` is the
    first class in the linearization carrying the attribute, whether or not that
    position is honoured; ``status`` is the verdict that accounts for both.
    """

    status: str
    undo_defining_class: Optional[str] = None
    declaring_class: Optional[str] = None


def _class_defs_by_name(tree: ast.Module) -> Dict[str, ast.ClassDef]:
    """Every class in the module, by name. A duplicated name is deliberately
    dropped rather than resolved: two top-level classes sharing a name is
    ambiguous, and ``resolve_registered_adapter_classes`` already refuses to
    guess between them."""
    found: Dict[str, List[ast.ClassDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            found.setdefault(node.name, []).append(node)
    return {name: nodes[0] for name, nodes in found.items() if len(nodes) == 1}


def _linearize(tree: ast.Module, class_name: str) -> List[ast.ClassDef]:
    """The class followed by its in-module ancestors, depth-first over ``bases``.

    Stands in for ``__mro__`` for a check that must never import operator code.
    Cycle-safe (a malformed hierarchy cannot hang this), and silently stops at
    any base this module does not define -- see the module docstring's disclosed
    bounds.
    """
    by_name = _class_defs_by_name(tree)
    order: List[ast.ClassDef] = []
    seen = set()
    stack = [class_name]
    while stack:
        name = stack.pop(0)
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        node = by_name[name]
        order.append(node)
        bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
        stack = bases + stack
    return order


def _own_body_binds(node: ast.ClassDef, name: str) -> bool:
    """True when this class's OWN body binds ``name`` -- the static mirror of the
    runtime's ``name in vars(klass)``.

    ONE predicate for BOTH the declaration attribute and ``undo_one``, because
    the runtime rule (``adapter_registry._resolve_undo_declaration``) asks the
    identical question about each of them: is this name in this class's own
    ``vars()``. Two predicates that answered it differently is precisely how this
    resolver first went wrong -- ``undo_one`` was matched as ``FunctionDef`` only,
    while the declaration was matched as ``FunctionDef``-or-assignment eleven
    lines away. A class carrying ``undo_one = _undo`` (an ordinary class-body
    binding of a module-level function, and the shape this project's own defects
    have taken twice) is honoured at runtime; reporting it as "no undo step here"
    produced a durable operator-facing block whose stated reason was FALSE and
    whose named repair could not clear it, because no declaration edit changes an
    undo-not-found verdict. An unclearable block is a state the operator cannot
    leave, so the two questions are answered here once.

    Counts: ``def`` / ``async def`` / nested ``class`` / ``name = ...``
    (including a tuple target) / ``name: T = ...``.

    Does NOT count a BARE annotation (``name: bool`` with no value): that binds
    nothing in ``vars()`` -- it only records an entry in ``__annotations__`` --
    so the runtime resolves it as absent. Counting it would be the same
    divergence in the opposite direction: the post-condition would report a
    project conformant while the trial preflight refused it.

    Disclosed bound: an exotic binding this does not model (an ``import`` inside
    a class body, a metaclass-synthesized attribute) resolves as absent, which is
    the fail-closed direction for a MISSING declaration and, for ``undo_one``,
    lands in the ``undo_not_found`` branch that :func:`resolve_undo_declaration_site`
    keeps clearable.
    """
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if stmt.name == name:
                return True
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name) and sub.id == name:
                        return True
        elif isinstance(stmt, ast.AnnAssign):
            if (stmt.value is not None
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == name):
                return True
    return False


def resolve_undo_declaration_site(tree: ast.Module,
                                  class_name: str) -> UndoDeclarationSite:
    """Resolve ``class_name``'s clause-(c) declaration, SCOPED to the ``undo_one``
    it is a claim about -- the static mirror of
    ``adapter_registry._resolve_undo_declaration``.

    The rule, in the same terms the kernel uses. Let ``d_undo`` be the index of
    the first class in the linearization whose OWN body defines ``undo_one``, and
    ``d_decl`` the index of the first whose OWN body carries the declaration. The
    declaration is honoured iff ``d_decl <= d_undo``.

    THE ONE resolver both the migration below and ``upgrade_reconcile``'s
    conformance post-condition read. A detector and an inserter that each decide
    for themselves which class they mean is the F-1 shared-resolver defect; there
    is one
    algorithm here so they cannot drift.
    """
    chain = _linearize(tree, class_name)
    if not chain:
        return UndoDeclarationSite(UNDO_DECLARATION_UNDO_NOT_FOUND)

    undo_at: Optional[int] = None
    decl_at: Optional[int] = None
    for index, node in enumerate(chain):
        if undo_at is None and _own_body_binds(node, UNDO_METHOD_NAME):
            undo_at = index
        if decl_at is None and _own_body_binds(node, UNDO_DECLARATION_ATTR):
            decl_at = index

    undo_class = chain[undo_at].name if undo_at is not None else None
    decl_class = chain[decl_at].name if decl_at is not None else None

    if undo_at is None and decl_at is not None:
        # ``undo_one`` is not bound anywhere this static walk can see, so it comes
        # from a base defined in ANOTHER module -- which this deliberately never
        # imports. The runtime, however, walks the FULL MRO: it will find
        # ``undo_one`` at some index BEYOND every class in this module, so any
        # in-module declaration necessarily satisfies ``d_decl <= d_undo`` and IS
        # honoured. Reporting this as unresolvable would leave a durable block
        # that survives the correct repair, which is a worse failure than the
        # false green it was guarding against: fail-closed is right for a MISSING
        # declaration, not for one that is present and will be read.
        #
        # ``undo_defining_class`` stays None on purpose -- this walk must not
        # claim to have located an ``undo_one`` it cannot see.
        return UndoDeclarationSite(UNDO_DECLARATION_DECLARED,
                                   declaring_class=decl_class)
    if undo_at is None:
        return UndoDeclarationSite(UNDO_DECLARATION_UNDO_NOT_FOUND)
    if decl_at is None:
        return UndoDeclarationSite(UNDO_DECLARATION_MISSING,
                                   undo_defining_class=undo_class)
    if decl_at > undo_at:
        return UndoDeclarationSite(UNDO_DECLARATION_SUPERSEDED_STATUS,
                                   undo_defining_class=undo_class,
                                   declaring_class=decl_class)
    return UndoDeclarationSite(UNDO_DECLARATION_DECLARED,
                               undo_defining_class=undo_class,
                               declaring_class=decl_class)


def render_undo_declaration(indent: str = "    ") -> str:
    """The class-body-indented declaration block this migration inserts.

    Pure string rendering. The VALUE is ``False`` and a comment says why, in
    terms a human (or an agent reading the file with them) can act on -- see the
    module docstring for the full reasoning. The attribute name comes from
    :data:`UNDO_DECLARATION_ATTR`, never a literal.
    """
    return (
        "\n"
        f"{indent}# TRIAL-ELIGIBILITY CONTRACT CLAUSE -- ADDED BY AN UPGRADE, NOT YET\n"
        f"{indent}# REVIEWED. A journaled trial (apply -> verify -> undo -> verify the\n"
        f"{indent}# prior state came back) is the only thing that can produce the proof\n"
        f"{indent}# needed to approve this for live use, and it is allowed ONLY when\n"
        f"{indent}# undo_one restores the recorded PRIOR state absolutely -- because\n"
        f"{indent}# after a crash the trial cannot know whether the change landed, so it\n"
        f"{indent}# runs undo_one anyway and may run it more than once.\n"
        f"{indent}#\n"
        f"{indent}# Left False on purpose: nothing automatic can tell whether undo_one\n"
        f"{indent}# writes the prior state back (safe to repeat) or undoes by\n"
        f"{indent}# compensating -- deleting what it created, subtracting what it added\n"
        f"{indent}# -- which repeated after a crash can destroy state the trial never\n"
        f"{indent}# touched. Set this to True ONLY IF undo_one restores the exact prior\n"
        f"{indent}# state; leaving it False means this operation kind is refused a\n"
        f"{indent}# trial, which is the safe outcome.\n"
        f"{indent}{UNDO_DECLARATION_ATTR} = False\n"
    )


def plan_undo_declaration_migration(
    source: str, context: "MigrationContext | None" = None,
) -> TransformResult:
    """Insert the clause-(c) declaration site into every registered adapter class
    in ``source`` that needs one, and return the replacement source.

    PURE: no filesystem access, so the engine can compose this with the other
    declared migrations on one in-memory copy of the module and write once.

    Per REGISTERED class (resolved from each module-level
    ``register_adapter(...)`` call, never from text position or a filename):

      * already declared at or below the class defining ``undo_one`` -> nothing
        to do, and NEVER shadowed with ``False`` (that declaration may be a
        reviewed ``True``);
      * declared only ABOVE an overriding ``undo_one`` -> re-declared on the
        OVERRIDING class, which is the only placement the runtime honours;
      * not declared -> declared on the class that DEFINES ``undo_one``;
      * no ``undo_one`` resolvable in this module -> left alone, benignly.

    Refuses -- source unchanged, non-benign, with a plain-language reason the
    engine turns into a durable operator-visible entry -- when the module cannot
    be parsed, makes no ``register_adapter(...)`` call, resolves no registration
    to a unique class, or when the rewrite would not have parsed or would not
    have landed where the runtime looks. It never rewrites a file it does not
    fully understand.
    """
    del context  # this migration needs nothing beyond the source text
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return TransformResult(source, False,
                               "could not be parsed, so it was left untouched")

    if not has_register_adapter_call(tree):
        return TransformResult(
            source, False,
            "this module registers no adapter with register_adapter(...), so "
            "there is no adapter class to record the undo-restore declaration "
            "on -- left untouched")

    resolved, ambiguous_count = resolve_registered_adapter_classes(tree)
    if not resolved:
        return TransformResult(
            source, False,
            f"none of this module's {ambiguous_count} register_adapter(...) "
            "call(s) resolve to a uniquely identifiable adapter class, so the "
            "undo-restore declaration has to be added by someone who knows "
            "which class it belongs on -- left untouched")

    # (end_lineno, text) per class needing the declaration, plus the human-
    # readable account of what was decided for every registered class.
    insertions: List[Tuple[int, str]] = []
    placed: List[str] = []
    already: List[str] = []
    unresolvable_undo: List[str] = []

    for class_name in sorted(resolved):
        site = resolve_undo_declaration_site(tree, class_name)
        if site.status == UNDO_DECLARATION_DECLARED:
            already.append(class_name)
            continue
        if site.status == UNDO_DECLARATION_UNDO_NOT_FOUND:
            unresolvable_undo.append(class_name)
            continue
        target_name = site.undo_defining_class
        target = _class_defs_by_name(tree).get(target_name or "")
        if target is None or not getattr(target, "end_lineno", None):
            unresolvable_undo.append(class_name)
            continue
        if target_name in placed:
            continue  # two registered classes sharing one undo definer
        placed.append(target_name)
        insertions.append((target.end_lineno, render_undo_declaration()))

    if not insertions:
        if already and not unresolvable_undo:
            return TransformResult(
                source, False,
                "every registered adapter class already records whether its "
                "undo step restores the prior state -- nothing to do",
                benign=True)
        # BENIGN, not a refusal: ``register_adapter`` captures ``cls.undo_one``
        # unconditionally, so a registered adapter with no ``undo_one`` anywhere
        # in its hierarchy cannot even import -- one with none in THIS module
        # inherits it from a base this static pass deliberately does not follow.
        # Blocking a whole project on that would be the over-firing guard
        # the capability-declared scope-correction warns about; the keystone is
        # the conformance post-condition, quantified over capability-declared
        # op_kinds only.
        return TransformResult(
            source, False,
            "no undo step is defined in this module for "
            f"{', '.join(unresolvable_undo)}, so there is nothing here for the "
            "undo-restore declaration to describe -- left untouched",
            benign=True)

    # Apply from the BOTTOM of the file upward so an earlier class's insertion
    # never shifts a later class's own end_lineno out from under it -- the same
    # ordering ``insert_missing_evidence_predicate_stubs`` uses.
    insertions.sort(key=lambda pair: pair[0], reverse=True)
    lines = source.splitlines(keepends=True)
    for end_lineno, text in insertions:
        lines[end_lineno:end_lineno] = [text]
    migrated = "".join(lines)

    try:
        new_tree = ast.parse(migrated)
    except SyntaxError:
        return TransformResult(
            source, False,
            "the rewrite would not have parsed, so nothing was changed")
    # END-STATE verification, not enumeration: re-resolve through the SAME
    # resolver and require every registered class to be honoured now. A rewrite
    # that inserted text but landed somewhere the runtime will not look is the
    # "looks migrated, still ineligible" failure this check exists to catch.
    for class_name in sorted(resolved):
        status = resolve_undo_declaration_site(new_tree, class_name).status
        if status not in (UNDO_DECLARATION_DECLARED,
                          UNDO_DECLARATION_UNDO_NOT_FOUND):
            return TransformResult(
                source, False,
                f"the rewrite did not record the undo-restore declaration where "
                f"it will actually be read for {class_name}, so nothing was "
                "changed")

    return TransformResult(
        migrated, True,
        "recorded whether the undo step restores the prior state (left as not "
        f"yet reviewed) on {', '.join(placed)}",
        detail=tuple(placed))
