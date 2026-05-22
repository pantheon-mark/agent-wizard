# Wizard Changes — Public Release Notes

This file is the canonical public release-notes + provenance manifest for the `wizard/` subtree distributed via the public `pantheon-mark/agent-wizard` repository.

Each entry records:

- A short public-facing change note
- `Source-Meta-Commit:` — the commit SHA in the private build repo at the moment of publication
- The public repo commit SHA after the publication is complete (filled in after subtree push)

Entries appear newest-first.

---

## 2026-05-22 — foundation-bundle generator first real-operator generation event (structural anonymization)

**Public-facing change:** the wizard distribution exercises the foundation-bundle generator pipeline against real-operator content for the first time. The release ships no code changes to the generator itself (the pipeline is unchanged from the prior `2026-05-22` internal first-generation event); what changes is the addition of a durable real-operator-content fixture under the wizard's test directory, exercising the same generator against operator answers from an actual real-world project rather than synthetic placeholders.

**Honest characterization.** This is a real-operator-content first-capture milestone, NOT operator-fit validation, NOT arms-length operator review, and NOT a stability commitment for v1.0.0 promotion. The operator for this capture is the wizard's primary author (operator role and build-session lead role collapse in this release); arms-length operator validation remains forthcoming.

**Privacy discipline.** All identifying entities in the real-operator content (entity identifiers across multiple categories — people, organizations, accounts, dates, amounts, locations, contact information) are captured using STABLE PLACEHOLDER LABELS rather than real values. The committed fixture preserves the operator content's STRUCTURAL SHAPE (scope / agents / orchestration / autonomy / phases) verbatim while keeping all third-party identifying information out of the distributed artifact. A real-label-to-placeholder mapping file lives on the operator's local disk outside any distributed repository. Operators using the wizard for sensitive content can adopt the same structural-anonymization discipline.

**Operator-facing notes:**

- The same generator pipeline (`wizard/scripts/generate_bundle.py` + `wizard/scripts/lib/generator.py`) is exercised; no version bump, no API change.
- The wizard's `wizard-proposes-user-confirms` operating principle (per `wizard/CLAUDE.md` rule 5) is exercised at both the derivation surface (operator answers → Claude proposes derived content → operator confirms/adjusts) and the review surface (operator reviews generated documents → Claude proposes per-document verdict + surprises → operator confirms/adjusts). Both surfaces are bootstrap-grade (Claude-facilitated, ad-hoc); designed-mechanism implementation of the interview surface is forthcoming in a later release.
- No operator action required at this release. Operator projects produced via earlier paths continue to be unaffected.

- Source-Meta-Commit: `<TBD at Commit A landing>`
- Public repo commit: `<TBD post-subtree-push>`

---

## 2026-05-22 — foundation-bundle generator pipeline + first internal generation event

**Public-facing change:** the wizard distribution now includes a foundation-bundle generator pipeline. A new library at `wizard/scripts/lib/generator.py` and a new CLI at `wizard/scripts/generate_bundle.py` together emit an operator-project bundle from a source foundation bundle plus a set of operator inputs supplied as JSON. The first internal generation event used the existing `v0.3.0` prerelease bundle as the source and synthetic placeholder inputs; the run produced seven foundation documents (`vision.md`, `prd.md` as a schema-only stub, `approach.md`, `execution_plan.md`, `technical_architecture.md`, `test_cases.md`, `audit_framework.md`) plus an operator manifest at `.wizard/manifest.yaml` carrying the foundation-bundle version, the source bundle's published commit, and the wizard generator code identity at emission time.

**Honest characterization.** This release is an INTERNAL first-fire milestone. The synthetic inputs do not represent a real operator system, and this release does not constitute operator-fit validation, known-tester recruitment, or a stability commitment. v1.0.0 promotion remains deferred until interview-driven generation and additional shape support (markdown agents, other system shapes) land in subsequent releases.

**Operator-facing notes:**

- The generator is stdlib-only — no Python package installation is required on the operator side to run it.
- The generator emits its operator manifest as deterministic text with a tight field set: `foundation_bundle_version`, `source_commit`, `generator_version`, and a per-file `files:` map carrying `managed:` / `base_hash:` / `current_hash_last_seen:` / `local_modifications:` / `merge_strategy:` per file. Package-side fields stay in the foundation-bundle's own `manifest.yaml`; the operator manifest is deliberately disjoint so downstream validators can detect operator vs. package context unambiguously.
- The wizard generator code identity is recorded automatically at generation time. The generator refuses to emit when the wizard build state is not clean, so the recorded identity always points to a published wizard state. A `--permissive-dirty` flag exists for development use and should not be used to produce v1.0.0+ bundles.
- The `prd.md` template ships as a schema-only stub at this prerelease: the operator authors content for the four canonical sections (Vision Link, Persona / JTBD, Functional Requirements, Non-Functional Requirements) per the section schema shipped at `wizard/foundation-bundles/v0.3.0/schemas/section-schema.yaml`. A full `prd.md` template is deferred to a future release when interview-driven PRD authoring lands.

No operator action required at this release. Operator projects produced via earlier paths continue to be unaffected.

- Source-Meta-Commit: `c37067f`
- Public repo commit: `6de09d7`

---

## 2026-05-21 — foundation-bundle-v0.3.0 prerelease package

**Public-facing change:** first concrete per-version foundation-bundle package activated at `wizard/foundation-bundles/v0.3.0/` with `status: prerelease` in the public registry. The package is self-contained: own `schemas/section-schema.yaml`, `templates/` (six foundation-doc `.md` files: vision, approach, technical_architecture, execution_plan, test_cases, audit_framework), `baselines/` (six per-template hash baselines), `manifest.yaml`, and `migration-manifest.yaml`. Section schema content is unchanged from the prior `v0/` schema-layer state — the package is a new layout/addressability layer over the same schema, not a schema revision.

The wizard's foundation-bundle layout convention is also updated in this release: per-version package directories (`v0.3.0/`, eventually `v1.0.0/`) may exist for pre-v1 prerelease packages as well as stable v1.0.0+ releases, decoupling directory layout from v1.0.0 stability commitment. The `v0/` schema-layer canonical directory continues to track rolling schema migration history. v1.0.0 promotion remains the explicit stability-commitment trigger and is deferred until the wizard's foundation-bundle generator + generator-version-identity mechanism are wired in subsequent releases.

No operator action required at this prerelease — the package is a structural prerelease ahead of the wizard's foundation-bundle generation pipeline going live. Operator projects continue to be unaffected.

- Source-Meta-Commit: `15757c5`
- Public repo commit: `eb3ce61`

---

## 2026-05-20 — Templates root + docs _index.md inventory updates (operator-impact minimal)

**Public-facing change:** two `_index.md` template-inventory files brought current. Specifically: `wizard/templates/root/_index.md` now lists `wizard_feedback.md` (template was already in the directory; the inventory pointer was just stale); `wizard/templates/docs/_index.md` now lists `how_your_system_works.md` (same shape — template existed, inventory was stale). No template content changed; no behavior change for operators running the wizard. This release accompanies build-side standup of operating-doc template variant/readiness policy (build-side governance work; not exposed in this distribution beyond the inventory fixes named above).

- Source-Meta-Commit: `ef84afd`
- Public repo commit: `c919e8a`

---

## 2026-05-20 — Distribution boundary v1 + cumulative interview content updates (since 2026-05-04)

**Public-facing change:** the wizard distribution now ships with cleaner internal language across the interview flow and supporting modules. Build-side provenance references (slice IDs, issue identifiers, internal governance paths) have been removed from operator-facing content; where references were load-bearing for semantic clarity, neutral version IDs (e.g., `foundation-bundle-v0.1`) replace them. This release also adds:

- A new `foundation-bundles/v0/` directory with the canonical `schemas/section-schema.yaml` (machine-readable section schema for the seven foundation doc types, with shape-extension metadata), `migration_manifest.yaml` (target-owned migration manifest stub), `baselines/<template>.hash.yaml` (per-template drift-detection hashes), and `README.md` describing the directory.
- A new `handoff_contracts/shape_detection_v0.md` defining the shape-detection handoff structure that downstream wizard surfaces consume.
- A new `shape_detection.md` canonical implementation spec for the shape-detection module (probe inventory, confidence rubric, lifecycle phases, stop conditions, control matrix).
- New interview helper modules: `_foundation_only_mode_gate.md`, `_pre_step_05_recheck.md`, `_pre_step_08_recheck.md`, `_stop_condition_reevaluate_loop.md`.
- A new `registry/` directory with `foundation-bundles.json` (version index) + README.
- A new `scripts/` directory with `bundle_hash.py` (hash-baseline tool for foundation-bundle drift detection) + supporting library.
- A new `templates/documents/` directory with the foundation-doc templates the wizard uses to generate operator-project artifacts.
- A new `test_fixtures/` directory with synthetic fixtures the wizard's internal validation surfaces exercise (operator-relevant for understanding the foundation-only-mode behavior + stop-condition reevaluate loop).
- Source-Meta-Commit: `9d6299f`
- Public repo commit: `247a264`

This release covers cumulative changes since the prior subtree publication at `2d28da0` (2026-05-19). The intervening build-side work that materialized in this distribution was substantial; the operator-facing summary above focuses on what changes for someone running the wizard.

---

## 2026-05-04 — v0 license + IP posture ratified

**Public-facing change:** added `LICENSE` (MIT, copyright 2026 Mark Tobias), `GENERATED_OUTPUTS.md` (operator's free-use grant for wizard-generated project content), and this `CHANGES.md` (canonical public release-notes + provenance manifest). Closes the prior "all rights reserved" default state for the public repository.

- Source-Meta-Commit: `7703dd7`
- Public repo commit: `bfc327e`

---

## Provenance discipline

- Every change to `wizard/` that reaches the public repo via `git subtree push` should be recorded above.
- The canonical authority is this file; commit messages may copy the same information but never replace it.
- For substantial structural changes, include a public-facing summary only. Do not reference private build-project governance, review records, or local paths.
- This file lives inside the public subtree. Its content is public-readable; treat all entries accordingly.
