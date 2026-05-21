# Stop-condition halt → re-evaluate-shape loop fixture corpus — a prior slice + a prior slice

## Purpose

Synthetic fixtures for the stop-condition halt → re-evaluate-shape loop implemented at `wizard/interview/_stop_condition_reevaluate_loop.md`. Each fixture supplies (a) a halt-firing scenario at pre-step-05 OR pre-step-08; (b) the operator's choice at the halt's three-path surface (`(a)` save-and-exit / `(b)` change-shape / `(c)` regulatory-revise); (c) expected loop iteration trace + terminal-state outcome.

These fixtures exercise the loop's state machine + iteration cap (2 at v0) + probe re-ask path (P-5/P-6/P-7) + (c) regulatory-exposure path including condition-4 framework-identification + regulated-flag-revision sub-cases + multi-framework UP-6 re-ask + foundation state preservation through iterations + terminal-state branching. **Producer-visible terminal outcomes are the CLOSED 4-value enum** `continued` / `foundation_only` / `scope_out` / `next_iteration` (per a prior advisor finding disposition; `forced_terminal` is internal-only branch state at sub-module § 6 — never recorded as producer-visible outcome).

## Scope

**v0 (a prior slice initial pack):** 4 fixtures covering condition 1/2/3 entry paths + (b) shape-revision loop + (c) named-framework regulatory-revise (GDPR only) + pre_step_08 late-emergence.

**a prior slice extension (2026-05-19):** 5 additional fixtures (scrl05-09) covering:

- Condition-4 (regulated + framework not identified) (c) path — both sub-cases (framework-identification AND regulated-flag-revision)
- Condition-4 → condition-1 transition (framework identification triggers cascading conditions)
- Multi-framework UP-6 re-ask (operator with 2+ framework-applicable fields)
- HIPAA named-framework (c) revise (parallel to scrl03 GDPR-revise pattern)

**Coverage class throughout:** synthetic-fixture coverage only (`demonstrated` evidence level per `the relevant build-side spec` § 3 success-criterion; NOT `validated`). Real-operator-input validation deferred to E-α tester slice OR next operator-facing slice. Iteration cap calibration (2) is hypothesis-only; first-real-operator-data may revise.

## Fixture inventory

### a prior slice initial pack

| Fixture | Entry scenario | Operator path | Expected terminal outcome (producer-visible) | Expected terminal_reason |
|---|---|---|---|---|
| `scrl01-hipaa-halt-to-foundation-only.md` | sc01 HIPAA halt at pre-step-05 (condition 1) | (b) → iterations 1+2 → cap reached → operator picks (i) foundation-only at § 7 forced-disclosure | `foundation_only` (+ stop_conditions cross-slice mutation per a prior advisor finding) | `iteration_cap_reached` |
| `scrl02-pci-halt-to-scope-out.md` | sc03 PCI-DSS halt at pre-step-05 (condition 3) | (b) → iterations 1+2 → cap reached → operator picks (ii) scope-out at § 7 forced-disclosure | `scope_out` (no cross-slice mutation) | `iteration_cap_reached` |
| `scrl03-gdpr-halt-to-c-revise-to-continue.md` | sc02 GDPR halt at pre-step-05 (condition 2) | (c) regulatory-revise → operator clarifies no EU customers → conditions cleared in 1 iteration | `continued` to step 05 | `regulatory_exposure_revised_clears_conditions` |
| `scrl04-pre-step-08-late-hipaa-to-foundation-only.md` | Markdown-agents shape with no step 03 HIPAA exposure; vision content (step 05) mentions "patient communication" → pre-step-08 late-emergence HIPAA halt | (b) → iterations 1+2 → cap reached → operator picks (i) foundation-only at § 7 forced-disclosure; vision + approach preserved on disk | `foundation_only` (+ stop_conditions cross-slice mutation) | `iteration_cap_reached` |

### a prior slice extension pack

| Fixture | Entry scenario | Operator path | Expected terminal outcome (producer-visible) | Expected terminal_reason |
|---|---|---|---|---|
| `scrl05-condition-4-identify-sector-framework-to-continue.md` | Condition 4 fires (regulated + framework unknown; sector-specific marker) | (c) framework-identification → operator names sector-specific advisory framework that does NOT trigger conditions 1/2/3 against markdown-agents | `continued` to step 05; `other_sector_specific[]` populated | `regulatory_exposure_revised_clears_conditions` |
| `scrl06-condition-4-identify-hipaa-to-foundation-only.md` | Condition 4 fires (regulated + framework unknown) | (c) framework-identification → operator names HIPAA → condition 1 fires post-revision → next_iteration → operator picks (b) → iter 2 cap → forced terminal foundation-only | `foundation_only` (+ stop_conditions cross-slice mutation per a prior advisor finding active-vs-transitional distinction; `fired: [1]`; `documented_in_foundation: [1]`; `resolved_during_loop: [4]`) | `iteration_cap_reached` |
| `scrl07-condition-4-revise-regulated-flag-to-continue.md` | Condition 4 fires (regulated + framework unknown; multi-bucket UP-6.1 markers) | (c) regulated-flag-revision → operator realizes initial UP-6.1 markers were over-cautious → `no_compliance_claim: no → yes` → conditions cleared | `continued` to step 05 | `regulatory_exposure_revised_clears_conditions` |
| `scrl08-multi-framework-up6-reask-hipaa-and-gdpr-revise.md` | Condition 1 fires (HIPAA + markdown-agents; GDPR also active) | (c) multi-field UP-6 re-ask → operator revises `hipaa_applicable: yes → no` AND `gdpr_applicable: yes → no` → conditions 1 + 2 BOTH cleared | `continued` to step 05; both frameworks revised; the relevant ADR-clean (no compliance-class-active-continuing path) | `regulatory_exposure_revised_clears_conditions` |
| `scrl09-condition-1-hipaa-named-framework-revise-to-continue.md` | sc05-class HIPAA halt at pre-step-05 (condition 1; operator over-cautious re: HIPAA covered-entity-status) | (c) UP-6 re-ask with HIPAA covered-entity disclosure → operator clarifies (de-identified aggregate statistics; not covered entity) → `hipaa_applicable: yes → no` → condition 1 cleared | `continued` to step 05 | `regulatory_exposure_revised_clears_conditions` |

**Producer-visible terminal outcome enum** (closed; per a prior advisor finding disposition): `continued` / `foundation_only` / `scope_out` / `next_iteration`. The internal branch state `forced_terminal` at sub-module § 6 (iteration cap reached AND conditions still fire) is NEVER recorded as a producer-visible outcome — module handles the final-choice prompt internally and maps operator's pick to `foundation_only` or `scope_out` with `terminal_reason: iteration_cap_reached`.

## Coverage matrix

| Trigger condition | (b) shape-revise path | (c) revise path | Cross-slice mutation | Multi-framework UP-6 re-ask |
|---|---|---|---|---|
| Condition 1 (HIPAA) | scrl01 (foundation-only at cap) | scrl08 (HIPAA + GDPR multi-framework revise) + scrl09 (HIPAA-revise standalone) | scrl01 (`documented_in_foundation: [1]`) | scrl08 (HIPAA + GDPR multi-field) |
| Condition 2 (GDPR) | (assumed symmetric per § 4.2 Variant A; not separately fixtured) | scrl03 (GDPR-revise standalone); scrl08 (GDPR-revise as co-active with HIPAA) | n/a (continued outcome) | scrl08 (co-active with HIPAA) |
| Condition 3 (PCI-DSS) | scrl02 (scope-out at cap) | (assumed symmetric per § 4.2 Variant A; not separately fixtured at v0) | n/a (scope-out has no mutation) | n/a |
| Condition 4 (regulated + framework unknown) | (operator picks (b) at re-prompt within scrl06 iter 2) | scrl05 (sector-framework-identification-clears) + scrl06 (HIPAA-identification-triggers-condition-1) + scrl07 (regulated-flag-revision-clears) | scrl06 (`documented_in_foundation: [1]` + `resolved_during_loop: [4]` — active-vs-transitional distinction per a prior advisor finding) | (assumed symmetric per § 4.3; not separately fixtured under condition 4) |
| Pre-step-08 late-emergence | scrl04 (HIPAA late-emergence) | (assumed symmetric per § 4.3; not separately fixtured at v0) | scrl04 (`documented_in_foundation: [1]`; `late_emergence_source: vision`) | n/a |

**Outcome distribution:** `continued` x5 (scrl03, scrl05, scrl07, scrl08, scrl09) / `foundation_only` x3 (scrl01, scrl04, scrl06) / `scope_out` x1 (scrl02).

**Reason-enum coverage:** `operator_clarification` (scrl03, scrl07, scrl08, scrl09) / `framework_identification` (scrl05, scrl06) — both reason values exercised per sub-module § 4.3.

## Coverage limits (known at v0 + a prior slice)

**Closed by a prior slice extension (compared to a prior slice):**

- ~~Condition 4 (regulated + no framework identified) recovery path: NOT exercised at v0~~ — **CLOSED by scrl05/scrl06/scrl07.** § 4.2 Variant B disclosure + § 4.3 condition-4 UP-6 re-ask variant now fixtured across both sub-cases (framework-identification + regulated-flag-revision).
- ~~(c) regulatory-exposure path tested for GDPR-revise case only (scrl03)~~ — **PARTIALLY CLOSED.** HIPAA-revise now fixtured (scrl09; parallel to scrl03 GDPR pattern). PCI-DSS / SOX / COPPA (c) paths remain assumed symmetric per § 4.2 Variant A framework-specific disclosure variants; not separately fixtured at v0.

**Retained known limits (a prior slice does not close):**

- Synthetic fixtures only; no real-operator data. Validation status = `demonstrated for synthetic fixtures; validation pending real-operator input`.
- Paper-replay walkthrough only (no executable wizard run; the wizard is a markdown-driven interview agent; replay = agent reads fixture frontmatter + walks loop sub-module mentally; expected outcomes recorded; no live operator interaction tested).
- Iteration cap calibration (2) is hypothesis-only; first-real-operator-data may revise.
- Probe re-ask path (step 02 fallback probes P-5/P-6/P-7 only) is a prior slice v0 default; first-real-operator-data may revise.
- PCI-DSS / SOX / COPPA (c) revise paths not separately fixtured (HIPAA + GDPR + sector-specific are covered; remaining named frameworks assumed symmetric per § 4.2 Variant A).
- Pre-step-08 late-emergence loop with vision+approach already on disk tested for HIPAA late-emergence only (scrl04); other framework late-emergence cases assumed to follow same pattern; pre-step-08 condition-4 late-emergence NOT separately fixtured (a prior slice pre_step_05 only).
- Mixed-shape per-component capability loop interaction not exercised (reserved for v1+ per a prior slice handoff contract § 5).
- Concurrent loop-then-late-emergence-at-pre-step-08 case tested with fresh iteration counter (scrl04 Decision E); inherit-counter alternative not exercised.
- Operator-mid-loop-interruption-then-resume case (loop fires; autocompaction occurs mid-iteration; operator resumes wizard) not exercised. `shape_revision.pending: true` is the recovery signal but no fixture exercises restart-mid-iteration behavior.

**New known limits surfaced by a prior slice (post R1 disposition):**

- **Sector-specific compliance-class frameworks (FERPA / GLBA / similar with enforceable controls) NOT exercised on continuing paths.** v0 has no 5th stop condition for sector-specific compliance frameworks beyond the named ones (HIPAA / GDPR / PCI-DSS / SOX / COPPA). Demonstrating an active compliance-class sector framework on a continuing path would violate the relevant ADR § 2.3 honest-characterization rule (compliance-class workloads on advisory-only controls must surface as stop condition). a tracked open question reserves the design space for the 5th stop condition. v0 fixtures use named-compliance frameworks (HIPAA + GDPR via scrl08) for multi-framework re-ask coverage; the sector-specific test case in scrl05 uses an explicitly advisory-only framework that doesn't trigger compliance-class concerns. **Forward-looking gap; not a demonstrated-working surface.**
- **Spec internal-inconsistency at condition-4 predicate corrected at per a prior advisor finding (2026-05-19).** Prior `shape_detection.md` § 8.3 row 4 + `_pre_step_05_recheck.md` line 59 predicate (any framework-applicable yes OR `other_sector_specific` non-empty AND framework_identification unknown) was internally incoherent — if a specific framework were `applicable: yes`, framework identification would NOT be `unknown` per UP-6 source semantics. Corrected to `no_compliance_claim == no AND framework_identification == unknown` matching UP-6 line 243's canonical condition-4-trigger case. Memory captured at `a relevant lesson record`. Fixtures scrl05/06/07 pre-state already aligned with corrected predicate.

## Regression coverage

a prior slice fixture pack (14 fixtures at `wizard/test_fixtures/shape_detection/`) + a prior slice fixture pack (5 fixtures at `wizard/test_fixtures/foundation_only_mode/`) + a prior slice fixture pack (4 fixtures scrl01-04) MUST continue to replay correctly post-a prior slice.

a prior slice adds fixtures only; no spec / contract / sub-module text changes (per Decision I minimal). a prior slice extension is additive.

## Cross-references

- a prior slice spec — `the originating slice spec`
- a prior slice spec — `the originating slice spec`
- Loop sub-module — `wizard/interview/_stop_condition_reevaluate_loop.md`
- a prior slice fixture corpus — `wizard/test_fixtures/shape_detection/` (source-scenario inputs derived from sc01-sc04 stop-condition fixtures)
- a prior slice fixture corpus — `wizard/test_fixtures/foundation_only_mode/` (terminal-state handoff target when loop converges to foundation-only)
- Validation evidence (a prior slice) — the relevant build-side validation evidence record
- Validation evidence (a prior slice) — the relevant build-side validation evidence record (condition-4 fixture extension)
- the relevant ADR § 2.3 — honest characterization rule (FERPA + sector-specific framework treatment at v0)
- a tracked open question — 5th stop condition (regulated + insufficient operator authority); E-γ-bound; sector-specific framework treatment also folds in here
