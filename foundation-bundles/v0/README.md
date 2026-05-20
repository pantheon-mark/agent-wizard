# Foundation bundle v0 directory

**Status:** v0.1 (additive minor extension to v0 baseline)
**Wizard distribution scope:** this directory ships in the public `pantheon-mark/agent-wizard` repo per the wizard distribution boundary.

## What's in this directory

| Path | Purpose | Released at |
|---|---|---|
| `schemas/section-schema.yaml` | Canonical machine-readable section schema for all 7 foundation-doc-types; v0.1 with shape-extension fields | foundation-bundle v0.1 |
| `migration_manifest.yaml` | Target-owned migration manifest stub; pre-first-generated-bundle baseline normalization classification | foundation-bundle v0.1 |
| `baselines/<template>.hash.yaml` | Per-template hash baselines for enforced-path drift detection | foundation-bundle v0.1 |
| `README.md` | This file | foundation-bundle v0.1 |

## Schema authority discipline

- The canonical human-readable prose specification for foundation-doc versioning + sections lives in the build-side foundation versioning documentation (not distributed in this directory).
- `schemas/section-schema.yaml` is the canonical machine-readable instance.
- The build-side render-contract validator reads the YAML as the contract; it does NOT embed schema constants.
- Drift between the build-side prose specification and `schemas/section-schema.yaml` is itself a render-contract violation.

## Future expansion

When the first wizard-driven foundation-bundle generation event fires:

- A new directory `wizard/foundation-bundles/v1.0/` is created.
- `migration_manifest.yaml` declares a migration class describing what is migrated from prior versions.
- Per-migration step files are authored when the first real migration event needs them.

When new system shapes ship (per the wizard's system-shape roadmap):

- Section schemas extend in place (additive minor); shape-specific sections populate per shape-extension fields.
- No directory restructure required at minor-version bumps.

## Cross-references

- `schemas/section-schema.yaml` — canonical machine-readable section schema (this directory).
- `migration_manifest.yaml` — target-owned migration manifest declaring what each release migrates from.
- `baselines/` — per-template hash baselines used by the build-side render-contract validator for enforced-path drift detection.
- `wizard/test_fixtures/foundation_render_contract/` — render-contract validation fixtures.
