"""Wizard-side machine-readable manifest contract loader.

Stdlib-only loader for the foundation-bundle hash-baseline manifest contract.
Loads + validates the JSON contract via `json.load()`; FAIL-fast on contract-id
mismatch, contract-version mismatch, or any of the structural validation gates.
Returns a dict; the caller (bundle_hash.py) consumes.

Wizard distribution stays pip-install-free: no PyYAML, no third-party deps.
JSON via stdlib `json` is the wizard-runtime contract format.
"""

import json
from pathlib import Path
from typing import Any, Dict, List


EXPECTED_CONTRACT_ID = "foundation-manifest-hash-baseline"
EXPECTED_CONTRACT_VERSIONS = {"manifest-v1"}

# Output fields the manifest snippet MUST emit per file (gate 7)
EXPECTED_MANIFEST_FILE_FIELDS = [
    "managed",
    "base_hash",
    "current_hash_last_seen",
    "local_modifications",
    "merge_strategy",
]

# Closed enum sets the contract MUST declare exactly (gate 5)
# Order-sensitive: contract enum lists must match these exactly.
EXPECTED_ENUMS = {
    "managed_by": ["shared", "operator", "wizard"],
    "local_modifications": ["expected", "allowed", "not_recommended"],
    "merge_strategy": ["three_way", "operator_review", "warn_on_drift", "frozen"],
}

# Required per-record fields in required_foundation_docs (gate 3)
REQUIRED_RECORD_FIELDS = ["path", "managed_by", "local_modifications", "merge_strategy"]


class ManifestContractError(Exception):
    """Raised when manifest contract load or validation fails."""


def load_manifest_contract(contract_path: Path) -> Dict[str, Any]:
    """Load + validate the wizard-distributed manifest contract JSON.

    Returns the parsed contract as a dict. Raises ManifestContractError with a
    specific gate-name on any of the 7 validation gates failing.

    Validation gates:
        0. Top-level value is a JSON object (not array, scalar, or null)
        1. contract_id matches EXPECTED_CONTRACT_ID
        2. contract_version is in EXPECTED_CONTRACT_VERSIONS
        3. Every required_foundation_docs record has all REQUIRED_RECORD_FIELDS
           with string types and non-empty path
        4. Paths in required_foundation_docs are unique
        5. enums.managed_by / enums.local_modifications / enums.merge_strategy
           match EXPECTED_ENUMS exactly (no extra values, no missing values)
        6. Every default value in required_foundation_docs references a known
           enum member (closed-set check)
        7. manifest_file_fields matches EXPECTED_MANIFEST_FILE_FIELDS exactly
    """
    try:
        with contract_path.open("r", encoding="utf-8") as f:
            contract = json.load(f)
    except FileNotFoundError as e:
        raise ManifestContractError(
            f"Contract file not found: {contract_path}"
        ) from e
    except json.JSONDecodeError as e:
        raise ManifestContractError(
            f"Contract file is not valid JSON: {contract_path}: {e}"
        ) from e

    # Gate 0 — top-level JSON shape must be an object
    if not isinstance(contract, dict):
        raise ManifestContractError(
            f"Gate 0 FAIL: contract top-level value must be a JSON object; "
            f"got {type(contract).__name__}"
        )

    # Gate 1 — contract_id match
    contract_id = contract.get("contract_id")
    if contract_id != EXPECTED_CONTRACT_ID:
        raise ManifestContractError(
            f"Gate 1 FAIL: contract_id mismatch — expected '{EXPECTED_CONTRACT_ID}', "
            f"got '{contract_id}'"
        )

    # Gate 2 — contract_version match (must be a string in expected set)
    contract_version = contract.get("contract_version")
    if not isinstance(contract_version, str) or contract_version not in EXPECTED_CONTRACT_VERSIONS:
        raise ManifestContractError(
            f"Gate 2 FAIL: contract_version must be a string in expected set; "
            f"got {type(contract_version).__name__}: {contract_version!r}, "
            f"expected one of {sorted(EXPECTED_CONTRACT_VERSIONS)}"
        )

    # Gate 5 — closed enums match expected sets EXACTLY (no extras; no missing)
    enums = contract.get("enums")
    if not isinstance(enums, dict):
        raise ManifestContractError(
            "Gate 5 FAIL: 'enums' field missing or not a dict"
        )
    for enum_name, expected_values in EXPECTED_ENUMS.items():
        enum_values = enums.get(enum_name)
        if enum_values != expected_values:
            raise ManifestContractError(
                f"Gate 5 FAIL: enums.{enum_name} must exactly match "
                f"{expected_values}; got {enum_values}"
            )

    # Gate 3 + 4 + 6 — required_foundation_docs structure + uniqueness + enum-resolve
    docs = contract.get("required_foundation_docs")
    if not isinstance(docs, list) or not docs:
        raise ManifestContractError(
            "Gate 3 FAIL: 'required_foundation_docs' missing or not a non-empty list"
        )

    seen_paths = set()
    for idx, record in enumerate(docs):
        if not isinstance(record, dict):
            raise ManifestContractError(
                f"Gate 3 FAIL: required_foundation_docs[{idx}] is not a dict"
            )
        # Gate 3: required fields present
        missing_fields = [f for f in REQUIRED_RECORD_FIELDS if f not in record]
        if missing_fields:
            raise ManifestContractError(
                f"Gate 3 FAIL: required_foundation_docs[{idx}] missing fields: "
                f"{missing_fields}"
            )
        # Gate 3: path is non-empty string
        path_val = record["path"]
        if not isinstance(path_val, str) or not path_val:
            raise ManifestContractError(
                f"Gate 3 FAIL: required_foundation_docs[{idx}].path must be a "
                f"non-empty string; got {type(path_val).__name__}: {path_val!r}"
            )
        # Gate 4: paths unique
        if path_val in seen_paths:
            raise ManifestContractError(
                f"Gate 4 FAIL: required_foundation_docs has duplicate path: {path_val}"
            )
        seen_paths.add(path_val)
        # Gate 6: enum-referencing fields are strings + resolve to known enum members
        for enum_field in ("managed_by", "local_modifications", "merge_strategy"):
            value = record[enum_field]
            if not isinstance(value, str):
                raise ManifestContractError(
                    f"Gate 6 FAIL: required_foundation_docs[{idx}].{enum_field} "
                    f"must be a string; got {type(value).__name__}"
                )
            if value not in enums[enum_field]:
                raise ManifestContractError(
                    f"Gate 6 FAIL: required_foundation_docs[{idx}].{enum_field} "
                    f"value '{value}' not in closed enum {enums[enum_field]}"
                )

    # Gate 7 — manifest_file_fields matches expected exactly
    manifest_file_fields = contract.get("manifest_file_fields")
    if manifest_file_fields != EXPECTED_MANIFEST_FILE_FIELDS:
        raise ManifestContractError(
            f"Gate 7 FAIL: manifest_file_fields must exactly match "
            f"{EXPECTED_MANIFEST_FILE_FIELDS}; got {manifest_file_fields}"
        )

    return contract


def default_contract_path() -> Path:
    """Return the default path to the wizard-distributed manifest contract.

    Resolved relative to this module's location: assumes standard wizard layout
    where wizard/scripts/lib/manifest_contract.py is two levels under wizard/.
    """
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent
    return wizard_root / "foundation-bundles" / "v0" / "contracts" / "foundation-manifest-hash-baseline-v1.json"


def main() -> int:
    """CLI smoke test: load default contract; print summary or error."""
    import sys

    path = default_contract_path()
    try:
        contract = load_manifest_contract(path)
    except ManifestContractError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"OK: loaded {path}")
    print(f"  contract_id: {contract['contract_id']}")
    print(f"  contract_version: {contract['contract_version']}")
    print(f"  required_foundation_docs: {len(contract['required_foundation_docs'])} entries")
    print(f"  enums: {list(contract['enums'].keys())}")
    print(f"  manifest_file_fields: {contract['manifest_file_fields']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
