# Stop-condition halt → re-evaluate-shape loop fixture corpus — S2.3

## Purpose

Synthetic fixtures for the stop-condition halt → re-evaluate-shape loop implemented at `wizard/interview/_stop_condition_reevaluate_loop.md`. Each fixture supplies (a) a halt-firing scenario at pre-step-05 OR pre-step-08; (b) the operator's choice at the halt's three-path surface (`(a)` save-and-exit / `(b)` change-shape / `(c)` regulatory-revise); (c) expected loop iteration trace + terminal-state outcome.

These fixtures exercise the loop's state machine + iteration cap (2 at v0) + probe re-ask path (P-5/P-6/P-7) + (c) regulatory-exposure path + foundation state preservation through iterations + terminal-state branching. **Producer-visible terminal outcomes are the CLOSED 4-value enum** `continued` / `foundation_only` / `scope_out` / `next_iteration` (per R1 C-001 disposition; `forced_terminal` is internal-only branch state at sub-module § 6 — never recorded as producer-visible outcome).

## Scope (S2.3 v0)

- Synthetic-fixture coverage only (`demonstrated` evidence level per `governance/methodology.md` § 3 success-criterion; NOT `validated`)
- Real-operator-input validation deferred to E-α tester slice OR next operator-facing slice
- Minimum 4 fixtures per S2.3 spec § A.8
- Iteration cap calibration (2) is hypothesis-only; first-real-operator-data may revise

## Fixture inventory

| Fixture | Entry scenario | Operator path | Expected terminal outcome (producer-visible) | Expected terminal_reason |
|---|---|---|---|---|
| `scrl01-hipaa-halt-to-foundation-only.md` | sc01 HIPAA halt at pre-step-05 | (b) → iterations 1+2 → cap reached → operator picks (i) foundation-only at § 7 forced-disclosure | `foundation_only` (+ stop_conditions cross-slice mutation per R1 C-002) | `iteration_cap_reached` |
| `scrl02-pci-halt-to-scope-out.md` | sc03 PCI-DSS halt at pre-step-05 | (b) → iterations 1+2 → cap reached → operator picks (ii) scope-out at § 7 forced-disclosure | `scope_out` (no cross-slice mutation) | `iteration_cap_reached` |
| `scrl03-gdpr-halt-to-c-revise-to-continue.md` | sc02 GDPR halt at pre-step-05 | (c) regulatory-revise → conditions cleared in 1 iteration | `continued` to step 05 | `regulatory_exposure_revised_clears_conditions` |
| `scrl04-pre-step-08-late-hipaa-to-foundation-only.md` | Markdown-agents shape with no step 03 HIPAA exposure; vision content (step 05) mentions "patient communication" → pre-step-08 late-emergence HIPAA halt | (b) → iterations 1+2 → cap reached → operator picks (i) foundation-only at § 7 forced-disclosure; vision + approach preserved on disk | `foundation_only` (+ stop_conditions cross-slice mutation per R1 C-002) | `iteration_cap_reached` |

**Producer-visible terminal outcome enum** (closed; post-R1 C-001 disposition): `continued` / `foundation_only` / `scope_out` / `next_iteration`. The internal branch state `forced_terminal` at sub-module § 6 (iteration cap reached AND conditions still fire) is NEVER recorded as a producer-visible outcome — module handles the final-choice prompt internally and maps operator's pick to `foundation_only` or `scope_out` with `terminal_reason: iteration_cap_reached`.

## Coverage limits (known at v0)

- Two iterations exercised in fixtures scrl01/scrl02/scrl04 (operator picks (b) at iteration 1 AND iteration 2 → cap reached at iteration 2); scrl03 exercises one (c) iteration. Mixed (b)+(c) within same loop session NOT exercised.
- HIPAA tested for (b) path (scrl01 + scrl04 via late-emergence); PCI-DSS tested for (b) only (scrl02); GDPR tested for (c) only (scrl03); condition 4 (regulated + no framework identified) recovery path NOT exercised at v0 — § 4.2 Variant B disclosure + § 4.3 condition-4 UP-6 re-ask variant are specified but no fixture exercises condition-4 entry (per R1 C-005 disposition)
- Pre-step-08 loop tested for HIPAA late-emergence only (scrl04); other framework late-emergence cases assumed to follow same pattern
- Mixed-shape per-component capability loop interaction not exercised (reserved for v1+ per S2.1 handoff contract § 5)
- Concurrent loop-then-late-emergence-at-pre-step-08 case tested with fresh iteration counter at pre_step_08 (Decision E); inherit-counter alternative not exercised

## Regression coverage

S2.1 fixture pack (14 fixtures at `wizard/test_fixtures/shape_detection/`) + S2.2 fixture pack (5 fixtures at `wizard/test_fixtures/foundation_only_mode/`) MUST continue to replay correctly post-S2.3. The `shape_revision` block is additive (`schema_minor: 0 → 1`); absent block defaults to `{ pending: false, iteration: 0, iteration_cap: 2, history: [] }` per § 9 consumer rules — S2.1 + S2.2 fixtures have no `shape_revision` block in expected outcomes; they SHOULD pass without modification.

## Cross-references

- S2.3 slice spec — `product_evidence/_slices/S2.3_stop_condition_reevaluate_loop_2026-05-19.md`
- Loop sub-module — `wizard/interview/_stop_condition_reevaluate_loop.md`
- S2.1 fixture corpus — `wizard/test_fixtures/shape_detection/` (source-scenario inputs derived from sc01-sc04 stop-condition fixtures)
- S2.2 fixture corpus — `wizard/test_fixtures/foundation_only_mode/` (terminal-state handoff target when loop converges to foundation-only)
- Validation evidence — `governance/validation/mech-stop-condition-reevaluate-loop-v0/2026-05-19_s2.3_initial_fixture_replay.md`
