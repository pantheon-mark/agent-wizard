# Foundation-only-mode gate — derived mode profile + per-step entry-guard pattern

## What this file does

Provides the single-source-of-truth for foundation-only-mode behavior across wizard interview steps 05-15. Specifies (a) the mode profile fields foundation-only-mode behavior gates on (Section 1; centralized projection, NOT independent capabilities, NOT persisted); (b) the derivation rule that maps the `shape_hypothesis.fallback_mode_offered` enum label to mode profile values (Section 2); (c) the entry-guard pattern each of `05_vision.md` through `15_close.md` follows (Section 3; placement varies — post-recheck for steps 05 + 08, file-start for the other 9 files); (d) the honest-characterization disclosure rules (Section 4); (e) the foundation doc set definition (Section 5); (f) the stop-condition DOCUMENT-path integration shape (Section 6); (g) a cross-reference to step 15's close-ceremony adaptation (Section 7); (h) the mechanism stack record (Section 8).

This file is **read-only** by per-step entry guards. Per-step files do NOT modify the mode profile fields or the derivation rule. The `shape_hypothesis.fallback_mode_offered` label (set by shape-detection at step 01/02 initial emit OR at the unsupported-shape transition per `wizard/shape_detection.md` § 6) is the persisted source-of-truth; mode profile fields derive at the moment of use (NOT persisted).

## When this file runs

This is a SHARED reference module, NOT an interview step. Per-step entry guards (in each of `05_vision.md` through `15_close.md`) consult this file's Sections 1, 2, and 3 to determine whether to follow the step's normal-behavior path OR the foundation-only adapted path. Steps 05-15's behavior branches accordingly.

The label `shape_hypothesis.fallback_mode_offered` is guaranteed to be set by the time per-step entry guards fire, because:

- Step 01 P1-8 emits initial `shape_hypothesis` with `fallback_mode_offered: complete | foundation-only | scope-out | not_offered` (per `wizard/shape_detection.md` § A.3)
- Step 02 P02-FB-5 may revise the label if step-02 fallback fires
- `_pre_step_05_recheck.md` Step 5 may set the label to `foundation-only` or `scope-out` if unsupported-shape transition fires at pre-step-05
- `_pre_step_08_recheck.md` may set the label similarly at pre-step-08

If the entry guard fires AND the label is missing from staging file, that is a wizard-internal-state error (covered in Section 3 below).

## Prerequisites

- `~/claude-wizard-draft/wizard_session_draft.md` exists and contains `shape_hypothesis.fallback_mode_offered` field
- Wizard execution has reached step 05 or later (steps 00-04 + `_pre_step_05_recheck.md` complete per `~/claude-wizard-draft/wizard_progress.md`)

## Reference spec

- The originating slice spec (build-side; not distributed) is the design provenance for this module.
- `wizard/shape_detection.md` § 6 — unsupported-shape transition (sets `fallback_mode_offered`)
- the relevant product spec section + § 4.4 — operator-facing contract
- the honest-characterization rule

---

## Section 1 — Mode profile (centralized projection; not independent capabilities)

Foundation-only-mode behavior gates on a **mode profile** — four fields that are a **deterministic projection** of the single `shape_hypothesis.fallback_mode_offered` enum label. They are NOT independent capabilities (unlike `control_matrix_active` capability fields in the shape detection contract, which are independent per shape × control combination). They are NOT persisted to the staging file at v0; per-step entry guards re-derive from the label at use.

*(Naming honesty: this is centralized mode projection, not a peer of capability contracts. The projection earns its keep ONLY through (a) version-checking the handoff contract before reading the label, AND (b) being transition-order-safe in step 05 + step 08 where pre-step re-checks can mutate the label.)*

| Mode profile field | Type | Meaning |
|---|---|---|
| `produce_foundation_docs` | boolean | Whether `vision.md` + `approach.md` + `technical_architecture.md` + `execution_plan.md` get written to operator project directory at step 15 close |
| `produce_system_implementation` | boolean | Whether agent prompts + scripts + `.env` + `.gitignore` + `start-session.sh` + `session_bootstrap.md` + `/agents/` + `/quality/` + `/work/` + `/logs/` + `/security/` get written at step 15 close |
| `capture_implementation_inputs` | boolean | Whether the interview keeps capturing implementation-specific inputs (e.g., credential rotation cadence, error-handling preferences) at steps 07-13; captured inputs land in foundation-doc sections in foundation-only mode |
| `honest_characterization_disclosure` | enum: `foundation_only` / `scope_out` / `complete` / `none` | Which honest-characterization disclosure path applies at step 15 close + in foundation-doc voice |

**No staging-file persistence at v0.** The label `shape_hypothesis.fallback_mode_offered` is the persisted source-of-truth. Per-step entry guards read the label from staging, consult the Section 2 derivation rule, and act on the derived values without writing them back. This avoids stale-label-vs-stale-projection divergence risk (single write point = label; no shadow copy).

Future v1 may persist projection fields for debugging or contract-observability; out of scope per the slice spec Deferred.

---

## Section 2 — Derivation rule (label → mode profile)

Per-step entry guards consult this table to determine behavior:

| `shape_hypothesis.fallback_mode_offered` | `produce_foundation_docs` | `produce_system_implementation` | `capture_implementation_inputs` | `honest_characterization_disclosure` |
|---|---|---|---|---|
| `complete` | true | true | true | `complete` |
| `foundation-only` | true | **false** | **true** | `foundation_only` |
| `scope-out` | false | false | false | `scope_out` |
| `not_offered` | true | true | true | `none` |

**Derivation invariants:**

1. The dominant branch adds behavior for is `produce_system_implementation == false` AND `produce_foundation_docs == true` — i.e., the `foundation-only` row.
2. `complete` and `not_offered` both yield `produce_system_implementation == true`; per-step entry guards treat them identically (normal-behavior path). The label distinction is preserved upstream for shape-detection diagnostic value but does not branch behavior at steps 05-15.
3. `scope-out` yields `produce_foundation_docs == false`. The wizard does NOT reach steps 05-15 in scope-out path (exit fired at unsupported-shape transition per `wizard/shape_detection.md` § 6). The row is included for completeness; per-step entry guards never fire under scope-out. If an entry guard fires WITH `fallback_mode_offered == scope-out`, that is an internal-state error (see Section 3).

**Mode profile fields are NOT independent.** They are a deterministic projection from the single label per the table; do NOT attempt to set them individually OR override the table without revising this file.

---

## Section 3 — Per-step entry-guard pattern

Each of `05_vision.md` through `15_close.md` includes a foundation-only-mode entry-guard sub-step. **Placement depends on whether the step contains a pre-step shape-detection re-check**:

- **Steps 05 + 08 (contain pre-step-05 / pre-step-08 re-checks):** the entry guard MUST be placed **AFTER** the re-check invocation (after the existing `## Pre-step-NN re-check` section in each file). Reason: `_pre_step_05_recheck.md` Step 5 + `_pre_step_08_recheck.md` Step 5 can mutate `shape_hypothesis.fallback_mode_offered` via the unsupported-shape transition; an entry guard running before the re-check would branch on stale state.
- **Steps 06, 07, 09, 10, 11, 12, 13, 14, 15 (no pre-step re-check):** the entry guard is placed at file start, immediately after the `## Sub-step resume check` section. No mutation of `fallback_mode_offered` happens within these files, so file-start placement is safe.

The entry-guard pattern (verbatim across all 11 files):

```markdown
## Foundation-only-mode entry guard

Before doing anything else in this step (or, for steps 05 + 08, before any step-NN user-facing question fires beyond the pre-step-NN re-check):

1. **Schema-version check (per handoff contract consumer rule).** Read `~/claude-wizard-draft/wizard_session_draft.md`; locate the `schema_versions` block under shape_hypothesis. Verify `schema_major == 0`. If `schema_major` mismatches the consumer expected major (currently `0` at v0), abort with operator-facing internal-state error: "I hit a wizard-internal version mismatch — the staging file's shape-detection schema major is `<actual>`, but this version of the wizard expects major `0`. Your project file is saved. Please update the wizard OR resume with the matching wizard version." Exit cleanly; do NOT proceed.

2. Locate the `shape_hypothesis.fallback_mode_offered` field.

3. Consult `wizard/interview/_foundation_only_mode_gate.md` § 2 derivation rule. Determine:
 - `produce_foundation_docs` (boolean)
 - `produce_system_implementation` (boolean)
 - `capture_implementation_inputs` (boolean)
 - `honest_characterization_disclosure` (enum value)

4. Branch:
 - If `produce_system_implementation == true` (label is `complete` OR `not_offered`): follow the rest of this file's existing step content below this entry guard (the wizard's normal behavior for this step).
 - If `produce_system_implementation == false` AND `produce_foundation_docs == true` (label is `foundation-only`): skip the existing step content and follow the section titled **`## Foundation-only adapted path`** at the end of this file.
 - If `produce_foundation_docs == false` (label is `scope-out`): wizard-internal-state error — wizard should have exited at the unsupported-shape transition; do NOT proceed past this step. Halt with internal-error message; foundation state preserved.

5. If `fallback_mode_offered` is missing from staging file entirely: wizard-internal-state error per `_pre_step_05_recheck.md` prerequisite check pattern. Halt; do NOT proceed. Tell operator: "I hit an internal state error in the wizard. The shape hypothesis is missing. Your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. Please resume the wizard; it'll pick up at the right step." Exit cleanly.
```

The entry-guard sub-step is **verbatim across all 11 step files** (steps 05 through 15) — only the placement differs (post-recheck for 05 + 08; file-start for the other 9). Consistency is load-bearing per the prior retrospective lesson #2 (spec-update-must-propagate-to-producers): if this pattern needs revision, it must be revised here AND in all 11 step files in the same revision; never in only one.

Each step file has two behavior paths after the entry guard:

1. **Normal behavior path** — the step's existing content (immediately below the entry guard); followed when `produce_system_implementation == true`
2. **Foundation-only adapted path** — a new section titled `## Foundation-only adapted path` appended at the end of each step file; followed when `produce_system_implementation == false`; the foundation-only disposition table (PRODUCE / ADAPT-capture / ADAPT-split / ADAPT-rebuild)

---

## Section 4 — Honest-characterization disclosure rules

Per the honest-characterization rule.

**When `honest_characterization_disclosure == foundation_only`:**

- Step 15 close: closing message + `next_steps.md` MUST surface verbatim:
 > "Foundation-only mode. Implementation deferred. Take these docs to Claude Code directly OR wait for v2 wizard shape support."
- `project_instructions.md` opening section MUST surface:
 > "These foundation docs describe your project at the system-blueprint level. They are implementation-agnostic. Implementation NOT included in this output."
- `manual.md` MUST surface: pointer to `next_steps.md`; no claim of "operating manual" semantics implying a running system.

**When `honest_characterization_disclosure == complete`:**

Normal wizard close path per `15_close.md` current content. No special foundation-only disclosure.

**When `honest_characterization_disclosure == scope_out`:**

Wizard exits at unsupported-shape transition; steps 05-15 never run. Captured here for completeness; not exercised by per-step entry guards.

**When `honest_characterization_disclosure == none`:**

Default markdown path with no transition fired. No special disclosure beyond normal wizard close.

**NOT silent fallback.** Foundation-only mode is always operator-elected (option b at unsupported-shape transition); never silently substituted by the wizard.

---

## Section 5 — Foundation doc set definition

In foundation-only mode (`produce_system_implementation == false` AND `produce_foundation_docs == true`), the **foundation doc set** is exactly four files, written to the operator project directory at step 15 close:

| File | Source step | Content shape |
|---|---|---|
| `vision.md` | Step 05 | Operator-facing project vision; foundation level; shape-agnostic |
| `approach.md` | Step 06 | Project approach / methodology; foundation level; shape-agnostic |
| `technical_architecture.md` | Step 08 (ADAPT-split) | Shape-agnostic technical architecture; INCLUDES § "Regulatory & compliance gaps (foundation-only mode)" if stop-condition DOCUMENT path fired at `_pre_step_05_recheck.md` Step 2b (per Section 6) |
| `execution_plan.md` | Step 13 + step 14 (ADAPT) | Foundation-level execution sequencing |

**SKIP from foundation doc set in foundation-only mode:**

- `test_cases.md` — implementation-validation-shape artifact; not foundation-level
- `audit_framework.md` — implementation-audit-shape artifact; not foundation-level

**Per-step captured-input sections** (ADAPT-capture pattern for steps 07, 09, 10, 11, 12, 13, 14): captured operator inputs land as sub-sections of `technical_architecture.md` § "Operational requirements". Specifically:

| Step | Captured-input section in `technical_architecture.md` |
|---|---|
| 07 (advisors) | § "Operational requirements" > "Advisor list" |
| 09 (credentials) | § "Operational requirements" > "Credential inventory" |
| 10 (validation) | § "Operational requirements" > "Validation rules" |
| 11 (error handling) | § "Operational requirements" > "Error-handling approach" |
| 12 (qa settings) | § "Operational requirements" > "QA approach" |
| 13 (operations) | § "Operational requirements" > "Operational requirements (cadence, scale, drift)" |
| 14 (document review) | (not captured here; produces simpler document review of the 4-doc foundation set) |

**Operator project directory structure in foundation-only mode**:

```
~/[project-name]/
├── vision.md
├── approach.md
├── technical_architecture.md
├── execution_plan.md
├── project_instructions.md # ADAPT: foundation-only voice
├── manual.md # ADAPT: pointer doc only
└── next_steps.md # NEW: path-forward guidance
```

NO subdirectories (no `/agents/`, `/quality/`, `/work/`, `/logs/`, `/security/`, `/docs/`, `/archive/`).
NO `.env`, `.gitignore`, `start-session.sh`, `session_bootstrap.md` (those are implementation).
NO `git init` (foundation docs are portable; operator decides repo strategy).
NO GitHub remote setup.
NO first-build-prompt generation.

---

## Section 6 — Stop-condition DOCUMENT-path integration

Per `wizard/shape_detection.md` § 8.5 + `_pre_step_05_recheck.md` Step 2b: stop conditions fired in foundation-only mode produce DOCUMENT-path entries (NOT HALT). Those entries flow into `technical_architecture.md` § "Regulatory & compliance gaps (foundation-only mode)" at step 15 close.

**Per gap entry shape (one section under § "Regulatory & compliance gaps (foundation-only mode)" of `technical_architecture.md`):**

```markdown
### Gap: <framework name>

**Status:** documented (foundation-only mode)
**Framework:** <e.g., HIPAA / GDPR / PCI-DSS / regulated-but-unnamed-framework>
**Capability gap:** <e.g., "PCI-DSS encryption-at-rest requires implementation that markdown-agents-on-Claude-Code does not provide"> (read from staging `stop_conditions.documented_in_foundation` + `control_matrix_active` status)
**Recommended resolution path:** <e.g., "Implementation in a shape supporting encryption-at-rest required before production data handling">
```

**Source data:**

- `stop_conditions.documented_in_foundation` (staging file; populated by `_pre_step_05_recheck.md` Step 2b)
- `control_matrix_active` (staging file; populated by classifier per `wizard/shape_detection.md` § 7)

**Empty case:** if `stop_conditions.documented_in_foundation` is empty (no stop conditions fired in foundation-only path), the § "Regulatory & compliance gaps (foundation-only mode)" header is omitted from `technical_architecture.md` entirely (no empty section).

---

## Section 7 — Close ceremony adaptation pointer

Step 15 close (`15_close.md`) implements the foundation-only-mode close ceremony. Full per-sub-step disposition lives at `15_close.md` § "Foundation-only adapted path"; this section is a summary cross-reference only.

**Summary of step 15 adaptation:**

- CLOSE-ASSEMBLY produces the 4-file foundation doc set per Section 5 + `project_instructions.md` (ADAPT — foundation-only voice per Section 4) + `manual.md` (ADAPT — pointer doc only per Section 4) + `next_steps.md` (NEW — path-forward guidance with honest-characterization disclosure per Section 4)
- SKIP all implementation file writes (agent prompts, scripts, `.env`, `.gitignore`, `start-session.sh`, `session_bootstrap.md`)
- SKIP all implementation directory creation (`/agents/`, `/quality/`, `/work/`, `/logs/`, `/security/`, `/docs/`, `/archive/`)
- SKIP `git init` and GitHub remote setup
- SKIP first-build-prompt generation
- Closing message + `next_steps.md` carry honest-characterization disclosure per Section 4

---

## Section 8 — Mechanism stack record (D2 § mechanism-stack-template)

Per the operational change safety spec mechanism-stack-template.

```yaml
mechanism_id: mech-foundation-only-mode-v0
mechanism_name: Foundation-only-mode behavior (steps 05-15)
mechanism_class: Skill — pure markdown (advisory or guided)
mechanism_type: markdown
hybrid_contract_status: not-applicable
canonical_governance_doc: wizard/interview/_foundation_only_mode_gate.md
primary_mechanism: this gate module (derived mode-profile schema + label-to-mode-profile derivation rule + per-step entry-guard pattern; label persisted in staging, mode profile NOT persisted); per-step `## Foundation-only adapted path` sections in wizard/interview/05_vision.md through 15_close.md
reinforcing_mechanisms:
  - shape_hypothesis.fallback_mode_offered label in staging file (set at unsupported-shape transition per wizard/shape_detection.md § 6) — persisted source-of-truth for derivation
  - wizard/handoff_contracts/shape_detection_v0.md § 8 cross-reference to this module
  - Derived mode-profile gating per the prior retrospective lesson record, applied with the framing correction (centralized projection of the single enum label, NOT a peer of control-matrix capability contracts; extends cleanly to new enum values)
  - Honest-characterization rule — disclosure surfaces at step 15 close + project_instructions.md + next_steps.md
detection_recovery_mechanisms:
  - Per-step entry-guard internal-state-error halt (when fallback_mode_offered missing OR scope-out reaches steps 05-15; foundation state preserved)
  - Stop-condition DOCUMENT-path integration (compliance gaps surfaced honestly in foundation docs rather than silenced)
  - Operator-resume optionality preserved via `capture_implementation_inputs: true` + staging file preservation (contract-specified; concrete resume tooling deferred)
rationale: Foundation-only mode is a behavior-shape mode that gates implementation-emit decisions across 11 interview steps. A shared gate module + derived mode profile + per-step entry-guard pattern provides single-source-of-truth and reduces propagation surface (per the prior retrospective lesson #2 spec-update-must-propagate-to-producers). The mode is deterministic; the derived projection extends cleanly if v2 adds more enum values to `fallback_mode_offered` (e.g., `partial-implementation` for a future hybrid mode). This is centralized mode projection, NOT a peer of control-matrix capability contracts; label persisted in staging, mode profile NOT persisted. Stop-condition DOCUMENT-path integration ensures honest characterization without silent fallback.
validation_method: manual paper-replay walkthrough of entry-guard branching + adapted-path execution against synthetic fixtures (5 foundation-only-mode fixtures + regression check). Per the validation evidence storage convention.
validation_evidence: validation/mech-foundation-only-mode-v0/2026-05-19_s2.2_initial_fixture_replay.md
known_coverage_limits:
  - Synthetic fixtures only; no real-operator data
  - Paper-replay only (markdown-driven interview agent; no executable run)
  - Foundation-doc TEMPLATES still markdown-shape-tinted (cross-shape neutralization deferred)
  - Operator-resume-to-full-build tooling (the relevant product spec requirement re-open path) NOT exercised at v0
  - DOCUMENT-path integration tested for HIPAA condition only (one fixture); GDPR/PCI-DSS/regulated-no-framework conditions assumed to follow same pattern
  - Mixed-shape per-component capability blocks not tested (reserved for v1+ handoff contract § 5)
  - Sub-step resume in foundation-only mode not exercised
reverify_trigger: first real-operator-input foundation-only mode session; OR foundation-doc template cross-shape neutralization slice completes; OR the relevant product spec requirement re-open path implementation slice completes; OR shape-detection contract major-version bump (would change fallback_mode_offered field semantics).
mvp_lifecycle: foundation-tier (gates behavior across 11 interview steps; load-bearing for honest characterization of unsupported-shape path)
```

---

## Cross-references

- The originating slice spec (build-side; not distributed) is the design provenance for this module.
- The originating slice spec (build-side; not distributed) — unsupported-shape transition + foundation-only-mode contract origin.
- `wizard/shape_detection.md` § A.5 + § 8.5 — DOCUMENT-path semantics
- `wizard/handoff_contracts/shape_detection_v0.md` — `fallback_mode_offered` field source
- the per-shape control matrix — honest characterization rule
- the operational change safety spec § mechanism-stack-template — mechanism stack record format for `mech-foundation-only-mode-v0`
- the relevant product spec section + § 4.4 — operator-facing contract
- `_pre_step_05_recheck.md` Step 2b — DOCUMENT-path source for stop-condition gap entries
