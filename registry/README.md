# Wizard Registry

**Status:** v0 stub (per S2.5 / Decision H — schema-only with empty `bundles: []`).
**Authority:** This directory is canonical for **wizard-produced foundation-bundle version index** per `governance/foundation_versioning.md` (D3) § 7.1.

## Files

- `foundation-bundles.json` — version index per D3 § 7.1 schema. **Empty at v0.** First entry populates at E-β fire (first wizard-driven foundation-bundle generation event per `governance/adrs/0018-stage-2-framework.md` § 2.3).

## Schema

Per `governance/foundation_versioning.md` v0 § 7.1:

```json
{
  "schema_version": "v1",
  "bundles": [
    {
      "foundation_bundle_version": "v1.0.0",
      "path": "wizard/foundation-bundles/v1.0.0/",
      "release_date": "2026-MM-DD",
      "source_commit": "<commit-SHA>",
      "manifest": "wizard/foundation-bundles/v1.0.0/manifest.yaml",
      "status": "current"
    }
  ]
}
```

Allowed `status` values: `current` / `superseded` / `deprecated` / `prerelease`.

## At v0

- Registry is **schema-only**; `bundles: []` empty array.
- No `wizard/foundation-bundles/<version>/` directory exists yet — first bundle directory + entry creates at E-β fire.
- `wizard upgrade-check` engine (D3 § 9.1) is NOT in scope for S2.5; runtime semantics ratification at E-β-firing slice or sequel slice.

## Cross-references

- `governance/foundation_versioning.md` v0 § 7 — registry schema canonical
- `governance/adrs/0017-foundation-versioning-migration-policy-v0.md` — D3 adoption authority
- `governance/adrs/0018-stage-2-framework.md` § 2.3 — E-β trigger; this registry's first entry populates when E-β fires
- `governance/adrs/0010-distribution-boundary-v0.md` — `wizard/` subtree publication boundary; this registry rides the public distribution
- `product_evidence/_slices/S2.5_validation_drift_tooling_2026-05-19.md` § A.8 Decision H — schema-only initial state
- `wizard/scripts/bundle_hash.py` — D3 § 4.1 hash-baseline tool that produces per-managed-file hashes for future bundle manifest entries
