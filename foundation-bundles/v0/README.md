# Foundation bundle v0 directory

**Status:** v0.1 (S2.6 2026-05-19 — additive minor extension to v0 baseline 2026-05-08)
**Authority:** `governance/foundation_versioning.md` § 1.1 + § 1.4 (canonical)
**Wizard distribution scope:** this directory ships in the public `pantheon-mark/agent-wizard` repo per ADR-0010 distribution boundary v0.

## What's in this directory

| Path | Purpose | Authored at |
|---|---|---|
| `schemas/section-schema.yaml` | Canonical machine-readable section schema for all 7 foundation-doc-types; v0.1 with shape-extension fields per S2.6 Decision D | S2.6 |
| `migration_manifest.yaml` | Target-owned migration manifest stub per `foundation_versioning.md` § 3; pre-E-β baseline normalization classification | S2.6 |
| `baselines/<template>.hash.yaml` | Per-template hash baselines for enforced-path drift detection per S2.6 Decision G | S2.6 |
| `README.md` | This file | S2.6 |

## Schema authority discipline (per IDQ-057)

- `governance/foundation_versioning.md` § 1.4 = canonical human-readable prose specification
- `schemas/section-schema.yaml` = canonical machine-readable instance
- `tools/validate_foundation_render_contract.py` (build-side) READS the YAML; does NOT embed schema
- Drift between § 1.4 prose and schemas/section-schema.yaml is itself a render-contract violation

## Future expansion

When v1 bundle release fires at E-β (per ADR-0018 G-2 hard gate):
- New directory `wizard/foundation-bundles/v1.0/` created
- `migration_manifest.yaml` declares `from: v0.x` migration class per § 3.1
- Per-migration step files at `migrations/v0-to-v1.0.md` authored when first real migration event needed

When new shapes ship (per NORTH_STAR roadmap):
- Section schemas extend in place (additive minor); shape-specific sections populate per shape-extension fields
- No directory restructure required at minor-version bumps

## Cross-references

- `governance/foundation_versioning.md` — canonical schema authority + migration manifest schema + drift detection
- `governance/adrs/0017-foundation-versioning-migration-policy-v0.md` — ADR canonical for D3 versioning + migration policy
- `governance/adrs/0010-distribution-boundary-v0.md` — wizard public distribution boundary
- `product_evidence/_slices/S2.6_foundation_doc_render_contract_2026-05-19.md` — slice spec that produced v0.1 schema extension
- `tools/validate_foundation_render_contract.py` — build-side validator; reads `schemas/section-schema.yaml` as canonical instance
- `wizard/test_fixtures/foundation_render_contract/` — render-contract fixtures (frc01 + frc02)
