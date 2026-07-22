"""``bulk-verify`` / ``status`` — the operator-runnable verification command
(Task C3, Cut 1.1 Cluster C / F-78).

Why this exists
----------------
During the estate dogfood run, verifying what a bulk run actually did
required hand-authored raw-API python — and that hand-rolled script hit a
real bug (``_GmailReadOnlyClient.users`` — an ``AttributeError``, because the
estate's own read-only wrapper never exposed that attribute in the first
place). A non-technical operator can neither author nor debug that. This
module is the fix: a first-class, single-named, self-describing command that
reports what a run did WITHOUT any hand-authored python, using only this
project's own sanctioned primitives.

Two sources, kept honestly separate
------------------------------------
1. **Durable records** (always available, never guessed): ``run_envelope.
   report_run_recoverability`` — the SAME D5 primitive (F-81's fix) that
   reads reconciled totals + per-id recoverability from the persisted run
   envelope, never a live re-scrape. This is the authoritative source for
   "what happened" and is reported every time this command runs.
2. **Read-only facade confirmation** (best-effort, honestly bounded): an
   attempt to independently confirm each reviewed/applied unit's current
   state through ``capability_api.build_read_facade`` — the SAME sanctioned,
   capability-facing two-arg call every capability uses, never a hand-built
   client. This module does NOT assume any particular facade method exists
   (that is exactly the ``.users`` mistake this task closes) — it reads the
   facade's own declared ``read_methods`` and only drives a method
   generically when exactly ONE of them is an unambiguous single-id lookup
   (one required parameter, by introspection). When the facade cannot be
   built at all (no declared ``read_only_scope``, no read-only client
   supplied to this invocation, or any other failure), or its surface is
   ambiguous (zero or more than one single-id candidate — the real, shipped
   Gmail facade's surface IS ambiguous: ``get_message``/``get_filter`` both
   qualify), this is reported HONESTLY as "not confirmed" with a plain-
   language reason. Never a crash, never an ``AttributeError`` escaping to
   the operator.

Read-only client scope note (disclosed, not overclaimed): this module never
constructs a vendor read-only client itself (doing so would require a vendor
SDK import / credential handling, which is exactly what would make this
module NOT scanner-clean and NOT op-kind-agnostic). ``read_only_client`` is
an optional keyword a PROGRAMMATIC caller may supply (a wrapper the operator
project owns, with its own credential-holding code, entirely outside this
scanned lib package). The plain CLI invocation below (the one Task C2's
allowlist matches) has no such wrapper wired at this cut, so a CLI run always
takes the honest "not attempted" branch for facade confirmation and reports
durable-records reconciliation only — still a strict improvement over no
verify command at all, and never a false claim of independent confirmation.

READ-ONLY, by construction
----------------------------
This module reads ``run_envelope``'s durable records and, at most, calls a
registered ``ReadFacade``'s own declared read method. It never imports
``adapter_registry``, never references ``run_operation`` /
``run_enveloped_operation``, never constructs or names a write-capable
credential, and performs no filesystem write of its own. See
``test_bulk_verify.py``'s scanner-clean test for the deterministic proof.

Op-kind-agnostic / shape-neutral: this module's own text (docstrings, log
lines, operator-facing messages) never names a vendor, an op_kind, or a
concrete field ("Gmail", "TRASH", "message") — "bulk-verify" means the same
role in every emitted project, per ``command_manifest.py``'s own convention.

Stdlib only — no third-party dependencies. Ships into the operator's own
runtime, ``agents/lib/external_write/``, alongside every other module in this
package.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# sys.path bootstrap: mirrors every sibling module's own convention (scan.py,
# capability_invariants.py, run_envelope.py, ...) so the ``external_write.*``
# imports below resolve whether this module is imported as part of the
# package or run/loaded standalone (the real CLI shape below).
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.capability_api import build_read_facade  # noqa: E402
from external_write.read_facade import ReadFacadeEligibilityError  # noqa: E402
from external_write.run_envelope import (  # noqa: E402
    load_run_envelope,
    report_run_recoverability,
)


@dataclass(frozen=True)
class BulkVerifyResult:
    """The outcome of ``verify_bulk_run``.

    run_id / run_state / counts / per_id / verified_by_id: passed through
    verbatim from ``run_envelope.report_run_recoverability`` — this module
    never recomputes or reinterprets those figures.
    facade_confirmation: this module's OWN best-effort, honestly-bounded
      read-only-facade confirmation attempt (see module docstring). Always a
      dict with at least ``attempted``/``confirmed``/``note`` keys, never
      absent.
    operator_message: a single plain-language block combining both, in the
      same "reconciled totals in plain language" shape every consumer of
      this tool reads. Never contains a Python traceback.
    """

    run_id: str
    run_state: str
    counts: Dict[str, int]
    per_id: Dict[str, str]
    verified_by_id: Dict[str, bool]
    facade_confirmation: Dict[str, Any]
    operator_message: str


def _single_id_lookup_candidates(facade: Any, read_methods: Sequence[str]) -> List[str]:
    """The subset of ``read_methods`` whose BOUND signature on ``facade``
    takes exactly one required positional-or-keyword parameter (besides the
    already-bound ``self``) -- i.e. a plausible "look up one unit by id"
    method, decided by INTROSPECTION of the facade's own real, declared
    surface, never by assuming a specific name (the ``.users`` mistake this
    task closes). A method whose signature cannot be introspected is simply
    excluded, not treated as an error -- this is a best-effort narrowing, not
    a required capability of every read method."""
    candidates: List[str] = []
    for name in read_methods:
        try:
            bound = getattr(facade, name)
            sig = inspect.signature(bound)
        except (AttributeError, TypeError, ValueError):
            continue
        required = [
            p for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if len(required) == 1:
            candidates.append(name)
    return candidates


def _confirm_via_read_facade(
    op_kind: str, read_only_client: Optional[Any], unit_ids: Sequence[str],
) -> Dict[str, Any]:
    """This module's OWN best-effort, honestly-bounded attempt to confirm
    each id in ``unit_ids`` is still reachable through the vendor's real
    read-only API, via the SAME sanctioned ``capability_api.build_read_facade``
    every capability uses. Never raises -- every failure mode (no client
    supplied, no declared read-only scope, a facade whose surface is
    ambiguous, or a per-id call that itself raises) is folded into the
    returned dict as an honest, plain-language ``note``, never a crash and
    never an assumed attribute (see module docstring's ``.users`` note)."""
    if read_only_client is None:
        return {
            "attempted": False,
            "confirmed": False,
            "available_read_methods": [],
            "per_id": {},
            "note": (
                "No read-only client was supplied to this tool invocation, so final "
                "state could not be independently confirmed. The totals above are "
                "read from this project's own durable run records only."
            ),
        }

    try:
        facade = build_read_facade(op_kind, read_only_client)
    except ReadFacadeEligibilityError as exc:
        return {
            "attempted": True,
            "confirmed": False,
            "available_read_methods": [],
            "per_id": {},
            "note": (
                "This run's operation kind has no read-only confirmation channel "
                f"available: {exc}"
            ),
        }
    except Exception as exc:  # noqa: BLE001 - fail-closed, never let this crash the operator
        return {
            "attempted": True,
            "confirmed": False,
            "available_read_methods": [],
            "per_id": {},
            "note": f"Could not build a read-only confirmation channel for this run: {exc}",
        }

    read_methods = list(facade.read_methods)
    candidates = _single_id_lookup_candidates(facade, read_methods)

    if len(candidates) != 1:
        return {
            "attempted": True,
            "confirmed": False,
            "available_read_methods": read_methods,
            "per_id": {},
            "note": (
                f"The read-only facade for this run exposes {read_methods!r}, but this "
                "tool found no single unambiguous by-id lookup method it can safely "
                "drive generically, so per-unit final state was not confirmed. The "
                "totals above are read from durable run records only."
            ),
        }

    method = getattr(facade, candidates[0])
    per_id_confirmation: Dict[str, Dict[str, Any]] = {}
    for uid in unit_ids:
        try:
            method(uid)
        except Exception as exc:  # noqa: BLE001 - an honest per-id failure, never a crash
            per_id_confirmation[uid] = {"reachable": False, "detail": str(exc)}
        else:
            per_id_confirmation[uid] = {"reachable": True, "detail": None}

    return {
        "attempted": True,
        "confirmed": True,
        "available_read_methods": read_methods,
        "per_id": per_id_confirmation,
        "note": (
            f"This run's read-only facade ({candidates[0]!r}) was used to confirm "
            "whether each reviewed/applied unit is still reachable through the "
            "vendor's real read-only API."
        ),
    }


def _build_operator_message(
    report: Dict[str, Any], facade_confirmation: Dict[str, Any],
) -> str:
    counts = report["counts"]
    lines = [
        "This is a read-only check: it makes NO changes to anything. It only "
        "reads this project's own saved records and, where possible, looks "
        "up the current state to confirm them.",
        "",
        f"Run {report['run_id']!r} ({report['run_state']}) -- reconciled from this "
        "project's own durable records:",
        f"  reviewed: {counts['reviewed']} (of {counts['reviewed_total']} total ever "
        "reviewed for this run)",
        f"  applied: {counts['applied']} (of {counts['applied_total']} total ever "
        "applied for this run)",
        f"  recoverable by this system: {counts['recoverable_by_system']}",
        f"  NOT recoverable by this system: {counts['not_recoverable_by_system']}",
        f"  independently verified at apply time: {counts['verified']}",
        f"  applied but not independently verified: {counts['applied_not_verified']}",
        "",
        "Final-state confirmation (read-only, best-effort): " + facade_confirmation["note"],
    ]
    return "\n".join(lines)


def verify_bulk_run(
    run_id: str,
    *,
    envelope_dir: Optional[str] = None,
    candidate_unit_ids: Optional[Sequence[str]] = None,
    read_only_client: Optional[Any] = None,
) -> BulkVerifyResult:
    """The single entrypoint this module's CLI (below) and any programmatic
    caller use. Reconciled totals + per-id recoverability come from durable
    records ONLY (``run_envelope.report_run_recoverability`` -- never a live
    re-scrape); final-state confirmation is a SEPARATE, best-effort, honestly
    -bounded attempt through the read-only facade (see module docstring).
    READ-ONLY: performs no write, mutation, or mint of any kind.
    """
    report = report_run_recoverability(
        run_id, candidate_unit_ids=candidate_unit_ids, envelope_dir=envelope_dir)
    env = load_run_envelope(run_id, envelope_dir=envelope_dir)
    unit_ids: Tuple[str, ...] = tuple(report["per_id"].keys())
    facade_confirmation = _confirm_via_read_facade(env.op_kind, read_only_client, unit_ids)
    operator_message = _build_operator_message(report, facade_confirmation)
    return BulkVerifyResult(
        run_id=report["run_id"],
        run_state=report["run_state"],
        counts=report["counts"],
        per_id=report["per_id"],
        verified_by_id=report["verified_by_id"],
        facade_confirmation=facade_confirmation,
        operator_message=operator_message,
    )


# ---------------------------------------------------------------------------
# CLI entrypoint (Task C3) -- the exact, copy-paste command Task C2's
# settings-allowlist + PreToolUse hook both treat as read-only (see
# command_manifest.BASELINE_COMMANDS's "bulk-verify" entry, reserved at this
# exact path by Task C1). Runs read-only; never mutates, writes, or mints
# anything. Prints reconciled totals in plain language, never a Python
# traceback -- mirrors capability_invariants.py's own CLI shape exactly
# (positional ``<run_id>``, an optional ``<envelope_dir>``, exit 1 only on a
# usage error, exit 0 on a successful report regardless of what the report
# says -- this is a status command, not a pass/fail gate).
#
# Usage:
#   python3 agents/lib/external_write/bulk_verify.py <run_id> [envelope_dir]
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _cli_sys

    if len(_cli_sys.argv) < 2:
        print(
            "NOT READY -- usage: python3 bulk_verify.py <run_id> [envelope_dir]. "
            "No run_id was given, so nothing was checked."
        )
        _cli_sys.exit(1)

    _cli_run_id = _cli_sys.argv[1]
    _cli_envelope_dir = _cli_sys.argv[2] if len(_cli_sys.argv) > 2 else None
    _cli_result = verify_bulk_run(_cli_run_id, envelope_dir=_cli_envelope_dir)

    print(_cli_result.operator_message)
    _cli_sys.exit(0)
