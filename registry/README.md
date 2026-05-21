# Wizard Registry

**Status:** Active — 1 entry (`v0.3.0` prerelease) as of 2026-05-21.
**Authority:** This directory is canonical for the **wizard-produced foundation-bundle version index** that operators discover for upgrade decisions.

## Files

- `foundation-bundles.json` — version index. First per-version package entry activated at the 2026-05-21 release (`v0.3.0`, `status: prerelease`).

## Schema

```json
{
  "schema_version": "v1",
  "bundles": [
    {
      "foundation_bundle_version": "v0.3.0",
      "path": "wizard/foundation-bundles/v0.3.0/",
      "release_date": "2026-05-21",
      "source_commit": "<commit-SHA>",
      "manifest": "wizard/foundation-bundles/v0.3.0/manifest.yaml",
      "status": "prerelease"
    }
  ]
}
```

Allowed `status` values: `current` / `superseded` / `deprecated` / `prerelease`.

## At current state

- Registry has 1 entry: `v0.3.0` with `status: prerelease`. The corresponding per-version package lives at `wizard/foundation-bundles/v0.3.0/` (self-contained: own schemas + templates + baselines + manifest + migration-manifest).
- Per-version directory layout is decoupled from v1.0.0 stability commitment per the canonical foundation-versioning specification § 1.3 layout-vs-stability decoupling — pre-v1 per-version packages may exist (status: prerelease) and v1.0.0 promotion is a separate stability-commitment trigger.
- The `wizard upgrade-check` engine is NOT yet wired; runtime semantics ratification is deferred to a future wizard release once the foundation-bundle generation pipeline lands.

## Cross-references

- `wizard/scripts/bundle_hash.py` — hash-baseline tool that produces per-managed-file hashes for future bundle manifest entries.
