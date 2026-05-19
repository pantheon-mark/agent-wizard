---
fixture_id: fom01-python-service-foundation-only
fixture_class: foundation-only-mode
source_shape: python-service-operator-facing
source_fixture: s02-python-service-clean
mode: foundation-only
expected_unsupported_shape_transition: step_01
expected_halt: false
notes: Operator chooses (b) foundation-only at the step-01 unsupported-shape transition. Wizard proceeds with foundation-doc-only mode through steps 05-15.
---

# Fixture fom01 — python-service-operator-facing + foundation-only

## Synthetic operator inputs

Source-shape inputs derived from `wizard/test_fixtures/shape_detection/s02-python-service-clean.md` (operator wants a continuous-runtime automation talking to external services).

**At step-01 unsupported-shape transition:** operator picks **(b) foundation-only**.

`shape_hypothesis.fallback_mode_offered` updates to `foundation-only` per `wizard/shape_detection.md` § 6.

## Expected per-step entry-guard branching

Per `wizard/interview/_foundation_only_mode_gate.md` § 2 derivation rule:

- `fallback_mode_offered: foundation-only`
- `produce_foundation_docs: true`
- `produce_system_implementation: false`
- `capture_implementation_inputs: true`
- `honest_characterization_disclosure: foundation_only`

Per-step entry guard branches to `## Foundation-only adapted path` section at end of each file (steps 05 through 15).

## Expected artifacts at step 15 close

**PRODUCED (7 files in operator project directory):**

- `vision.md`
- `approach.md`
- `technical_architecture.md` (with `## Operational requirements` sub-sections from steps 07/09/10/11/12/13 captures; NO `## Regulatory & compliance gaps` section since no stop conditions fired)
- `execution_plan.md`
- `project_instructions.md` (foundation-only voice; opening line: "These foundation docs describe your project at the system-blueprint level. They are implementation-agnostic. Implementation NOT included in this output.")
- `manual.md` (pointer doc; surfaces pointer to `next_steps.md`)
- `next_steps.md` (NEW per spec § A.4 template; mentions shape `python-service-operator-facing`; two paths forward enumerated)

**SKIPPED (NOT in operator project directory):**

- `.env`
- `.gitignore`
- `start-session.sh`
- `session_bootstrap.md`
- `test_cases.md`
- `audit_framework.md`
- Any subdirectory: `/agents/`, `/quality/`, `/work/`, `/logs/`, `/security/`, `/docs/`, `/archive/`
- `/security/credentials_registry.md`
- `/security/gitignore_manifest.md`
- `/quality/validation_gate_config.md`
- `/quality/source_registry.md`
- `/quality/advisor_knowledge_base.md`
- `/advisor/interview-guides/`

**NOT INITIALIZED:**

- Git repository in operator project directory
- GitHub remote

**NOT GENERATED:**

- First build prompt

## Expected staging-file captures (in addition to normal staging state)

Under `## Foundation-only-mode captures > *` sections:

- `Advisor list` (from step 07)
- `Credential inventory` (from step 09)
- `Validation rules` (from step 10)
- `Error-handling approach` (from step 11)
- `QA approach` (from step 12)
- `Operational requirements (cadence, scale, drift)` (from step 13)
- `Document review acknowledgment` (from step 14)
- `Architecture notes` (from step 08)

## Expected CLOSE-13 closing message (verbatim contract)

> Foundation-only mode complete. I've written 7 foundation documents to your project directory at `[PROJECT_DIR]/`. The key file to read next is `next_steps.md` — it walks you through what was produced, what was NOT produced (and why), and your two paths forward (direct Claude Code build OR wait for v2 wizard shape support).
>
> Your project file at `~/claude-wizard-draft/wizard_session_draft.md` is preserved. If you re-run the wizard later (when v2 adds support for your project shape, or if your situation changes), the wizard will recognize the preserved state and pick up appropriately.

## Replay outcome

Manual replay walks through entry-guard branching from step 05 through step 15; verifies adapted-path execution for each step; verifies output file set + non-emitted file set + closing message.

PASS criterion: 7 files produced + 0 implementation files produced + no git init + no first build prompt + closing message matches verbatim.

FAIL criterion: any of the 7 expected files missing OR any implementation file produced OR git init runs OR first build prompt generated OR closing message diverges.
