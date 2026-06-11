"""Deterministic financial-guardrail projection (pure-code arithmetic).

The generated system's autonomous spend is governed against the plan's separate monthly
Agent-SDK automation credit (a real per-user dollar pool, effective 2026-06-15; not a flat-plan
ceiling). The wizard computes every dollar value; the operator answers only plain choices (plan,
sharing posture, exhaustion behavior). The two arithmetic values — the per-project budget and the
intensive-operation threshold — are the money safety-envelope, so they are computed HERE in pure
code, never authored by the model (LLM-authored arithmetic is a replay-drift + fabrication risk on
a number the operator is shown as authoritative and that keys the cost-log alert thresholds and the
cross-system fairness split).

Two `projection`-class fields (deterministic views of prior confirmed payload fields — same class
the dependency projections use; see derived-record-contract + derivation-prompts/projection.md):

  PROJECT_AUTOMATION_BUDGET      <- round(AUTOMATION_CREDIT_POOL x share fraction)
  INTENSIVE_OPERATION_THRESHOLD  <- max(1, round(0.10 x PROJECT_AUTOMATION_BUDGET))

The share fraction is fixed per the confirmed sharing posture: a system that is the operator's
SOLE automation system may use most of the pool; one of SEVERAL is held to a modest slice so the
operator's other wizard-built systems have room (the credit is per-USER, not per-system, so the
split is the only thing stopping one system from starving another — fairness-only/advisory, but it
parameterizes the real budget the agents meter against).

`AUTOMATION_CREDIT_POOL` itself is NOT computed here — it is an `extraction`-class plan->dollar
lookup the operator confirms against the visible plan table at step 02 (a lookup, not arithmetic).

Determinism: rounding is ROUND_HALF_UP on dollars (not Python's banker's rounding), so the same
inputs always yield byte-identical output — the property the change-propagation engine relies on to
auto-halt an unchanged financial subset. Fail-closed: an unparseable pool or out-of-enum share is a
hard error (no silent coercion of a money value).

Stdlib-only, pip-install-free.
"""

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List


# --- canonical field keys (the projections' _derivation_inputs) --------------
POOL_FIELD = "AUTOMATION_CREDIT_POOL"
SHARE_FIELD = "PROJECT_SHARE_POSTURE"
BUDGET_FIELD = "PROJECT_AUTOMATION_BUDGET"
THRESHOLD_FIELD = "INTENSIVE_OPERATION_THRESHOLD"

# Fixed share fractions by confirmed sharing posture (closed enum; fail-closed on anything else).
_SHARE_FRACTION = {
    "sole": Decimal("0.9"),
    "one-of-several": Decimal("0.4"),
}

# Intensive-operation threshold as a fraction of the project budget (one estimated-expensive
# operation above this pauses for operator approval). Mirrors scaffold INTENSIVE_OPERATION_THRESHOLD_PCT=10.
_THRESHOLD_FRACTION = Decimal("0.10")

# Each financial projection field and the prior confirmed field keys it reshapes.
_INPUTS: Dict[str, List[str]] = {
    BUDGET_FIELD: [POOL_FIELD, SHARE_FIELD],
    THRESHOLD_FIELD: [BUDGET_FIELD],
}

PROJECTION_FIELDS = frozenset(_INPUTS)


class FinancialProjectionError(Exception):
    """Raised on a malformed money input or out-of-enum share posture (fail-closed)."""


def derivation_inputs_for(field: str) -> List[str]:
    """The canonical field keys a given financial projection reshapes (its `_derivation_inputs`)."""
    try:
        return list(_INPUTS[field])
    except KeyError:
        raise FinancialProjectionError(
            f"unknown financial projection field {field!r}; known: {sorted(_INPUTS)}")


def _parse_dollars(raw: str, where: str) -> Decimal:
    """Parse a confirmed dollar string ('$100', '$40', '40', '$100/seat') -> Decimal dollars.
    Fail-closed: a money value we cannot read is a hard error, never a silent 0."""
    if not isinstance(raw, str) or not raw.strip():
        raise FinancialProjectionError(f"{where}: missing dollar value (got {raw!r})")
    cleaned = raw.replace(",", "")
    if "-" in cleaned:
        # A negative money value is malformed for an automation budget — fail closed rather than
        # silently parsing the digit run after the sign.
        raise FinancialProjectionError(f"{where}: dollar amount cannot be negative ({raw!r})")
    m = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not m:
        raise FinancialProjectionError(f"{where}: no parseable dollar amount in {raw!r}")
    return Decimal(m.group(0))


def _round_dollars(value: Decimal) -> int:
    """Round to whole dollars, ROUND_HALF_UP (deterministic; not banker's rounding)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def project(field: str, inputs: Dict[str, str]) -> str:
    """Compute one financial projection value from the prior confirmed field values.

    `inputs` maps each canonical input field key (per derivation_inputs_for) to its confirmed
    string value from the transcript. Returns the value as a '$<dollars>' string. Fail-closed on
    a missing required input, an unparseable pool/budget, or an out-of-enum share posture."""
    if field not in _INPUTS:
        raise FinancialProjectionError(
            f"unknown financial projection field {field!r}; known: {sorted(_INPUTS)}")
    for key in _INPUTS[field]:
        if key not in inputs:
            raise FinancialProjectionError(f"{field}: missing required input {key!r}")

    if field == BUDGET_FIELD:
        pool = _parse_dollars(inputs[POOL_FIELD], POOL_FIELD)
        share_raw = inputs[SHARE_FIELD]
        if share_raw not in _SHARE_FRACTION:
            raise FinancialProjectionError(
                f"{SHARE_FIELD}: value {share_raw!r} not in closed enum {sorted(_SHARE_FRACTION)}")
        budget = _round_dollars(pool * _SHARE_FRACTION[share_raw])
        return f"${budget}"

    # THRESHOLD_FIELD
    budget = _parse_dollars(inputs[BUDGET_FIELD], BUDGET_FIELD)
    threshold = max(1, _round_dollars(budget * _THRESHOLD_FRACTION))
    return f"${threshold}"


def main() -> int:
    import sys
    if len(sys.argv) < 2 or sys.argv[1] not in _INPUTS:
        print(f"usage: financial_projection.py <FIELD> [KEY=VALUE ...]", file=sys.stderr)
        print(f"  FIELD one of: {sorted(_INPUTS)}", file=sys.stderr)
        return 2
    field = sys.argv[1]
    inputs = {}
    for arg in sys.argv[2:]:
        k, _, v = arg.partition("=")
        inputs[k] = v
    try:
        print(project(field, inputs))
    except FinancialProjectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
