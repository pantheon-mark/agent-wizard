# Foundation-only-mode fixture corpus — S2.2

## Purpose

Synthetic fixtures for foundation-only-mode behavior across wizard interview steps 05-15. Each fixture supplies (a) a source-shape input that triggers the unsupported-shape transition at step 01/02 or pre-step-05; (b) `fallback_mode_offered: foundation-only` as the operator's choice at the transition; (c) expected outcomes for which artifacts are produced vs skipped through step 15 close.

These fixtures exercise the entry-guard pattern + per-step adapted-path behavior defined at `wizard/interview/_foundation_only_mode_gate.md` + the per-step `## Foundation-only adapted path` sections of `wizard/interview/05_vision.md` through `15_close.md`.

## Scope (S2.2 v0)

- Synthetic-fixture coverage only (`demonstrated` evidence level per `governance/methodology.md` § 3 success-criterion; NOT `validated`)
- Real-operator-input validation deferred to E-α tester slice OR next operator-facing slice
- Minimum 5 fixtures per S2.2 spec § A.8

## Fixture inventory

| Fixture | Source shape | Mode | Expected paths exercised |
|---|---|---|---|
| `fom01-python-service-foundation-only.md` | python-service-operator-facing (s02) | foundation-only | Unsupported-shape transition at step 01 → (b) foundation-only; all 11 step entry guards branch to adapted path; 7 foundation-only artifacts produced |
| `fom02-claude-skills-foundation-only.md` | claude-skills (s03) | foundation-only | Same as fom01 |
| `fom03-node-ui-foundation-only.md` | node-ui (s04) | foundation-only | Same as fom01 |
| `fom04-markdown-document-path.md` | markdown-agents (s01) + HIPAA stop condition | foundation-only DOCUMENT path | Unsupported-shape transition does NOT fire at step 01 (shape is markdown); operator picks foundation-only at pre-step-05 stop-condition recovery; DOCUMENT path adds compliance gap entry to `technical_architecture.md` § "Regulatory & compliance gaps (foundation-only mode)" |
| `fom05-mixed-shape-foundation-only.md` | mixed (s07) | foundation-only | Unsupported-shape transition fires at step 01 with shape `mixed`; capability-based stop conditions evaluate against weakest-path; if compliance gaps exist they land in DOCUMENT path |

## Cross-references

- S2.2 slice spec — `product_evidence/_slices/S2.2_foundation_only_mode_2026-05-19.md`
- Gate module — `wizard/interview/_foundation_only_mode_gate.md`
- S2.1 fixture corpus — `wizard/test_fixtures/shape_detection/` (source-shape inputs derived from these)
- Validation evidence — `governance/validation/mech-foundation-only-mode-v0/2026-05-19_s2.2_initial_fixture_replay.md`
