"""Operator acknowledgement of an unrepairable bespoke writer -- the ONE sanctioned
exit from ``WriterState.NEEDS_PERSON``, and the operator's ENTRYPOINT to it.

This module is the OPERATOR-FACING NAME for this act. Until now the exit existed
only as a Python function: a writer that needs a person had a real, working way out
that no surface an operator or their assistant reads ever named, so the state was
leavable only by someone who already knew to look. That is the same shape as a
state with no exit at all. The ``__main__`` block at the bottom of this file is the
command, ``ACKNOWLEDGEMENT_ENTRYPOINT_REL`` is the path that names it, and
``acknowledgement_command`` is the ONE renderer of the invocation -- so every
surface that has to tell an operator what to run names the same one.

Why the entrypoint is HERE and not in ``writer_commands``, where the function
lives: an operator reads the name of the command they are told to run. "Acknowledge
a writer" is what they are doing; "writer commands" is a layer in a diagram. The
other name stays internal and is never spelled in operator-facing text, so the two
are not two spellings of one thing. It also removes this module's own worst
property -- until this entrypoint existed it had zero production consumers, a
re-export facade shipped into every emitted project that nothing ever called.

This module keeps the name and the surface it has always had, because it is already
present in every emitted operator project, is enrolled in the emitted-lib file set,
and is loaded BY NAME by the build-side upgrade reconcile's own tests. What changed
is where the code lives: the machinery split into layers so the eligibility rule
could be tightened at all.

  * ``writer_ack_store``  -- the records: persistence, the hash-validity rule, and
                             the write primitive. Imports no sibling.
  * ``writer_commands``   -- the command: validates through the structural-state
                             core, writes through the store.

Both are re-exported here, so ``from external_write import writer_acknowledgement``
still gives you ``acknowledge_writer`` / ``active_acknowledgements`` /
``ACKNOWLEDGEMENTS_REL`` / ``ACKNOWLEDGEMENT_SCHEMA`` / ``WriterAcknowledgementError``
as the SAME objects, not copies -- asserted by identity in
``test_external_write_writer_state_layers.PublicSurfaceIdentityTests``. Nothing is
re-declared here and no value is re-spelled; there is still exactly one declaration
of each name.

Why the split was necessary
---------------------------
This module used to reach back into the state module for the open-entry list so it
could refuse to record a decision about a file nothing had flagged, while the state
module reached in here for the active records so it could label an entry
``acknowledged_risk``. Both imports were function-scope, so neither ever failed at
import time and nothing in the suite noticed the cycle -- but it meant any check
this side wanted to make about a writer's STATE had to come from the module already
asking it about decisions. The state question now goes to the structural-state core,
which knows nothing about records at all.

The four properties that keep this from being a hole -- explicit, hash-bound,
visible, audited -- are documented and enforced where they live, in
``writer_ack_store``. Never a silent dismissal: the word "acknowledge" is
deliberate, because the risk is accepted and recorded, not resolved.

Enforcement ceiling (disclosure): build-time + operator-as-approver, NOT a
runtime/OS sandbox -- the same ceiling every module in this package discloses. An
acknowledgement records a decision; it does not make the writer safe.

Stdlib only -- no third-party dependencies. The only non-stdlib imports are two
sibling modules of this same trusted package.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# sys.path bootstrap (mirrors ``trial_recovery.py`` / ``trial_journal.py``): make
# the package parent importable when this file is run as a direct script from the
# project root, which is exactly how the operator invokes it.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.writer_ack_store import (  # noqa: E402,F401
    ACKNOWLEDGEMENT_SCHEMA,
    ACKNOWLEDGEMENTS_REL,
    WriterAcknowledgementError,
    active_acknowledgements,
)
from external_write.writer_commands import acknowledge_writer  # noqa: E402,F401
from external_write.writer_state_core import (  # noqa: E402
    ExternalWriteStateReadError,
)

__all__ = [
    "ACKNOWLEDGEMENTS_REL",
    "ACKNOWLEDGEMENT_SCHEMA",
    "ACKNOWLEDGEMENT_ENTRYPOINT_REL",
    "CONFIRMATION_PLACEHOLDER",
    "EXIT_BAD_ARGS",
    "EXIT_RECORDED",
    "EXIT_REFUSED",
    "FLAG_CONFIRMATION",
    "FLAG_WRITER",
    "USAGE",
    "WriterAcknowledgementError",
    "acknowledge_writer",
    "acknowledgement_command",
    "active_acknowledgements",
    "parse_acknowledgement_args",
]


# ---------------------------------------------------------------------------
# The entrypoint, and the ONE renderer of the command that names it
# ---------------------------------------------------------------------------

#: The project-relative path of THIS file in an emitted operator project.
#: Spelled once, here, because several surfaces render a command that has to point
#: at it: this module's own ``acknowledgement_command``, the state->action registry
#: (through that function), the operator-invocable command manifest, and the
#: rebuild skill's operator-facing text. A re-spelling is how a named repair comes
#: to name a path that no longer exists.
ACKNOWLEDGEMENT_ENTRYPOINT_REL = "agents/lib/external_write/writer_acknowledgement.py"

FLAG_WRITER = "--writer"
FLAG_CONFIRMATION = "--operator-confirmation"

#: What goes where the operator's own words go, in a command rendered BEFORE they
#: have said them. Deliberately carries no apostrophe: the rendered command quotes
#: every interpolated value, and an apostrophe inside a single-quoted shell
#: argument turns a paste-ready line into a puzzle.
CONFIRMATION_PLACEHOLDER = "<what you said, word for word>"

# Process exit codes, following this package's existing CLI convention (0 =
# succeeded, 1 = refused by domain logic, 2 = usage error).
EXIT_RECORDED = 0
EXIT_REFUSED = 1
EXIT_BAD_ARGS = 2

USAGE = (
    f"Usage: python3 {ACKNOWLEDGEMENT_ENTRYPOINT_REL} "
    f"{FLAG_WRITER} <the flagged file> "
    f"{FLAG_CONFIRMATION} <your own words, on one line>\n"
    "Records that you accept the risk of leaving ONE flagged file as it is, for "
    "a file our own rebuild cannot rewrite for you.\n"
    "It records a decision; it does not make the file safe, and it does not "
    "switch anything on.\n"
    "The decision is kept on file, stays visible, and is asked again the moment "
    "that file changes.\n"
    "Run it from your project's top folder.\n"
    f"Exit codes: {EXIT_RECORDED} = recorded; "
    f"{EXIT_REFUSED} = not recorded (it says why); "
    f"{EXIT_BAD_ARGS} = the command was not understood."
)


def acknowledgement_command(writer_relpath: str, *,
                            operator_confirmation: Optional[str] = None) -> str:
    """The exact, paste-ready command that leaves ``needs_person`` for ONE writer.

    Rendered in ONE place so every surface that has to name this repair names the
    same one. A SINGLE PHYSICAL LINE, every interpolated value ``shlex.quote``'d --
    a command that wraps is the paste hazard this package has already paid for
    once, and a writer relpath is data read off a queue on disk.

    ``operator_confirmation`` is optional on purpose. A surface that renders this
    command as guidance -- a health report, an acceptance refusal, a skill -- does
    not yet know what the operator will say, and it must not invent it: a machine
    that filled in an operator's consent would be forging it. Omitted, the
    confirmation renders as ``CONFIRMATION_PLACEHOLDER``, which is visibly a blank
    to fill in and is refused by the command itself if pasted unchanged only in the
    sense that it is not what the operator said -- the operator replaces it.

    Fail-closed on a confirmation that spans lines: ``shlex.quote`` escapes shell
    metacharacters but does NOT strip an embedded newline, so interpolating one
    would emit a "single line" command that is not one. Raises rather than emit it,
    the same rule and for the same reason as the acceptance CLI's own renderer.
    """
    confirmation = (CONFIRMATION_PLACEHOLDER if operator_confirmation is None
                    else operator_confirmation)
    if "\n" in confirmation or "\r" in confirmation:
        raise ValueError(
            "refusing to build an acknowledgement command: the confirmation text "
            "contains a line break, and quoting does not strip one -- the "
            "rendered command would not be a single physical line. Use a "
            "single-line confirmation.")
    parts = ["python3", ACKNOWLEDGEMENT_ENTRYPOINT_REL,
             FLAG_WRITER, writer_relpath,
             FLAG_CONFIRMATION, confirmation]
    return " ".join(shlex.quote(p) for p in parts)


def parse_acknowledgement_args(
        argv: Any) -> Tuple[Optional[Dict[str, Optional[str]]], Optional[str]]:
    """Strict, fail-closed parse of an acknowledgement invocation's argv.

    Returns ``(options, None)`` for a recognized shape, or ``(None, message)`` for
    ANY other input. DENY BY DEFAULT: there is no branch that ignores an argument
    it does not recognize and proceeds anyway. This package has already shipped
    that defect once -- an unrecognized probe flag was silently dropped and the
    wrapper ran the live job regardless -- and what this command writes is a
    record of an operator's consent.

    A blank or whitespace-only confirmation is refused HERE as well as by the
    command itself: what the operator said is the whole content of the record, and
    an empty one would be a silent acknowledgement.

    The rendered ``CONFIRMATION_PLACEHOLDER`` is refused for the same reason. This
    command is printed with that blank BEFORE the operator has said anything;
    pasted unedited it would write this module's own placeholder into the record as
    their verbatim decision. The act would still be theirs, but the field's entire
    content is supposed to be THEIR words, and a machine-supplied stand-in sitting
    in it is the forged-consent shape in the one field that exists to prevent it.
    Only the placeholder itself is refused (trimmed), so words that merely happen to
    quote the phrase still pass.
    """
    args = list(argv or ())
    options: Dict[str, Optional[str]] = {FLAG_WRITER: None,
                                         FLAG_CONFIRMATION: None}
    index = 0
    while index < len(args):
        flag = args[index]
        if flag not in options:
            return None, f"unrecognized argument {flag!r}.\n\n{USAGE}"
        if index + 1 >= len(args):
            return None, f"{flag} needs a value.\n\n{USAGE}"
        options[flag] = args[index + 1]
        index += 2
    if not (options[FLAG_WRITER] or "").strip():
        return None, f"missing required {FLAG_WRITER}.\n\n{USAGE}"
    if not (options[FLAG_CONFIRMATION] or "").strip():
        return None, f"missing required {FLAG_CONFIRMATION}.\n\n{USAGE}"
    if (options[FLAG_CONFIRMATION] or "").strip() == CONFIRMATION_PLACEHOLDER:
        return None, (
            f"the {FLAG_CONFIRMATION} is still the blank the command was printed with "
            f"({CONFIRMATION_PLACEHOLDER}). Replace it with your own words -- what goes on "
            "record has to be what you said, not what was printed for you to fill in -- then "
            "run it again. If you are not sure what to put there, ask your assistant to show "
            "you the command with your own wording already in it."
            f"\n\n{USAGE}")
    return options, None


# ---------------------------------------------------------------------------
# CLI -- the operator-invocable exit from `needs_person`.
#
# Kernel-side, like every other operator entrypoint in this package. Never prints
# a traceback -- a non-technical operator reads this output -- and never claims the
# file is now safe: what it records is a decision to accept the risk.
#
# Run from the project root, which is where the writer relpaths in the queue and
# the acknowledgement store both resolve from. There is deliberately no
# --project-root flag: every operator-facing command this package ships is
# documented as run from the project's top folder, and a path flag is one more
# thing a non-technical operator could get wrong on the one command whose whole
# purpose is recording what they decided.
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _options, _error = parse_acknowledgement_args(_sys.argv[1:])
    if _error is not None:
        print(_error, file=_sys.stderr)
        _sys.exit(EXIT_BAD_ARGS)

    try:
        _record = acknowledge_writer(
            ".", _options[FLAG_WRITER],
            operator_confirmation=_options[FLAG_CONFIRMATION])
    except WriterAcknowledgementError as _exc:
        # A refusal, in plain language. Exit 1, so nothing checking the status
        # reads a refusal as a recorded decision.
        print(str(_exc), file=_sys.stderr)
        _sys.exit(EXIT_REFUSED)
    except ExternalWriteStateReadError:
        # Fail-closed: an existing-but-unreadable queue must never present as
        # "this file is not flagged" and refuse for the wrong reason, nor as
        # "it is flagged" and record against nothing.
        print("nothing was recorded -- the list of flagged files could not be "
              "read, so it is not possible to tell whether this file is one of "
              "them. Ask your assistant to look at "
              "agents/handoffs/pending_migrations.json with you, then run this "
              "again.", file=_sys.stderr)
        _sys.exit(EXIT_REFUSED)

    print(f"RECORDED: you accept the risk of leaving "
          f"{_record['writer_relpath']!r} as it is. This decision stays visible "
          "and will be asked again the moment that file changes. It does not "
          "make the file safe and it does not switch anything on.")
    _sys.exit(EXIT_RECORDED)
