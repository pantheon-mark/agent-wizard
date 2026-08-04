"""Taking an approval back -- the operator's ENTRYPOINT to repudiating a capability's
acceptance, and the ONE renderer of the command that names it.

Why this module exists
----------------------
An operator could approve a capability for live external writes and had no way to un-approve it.
There was no command, and there was no function either. That gap has two faces, and the second
is the worse one:

  * an approval they changed their mind about stayed live, with a hand edit of a trust file as
    the only way out; and
  * a record of consent they do NOT recognise -- one whose receipt is gone, or that they never
    gave -- read as genuine to every future consumer of the acceptance log, with no sanctioned
    way to mark it otherwise.

This file is the operator-facing NAME for the act. ``REPUDIATION_ENTRYPOINT_REL`` is the path
that names it, ``repudiation_command`` is the ONE renderer of the invocation -- so every surface
that has to tell an operator what to run names the same one -- and the ``__main__`` block at the
bottom is the command.

Why the entrypoint is HERE and the transition is not
----------------------------------------------------
``lifecycle_state.repudiate_acceptance`` does the work, and this module does not re-implement any
part of it. Flipping ``accepted`` back to ``false`` is a state transition on the flag that
authorizes live writes; it belongs with the one function that already owned that transition (the
staleness revocation), and both now go through the same internal step. What lives here is the
operator's name for the act, the argument contract, and the plain-language output -- nothing that
decides anything.

Never a machine's decision
--------------------------
What this command records is the operator's own words. There is no default for them: a blank or
whitespace-only confirmation is refused by the parser here AND by the transition itself, and
nothing in this package writes that field from a literal. The flag is spelled
``--operator-confirmation`` deliberately -- the same spelling the acceptance CLI uses and the
same one the static baked-consent check watches -- so a command line built in code with the words
written in it is caught by the check that already exists, rather than by a second one nobody
wrote.

Enforcement ceiling (disclosure): build-time + operator-as-approver, NOT a runtime or OS sandbox
-- the same ceiling every module in this package discloses. Recording a withdrawal and clearing
the flag is the sanctioned path out; it is not a claim that nothing can set that flag again by
hand.

Stdlib only -- no third-party dependencies. The only non-stdlib imports are sibling modules of
this same trusted package.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# sys.path bootstrap (mirrors ``writer_acknowledgement.py`` / ``trial_recovery.py``): make the
# package parent importable when this file is run as a direct script from the project root,
# which is exactly how the operator invokes it.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.capability_identity import (  # noqa: E402
    IdentityResolutionError,
)
from external_write.lifecycle_state import (  # noqa: E402,F401
    ReconcileStateError,
    RepudiationResult,
    repudiate_acceptance,
)

__all__ = [
    "CONFIRMATION_PLACEHOLDER",
    "EXIT_BAD_ARGS",
    "EXIT_RECORDED",
    "EXIT_REFUSED",
    "FLAG_CAPABILITY",
    "FLAG_CONFIRMATION",
    "REPUDIATION_ENTRYPOINT_REL",
    "RepudiationResult",
    "USAGE",
    "parse_repudiation_args",
    "repudiate_acceptance",
    "repudiation_command",
]


# ---------------------------------------------------------------------------
# The entrypoint, and the ONE renderer of the command that names it
# ---------------------------------------------------------------------------

#: The project-relative path of THIS file in an emitted operator project. Spelled once, here,
#: because several surfaces render a command that has to point at it: this module's own
#: ``repudiation_command``, the emitted self-QA battery's dangling-receipt failure, and the
#: operator-invocable command manifest. A re-spelling is how a named repair comes to name a path
#: that no longer exists.
REPUDIATION_ENTRYPOINT_REL = "agents/lib/external_write/acceptance_repudiation.py"

FLAG_CAPABILITY = "--capability-id"
#: The SAME spelling the acceptance CLI uses, and the same one ``scan.OPERATOR_CONFIRMATION_FLAG``
#: watches for a machine-written literal. Deliberate: reusing it puts a baked repudiation inside
#: the reach of the static check that already exists. Pinned equal by test.
FLAG_CONFIRMATION = "--operator-confirmation"

#: What goes where the operator's own words go, in a command rendered BEFORE they have said them.
#: Deliberately carries no apostrophe: the rendered command quotes every interpolated value, and
#: an apostrophe inside a single-quoted shell argument turns a paste-ready line into a puzzle.
CONFIRMATION_PLACEHOLDER = "<what you said, word for word>"

# Process exit codes, following this package's existing CLI convention (0 = succeeded, 1 =
# refused by domain logic, 2 = usage error).
EXIT_RECORDED = 0
EXIT_REFUSED = 1
EXIT_BAD_ARGS = 2

USAGE = (
    f"Usage: python3 {REPUDIATION_ENTRYPOINT_REL} "
    f"{FLAG_CAPABILITY} <the capability> "
    f"{FLAG_CONFIRMATION} <your own words, on one line>\n"
    "Takes back your approval for ONE capability: it is switched off, your decision is put on "
    "record, and it is queued for a fresh trial if you ever want it back.\n"
    "The original approval record is kept -- nothing is erased, a withdrawal is added.\n"
    "Run it from your project's top folder.\n"
    f"Exit codes: {EXIT_RECORDED} = taken back; "
    f"{EXIT_REFUSED} = it did not finish -- read the message, which says whether anything "
    "changed (almost always nothing did, but the state check that runs AFTER the change can "
    f"fail on its own); {EXIT_BAD_ARGS} = the command was not understood."
)


def repudiation_command(capability_id: str, *,
                        operator_confirmation: Optional[str] = None) -> str:
    """The exact, paste-ready command that takes ONE capability's approval back.

    Rendered in ONE place so every surface that has to name this way out names the same one. A
    SINGLE PHYSICAL LINE, every interpolated value ``shlex.quote``'d -- a command that wraps is a
    paste hazard this package has already paid for once, and a capability id is data read off a
    file on disk.

    ``operator_confirmation`` is optional on purpose. A surface that renders this command as
    guidance -- a self-QA failure, a health report, a skill -- does not yet know what the
    operator will say, and it must not invent it: a machine that filled in an operator's decision
    would be forging it. Omitted, it renders as ``CONFIRMATION_PLACEHOLDER``, which is visibly a
    blank for the operator to replace.

    Fail-closed on a confirmation that spans lines: ``shlex.quote`` escapes shell metacharacters
    but does NOT strip an embedded newline, so interpolating one would emit a "single line"
    command that is not one. Raises rather than emit it -- the same rule, for the same reason, as
    the acknowledgement and acceptance renderers.
    """
    confirmation = (CONFIRMATION_PLACEHOLDER if operator_confirmation is None
                    else operator_confirmation)
    if "\n" in confirmation or "\r" in confirmation:
        raise ValueError(
            "refusing to build a repudiation command: the confirmation text contains a line "
            "break, and quoting does not strip one -- the rendered command would not be a "
            "single physical line. Use a single-line confirmation.")
    parts = ["python3", REPUDIATION_ENTRYPOINT_REL,
             FLAG_CAPABILITY, capability_id,
             FLAG_CONFIRMATION, confirmation]
    return " ".join(shlex.quote(p) for p in parts)


def parse_repudiation_args(
        argv: Any) -> Tuple[Optional[Dict[str, Optional[str]]], Optional[str]]:
    """Strict, fail-closed parse of a repudiation invocation's argv.

    Returns ``(options, None)`` for a recognized shape, or ``(None, message)`` for ANY other
    input. DENY BY DEFAULT: there is no branch that ignores an argument it does not recognize and
    proceeds anyway. This package has already shipped that defect once -- an unrecognized probe
    flag was silently dropped and the wrapper ran the live job regardless -- and what this
    command writes is a record of the operator's own decision.

    A blank or whitespace-only confirmation is refused HERE as well as by the transition itself:
    what the operator said is the whole content of the record, and an empty one would be a
    silent withdrawal recorded against nobody's words.

    The rendered ``CONFIRMATION_PLACEHOLDER`` is refused for the same reason, and it is not a
    cosmetic check. The command is rendered with that blank BEFORE the operator has said
    anything; pasted unedited it would write the machine's own placeholder into the audit log as
    their verbatim consent. The act would still be theirs, but the field's entire content is
    supposed to be THEIR words -- a machine-supplied stand-in sitting in it is the forged-consent
    shape, in the one field that exists to prevent it. Only the placeholder itself is refused
    (trimmed), so words that merely happen to quote the phrase still pass.
    """
    args = list(argv or ())
    options: Dict[str, Optional[str]] = {FLAG_CAPABILITY: None, FLAG_CONFIRMATION: None}
    index = 0
    while index < len(args):
        flag = args[index]
        if flag not in options:
            return None, f"unrecognized argument {flag!r}.\n\n{USAGE}"
        if index + 1 >= len(args):
            return None, f"{flag} needs a value.\n\n{USAGE}"
        options[flag] = args[index + 1]
        index += 2
    if not (options[FLAG_CAPABILITY] or "").strip():
        return None, f"missing required {FLAG_CAPABILITY}.\n\n{USAGE}"
    if not (options[FLAG_CONFIRMATION] or "").strip():
        return None, f"missing required {FLAG_CONFIRMATION}.\n\n{USAGE}"
    if (options[FLAG_CONFIRMATION] or "").strip() == CONFIRMATION_PLACEHOLDER:
        return None, (
            f"the {FLAG_CONFIRMATION} is still the blank the command was printed with "
            f"({CONFIRMATION_PLACEHOLDER}). Replace it with your own words -- what goes on "
            "record has to be what you said, not what was printed for you to fill in."
            f"\n\n{USAGE}")
    return options, None


# ---------------------------------------------------------------------------
# CLI -- the operator-invocable way to take an approval back.
#
# Kernel-side, like every other operator entrypoint in this package. It never claims more than
# the transition actually reached: the note it prints comes from the transition itself, which
# picks its wording from the state it observed AFTER reconciling, not from what it intended to do.
#
# On error output, stated to what the except tuple below actually establishes rather than as an
# absolute: the two failures this command can produce by its OWN logic -- an id that names no
# capability, and project state that cannot be read -- are caught and printed in plain language.
# An I/O failure underneath (the descriptor write, the log append) is NOT caught and would reach
# the operator as a traceback. That is a real residual, not a claim to have covered everything.
#
# Run from the project root, which is where the descriptor set and the acceptance log both
# resolve from. There is deliberately no --project-root flag: every operator-facing command this
# package ships is documented as run from the project's top folder, and a path flag is one more
# thing to get wrong on a command whose whole purpose is recording what the operator decided.
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _options, _error = parse_repudiation_args(_sys.argv[1:])
    if _error is not None:
        print(_error, file=_sys.stderr)
        _sys.exit(EXIT_BAD_ARGS)

    try:
        _result = repudiate_acceptance(
            ".", _options[FLAG_CAPABILITY],
            operator_confirmation=_options[FLAG_CONFIRMATION])
    except IdentityResolutionError as _exc:
        # Already plain language, no traceback text -- see that exception's own
        # `.operator_message`.
        print(f"nothing was changed -- {_exc.operator_message}", file=_sys.stderr)
        _sys.exit(EXIT_REFUSED)
    except ReconcileStateError as _exc:
        print(_exc.operator_message, file=_sys.stderr)
        _sys.exit(EXIT_REFUSED)

    if not _result.repudiated:
        print(_result.reason, file=_sys.stderr)
        _sys.exit(EXIT_REFUSED)

    print(_result.note)
    _sys.exit(EXIT_RECORDED)
