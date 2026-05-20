# Wizard Registry

**Status:** v0 stub — schema-only with empty `bundles: []`.
**Authority:** This directory is canonical for the **wizard-produced foundation-bundle version index** that operators discover for upgrade decisions.

## Files

- `foundation-bundles.json` — version index. **Empty at v0.** First entry populates at the first wizard-driven foundation-bundle generation event.

## Schema

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
- No `wizard/foundation-bundles/<version>/` directory exists yet — the first bundle directory + entry are created at the first wizard-driven foundation-bundle generation event.
- The `wizard upgrade-check` engine is NOT in scope at v0; runtime semantics ratification is deferred to a future wizard release.

## Cross-references

- `wizard/scripts/bundle_hash.py` — hash-baseline tool that produces per-managed-file hashes for future bundle manifest entries.
