"""Field-manifest loader + validator (stdlib-only).

The field manifest is the per-field derivation contract: for every field the interview
produces, HOW it is derived (derivation_class), whether it is an operator decision
(decision_field + decision_kind), the value's shape + any constraints, which interview
question-IDs feed it, and which foundation doc renders it. The derivation step reads this
so no field knowledge is hardcoded in the barrier.

Validation enforces the decision-field coupling rule from the derived-record contract:
  - a classification or policy field is ALWAYS a decision (decision_field == true); and
  - decision_field == true exactly when decision_kind != 'none'.
plus enum/decision-kind closure, the closed_value => enum_domain rule, the policy =>
explicit-negative-permissions rule, and the source-question requirement for non-auto fields.
Fail-closed: any violation, contract mismatch, or shape mismatch is a hard error.

Stdlib-only, pip-install-free.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


EXPECTED_CONTRACT_ID = "field-manifest"
EXPECTED_CONTRACT_VERSIONS = {"field-manifest-v1"}

# Mirror the derived-record contract enums (the manifest couples to that contract).
DERIVATION_CLASSES = {"extraction", "synthesis", "classification", "policy", "auto", "authoring", "projection"}
DECISION_KINDS = {"none", "closed_value", "policy_rule", "schedule", "threshold",
                  "spend_limit", "integration_boundary"}
# Provenance source classes (mirror the derived-record contract `source` enum). A field
# MAY declare an explicit `source` to override the class-default the envelope assembler picks
# (e.g. a lookup-extraction field whose value is plan-derived, not the operator's words).
SOURCE_CLASSES = {"operator-content", "operator-preference", "claude-derived-operator-confirmed",
                  "auto", "ambiguous"}
# Classes that the derived-record contract forces to be decisions.
_DECISION_CLASSES = {"classification", "policy"}

REQUIRED_FIELD_KEYS = (
    "field", "group_id", "derivation_class", "decision_field", "decision_kind",
    "value_shape", "source_question_ids", "preview_doc",
)
# Keys consumed into typed FieldSpec attributes; everything else becomes `constraints`.
# `source` is an OPTIONAL typed key (an explicit provenance override; not in REQUIRED_FIELD_KEYS).
_TYPED_KEYS = set(REQUIRED_FIELD_KEYS) | {"source"}


class FieldManifestError(Exception):
    """Raised on manifest load/validation failure, or an unknown field lookup (fail-closed)."""


@dataclass(frozen=True)
class FieldSpec:
    field: str
    group_id: str
    derivation_class: str
    decision_field: bool
    decision_kind: str
    value_shape: str
    source_question_ids: List[str]
    preview_doc: str
    constraints: Dict[str, Any]   # enum_domain / required_columns / requires_explicit_negative_permissions / notes / ...
    source: Optional[str] = None  # explicit `_source` override; None => the envelope assembler uses the class default


@dataclass(frozen=True)
class FieldManifest:
    system_shape: str
    fields: Dict[str, FieldSpec]

    def spec_for(self, field: str) -> FieldSpec:
        if field not in self.fields:
            raise FieldManifestError(f"unknown field {field!r}")
        return self.fields[field]


def _require(cond: bool, invariant: str, detail: str) -> None:
    if not cond:
        raise FieldManifestError(f"{invariant} FAIL: {detail}")


def default_manifests_dir() -> Path:
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent
    return wizard_root / "foundation-bundles" / "v0" / "field-manifests"


def load_field_manifest(system_shape: str, manifests_dir: Optional[Path] = None) -> FieldManifest:
    """Load + validate the field manifest for the given shape. Fail-closed throughout."""
    mdir = manifests_dir or default_manifests_dir()
    path = Path(mdir) / f"{system_shape}.json"
    if not path.exists():
        raise FieldManifestError(f"field manifest not found for shape {system_shape!r}: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise FieldManifestError(f"manifest is not valid JSON: {path}: {e}") from e

    _require(isinstance(data, dict), "contract", "top-level value must be an object")
    _require(data.get("contract_id") == EXPECTED_CONTRACT_ID, "contract_id",
             f"expected {EXPECTED_CONTRACT_ID!r}, got {data.get('contract_id')!r}")
    cv = data.get("contract_version")
    _require(isinstance(cv, str) and cv in EXPECTED_CONTRACT_VERSIONS, "contract_version",
             f"must be one of {sorted(EXPECTED_CONTRACT_VERSIONS)}; got {cv!r}")
    _require(data.get("system_shape") == system_shape, "system_shape_match",
             f"file declares {data.get('system_shape')!r} but asked for {system_shape!r}")
    _require(isinstance(data.get("fields"), list), "fields", "must be a list")

    fields: Dict[str, FieldSpec] = {}
    for raw in data["fields"]:
        _require(isinstance(raw, dict), "field", "each field entry must be an object")
        for k in REQUIRED_FIELD_KEYS:
            _require(k in raw, "field_key", f"field entry missing required key {k!r}: {raw.get('field')!r}")
        name = raw["field"]
        _require(isinstance(name, str) and name, "field_name", "field must be a non-empty string")
        _require(name not in fields, "field_unique", f"duplicate field {name!r}")

        dclass = raw["derivation_class"]
        dkind = raw["decision_kind"]
        dfield = raw["decision_field"]
        _require(dclass in DERIVATION_CLASSES, "derivation_class",
                 f"{name}: {dclass!r} not in {sorted(DERIVATION_CLASSES)}")
        _require(dkind in DECISION_KINDS, "decision_kind",
                 f"{name}: {dkind!r} not in {sorted(DECISION_KINDS)}")
        _require(isinstance(dfield, bool), "decision_field", f"{name}: decision_field must be boolean")
        _require(isinstance(raw["value_shape"], str) and raw["value_shape"], "value_shape",
                 f"{name}: value_shape must be a non-empty string")
        _require(isinstance(raw["source_question_ids"], list), "source_question_ids",
                 f"{name}: source_question_ids must be a list")
        _require(isinstance(raw["preview_doc"], str), "preview_doc", f"{name}: preview_doc must be a string")

        # Decision-field coupling (the derived-record contract rule):
        if dclass in _DECISION_CLASSES:
            _require(dfield is True, "decision_coupling",
                     f"{name}: derivation_class {dclass!r} must be a decision (decision_field true)")
        _require(dfield == (dkind != "none"), "decision_coupling",
                 f"{name}: decision_field ({dfield}) must be true exactly when decision_kind ({dkind!r}) != 'none'")

        # closed_value decisions must name the allowed set.
        if dkind == "closed_value":
            _require(bool(raw.get("enum_domain")), "enum_domain",
                     f"{name}: decision_kind closed_value requires a non-empty enum_domain")
        # policy fields must require explicit negative permissions.
        if dclass == "policy":
            _require(raw.get("requires_explicit_negative_permissions") is True,
                     "policy_negative_permissions",
                     f"{name}: policy fields must set requires_explicit_negative_permissions: true")
        # non-auto fields must declare at least one source question (the static analog of the
        # derived-record contract's input-citation requirements). auto fields take no source;
        # projection fields take no source either — a projection is a deterministic role-filter/
        # reshape of PRIOR PAYLOAD FIELDS (declared at derive time via _derivation_inputs), never
        # raw answers, so it carries no source_question_ids (derived-record contract DR-5).
        if dclass in ("auto", "projection"):
            _require(raw["source_question_ids"] == [], "no_source_questions",
                     f"{name}: {dclass} fields take no source_question_ids")
        else:
            _require(len(raw["source_question_ids"]) > 0, "source_required",
                     f"{name}: {dclass} field must declare at least one source question-ID")

        # optional explicit provenance override (else the envelope assembler uses the class default)
        src_override = raw.get("source")
        if src_override is not None:
            _require(src_override in SOURCE_CLASSES, "source",
                     f"{name}: source {src_override!r} not in {sorted(SOURCE_CLASSES)}")

        constraints = {k: v for k, v in raw.items() if k not in _TYPED_KEYS}
        fields[name] = FieldSpec(
            field=name, group_id=raw["group_id"], derivation_class=dclass,
            decision_field=dfield, decision_kind=dkind, value_shape=raw["value_shape"],
            source_question_ids=list(raw["source_question_ids"]), preview_doc=raw["preview_doc"],
            constraints=constraints, source=src_override,
        )

    return FieldManifest(system_shape=system_shape, fields=fields)


def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: field_manifest.py <system-shape> [manifests-dir]", file=sys.stderr)
        return 2
    mdir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        m = load_field_manifest(sys.argv[1], mdir)
    except FieldManifestError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"OK: {len(m.fields)} fields for shape {m.system_shape!r}")
    decisions = [f for f, s in m.fields.items() if s.decision_field]
    print(f"  decision fields: {sorted(decisions)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
