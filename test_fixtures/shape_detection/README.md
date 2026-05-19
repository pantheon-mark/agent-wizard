# Shape-detection fixture pack

**Source:** S2.1 slice spec § B (fixtures plan). Created at S2.1 implementation 2026-05-19.
**Mechanism:** `mech-shape-detection-v0` per `wizard/shape_detection.md`.

## Fixture format

Each fixture is a markdown file with YAML frontmatter capturing synthetic operator inputs + expected classifier outcomes. Fixtures are replayed by walking the classifier logic manually OR (future) by a programmatic replay harness.

Frontmatter fields:

```yaml
---
fixture_id: <short-kebab>
fixture_class: shape | stop-condition | mixed-signal | forward-offered
target_shape: <expected shape per § 2.3>   # for shape fixtures
target_stop_condition: <1-4>               # for stop-condition fixtures
expected_confidence: high | medium | low
expected_emit_step: 01 | 02
expected_recheck_outcome: confirmed | revised | halted   # for fixtures that exercise re-check
expected_halt: true | false
notes: <one-line context>
---
```

## Fixture index

| ID | Class | Target | Confidence | Emit step | Halt? |
|---|---|---|---|---|---|
| `s01-markdown-agents-clean` | shape | markdown-agents | high | 01 | no |
| `s02-python-service-clean` | shape | python-service-operator-facing | high | 01 | no |
| `s03-claude-skills-clean` | shape | claude-skills | high | 01 | no |
| `s04-node-ui-clean` | shape | node-ui | high | 01 | no |
| `s05-multi-user-datastore-clean` | shape | multi-user-datastore | high | 01 | no |
| `s06-hosted-cloud-clean` | shape | hosted-cloud | high | 01 | no |
| `s07-mixed-shapes` | shape | mixed | medium | 02 | no |
| `s08-unknown-low-signal` | shape | unknown | low | 02 | no |
| `sc01-hipaa-markdown-halt` | stop-condition | 1 (HIPAA+markdown) | high | 01 | yes (pre-step-05) |
| `sc02-gdpr-markdown-halt` | stop-condition | 2 (GDPR+markdown) | high | 01 | yes (pre-step-05) |
| `sc03-pci-markdown-halt` | stop-condition | 3 (PCI+markdown) | high | 01 | yes (pre-step-05) |
| `sc04-regulated-no-framework-halt` | stop-condition | 4 (regulated + no framework) | high | 01 | yes (pre-step-05) |
| `ms01-mixed-signal-resolved-by-fallback` | mixed-signal | markdown-agents | medium → high | 02 | no |
| `fo01-forward-offered-newsletter` | forward-offered | python-service-operator-facing | high | 01 | no |

## Replay protocol

Per `governance/operational_change_safety.md` v0 § 5 validation evidence storage:

1. Walk the classifier logic manually for each fixture
2. Record actual emit + (if applicable) re-check outcome + (if applicable) halt outcome
3. Compare to expected per fixture frontmatter
4. File results at `governance/validation/mech-shape-detection-v0/<date>_<event-tag>.md`
5. Update validation evidence index at `governance/validation/README.md`

S2.1 initial replay: `governance/validation/mech-shape-detection-v0/2026-05-19_s2.1_initial_fixture_replay.md`.

## Coverage limits at v0

- Synthetic inputs only; not real-operator data
- 14 fixtures covers basic discrimination + each stop condition + 1 mixed-signal + 1 forward-offered
- Multi-step re-check scenarios (where pre-step-05 confirms but pre-step-08 revises) NOT covered at v0 — bind to next operator-facing slice
- Late-emergence stop-condition scenarios (regulatory exposure discovered at step 05-07) NOT covered at v0 — bind to next operator-facing slice
- "Operator picks (b) foundation-only at unsupported-shape transition" path NOT exercised at v0 — bind to downstream slice that implements foundation-only-mode behavior across steps 05-15 (out of S2.1 scope per decision F)
- Stop-condition loop-back-to-step-02 NOT exercised at v0 — bind to downstream slice that implements the loop per decision G

## Cross-references

- `wizard/shape_detection.md` — canonical spec
- `wizard/handoff_contracts/shape_detection_v0.md` — handoff contract
- `governance/operational_change_safety.md` v0 § 5 — validation evidence storage convention
- `governance/validation/mech-shape-detection-v0/2026-05-19_s2.1_initial_fixture_replay.md` — first replay evidence
