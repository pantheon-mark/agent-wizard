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
    """

    source: str
    changed: bool
    reason: str
    detail: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MigrationContext:
    """Everything a migration may need that is not the source text itself.

    Deliberately a value object, not a live module handle: a migration must stay
    a pure function of its inputs so the engine can compose migrations in memory.
    """

    required_predicates: Tuple[str, ...] = field(default_factory=tuple)
