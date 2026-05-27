# Synthetic Foundation Bundle

**Status:** v0 (per a prior slice).
**Purpose:** structural placeholder bundle for exercising `wizard/scripts/bundle_hash.py` (mech-hash-baseline-v0). NOT real operator content; NOT a generated bundle template; NOT for wizard runtime use.

## Layout

Matches `the relevant build-side spec` (D3) § 1.1 + § 5 operator-project structure:

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

- `the relevant build-side spec` v0 § 1.1 — required foundation-doc filenames
- `the relevant build-side spec` v0 § 4.1 — per-file hash schema
- `wizard/scripts/bundle_hash.py` — tool consumed by this fixture
- `the originating slice spec` — synthetic bundle rationale
- the relevant build-side validation evidence record — validation evidence using this fixture
