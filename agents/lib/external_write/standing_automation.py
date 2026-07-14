"""Safe standing-automation entrypoint primitive (Task 9, B2 / F-42 -- v0.13.0 Slice 2).

Why this exists
----------------
Dogfood ground truth (estate-tracker, v0.11.0, log-confirmed): an emitted
standing-automation runner had no dry-run/check mode at all, and its own
hand-rolled argv handling SILENTLY IGNORED an unrecognized flag -- a
``--checkonly`` probe (a flag that does not exist) -- and ran the full live
job anyway. That fell through to a real, unapproved, off-schedule external
send (an email + digest actually went out). See
``external_review/estate-tracker_dogfood_finding_B2-safe-standing-automation_2026-07-13.md``.

R1 (design consult, finding F-R1.5) found that a lib primitive alone is
bypassable if every generated wrapper is left free to re-implement its own
flag handling: "a lib primitive a generated wrapper *might* call is fragile;
the safe parser must live at the actual executable boundary." So the fix here
is not "add a --check flag to the existing hand-rolled parser" -- it is "there
is no hand-rolled parser left to get wrong": a standing-automation runner
delegates its ENTIRE argv decision to `run_standing_automation` below, the
sole place that decides between a live run and a --check/--dry-run preview.
See ``agents/cron/cron_config.md``'s "Standing automation runners" section for
the enforcement-locus documentation (the Orchestrator, per that file's
single-coordination-point rule, is the single scheduled-invocation boundary
every scheduled job routes through).

The mechanism
-------------
1. Strict, fail-closed argv parsing (`parse_standing_automation_args`): the
   ONLY recognized shapes are an empty argv (live run) or exactly one of
   `--check` / `--dry-run` (preview). Anything else -- an unrecognized flag, a
   typo, extra arguments, a recognized flag combined with something else -- is
   a parse failure. Deny-by-default: there is no "else: ignore and proceed"
   branch. `run_standing_automation` treats a parse failure as a hard refusal
   and returns BEFORE `build_operation`, `run_live`, or `client` are ever
   touched -- an unrecognized flag can never fall through to a live run
   (closes the F-42 defect structurally, not just by adding a recognized
   flag).
2. `--check` / `--dry-run` reuse the EXISTING isolated `dry_run` test-target
   surface (ADR-0041 Amendment 2026-07-05) -- not a new fake check path. It
   builds the same Operation the live run would build, self-mints a receipt
   scoped ONLY to this local preview (`_mint_check_receipt` -- never returned,
   persisted, or usable to authorize anything else), and calls
   `external_write.adapters.run_operation(..., target="dry_run")`: the SAME
   function + code path a live run eventually uses, so the preview cannot
   silently diverge from the real read/plan/gate-evaluate logic. That
   function's own no-mutation guarantee (adapters.py Step 1.5) means
   `client.write` / `client.read` are never reached for a dry_run call,
   regardless of the operation's risk class or acceptance state -- already
   proven in test_external_write_adapters.py's TestDryRunNoMutation, and
   re-proven at THIS primitive's own boundary in
   test_external_write_standing_automation.py.
3. Op_kind-agnostic: nothing in this module inspects `op.op_kind`,
   `op.surface`, or `op.schema` -- it is a generic
   ``(argv, build_operation, run_live, client)`` dispatcher that any standing
   automation (a Gmail filter rule, a spreadsheet status sweep, a recurring
   digest email) reuses unmodified.

What this module deliberately does NOT do
------------------------------------------
It does not decide what the live job does (`run_live` is entirely
caller-supplied -- the caller's own production logic, unchanged), and it does
not mint or accept a receipt usable for a LIVE write: the live branch never
constructs or sees a receipt at all here -- the caller's own `run_live`
obtains its own live authorization exactly as it always has. The receipt
`_mint_check_receipt` builds authorizes nothing beyond the unconditional,
no-mutation `dry_run` preview.

Stdlib only -- no third-party dependencies.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Sequence

from external_write.operations import Operation, Result
from external_write.adapters import run_operation

# The only two recognized flags -- aliases for the same intent (a read + plan +
# gate-evaluate preview that makes no external call). Exactly one, alone, is
# the only non-empty argv this parser accepts; everything else is refused.
FLAG_CHECK = "--check"
FLAG_DRY_RUN = "--dry-run"
RECOGNIZED_FLAGS = (FLAG_CHECK, FLAG_DRY_RUN)
_RECOGNIZED_FLAG_SET = frozenset(RECOGNIZED_FLAGS)

USAGE = (
    "Usage: [--check | --dry-run]\n"
    "  (no arguments)   run this scheduled job for real\n"
    "  --check          preview only -- read, plan, and check whether this run\n"
    "                   would be allowed; sends nothing, writes nothing, calls\n"
    "                   nothing external\n"
    "  --dry-run        same as --check"
)

MODE_LIVE = "live"
MODE_CHECK = "check"
MODE_REFUSED = "refused_bad_args"

# Exit codes. Non-zero on a parse failure is the acceptance bar (never 0, so a
# caller checking the process exit status can never mistake a refused
# invocation for success). 2 mirrors this package's existing CLI convention
# for a usage/argument error (see acceptance_ceremony.py / coverage_gate.py's
# own __main__ blocks: 0 = succeeded, 1 = refused by domain logic, 2 = usage
# error).
EXIT_OK = 0
EXIT_BAD_ARGS = 2


@dataclass(frozen=True)
class StandingAutomationOutcome:
    """The outcome of one standing-automation invocation.

    mode:      MODE_REFUSED ("refused_bad_args") | MODE_CHECK ("check") | MODE_LIVE ("live").
    exit_code: the process exit code a wrapper's own `if __name__ == "__main__":`
               block should use (`sys.exit(outcome.exit_code)`).
    message:   one plain-language, operator-facing line describing what happened --
               never a traceback, never an internal label (op_kind / risk_class /
               gate / receipt) leaked into the text.
    result:    the underlying `Result` from `run_operation` (mode == "check"), or
               whatever `run_live` returned (mode == "live"); `None` for a refusal.
    """

    mode: str
    exit_code: int
    message: str
    result: Optional[Any] = None


def parse_standing_automation_args(argv: Sequence[str]):
    """Strict, fail-closed parse of a standing-automation invocation's argv.

    Returns ``(mode, None)`` for a recognized shape -- ``(MODE_LIVE, None)``
    for an empty argv, ``(MODE_CHECK, None)`` for a single recognized check
    flag -- or ``(None, message)`` for ANY other input: more than one
    argument, an unrecognized flag, a recognized flag combined with something
    else. `message` is a plain-language, resumable explanation (what was
    wrong + the valid usage), never a traceback.

    Deny-by-default: this function has no "else: ignore and proceed" branch,
    so the caller (`run_standing_automation`) can treat a ``None`` mode as an
    unconditional hard refusal -- it never guesses that an unrecognized
    argument was harmless (the exact F-42 defect: a `--checkonly` probe was
    silently ignored and the wrapper ran the full live job anyway).
    """
    args = list(argv)
    if len(args) == 0:
        return MODE_LIVE, None
    if len(args) == 1 and args[0] in _RECOGNIZED_FLAG_SET:
        return MODE_CHECK, None
    bad = next((a for a in args if a not in _RECOGNIZED_FLAG_SET), args[0])
    return None, (
        f"'{bad}' is not a recognized option for this scheduled job -- refusing "
        "to run it rather than guessing what you meant. This never falls "
        "through to a live run just because it does not recognize an "
        f"argument.\n\n{USAGE}"
    )


def _mint_check_receipt(op: Operation, *, clock: Optional[Callable[[], datetime]] = None) -> dict:
    """Self-mint a receipt for the LOCAL --check/--dry-run preview ONLY.

    Valid ONLY to unlock `run_operation`'s dry_run branch (Step 1 receipt
    validation -> Step 1.5 no-mutation preview) -- it is never returned to a
    caller, never persisted to disk, and never usable to authorize a live
    write. The live branch of `run_standing_automation` never constructs or
    sees a receipt from this function at all; the caller's own `run_live`
    obtains its OWN receipt through the operator's real approval/broker path
    exactly as it always has.
    """
    now = clock() if clock is not None else datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=300)
    return {
        "approved_operation_digest": op.digest(),
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _check_message(result: Result) -> str:
    """Render a plain-language, operator-facing line describing a --check outcome.

    Never leaks an internal label (op_kind, risk_class, target, gate) -- the
    underlying refusal reason (when present) is itself already written in
    plain language by write_gate.py / adapters.py, so it is surfaced verbatim.
    """
    detail = result.detail if isinstance(result.detail, dict) else {}
    if result.status == "written" and detail.get("dry_run") is True:
        return (
            "Check only -- nothing was sent, written, or changed. This job "
            "would be allowed to run for real on its next scheduled trigger."
        )
    reason = detail.get("reason") or result.status
    return (
        "Check only -- nothing was sent, written, or changed. This job would "
        f"NOT be allowed to run for real right now: {reason}"
    )


def run_standing_automation(
    argv: Sequence[str],
    *,
    build_operation: Callable[[], Operation],
    run_live: Callable[[Any], Any],
    client: Any,
    descriptor_set: Any = None,
    cap_ledger: Any = None,
    clock: Any = None,
) -> StandingAutomationOutcome:
    """The SOLE dispatcher a standing-automation runner uses to decide between a
    --check preview and a live run.

    A standing-automation runner (a Gmail filter sweep, a spreadsheet status
    sweep, a digest email, ...) calls this ONCE with its own argv and its own
    ``build_operation`` / ``run_live`` / ``client`` -- it must not parse flags
    itself and must not call ``run_live`` / touch ``client`` from anywhere
    else. That is what makes a wrapper built on this primitive unable to
    reproduce the F-42 defect: it has no other branch left to get wrong.

    Parameters
    ----------
    argv:            the runner's own argv (e.g. ``sys.argv[1:]``).
    build_operation: zero-arg callable returning the ``Operation`` this run
                     would perform. Called ONLY for a --check/--dry-run
                     preview or implicitly by the caller's own ``run_live`` for
                     a live run -- never called for a refused (bad-args)
                     invocation.
    run_live:        one-arg callable (given ``client``) that performs the
                     REAL scheduled job, exactly as it always has. Called
                     ONLY when ``argv`` parses to a live run (empty argv);
                     never called for --check/--dry-run and never called for
                     a refused invocation.
    client:          the surface client the live job would use. Passed to
                     `run_operation` for the --check path too (proving no
                     external call reaches it there), but never touched
                     directly by this function -- only `run_operation`'s own
                     dry_run no-mutation guarantee, or the caller's
                     `run_live`, ever calls it.
    descriptor_set / cap_ledger / clock: passed straight through to
                     `run_operation` for the --check path (irrelevant to a
                     dry_run call's outcome, which is unconditional, but kept
                     for API symmetry / deterministic tests).

    Returns
    -------
    A `StandingAutomationOutcome`. `run_standing_automation` itself never
    raises for a parse failure or a --check preview; the live path (mode ==
    "live") propagates whatever `run_live` itself raises or returns --
    that is the caller's own job logic, unchanged.
    """
    mode, error = parse_standing_automation_args(argv)
    if mode is None:
        return StandingAutomationOutcome(
            mode=MODE_REFUSED, exit_code=EXIT_BAD_ARGS, message=error, result=None)

    if mode == MODE_CHECK:
        op = build_operation()
        receipt = _mint_check_receipt(op, clock=clock)
        result = run_operation(
            op, receipt, client, target="dry_run",
            descriptor_set=descriptor_set, cap_ledger=cap_ledger, clock=clock)
        return StandingAutomationOutcome(
            mode=MODE_CHECK, exit_code=EXIT_OK, message=_check_message(result), result=result)

    # mode == MODE_LIVE -- the only path that may ever touch `client` for real.
    live_result = run_live(client)
    return StandingAutomationOutcome(
        mode=MODE_LIVE, exit_code=EXIT_OK, message="Live run completed.", result=live_result)
