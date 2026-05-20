# Negative manifest-contract fixtures

Each fixture is INTENTIONALLY INVALID and EXPECTED to FAIL when loaded by
`wizard/scripts/lib/manifest_contract.py:load_manifest_contract()`.

| Fixture | Tests gate | Failure mode |
|---|---|---|
| `missing_version.json` | Gate 2 | `contract_version` field absent |
| `wrong_version.json` | Gate 2 | `contract_version` value not in EXPECTED_CONTRACT_VERSIONS |
| `wrong_id.json` | Gate 1 | `contract_id` value does not match EXPECTED_CONTRACT_ID |
| `enum_missing_frozen.json` | Gate 5 | `enums.merge_strategy` does not exact-match EXPECTED_ENUMS (missing `frozen`) |
| `default_unknown_enum.json` | Gate 6 | default `merge_strategy` value not a member of `enums.merge_strategy` closed set |
| `missing_record_field.json` | Gate 3 | a `required_foundation_docs` record missing the `merge_strategy` field |

Per-fixture `description` field documents the expected gate failure inline.

Gates 4 (path uniqueness) and 7 (manifest_file_fields exact match) are not
exercised by dedicated negative fixtures — they are code-guarded by
`load_manifest_contract()` and exercised by the in-memory mutation tests in
`wizard/scripts/lib/test_manifest_contract.py` (see `T09_PathUniqueness_Gate4`
and `T10_ManifestFileFields_Gate7`).

Gate 0 (top-level JSON shape) is exercised by an in-memory test rather than a
fixture file because a top-level JSON array is not a valid manifest at all.

## Validation
Run the test module: `python3 -m unittest discover -s wizard/scripts/lib -p "test_*.py"`
