# Foundation bundle v0 directory (schema-layer canonical)

**Status:** v0.2 schema layer (test_cases.md shape-neutral 5-section rewrite from prior 3-section markdown-agents-locked structure; foundation-bundle-v0.2 release 2026-05-20). First concrete per-version package at `wizard/foundation-bundles/v0.3.0/` (status: prerelease; 2026-05-21).
**Wizard distribution scope:** this directory ships in the public `pantheon-mark/agent-wizard` repo per the wizard distribution boundary.
**Layout authority:** per the canonical foundation-versioning specification § 7 (directory layout) + § 1.3 layout-vs-stability decoupling — `v0/` is the schema-layer canonical directory (rolling pre-v1 schema migration); per-version packages (`v0.3.0/`, `v1.0.0/`, etc.) live as sibling directories under `wizard/foundation-bundles/`.

## What's in this directory

| Path | Purpose | Released at |
|---|---|---|
| `schemas/section-schema.yaml` | Canonical machine-readable section schema for all 7 foundation-doc-types; v0.2 with shape-extension fields + shape-neutral test_cases entry | foundation-bundle v0.2 |
| `migration_manifest.yaml` | Target-owned migration manifest; tracks v0.x rolling pre-stabilization transitions per the foundation-versioning policy | foundation-bundle v0.2 |
| `baselines/<template>.hash.yaml` | Per-template hash baselines for enforced-path drift detection (all 6 templates at schema_revision: v0.2) | foundation-bundle v0.2 |
| `README.md` | This file | foundation-bundle v0.2 |

## Schema authority discipline

- The canonical human-readable prose specification for foundation-doc versioning + sections lives in the build-side foundation versioning documentation (not distributed in this directory).
- `schemas/section-schema.yaml` is the canonical machine-readable instance.
- The build-side render-contract validator reads the YAML as the contract; it does NOT embed schema constants.
- Drift between the build-side prose specification and `schemas/section-schema.yaml` is itself a render-contract violation.

## Per-version package activation

First concrete per-version package activated at `wizard/foundation-bundles/v0.3.0/` (2026-05-21; status: prerelease per registry; pre-v1 per § 1.3 layout-vs-stability decoupling). Per-version packages are self-contained: own `schemas/` + `templates/` + `baselines/` + `manifest.yaml` + `migration-manifest.yaml`. The `v0/` schema-layer canonical directory remains for rolling schema migration tracking and for any future v0.x → v0.x+1 schema-layer-only transitions.

When the next per-version package is created (e.g., v0.4.0 prerelease OR v1.0.0 stable):

- A new directory `wizard/foundation-bundles/<full-semver>/` is created (full semver naming per § 7).
- That package's `migration-manifest.yaml` declares the migration class describing what it migrates from (per-version target-owned discipline per § 3).
- Per-migration step files at `migrations/<source>-to-<target>.md` are authored when the first real migration event needs them (deferred under § 1.3 pre-v1 stabilization clause where applicable).
- v1.0.0 promotion is the **stability-commitment trigger** (forfeit of pre-v1 stabilization clause per § 1.3); the generator-version-identity mechanism must be wired before v1.0.0 manifest.

When new system shapes ship (per the wizard's system-shape roadmap):

- Section schemas extend in place (additive minor); shape-specific sections populate per shape-extension fields.
- No directory restructure required at minor-version bumps.

## Cross-references

- `schemas/section-schema.yaml` — canonical machine-readable section schema (this directory).
- `migration_manifest.yaml` — target-owned migration manifest declaring what each release migrates from.
- `baselines/` — per-template hash baselines used by the build-side render-contract validator for enforced-path drift detection.
- `wizard/test_fixtures/foundation_render_contract/` — render-contract validation fixtures.
