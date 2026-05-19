# Synthetic Foundation Bundle

**Status:** v0 (per S2.5 § A.7 Decision G).
**Purpose:** structural placeholder bundle for exercising `wizard/scripts/bundle_hash.py` (mech-hash-baseline-v0). NOT real operator content; NOT a generated bundle template; NOT for wizard runtime use.

## Layout

Matches `governance/foundation_versioning.md` (D3) § 1.1 + § 5 operator-project structure:

```
_synthetic_bundle/
└── foundation/
    ├── vision.md
    ├── prd.md
    ├── approach.md
    ├── execution_plan.md
    ├── technical_architecture.md
    ├── test_cases.md
    └── audit_framework.md
```

Each foundation-doc file contains a single-line placeholder marker (`This is a structural placeholder for...`). Real foundation-doc content lives in operator-project bundles produced at E-β fire.

## How exercised

```
wizard/scripts/bundle_hash.py wizard/test_fixtures/_synthetic_bundle/
```

Produces a YAML manifest snippet with per-file `base_hash` entries per D3 § 4.1 schema. No-op except for proving the tool's contract works end-to-end.

## Cross-references

- `governance/foundation_versioning.md` v0 § 1.1 — required foundation-doc filenames
- `governance/foundation_versioning.md` v0 § 4.1 — per-file hash schema
- `wizard/scripts/bundle_hash.py` — tool consumed by this fixture
- `product_evidence/_slices/S2.5_validation_drift_tooling_2026-05-19.md` § A.7 Decision G — synthetic bundle rationale
- `governance/validation/mech-hash-baseline-v0/2026-05-19_s2.5_initial.md` — validation evidence using this fixture
