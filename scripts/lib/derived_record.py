"""Derived-record loader + validator (stdlib-only).

A DERIVED RECORD is the structured result of deriving an operator's foundation-doc
input fields from interview answers: a flat field payload (key -> value) plus a
per-field audit envelope (the `_audit` map). This module loads the wizard-distributed
derived-record contract (JSON) as canonical authority for the envelope enums + keys,
then validates a derived-record dict against it (invariants DR-1..DR-10), FAIL-fast.

Two orthogonal envelope axes: provenance (`_source` — where a value came from) and
derivation (`_derivation_class` — how it was produced). Decision-ness (`_decision_field`
+ `_decision_kind`) is a third, independent axis. Field values project verbatim into
the emission plan's foundation_doc_inputs; the envelope never enters the emission plan.

Wizard distribution stays pip-install-free: no PyYAML, no jsonschema, no third-party
deps. JSON via stdlib `json` is the wizard-runtime contract format.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


EXPECTED_CONTRACT_ID = "derived-record"
EXPECTED_CONTRACT_VERSIONS = {"derived-record-v1"}

# Top-level keys that are record metadata, not derivable payload fields.
TOP_LEVEL_META_KEYS = frozenset({"_provenance", "_audit", "_schema_extension_points", "_source_taxonomy"})

_ACCEPTED_STATES = {"accepted", "accepted_with_adjustments", "accepted_uncertain_for_now"}


class DerivedRecordError(Exception):
    """Raised when derived-record load or validation fails. Message names the invariant."""


# --- contract loading --------------------------------------------------------

def load_contract(contract_path: Path) -> Dict[str, Any]:
    """Load + lightly validate the derived-record contract JSON."""
    try:
        with contract_path.open("r", encoding="utf-8") as f:
            contract = json.load(f)
    except FileNotFoundError as e:
        raise DerivedRecordError(f"Contract file not found: {contract_path}") from e
    except json.JSONDecodeError as e:
        raise DerivedRecordError(f"Contract file is not valid JSON: {contract_path}: {e}") from e
    if not isinstance(contract, dict):
        raise DerivedRecordError("Contract top-level value must be a JSON object")
    if contract.get("contract_id") != EXPECTED_CONTRACT_ID:
        raise DerivedRecordError(
            f"contract_id mismatch — expected '{EXPECTED_CONTRACT_ID}', got '{contract.get('contract_id')}'"
        )
    cv = contract.get("contract_version")
    if not isinstance(cv, str) or cv not in EXPECTED_CONTRACT_VERSIONS:
        raise DerivedRecordError(
            f"contract_version must be one of {sorted(EXPECTED_CONTRACT_VERSIONS)}; got {cv!r}"
        )
    for key in ("enums", "required_envelope_keys", "known_optional_envelope_keys",
                "top_level_meta_keys", "annotation_key_suffixes", "annotation_key_prefixes"):
        if key not in contract:
            raise DerivedRecordError(f"contract missing required section '{key}'")
    return contract


def default_contract_path() -> Path:
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent
    return wizard_root / "foundation-bundles" / "v0" / "contracts" / "derived-record-contract-v1.json"


# --- helpers -----------------------------------------------------------------

def _require(cond: bool, invariant: str, detail: str) -> None:
    if not cond:
        raise DerivedRecordError(f"{invariant} FAIL: {detail}")


def _enum_member(enums: Dict[str, List[str]], enum_name: str, value: Any, where: str) -> None:
    members = enums.get(enum_name, [])
    _require(value in members, "DR-2", f"{where} value {value!r} not in closed enum {enum_name}={members}")


def _nonempty_list(val: Any) -> bool:
    return isinstance(val, list) and len(val) > 0


def _is_stub(value: Any) -> bool:
    """Empty or whitespace-only content counts as a stub."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _is_placeholder_like(value: Any) -> bool:
    """A `<...>` angle-bracket placeholder token (label-map style)."""
    return isinstance(value, str) and "<" in value and ">" in value


def _is_tbd_like(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith("tbd")


def _allowed_extra_key(key: str, contract: Dict[str, Any]) -> bool:
    if key in contract["required_envelope_keys"]:
        return True
    if key in contract["known_optional_envelope_keys"]:
        return True
    for suf in contract["annotation_key_suffixes"]:
        if key.endswith(suf):
            return True
    for pre in contract["annotation_key_prefixes"]:
        if key.startswith(pre):
            return True
    return False


# --- envelope validation -----------------------------------------------------

def validate_envelope(field: str, env: Dict[str, Any], value: Any,
                      contract: Dict[str, Any], payload_keys: set) -> None:
    """Validate one field's audit envelope (DR-2..DR-10) against the contract."""
    enums = contract["enums"]
    where = f"_audit[{field!r}]"
    _require(isinstance(env, dict), "DR-1", f"{where} must be an object")

    # DR-1 (per-field): required envelope keys present
    for k in contract["required_envelope_keys"]:
        _require(k in env, "DR-1", f"{where} missing required envelope key '{k}'")

    # DR-2: closed enums (fail-closed)
    _enum_member(enums, "source", env["_source"], f"{where}._source")
    _enum_member(enums, "derivation_class", env["_derivation_class"], f"{where}._derivation_class")
    _enum_member(enums, "decision_kind", env["_decision_kind"], f"{where}._decision_kind")
    _require(isinstance(env["_decision_field"], bool), "DR-2", f"{where}._decision_field must be a bool")
    cstate = env.get("_confirmation_state")
    if cstate is not None:
        _enum_member(enums, "confirmation_state", cstate, f"{where}._confirmation_state")

    src = env["_source"]
    cls = env["_derivation_class"]
    dkind = env["_decision_kind"]
    dfield = env["_decision_field"]

    # DR-3: a model-derived value must be confirmed
    if src == "claude-derived-operator-confirmed":
        _require(cstate in _ACCEPTED_STATES, "DR-3",
                 f"{where} source=claude-derived requires _confirmation_state in {sorted(_ACCEPTED_STATES)}; got {cstate!r}")
        _require(isinstance(env.get("_confirmed_at"), str) and env.get("_confirmed_at") != "", "DR-3",
                 f"{where} source=claude-derived requires a non-empty _confirmed_at")

    # DR-4: a stated preference is not derived
    if src == "operator-preference":
        _require("_derivation_inputs" not in env, "DR-4",
                 f"{where} source=operator-preference must NOT carry _derivation_inputs (use _source_question_ids)")

    # DR-5: derived classes must declare their inputs
    if cls in ("synthesis", "policy"):
        _require(_nonempty_list(env.get("_derivation_inputs")), "DR-5",
                 f"{where} derivation_class={cls} requires non-empty _derivation_inputs")
    if cls == "classification":
        _require(_nonempty_list(env.get("_derivation_inputs")) or _nonempty_list(env.get("_source_question_ids")),
                 "DR-5", f"{where} derivation_class=classification requires non-empty _derivation_inputs OR _source_question_ids")
    if cls == "authoring":
        # authored narrative: grounded in the operator's raw answers (question IDs), not prior fields.
        _require(_nonempty_list(env.get("_source_question_ids")), "DR-5",
                 f"{where} derivation_class=authoring requires non-empty _source_question_ids")
        _require("_derivation_inputs" not in env, "DR-5",
                 f"{where} derivation_class=authoring must not carry _derivation_inputs at v0 (answer-only)")

    # DR-6: decision-ness coupling (one-way to class; biconditional with kind)
    if cls in ("classification", "policy"):
        _require(dfield is True, "DR-6", f"{where} derivation_class={cls} requires _decision_field == true")
    _require((dfield is True) == (dkind != "none"), "DR-6",
             f"{where} _decision_field/_decision_kind mismatch: _decision_field={dfield}, _decision_kind={dkind!r}")

    # DR-7: ambiguous source must list its candidates
    if src == "ambiguous":
        cands = env.get("_source_candidates")
        _require(_nonempty_list(cands), "DR-7", f"{where} source=ambiguous requires non-empty _source_candidates")
        for c in cands:
            _require(c in enums["source"], "DR-7", f"{where} _source_candidates member {c!r} is not a legal source class")

    # DR-8: declared inputs resolve
    for k in env.get("_derivation_inputs", []) or []:
        _require(k in payload_keys, "DR-8", f"{where} _derivation_inputs references unknown payload key {k!r}")
    if "_source_question_ids" in env:
        sqi = env["_source_question_ids"]
        _require(_nonempty_list(sqi) and all(isinstance(q, str) and q for q in sqi), "DR-8",
                 f"{where} _source_question_ids must be a non-empty list of non-empty strings")

    # DR-9: no stub content for a projecting field (placeholder/TBD allowances)
    projects = cstate != "deferred_not_emittable"
    if projects:
        if _is_stub(value):
            _require(False, "DR-9", f"{where} projecting field has empty/stub content")
        if _is_placeholder_like(value):
            _require("_label_map_reference" in env or env.get("_intentional_placeholder") is True, "DR-9",
                     f"{where} placeholder-like content requires _label_map_reference or _intentional_placeholder")
        if _is_tbd_like(value):
            _require("_revisit_trigger" in env, "DR-9",
                     f"{where} TBD-class content requires a _revisit_trigger")

    # DR-10: uncertain requires a revisit trigger; unknown envelope keys fail-closed
    if cstate == "accepted_uncertain_for_now":
        _require("_revisit_trigger" in env, "DR-10",
                 f"{where} _confirmation_state=accepted_uncertain_for_now requires a _revisit_trigger")
    for k in env:
        _require(_allowed_extra_key(k, contract), "DR-10",
                 f"{where} unknown envelope key {k!r} is neither a known key nor an annotation key (fail-closed)")


# --- record validation -------------------------------------------------------

def validate_derived_record(record: Dict[str, Any], contract: Dict[str, Any]) -> None:
    """Validate a derived-record dict (payload + `_audit`) against the contract; FAIL-fast."""
    _require(isinstance(record, dict), "DR-1", "derived record must be a JSON object")
    _require(isinstance(record.get("_audit"), dict), "DR-1", "derived record must carry an `_audit` object")
    audit = record["_audit"]
    meta = set(contract["top_level_meta_keys"])
    payload_keys = {k for k in record if k not in meta}

    # DR-1: payload <-> audit parity
    for k in payload_keys:
        _require(k in audit, "DR-1", f"payload key {k!r} has no `_audit` envelope entry")
    for k in audit:
        _require(k in payload_keys, "DR-1", f"`_audit` entry {k!r} has no corresponding payload key")

    for field in sorted(payload_keys):
        validate_envelope(field, audit[field], record[field], contract, payload_keys)


def load_derived_record(record_path: Path, contract_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load a derived-record JSON file + the contract; validate; return the record dict."""
    contract = load_contract(contract_path or default_contract_path())
    try:
        with Path(record_path).open("r", encoding="utf-8") as f:
            record = json.load(f)
    except FileNotFoundError as e:
        raise DerivedRecordError(f"Record file not found: {record_path}") from e
    except json.JSONDecodeError as e:
        raise DerivedRecordError(f"Record file is not valid JSON: {record_path}: {e}") from e
    validate_derived_record(record, contract)
    return record


def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: derived_record.py <record.json> [contract.json]", file=sys.stderr)
        return 2
    contract_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        rec = load_derived_record(Path(sys.argv[1]), contract_path)
    except DerivedRecordError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    n = len([k for k in rec if k not in TOP_LEVEL_META_KEYS])
    print(f"OK: validated derived record with {n} payload fields")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
