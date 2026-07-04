"""Registered-capability-workflows PROJECTION (B1-6, NET-NEW): the QA-visible half of closing
the design's structural blind spot named in the B1-6 brief — the emitted QA agent reads
`quality/co-protected-workflows.md` on every audit and flags any artifact matching a REGISTERED
pattern; an off-plan capability the plan never anticipated (the mailbox capability in the estate
blowup) was invisible to that guard because nothing in the file registered it. Today the file is
a STATIC template: five generic wizard-constant categories (Financial / External communications /
Irreversible file-or-data / Guardrail / Legal) plus "How protection works" — zero placeholders,
emitted verbatim. This module ADDS a projected section over that static prose (the prose is
untouched) that lists each per-capability high-risk workflow, derived automatically from THIS
system's confirmed capability descriptors — so a capability the plan never anticipated still gets
a concrete, QA-matchable pattern instead of staying invisible until someone remembers to add it
by hand.

Reuses B1-2's capability_descriptor_registry.build_descriptor_entries() verbatim for entry shape
and fail-safe risk-class resolution (F-28 — an unknown/absent risk_class NEVER resolves to
read_only_local) — this module defines no new risk-resolution logic, only the registration
FILTER over the SAME entries: which risk classes are "co-protected" (require QA-visible
registration) and which are not.

Registration rule (design §4.5 — don't over-register): only PROTECTION-REQUIRING risk classes are
registered — `irreversible_external`, `standing_automation`, `sensitive_data`. `read_only_local`
and `reversible_external` are deliberately excluded: registering every capability regardless of
risk would give the QA agent (and, transitively, the operator reviewing its flags) no signal to
distinguish a real high-risk pattern from noise, training rubber-stamping instead of scrutiny — the
same over-firing failure mode the coverage gate (B1-5) and the fail-safe resolver (B1-1/B1-2) both
guard against from the opposite direction (never omitting a risk; never manufacturing one that
isn't there). Because build_descriptor_entries() already fail-safe-resolves an absent/unrecognized
risk_class to `irreversible_external` (F-28), an unclassified writer is never a silent fourth case
here — it already lands in the registered set through the same shared resolver B1-2 uses.

F-29 (standing_automation): a registered `standing_automation` capability is recognized here as a
distinct action class that enters the ceremony-maturity ladder — it starts supervised and earns
autonomy over a run of clean outcomes — but its RECOVERY FLOOR does NOT graduate: maturity
graduates supervision and narration, never the backup/recover safety net (mirrors the exact
phrasing of B1-4's adapter-side enforcement in `agents/lib/external_write/write_gate.py`: "Maturity
graduates supervision, never this safety net."). Every registered `standing_automation` row states
this explicitly — the QA-visible/narrated half of F-29; the adapter-side floor enforcement itself
is B1-4, already done, and is not re-implemented here.

`project()` -> CO_PROTECTED_CAPABILITY_ROWS: a `projection`-class markdown table BODY (rows only;
the template owns the header), mirroring the source_registry.md / capability_descriptor_registry.md
pattern used by `dependency_projection.py` / `capability_descriptor_registry.py`: template owns
header/prose (the five static categories + "How protection works" stay byte-for-byte what they
were), code owns the projected body via a single `{{CO_PROTECTED_CAPABILITY_ROWS}}` placeholder.

Stdlib-only, pip-install-free.
"""

from typing import Any, Dict, List

from capability_descriptor_registry import build_descriptor_entries  # type: ignore
from dependency_projection import IDENTITY_FIELD, DependencyProjectionError  # type: ignore


class CoProtectedWorkflowsError(DependencyProjectionError):
    """Raised on a malformed capability-descriptor input (fail-closed). Subclasses
    DependencyProjectionError so a caller already handling identity-parse / descriptor-registry
    failures catches this too without a second except clause."""


# The PROTECTION-REQUIRING risk classes (design §4.5): the only classes this projection
# registers. Deliberately a subset of dependency_projection.RISK_CLASSES, never a redefinition
# of it — see the module docstring for why read_only_local / reversible_external are excluded.
STANDING_AUTOMATION = "standing_automation"
PROTECTED_RISK_CLASSES = frozenset({
    "irreversible_external", STANDING_AUTOMATION, "sensitive_data",
})

# F-29: the fixed, non-graduating recovery-floor note stated on every registered
# standing_automation row. Phrasing mirrors B1-4's adapter-side enforcement message in
# agents/lib/external_write/write_gate.py verbatim ("Maturity graduates supervision, never
# this safety net.") so the QA-visible narration and the enforced behavior never diverge in
# wording. This module does not enforce the floor (that is B1-4); it registers/narrates it.
STANDING_AUTOMATION_FLOOR_NOTE = (
    "Runs on a recurring or unattended basis (a server-side filter, rule, or scheduled job), not "
    "a single confirmed action. It may enter the ceremony-maturity ladder — starting supervised "
    "and earning autonomy over a run of clean outcomes — but its recovery floor is "
    "NON-GRADUATING: maturity graduates supervision and narration, never the backup/recover "
    "safety net."
)

_PROTECTION_NOTE = {
    "irreversible_external": (
        "Has an external effect that cannot be undone without a backup or restore operation."
    ),
    "sensitive_data": (
        "Touches data that requires extra care (personal, financial, or confidential)."
    ),
    STANDING_AUTOMATION: STANDING_AUTOMATION_FLOOR_NOTE,
}

# This projection's field name (for derivation_inputs_for / project, mirroring
# capability_descriptor_registry.py's / dependency_projection.py's field-name constants).
MARKDOWN_FIELD = "CO_PROTECTED_CAPABILITY_ROWS"
_FIELDS = (MARKDOWN_FIELD,)


def derivation_inputs_for(field: str) -> List[str]:
    """The canonical field key this projection reshapes (its `_derivation_inputs`) — the SAME
    single source B1-2's descriptor registry reads (EXTERNAL_DEPENDENCY_IDENTITY; the five
    descriptor fields live there only, so no ANNOTATION join is needed here either)."""
    if field in _FIELDS:
        return [IDENTITY_FIELD]
    raise CoProtectedWorkflowsError(
        f"unknown co-protected-workflows field {field!r}; known: {sorted(_FIELDS)}")


def build_registered_workflows(identity_json: str) -> List[Dict[str, Any]]:
    """Filter B1-2's descriptor entries (build_descriptor_entries) down to the ones whose
    fail-safe-resolved risk_class requires protection (PROTECTED_RISK_CLASSES). No re-derivation
    of risk resolution, action_class validation, or entry shape — this is purely a registration
    filter over entries B1-2 already produces. Fail-closed (propagates
    DependencyProjectionError on malformed input); deterministic (input order preserved)."""
    entries = build_descriptor_entries(identity_json)  # fail-closed; F-28 fail-safe risk_class
    return [e for e in entries if e["risk_class"] in PROTECTED_RISK_CLASSES]


def _md_cell(text: Any) -> str:
    # Markdown table cells cannot contain a raw pipe; escape defensively (mirrors
    # dependency_projection._md_cell / capability_descriptor_registry._md_cell).
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def project(field: str, identity_json: str) -> str:
    """Produce the markdown table BODY (rows only; the template owns the header) for
    CO_PROTECTED_CAPABILITY_ROWS: one row per build_registered_workflows() entry, columns
    Capability | Action class | Risk class | What's protected (mirrors
    wizard/templates/quality/co-protected-workflows.md's "Registered capability workflows"
    header). Returns "" when no capability's risk_class requires protection (valid empty body —
    the static prose above and below the placeholder still emits)."""
    if field != MARKDOWN_FIELD:
        raise CoProtectedWorkflowsError(
            f"unknown co-protected-workflows markdown field {field!r}; known: {MARKDOWN_FIELD!r}")
    rows = build_registered_workflows(identity_json)
    lines: List[str] = []
    for e in rows:
        action_class = e["action_class"] if e["action_class"] is not None else "Unknown"
        note = _PROTECTION_NOTE.get(e["risk_class"], "Protected — see risk class.")
        cells = [
            _md_cell(e["name"]),
            _md_cell(action_class),
            _md_cell(e["risk_class"]),  # never None (fail-safe resolved by build_descriptor_entries)
            _md_cell(note),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: co_protected_workflows.py <identity.json>", file=sys.stderr)
        return 2
    identity = open(sys.argv[1], encoding="utf-8").read()
    try:
        print(project(MARKDOWN_FIELD, identity))
    except DependencyProjectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
