"""The declared set of adapter migrations the upgrade engine iterates.

Why a declared set
------------------
An adapter migration used to be a function somebody had to remember to call. One
was written, reviewed, tested against copies of real operator adapters -- and
never wired to any real flow, so every existing install stayed broken while a
fresh install was correct and every gate stayed green. Membership in
``ADAPTER_MIGRATIONS`` is now the ONLY way a migration exists: the engine
iterates this tuple, so writing a migration without wiring it is not a mistake
you can make.

Every migration is a PURE function of source text. It returns replacement source;
it never reads or writes a file. The engine reads each adapter module once,
threads the text through every migration in order, and writes once atomically --
so two migrations on the same module can never clobber each other.

Stdlib only. Build-side toolkit code -- ships with the engine, never into the
operator project's emitted lib.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Tuple


@dataclass(frozen=True)
class TransformResult:
    """What one migration did to one module's source text.

    ``changed`` is the ONLY signal the engine acts on. ``reason`` is
    operator-facing plain language and is recorded whether or not anything
    changed -- a refusal that goes nowhere is how remediation outcomes get lost.

    ``benign`` is True ONLY for an unchanged outcome that means "correctly
    nothing to do" -- the module already has whatever this migration would have
    added. It is False (the default) for EVERY unchanged outcome that means "I
    could not act and a human must": an unparseable module, a class that could
    not be uniquely resolved, a missing insertion point, or anything else this
    migration refused to guess at. A structural flag rather than matching words
    in ``reason``, because prose can change (or a refusal reason can coincide
    with benign-sounding words) without the underlying outcome changing -- the
    caller that decides whether to queue a blocking entry must never have to
    re-derive "was this actually a no-op" from a string.
    """

    source: str
    changed: bool
    reason: str
    detail: Tuple[str, ...] = field(default_factory=tuple)
    benign: bool = False


@dataclass(frozen=True)
class MigrationContext:
    """Everything a migration may need that is not the source text itself.

    Deliberately a value object, not a live module handle: a migration must stay
    a pure function of its inputs so the engine can compose migrations in memory.
    """

    required_predicates: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AdapterMigration:
    """One declared adapter migration.

    ``name`` is stable and operator-visible: it is recorded on every queue entry
    and every refusal reason, so an outcome can always be traced back to the
    migration that produced it.
    """

    name: str
    plan: Callable[[str, MigrationContext], TransformResult]


def _provisioner_migration(source: str, context: MigrationContext) -> TransformResult:
    # Imported lazily: provisioner_migration imports this module for its value
    # types, so a module-scope import here would be circular.
    from provisioner_migration import plan_provisioner_migration
    return plan_provisioner_migration(source, context)


def _evidence_predicate_migration(source: str,
                                  context: MigrationContext) -> TransformResult:
    from capability_code_scaffold import plan_missing_evidence_predicates
    return plan_missing_evidence_predicates(source, context)


#: The declared set, applied IN ORDER to one in-memory copy of each adapter
#: module. Order is deliberate and load-bearing: the evidence-predicate stub
#: inserts at the registered class's end_lineno, and moving the read-client
#: builder onto that same class also changes where the class ends. Running the
#: predicate stub first preserves the behaviour that shipped before the two were
#: composed, and the engine re-parses between migrations so the second one sees
#: the first one's real line numbers.
ADAPTER_MIGRATIONS: Tuple[AdapterMigration, ...] = (
    AdapterMigration("missing_evidence_predicates", _evidence_predicate_migration),
    AdapterMigration("module_level_provisioner", _provisioner_migration),
)
