"""The capability-descriptor REGISTRY (B1-2, NET-NEW): two renderings of one projection over
the typed capability-descriptor fields B1-1 added to EXTERNAL_DEPENDENCY_IDENTITY.

D-B1-b (LOCKED): the descriptor registry IS the machine-readable accepted-descriptor set that
governs runtime enforcement. Every entry defaults `accepted: false` — fail-safe: until something
explicitly marks an entry accepted (a B2 runtime flow, not this module), downstream enforcement
(B1-4's adapter, B1-5's coverage gate) must refuse to treat the capability as live.

Two renderings, ONE projection over the same canonical field (EXTERNAL_DEPENDENCY_IDENTITY —
descriptor fields live there only; ANNOTATION carries no descriptor data, so unlike the three
dependency_projection.py surfaces this projection needs no annotation join):

  (A) build_descriptor_entries() / render_descriptor_registry_json()
      The machine-readable set — a list of dicts, one per descriptor-bearing dependency, with
      EXACTLY the keys: id, name, action_class, risk_class, recovery_profile_ref,
      declared_test_target, blast_radius_cap, accepted. THIS is the cross-task contract B1-4's
      runtime adapter and B1-5's build-time coverage gate consume (schema documented on
      build_descriptor_entries below). Physical emission into the operator's security/ directory
      is deferred to B2 (see the B1-2 report) — this module is the pure-code producer + schema.

  (B) project() -> CAPABILITY_DESCRIPTOR_REGISTRY_ROWS
      A `projection`-class markdown table BODY (rows only; the template owns the header),
      mirroring the source_registry.md pattern in dependency_projection.py: human/QA-readable
      view of the same entries, for wizard/templates/quality/capability_descriptor_registry.md.

Inclusion rule (documented decision, per the B1-2 brief's open question): a dependency is
included in EITHER rendering iff it carries at least one of the five descriptor fields (i.e. it
was captured as a CAPABILITY, not a bare data source). A dependency with none of the five fields
present is not a capability at all in this taxonomy and is excluded from both renderings — it
never reaches B1-4's adapter as a governed action, so listing it here (with a fabricated
action_class) would misrepresent it as one. A dependency that carries SOME but not all fields
(e.g. action_class set, risk_class omitted) IS included, with risk_class always fail-safe-resolved
via B1-1's resolve_risk_class() (F-28: never silently downgraded to read_only_local) and every
other absent descriptor field carried through as `None` (JSON null) rather than fabricated.

Fail-closed parse: reuses dependency_projection.parse_identity(), which already validates every
present descriptor field and raises DependencyProjectionError on malformed JSON, a non-array
payload, a non-object entry, or an out-of-vocabulary field value — never silently drops a
capability.

Stdlib-only, pip-install-free.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from dependency_projection import (  # type: ignore
    parse_identity, resolve_risk_class, IDENTITY_FIELD, DependencyProjectionError, UNKNOWN,
)


class CapabilityDescriptorRegistryError(DependencyProjectionError):
    """Raised on a malformed capability-descriptor registry input (fail-closed). Subclasses
    DependencyProjectionError so a caller already handling identity-parse failures catches this
    too without a second except clause; distinct name so a registry-specific failure (e.g. an
    unknown projection field) is identifiable in its own right."""


# The five OPTIONAL descriptor fields (B1-1, dependency_projection.py). A dependency "carries
# descriptor fields" iff at least one of these keys is present on its identity row (regardless of
# value) — that presence is what marks it as a CAPABILITY rather than a bare data source.
_DESCRIPTOR_FIELDS = (
    "action_class", "risk_class", "recovery_profile_ref", "declared_test_target",
    "blast_radius_cap",
)

# The machine-readable entry's exact key order (the cross-task contract for B1-4 / B1-5).
# `phase_id` is an ADDITIVE per-entry key: it binds an operator-declared capability to the plan
# phase it was defined under, and the acceptance ceremony REQUIRES it before it will ever flip a
# descriptor to accepted:true (a descriptor with no phase binding can never be accepted — fail-
# safe). It defaults to None here: at build/interview time no plan phase is known; the operate-
# time add-capability cascade (which lands a descriptor via the operator-side registration helper)
# is what populates it. The coverage gate and the runtime write gate read only their own keys and
# ignore phase_id entirely, so adding it is transparent to them.
ENTRY_KEYS = (
    "id", "name", "action_class", "risk_class", "recovery_profile_ref",
    "declared_test_target", "blast_radius_cap", "accepted", "phase_id",
)

# This projection's field names (for derivation_inputs_for / project, mirroring
# capability_projection.py's / dependency_projection.py's field-name constants).
REGISTRY_FIELD = "CAPABILITY_DESCRIPTOR_REGISTRY"
MARKDOWN_FIELD = "CAPABILITY_DESCRIPTOR_REGISTRY_ROWS"
_FIELDS = (REGISTRY_FIELD, MARKDOWN_FIELD)


def _carries_descriptor_fields(row: Dict[str, Any]) -> bool:
    return any(f in row for f in _DESCRIPTOR_FIELDS)


def derivation_inputs_for(field: str) -> List[str]:
    """The canonical field key(s) this projection reshapes (its `_derivation_inputs`). Both
    renderings read ONLY EXTERNAL_DEPENDENCY_IDENTITY — the five descriptor fields live there;
    EXTERNAL_DEPENDENCY_ANNOTATION carries no descriptor data, unlike the three
    dependency_projection.py surfaces that also join annotation for purpose/what-stops text."""
    if field in _FIELDS:
        return [IDENTITY_FIELD]
    raise CapabilityDescriptorRegistryError(
        f"unknown capability descriptor registry field {field!r}; known: {sorted(_FIELDS)}")


def build_descriptor_entries(identity_json: str) -> List[Dict[str, Any]]:
    """Build the machine-readable descriptor-set entries (rendering A) from the canonical
    EXTERNAL_DEPENDENCY_IDENTITY record. Fail-closed: parse_identity() raises
    DependencyProjectionError on any malformed record or descriptor field.

    One entry per identity row that carries >=1 descriptor field, in input order (deterministic:
    identical input -> identical output). Each entry has EXACTLY the keys in ENTRY_KEYS:
      id                    -- the dependency's canonical id (string)
      name                  -- the dependency's canonical name (string)
      action_class          -- raw value if present, else None (no fail-safe resolver defined
                               for this field at B1-1; a missing action_class is a wizard-capture
                               gap, not a resolvable enforcement risk)
      risk_class            -- ALWAYS resolve_risk_class(row): fail-safe-resolved, never the raw
                               absent/unknown value (F-28 — never read_only_local by omission)
      recovery_profile_ref  -- raw value if present, else None
      declared_test_target  -- raw value if present, else None
      blast_radius_cap      -- raw value if present, else None
      accepted              -- ALWAYS False (D-B1-b: runtime marking is a later slice)
      phase_id              -- raw value if present, else None (at build time no plan phase is
                               known; the operate-time cascade populates it — see ENTRY_KEYS)
    """
    rows = parse_identity(identity_json)  # fail-closed; validates every present descriptor field
    entries: List[Dict[str, Any]] = []
    for row in rows:
        if not _carries_descriptor_fields(row):
            continue
        entries.append({
            "id": row["id"],
            "name": row["name"],
            "action_class": row.get("action_class"),
            "risk_class": resolve_risk_class(row),
            "recovery_profile_ref": row.get("recovery_profile_ref"),
            "declared_test_target": row.get("declared_test_target"),
            "blast_radius_cap": row.get("blast_radius_cap"),
            "accepted": False,
            "phase_id": row.get("phase_id"),
        })
    return entries


# ---------------------------------------------------------------------------
# Base declared descriptors (B2-T2)
# ---------------------------------------------------------------------------
#
# The coverage gate's demand side (external_write.coverage_gate.evaluate_coverage_gate) iterates
# the STATIC external_write.contracts.OPERATION_CONTRACTS registry — the built-in op_kind
# delete_record (risk_class irreversible_external, requires_accepted_phase=True) is ALWAYS
# registered for any writes-back system, whether or not the operator declared any capability of
# their own. With zero descriptors, coverage FAILS on delete_record alone (`uncovered_mutator`),
# so every fresh writes-back system needs a BASE declared descriptor covering each built-in
# guarded op_kind's risk class before it can ever pass coverage.
#
# The emitted descriptor set for a system = base_declared_descriptors() + the operator's
# declared-capability descriptors (build_descriptor_entries(), added by the emit/cascade in a
# later task). This module supplies only the base half.

# Reserved id/name prefix for a base descriptor. A real operator-declared dependency id/name is a
# free-form string the operator or the interview chose for an actual surface (e.g.
# "google_sheets"); this dunder-bracketed, colon-delimited sentinel is not a shape any real
# surface identifier takes, so write_gate._covering_entry's id/name==op.surface join can never
# match a base entry against a live operation — even in the (never-taken) case where a base
# entry's `accepted` were somehow True. Base entries are always emitted accepted:false and this
# module never mutates that.
BASE_DESCRIPTOR_ID_PREFIX = "__builtin__:"

# op_kind -> the action_class (dependency_projection.ACTION_CLASSES vocabulary) that best
# describes the built-in operation, for the op_kinds this producer knows how to represent. A
# guarded op_kind not listed here (a future addition to OPERATION_CONTRACTS) falls back to the
# generic "mutate" action class rather than a fabricated specific one.
_BUILTIN_ACTION_CLASS_BY_OP_KIND = {
    "delete_record": "delete",
}
_BUILTIN_ACTION_CLASS_DEFAULT = "mutate"


def _agents_lib_path() -> str:
    """The wizard/agents/lib directory (the external_write package's parent), computed from this
    file's own location so it resolves regardless of caller cwd."""
    return str(Path(__file__).resolve().parents[2] / "agents" / "lib")


def _guarded_op_kinds_by_risk_class() -> "Dict[str, List[str]]":
    """Read the REAL external_write.contracts.OPERATION_CONTRACTS registry (a one-directional
    cross-tree import: external_write cannot import the build-side tree — D-B1-a — but the build
    side importing external_write's pure declarative registries introduces no cycle), grouped by
    effective risk class, restricted to GUARDED (coverage-requiring) op_kinds. Mirrors
    external_write.coverage_gate._is_guarded_mutator's exact boundary by calling it directly, so
    this can never silently drift from what the coverage gate actually demands: read_only_local
    and plain reversible_external (non-requires_accepted_phase) op_kinds are excluded; every
    op_kind whose effective risk_class is in GATED_RISK_CLASSES, or whose contract sets
    requires_accepted_phase=True, is included under its effective risk_class."""
    import sys
    agents_lib = _agents_lib_path()
    if agents_lib not in sys.path:
        sys.path.insert(0, agents_lib)
    from external_write.contracts import OPERATION_CONTRACTS  # type: ignore
    from external_write.coverage_gate import (  # type: ignore
        _is_guarded_mutator, _effective_contract_risk_class,
    )
    by_risk: Dict[str, List[str]] = {}
    for op_kind in sorted(OPERATION_CONTRACTS):
        contract = OPERATION_CONTRACTS[op_kind]
        if not _is_guarded_mutator(contract):
            continue
        rc = _effective_contract_risk_class(contract)
        by_risk.setdefault(rc, []).append(op_kind)
    return by_risk


def base_declared_descriptors() -> List[Dict[str, Any]]:
    """The BASE declared (accepted:false) descriptor entries every emitted writes-back system
    must carry: one per DISTINCT effective risk class among the built-in GUARDED op_kinds in
    external_write.contracts.OPERATION_CONTRACTS (today: exactly one, for delete_record's
    irreversible_external). Each entry has EXACTLY the ENTRY_KEYS schema, `accepted` ALWAYS
    False, a reserved BASE_DESCRIPTOR_ID_PREFIX-prefixed id/name (never a real capability
    surface), the covering risk_class, and an action_class reflecting the built-in op (delete
    for delete_record; "mutate" for any op_kind this producer does not specifically recognize).
    recovery_profile_ref / declared_test_target / blast_radius_cap are None — a base entry
    describes only that the built-in op EXISTS and is unaccepted, not any specific test-target or
    recovery commitment (those are the operator-declared capability's job).

    Deterministic: sorted by risk_class, so identical OPERATION_CONTRACTS input always yields
    identical output order.

    The emitted descriptor set for a system = base_declared_descriptors() + the operator's
    build_descriptor_entries() (added by the emit/cascade in a later task)."""
    by_risk = _guarded_op_kinds_by_risk_class()
    entries: List[Dict[str, Any]] = []
    for risk_class in sorted(by_risk):
        op_kinds = by_risk[risk_class]
        action_class = _BUILTIN_ACTION_CLASS_DEFAULT
        for op_kind in op_kinds:
            if op_kind in _BUILTIN_ACTION_CLASS_BY_OP_KIND:
                action_class = _BUILTIN_ACTION_CLASS_BY_OP_KIND[op_kind]
                break
        base_id = f"{BASE_DESCRIPTOR_ID_PREFIX}{risk_class}"
        entries.append({
            "id": base_id,
            "name": base_id,
            "action_class": action_class,
            "risk_class": risk_class,
            "recovery_profile_ref": None,
            "declared_test_target": None,
            "blast_radius_cap": None,
            "accepted": False,
            # A base placeholder is never accepted and never passed to the ceremony, so it owns
            # no plan phase; phase_id is null (the schema tolerates it — see ENTRY_KEYS).
            "phase_id": None,
        })
    return entries


def render_descriptor_registry_json(identity_json: str) -> str:
    """Canonical JSON text for the machine-readable descriptor set: a JSON array of
    build_descriptor_entries() entries, each key in ENTRY_KEYS order (insertion order is
    preserved by dict + json.dumps without sort_keys — the order documented as the cross-task
    contract), indent=2, trailing newline, deterministic (no clock / no randomness)."""
    entries = build_descriptor_entries(identity_json)
    return json.dumps(entries, indent=2, ensure_ascii=False) + "\n"


def _md_cell(text: Any) -> str:
    # Markdown table cells cannot contain a raw pipe; escape defensively (mirrors
    # dependency_projection._md_cell — canonical values here are prose/enum strings).
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _fmt(value: Any, none_text: str = UNKNOWN) -> str:
    return none_text if value is None else str(value)


def project(field: str, identity_json: str) -> str:
    """Produce the markdown table BODY (rows only; the template owns the header) for
    CAPABILITY_DESCRIPTOR_REGISTRY_ROWS (rendering B): one row per build_descriptor_entries()
    entry, columns Capability | Action class | Risk class | Test target | Blast-radius cap |
    Recovery profile | Accepted (mirrors wizard/templates/quality/capability_descriptor_registry.md's
    header). Returns "" when no dependency carries a descriptor field (valid empty body)."""
    if field != MARKDOWN_FIELD:
        raise CapabilityDescriptorRegistryError(
            f"unknown capability descriptor registry markdown field {field!r}; "
            f"known: {MARKDOWN_FIELD!r}")
    entries = build_descriptor_entries(identity_json)
    lines: List[str] = []
    for e in entries:
        cells = [
            _md_cell(e["name"]),
            _md_cell(_fmt(e["action_class"])),
            _md_cell(e["risk_class"]),  # never None (fail-safe resolved)
            _md_cell(_fmt(e["declared_test_target"])),
            _md_cell(_fmt(e["blast_radius_cap"], "(no cap set)")),
            _md_cell(_fmt(e["recovery_profile_ref"], "(none)")),
            _md_cell("Yes" if e["accepted"] else "No"),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    import sys
    if len(sys.argv) < 3 or sys.argv[1] not in ("json", "markdown"):
        print("usage: capability_descriptor_registry.py <json|markdown> <identity.json>",
              file=sys.stderr)
        return 2
    identity = open(sys.argv[2], encoding="utf-8").read()
    try:
        if sys.argv[1] == "json":
            print(render_descriptor_registry_json(identity), end="")
        else:
            print(project(MARKDOWN_FIELD, identity))
    except DependencyProjectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
