"""The operator-invocable command manifest (Task C1, Cut 1.1 Cluster C / F-78).

Why this exists
----------------
During the estate dogfood run, a non-technical operator could not run the
emitted verify/scan/self-QA tools: they were blocked by Claude Code's
auto-mode permission classifier, needed interpreter-hunting, or required a
hand-authored python one-liner to drive. F-78's fix is a settings-allowlist
(Task C2's `.claude/settings.json` `permissions.allow`) plus a PreToolUse
auto-approve hook (Task C2) plus an operator-facing blast-radius disclosure
(Task C3/C4) -- and every one of those three consumers needs the SAME
answer to one question: is THIS command read-only (safe to run without
interrupting the operator) or a live write (must always ask)?

This module is that single source. It classifies every operator-invocable
command this project ships by ROLE, not by a hardcoded per-vendor/per-op-kind
name -- "capability_invariants" and "bulk-review" mean the same thing in a
Gmail-backed project or an Acme-CRM-backed one; only the concrete script
underneath varies. Task C2 (settings-allowlist + PreToolUse hook) and Task C3
(the `bulk-verify`/`status` command this manifest reserves a slot for below)
both read this module rather than re-deriving their own classification --
exactly the same "one canonical source, every consumer reads it, none
re-implements it" discipline `capability_invariants.py`'s own seven checks
already follow for the primitives THEY compose.

The one invariant that matters most: allowlist eligibility
------------------------------------------------------------
A `live_write` command must NEVER be allowlist-eligible. `is_allowlist_eligible`
below is the single predicate every consumer must call -- it is computed FRESH
from `command_class` + `writes_external` every time, never a stored per-entry
boolean a manifest author (or a careless future edit) could flip independently
of the fields that actually describe the command's behavior. See that
function's own docstring for exactly why this holds even for a malformed or
duck-typed entry that does not go through `CommandEntry.__post_init__`'s own
construction-time guard.

Stdlib only -- no third-party dependencies. Ships into the operator's own
runtime, `agents/lib/external_write/`, alongside every other module this
package's docstrings describe as "ships into the operator's own runtime".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# The three command classes (locked design, Cut 1.1 Cluster C plan, Task C1).
# ---------------------------------------------------------------------------
READ_ONLY = "read_only"
READ_ONLY_PII = "read_only_pii"
LIVE_WRITE = "live_write"

_VALID_CLASSES = frozenset({READ_ONLY, READ_ONLY_PII, LIVE_WRITE})
_ELIGIBLE_CLASSES = frozenset({READ_ONLY, READ_ONLY_PII})


class CommandManifestError(ValueError):
    """Raised when a manifest entry's own declared fields are not well-formed
    (an unrecognized `command_class`, or a `live_write` entry that does not
    also declare `writes_external=True`) -- caught at construction time,
    never silently accepted. See `CommandEntry.__post_init__`."""


@dataclass(frozen=True)
class CommandEntry:
    """One operator-invocable command's classification.

    name:            the logical command role (e.g. "capability_invariants",
                      "bulk-review") -- op-kind-agnostic; the same name means
                      the same role in every emitted project regardless of
                      which vendor/capability the underlying script targets.
    command_prefix:  the invocable command-line prefix a consumer (Task C2's
                      settings-allowlist / PreToolUse hook) matches against.
                      For a fixed, always-shipped lib script this is the real,
                      literal prefix (verified against this project's own
                      emitted CLI entrypoints -- see the module docstring's
                      cross-references below). For a per-capability-generated
                      command (the live-write role, whose concrete script name
                      is decided per capability at scaffold time) this is a
                      representative, documented shape, not a literal
                      standing invocation -- Task C2 never needs to MATCH a
                      live_write prefix to grant an allow-rule (a live_write
                      command is never allow-eligible in the first place; see
                      `is_allowlist_eligible`), so a representative shape is
                      sufficient here.
    command_class:   one of READ_ONLY / READ_ONLY_PII / LIVE_WRITE.
    writes_external: True iff running this command can perform a live write to
                      an external system (a vendor mailbox, a sheet, ...).
    allowed_outputs: plain-language description(s) of what this command may
                      print/produce -- the same disclosure Task C3/C4's
                      operator-facing blast-radius text reads from, so that
                      text is never hand-authored out of sync with what the
                      manifest actually classifies.
    """

    name: str
    command_prefix: str
    command_class: str
    writes_external: bool
    allowed_outputs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.command_class not in _VALID_CLASSES:
            raise CommandManifestError(
                f"command {self.name!r} declares command_class={self.command_class!r}, "
                f"which is not one of {sorted(_VALID_CLASSES)}"
            )
        # A live_write entry must also honestly declare writes_external=True --
        # the two fields describe the same underlying fact (this command can
        # perform a real external write) and must agree. This is a
        # construction-time hardening layer, not the thing that actually makes
        # eligibility safe: is_allowlist_eligible below denies a live_write
        # command regardless of writes_external's value, and denies a
        # writes_external=True command regardless of command_class's value --
        # see that function's own docstring for why the predicate itself, not
        # this guard, is the load-bearing invariant.
        if self.command_class == LIVE_WRITE and not self.writes_external:
            raise CommandManifestError(
                f"command {self.name!r} is declared command_class=live_write but "
                "writes_external is False -- a live-write command must also "
                "declare writes_external=True (fix this manifest entry)."
            )


def is_allowlist_eligible(entry) -> bool:
    """The ONE predicate every consumer of this manifest -- Task C2's
    settings-allowlist build, Task C2's PreToolUse auto-approve hook, and the
    operator-facing blast-radius disclosure -- must call to decide whether a
    command may ever be auto-approved. Never re-derive this logic at the call
    site; read this function.

    `entry` only needs `.command_class` and `.writes_external` attributes (a
    `CommandEntry`, or any duck-typed object with those two fields) -- this is
    deliberate: the guarantee below must hold even for an entry that never
    passed through `CommandEntry.__post_init__`'s construction-time guard.

    By construction, NOT a stored per-entry flag:
      * `entry.command_class not in {read_only, read_only_pii}` alone is
        sufficient to return False -- a `live_write` entry is excluded here
        regardless of what its own `writes_external` field says (even a
        malformed entry that somehow carries command_class=live_write with
        writes_external=False -- impossible to construct as a real
        `CommandEntry` per `__post_init__`, but not impossible for an
        arbitrary duck-typed object -- still resolves ineligible).
      * `entry.writes_external` being True alone is ALSO sufficient to return
        False -- a mistakenly-mislabeled entry (command_class=read_only but
        writes_external=True) is excluded here too, regardless of its class.
    There is no single field whose value alone GRANTS eligibility; both
    conditions must hold, and either one alone is enough to deny it. This is
    what makes "you cannot mark a live-write command allowlist-eligible" true
    of the predicate itself, not merely of well-behaved manifest authoring.
    """
    return entry.command_class in _ELIGIBLE_CLASSES and not entry.writes_external


# ---------------------------------------------------------------------------
# Baseline commands (Task C1). Every prefix below for an ALREADY-SHIPPED
# lib script is the real, verified invocation this project's own skills
# already document (see skills/next-phase.md, skills/rebuild-paused-
# capability.md, and each module's own "CLI entrypoint" docstring section) --
# not invented here. `bulk-review` is the estate dogfood's own name for the
# scan/review role (F-78's "runner.py bulk-review (scan)"); this project's
# real equivalent for that role is `scan.py`, the AST bypass scanner. Kept
# distinct from `capability_invariants`/`capability_health` (this project's own
# additional read-only self-QA commands) so the manifest covers every
# operator-invocable read-only tool, not only the ones the plan named.
#
# `bulk-verify` (Task C3, forthcoming): reserved here, read_only, so Task C2's
# allowlist and Task C3's actual implementation agree on the same prefix from
# the start -- Task C3 must build `bulk_verify.py` at the path named below,
# not invent its own.
#
# `bulk-apply --target live` represents the live-write role every scaffolded
# capability's own `run_approved`/`run_bulk_approved` entrypoint exposes (see
# scripts/lib/capability_code_scaffold.py's rendered `target: str = "live"`
# parameter) -- the concrete script name is decided per capability at scaffold
# time, so `command_prefix` here is representative, not a literal standing
# invocation (see `CommandEntry.command_prefix`'s own docstring for why that is
# sufficient: a live_write entry is never allow-eligible, so nothing needs to
# prefix-match it to grant an allow-rule).
# ---------------------------------------------------------------------------
BASELINE_COMMANDS: Tuple[CommandEntry, ...] = (
    CommandEntry(
        name="capability_invariants",
        command_prefix="python3 agents/lib/external_write/capability_invariants.py",
        command_class=READ_ONLY,
        writes_external=False,
        allowed_outputs=(
            "a plain-language structural pass/fail report for one capability, to stdout",
        ),
    ),
    CommandEntry(
        name="capability_health",
        command_prefix="python3 agents/lib/external_write/capability_health.py",
        command_class=READ_ONLY,
        writes_external=False,
        allowed_outputs=(
            "a plain-language capability health report (JSON) to stdout",
        ),
    ),
    CommandEntry(
        name="bulk-review",
        command_prefix="python3 agents/lib/external_write/scan.py",
        command_class=READ_ONLY,
        writes_external=False,
        allowed_outputs=(
            "a structural safety-scan violation report to stdout",
        ),
    ),
    CommandEntry(
        name="bulk-verify",
        command_prefix="python3 agents/lib/external_write/bulk_verify.py",
        command_class=READ_ONLY,
        writes_external=False,
        allowed_outputs=(
            "reconciled totals + recoverability, from durable records only "
            "(Task C3 builds this command against this reserved prefix)",
        ),
    ),
    CommandEntry(
        name="bulk-apply --target live",
        command_prefix="python3 agents/<capability>.py bulk-apply --target live",
        command_class=LIVE_WRITE,
        writes_external=True,
        allowed_outputs=(),
    ),
    CommandEntry(
        name="operator-acceptance",
        command_prefix="python3 agents/lib/external_write/operator_acceptance.py",
        command_class=LIVE_WRITE,
        writes_external=True,
        allowed_outputs=(),
    ),
)


def find_command(name: str, commands: Tuple[CommandEntry, ...] = BASELINE_COMMANDS) -> Optional[CommandEntry]:
    """The `CommandEntry` named `name` in `commands` (default: the shipped
    `BASELINE_COMMANDS`), or `None` if no entry carries that name. Linear scan
    over a handful of entries -- no index worth maintaining at this size."""
    for entry in commands:
        if entry.name == name:
            return entry
    return None


def allowlist_eligible_prefixes(commands: Tuple[CommandEntry, ...] = BASELINE_COMMANDS) -> Tuple[str, ...]:
    """The `command_prefix` of every entry in `commands` for which
    `is_allowlist_eligible` is True, in manifest order. Task C2's
    settings.json `permissions.allow` build reads THIS -- it must never
    re-derive eligibility itself (see `is_allowlist_eligible`'s own
    docstring)."""
    return tuple(entry.command_prefix for entry in commands if is_allowlist_eligible(entry))


def manifest_as_dicts(commands: Tuple[CommandEntry, ...] = BASELINE_COMMANDS) -> list:
    """A plain, JSON-serializable projection of `commands` -- a list of dicts
    keyed exactly per the locked design (`class`, `writes_external`,
    `allowed_outputs`, plus `name` and `command_prefix`). This is how a
    non-python consumer (Task C2's `.sh` PreToolUse hook) reads this manifest:
    `python3 -c "import json, command_manifest as m; print(json.dumps(m.manifest_as_dicts()))"`
    -- the same python3-subprocess convention `receipt_gate.sh` already uses
    for its own decision logic, rather than maintaining a second, independently
    -driftable copy of this data as a static file on disk."""
    return [
        {
            "name": entry.name,
            "command_prefix": entry.command_prefix,
            "class": entry.command_class,
            "writes_external": entry.writes_external,
            "allowed_outputs": list(entry.allowed_outputs),
            "allowlist_eligible": is_allowlist_eligible(entry),
        }
        for entry in commands
    ]
