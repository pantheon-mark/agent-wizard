# Wizard Changes — Public Release Notes

This file is the canonical public release-notes + provenance manifest for the `wizard/` subtree distributed via the public `pantheon-mark/agent-wizard` repository.

Each entry records:

- A short public-facing change note
- `Source-Meta-Commit:` — the commit SHA in the private build repo at the moment of publication
- The public repo commit SHA after the publication is complete (filled in after subtree push)

Entries appear newest-first.

---

## 2026-05-29 — generated systems now inherit a base operating scaffold + a curated operating-principles corpus

**Public-facing change:** the wizard's deterministic generator can now emit a complete operator-system layout — not just the foundation documents. A generated project now includes its **base operating scaffold** (the root `CLAUDE.md`, `project_instructions.md` with the resolved model-tier map, `start-session.sh`, and the operational directories `logs/` / `quality/` / `work/` / `docs/` / `security/` / `archive/`), the **agent execution layer** (the orchestrator + QA + specialist prompts and their invocation scripts), and a **curated corpus of inherited operating principles**.

- **Inherited operating principles, single-homed in `quality/rules_library.md`.** A set of operating principles (identified `OP-…`) is installed as structured Rule entries — covering change management, epistemic discipline, contract integrity, decision-making, verification, operator interaction, estimation, controls, and more. Each principle lives in exactly one place; other files (the root `CLAUDE.md`, the agent prompts, the validation-gate config, the audit log) carry a short cross-reference or enforcement pointer back to it rather than a duplicate copy.
- **A `decisions/` decision-record core.** Generated systems ship a decision-record template — with an explicit **Operator actions** field for load-bearing manual steps — plus an index, so the system records its own architectural decisions over time.
- **Model selection stays programmatic.** The generator resolves the model-tier → model mapping into `project_instructions.md` and `start-session.sh`; the operator never has to pick a model by hand.
- **Provisional authority handling, recorded honestly.** Principles that depend on the operator's authority preferences are installed under a conservative, operator-approval-first default and recorded in a machine-readable sidecar, so they can be revisited automatically once the operator's authority profile is captured.

**Operator-facing notes:**

- No operator action required. This is part of the in-progress generation pipeline; the end-to-end generate-and-hand-off flow is still being completed, and a generated system is produced into a staging location for review before it becomes a live project.
- The installed operating principles are designed to be read at session start — the generated `CLAUDE.md` points to them and inlines the few that matter most at the start of every session.

**Source-Meta-Commit:** (filled at publication)
**Public repo commit:** (filled after subtree push)

---

## 2026-05-28 — foundation bundle v0.4.0: technical_architecture template refactor (single-home + cross-reference + extended-info + deferred-state rendering)

**Public-facing change:** foundation bundle releases its first major-breaking schema refactor in the v0.x prerelease series (v0.3.0 → v0.4.0). The `technical_architecture.md` template now follows a **single-home + cross-reference + extended-info + deferred-state rendering** discipline for content that crosses doc boundaries.

- **Two section-schema refactors:** `technical_architecture.agent_roster` removed (canonical home now `approach.md § Agent Roster`); `technical_architecture.permission_boundaries` removed (canonical home now `execution_plan.md § Human-in-the-Loop Map`). Two new sections added: `agent_architecture_detail` + `permission_boundary_architecture`, both with `population_status: deferred` + concrete `undefer_trigger`.
- **Cross-reference convention:** downstream sections start with an italic note containing a **live Markdown link** to the canonical home + a projection description + an extension-purpose statement + a non-duplication assertion. This is the canonical discipline going forward for any field that crosses doc boundaries.
- **Deferred-state rendering:** new sections without populated content carry a fixed deferred-state stub text directly in the template (no placeholder substitution at deferred state). When the `undefer_trigger` fires, a future minor-additive release introduces the corresponding placeholder + flips the section to `populated`.
- **No new placeholders at v0.4.0** — three placeholders REMOVED (`{{AGENT_ROSTER_ROWS}}`, `{{AUTONOMOUS_ACTIONS}}`, `{{ASKS_FIRST_ACTIONS}}`); zero added.
- **Upgrade-plan tier reporting fix:** `wizard upgrade-plan` + `wizard upgrade-check` now correctly report `tier: major-breaking` for v0.3.0 → v0.4.0 by reading the target-owned migration manifest's `class:` field instead of inferring tier from naive semver arithmetic (which would mis-classify a minor-version bump as `minor-additive`).

**Operator-facing notes:**

- No operator action required. Per the foundation-versioning pre-v1 stabilization clause, the v0.3.0 → v0.4.0 migration carries `stabilization_exemption: pre-v1-no-operator-project-dependency` — no operator project depends on v0.3.0, so no operator-project migration runbook is required.
- `wizard upgrade-plan --to v0.4.0` reports the migration as `tier: major-breaking` end-to-end.
- The two NEW deferred sections in `technical_architecture.md` will render as honest stub text describing why the content is not yet captured + when it will be. Operators should NOT author content into these sections at this version.

**Source-Meta-Commit:** d4fbf73
**Public repo commit:** 1599d9b

---

## 2026-05-28 — foundation-bundle upgrade lifecycle: plan-only CLI + drift detection + content-addressed strict-receipt provenance

**Public-facing change:** the wizard ships its first operator-facing upgrade lifecycle: two new CLI commands (`wizard upgrade-check` + `wizard upgrade --to <version> --plan-only` / `wizard upgrade-plan --to <version>`) plus a content-addressed strict-receipt provenance file emitted alongside each foundation bundle. At this release the lifecycle is **plan-only** — the CLI describes what an upgrade would do but does not apply changes. The apply path lands at the next release that ships the per-operator-project state files.

- **Two new CLI commands operationalize what the foundation-versioning policy described.**
  - `wizard upgrade-check` reads an operator project's `.wizard/manifest.json` plus the public bundle registry and reports: available newer versions, per-target upgrade tier, per-managed-file drift status, and the current standing-approval status.
  - `wizard upgrade --to <version> --plan-only` produces a written upgrade plan (planned migration steps, planned drift handling per merge strategy, planned post-validation). `wizard upgrade-plan --to <version>` is the same thing with a tidier subcommand name.
  - At this release **`--plan-only` is mandatory** on `wizard upgrade --to <version>`; calling without it produces a clear error pointing to the next release. The apply path itself ships at the release that adds operator-project state files.
- **Standing approval is fully disabled at this release.** Every upgrade requires explicit operator approval, including clean patch-mechanical ones. The CLI reports `standing_approval_status: unavailable_idq_050_open`. This is honest about a precondition that hasn't shipped yet (operator authority profile generation); when that ships, standing approval activates per the documented profile-gated rules.
- **Hash-based drift detection** runs in **non-destructive planning mode** at this release. The engine reports candidate diffs + plan actions per merge strategy (`three_way` / `operator_review` / `warn_on_drift` / `frozen`) but does not write merged content. The real merge algorithm + write semantics ship at a later release.
- **New `foundation-bundle.provenance.json` ships alongside each foundation bundle.** An 11-field content-addressed strict receipt records what was in the bundle + how it was generated, with a separate `generated_at` timestamp that is metadata-only (not in any content hash) so byte-level reproducibility holds across re-emissions. The receipt also names its own schema_version + hash_algorithm + canonicalization_version so future changes are explicit.
- **JSON sidecars** (`manifest.json` + `migration-manifest.json`) now ship alongside their YAML companions in each `wizard/foundation-bundles/<version>/` directory. The wizard's runtime CLI consumes the JSON; the YAML stays the human-facing copy. No third-party Python dependencies introduced.

**Operator-facing notes:**

- No operator action required at this release. There is no operator-project apply path yet — the upgrade CLI is plan-only.
- If you experiment with the CLI against a test operator project, expect the standing-approval status to show `unavailable_idq_050_open` and expect `wizard upgrade --to <version>` to refuse without `--plan-only`.
- No version bump on the policy itself; this is the implementation of the previously-shipped foundation-versioning policy (minor-additive update to the implementation document).

- Source-Meta-Commit: `dafaee0`
- Public repo commit: `64448af`

---

## 2026-05-27 — clearer, more honest execution model for generated multi-agent systems (+ a session-lock fix)

**Public-facing change:** the wizard's generated markdown-agent systems now carry a clearer and more honest description of *how they run*, plus a real fix to the session lock that coordinates them.

- **Coordination model made explicit.** Every generated system has one **Orchestrator** that coordinates the work (selects from the queue, routes work, tracks session state); the **specialist agents** do the domain work. You interact with the work queue and the Claude Code session the Orchestrator runs in — not with individual agents directly. The `technical_architecture.md` template now states this up front.
- **Honest autonomy.** The `execution_plan.md` template now makes clear the system **runs when invoked** — either when you start a Claude Code session, or when a scheduled job starts the Orchestrator on a cadence you set. It is not an always-on background service and does not act while no session is open. "Operating on a cadence" means a scheduled run starts, completes its work, and exits.
- **Session-lock fix (important).** The single session lock (`maintenance_mode.md`) is now owned by the Orchestrator and lives in one place (the project root). Previously a path mismatch — plus a leftover check inside the specialist invocation script — could have caused scheduled or Orchestrator-spawned agent work to be skipped even though the system looked configured. Scheduled jobs now invoke the Orchestrator (which routes to agents); directly scheduling a single agent is an advanced exception. The agent handoff record now always includes a `stop_reason`.
- Default execution is **sequential for tasks that share files** (parallel only when write scopes are clearly separate), to avoid two agents clobbering the same file.

No schema, manifest, placeholder-key, or generated-output *structure* changes — template wording + the invocation script's session-lock handling.

**Operator-facing notes:**

- No operator action required for existing setups. If you regenerate or re-read your foundation docs, you'll see the clearer coordination + autonomy wording. The session-lock fix prevents a "configured but does nothing on schedule" failure mode.
- No version bump (clarifying wording + a corrective fix; no compatibility-affecting structural change).

- Source-Meta-Commit: `9dda645`
- Public repo commit: `8fa6702`

---

## 2026-05-27 — internal documentation hygiene (continued): remaining build-process references removed

**Public-facing change:** a follow-on to the prior hygiene pass that finishes removing short citations to the wizard's *private* build-process design records from the public files. Covered: two interview-step modules, several foundation-bundle docs (a migration manifest, a README, two section schemas, two hash baselines), one generator unit test, and eleven test fixtures. Each citation was either deleted (where the surrounding text already carried the meaning) or replaced with a plain-language description of the rule/behavior it pointed at (e.g. "the foundation-versioning policy", "the validation evidence storage convention"). The build-side reference checker that guards the public files was extended to catch the remaining identifier forms, plus a new advisory (non-blocking) review pass for the few ambiguous forms that can also be legitimate public wording. No code, schema, manifest, template, placeholder-key, or generated-output changes — wording only.

**Operator-facing notes:**

- No operator action required. Wizard behavior and every generated output are unchanged; this only finishes tidying internal references out of the public files.
- No version bump.

- Source-Meta-Commit: `719b5f9`
- Public repo commit: `d13834a`

---

## 2026-05-27 — internal documentation hygiene: removed build-process references from public files

**Public-facing change:** several public wizard files (interview-step modules, the bundle-generator script, and two foundation-bundle docs) carried short citations pointing at the wizard's *private* build-process design records — identifiers that an operator has no access to and does not need. Those citations were removed or replaced with plain-language descriptions of the rule/behavior they pointed at (e.g. "the honest-characterization rule", "the foundation-versioning policy"). No code, schema, manifest, template, placeholder-key, or generated-output changes — wording only.

**Operator-facing notes:**

- No operator action required. Wizard behavior and every generated output are unchanged; this only tidies internal references out of the public files.
- No version bump.

- Source-Meta-Commit: `77e365f`
- Public repo commit: `e506719`

---

## 2026-05-26 — stop-condition test fixture: pre-step-08 late-emergence regulated-data case

**Public-facing change:** one new test fixture is added to the stop-condition re-evaluate-loop fixture set (`test_fixtures/stop_condition_reevaluate_loop/`), covering the case where regulated-data exposure surfaces late (at the pre-architecture re-check) via an advisor the operator added, with the specific framework not yet identified — then resolves to foundation-only mode. No code, schema, manifest, template, or placeholder-key changes; test-fixture content only.

**Operator-facing notes:**

- No operator action required. This is an internal test-coverage addition; it does not change wizard behavior or any generated output.
- No version bump.

- Source-Meta-Commit: `3ad51d4`
- Public repo commit: `3d08afb`

---

## 2026-05-26 — foundation-bundle templates: lifecycle + maintenance completeness

**Public-facing change:** two of the `v0.3.0` foundation-bundle templates gain more complete coverage of system-lifecycle and maintenance topics, surfaced while walking a real-operator-generated bundle. No code, schema, manifest, or placeholder-key changes — template prose only; generated bundles continue to render from the same keys.

- **Audit-framework template:** the autonomy framing is generalized so it applies across every autonomy level rather than implying only a subset is defined; a new **Rules library** section consolidates rule definitions already used elsewhere in the wizard; and a new **System lifecycle** section adds **Maintenance** and **Upgrades** subsections so an operator-facing bundle documents how the system is kept healthy and how it is upgraded over time.
- **Test-cases template:** an introductory note now makes explicit that some test cases reference mechanisms defined in the broader foundation documents (not all mechanisms are defined inside the test file itself), and a new **Test maintenance** section covers how the test suite is maintained and evolved as the system changes.

**Operator-facing notes:**

- No operator action required. These are template-content improvements; operator projects generated from earlier template states are unaffected unless regenerated.
- No version bump (the templates remain part of the `v0.3.0` prerelease bundle); no generator or schema change.

- Source-Meta-Commit: `a6f00c5`
- Public repo commit: `b6c28d4`

---

## 2026-05-22 — foundation-bundle generator first real-operator generation event (structural anonymization)

**Public-facing change:** the wizard distribution exercises the foundation-bundle generator pipeline against real-operator content for the first time. The release ships no code changes to the generator itself (the pipeline is unchanged from the prior `2026-05-22` internal first-generation event); what changes is the addition of a durable real-operator-content fixture under the wizard's test directory, exercising the same generator against operator answers from an actual real-world project rather than synthetic placeholders.

**Honest characterization.** This is a real-operator-content first-capture milestone, NOT operator-fit validation, NOT arms-length operator review, and NOT a stability commitment for v1.0.0 promotion. The operator for this capture is the wizard's primary author (operator role and build-session lead role collapse in this release); arms-length operator validation remains forthcoming.

**Privacy discipline.** All identifying entities in the real-operator content (entity identifiers across multiple categories — people, organizations, accounts, dates, amounts, locations, contact information) are captured using STABLE PLACEHOLDER LABELS rather than real values. The committed fixture preserves the operator content's STRUCTURAL SHAPE (scope / agents / orchestration / autonomy / phases) verbatim while keeping all third-party identifying information out of the distributed artifact. A real-label-to-placeholder mapping file lives on the operator's local disk outside any distributed repository. Operators using the wizard for sensitive content can adopt the same structural-anonymization discipline.

**Operator-facing notes:**

- The same generator pipeline (`wizard/scripts/generate_bundle.py` + `wizard/scripts/lib/generator.py`) is exercised; no version bump, no API change.
- The wizard's `wizard-proposes-user-confirms` operating principle (per `wizard/CLAUDE.md` rule 5) is exercised at both the derivation surface (operator answers → Claude proposes derived content → operator confirms/adjusts) and the review surface (operator reviews generated documents → Claude proposes per-document verdict + surprises → operator confirms/adjusts). Both surfaces are bootstrap-grade (Claude-facilitated, ad-hoc); designed-mechanism implementation of the interview surface is forthcoming in a later release.
- No operator action required at this release. Operator projects produced via earlier paths continue to be unaffected.

- Source-Meta-Commit: `ca22c00`
- Public repo commit: `5f2fe67`

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
