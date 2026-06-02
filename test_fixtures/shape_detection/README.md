# Shape-detection fixture pack

**Source:** a prior slice spec § B (fixtures plan). Created at a prior slice implementation 2026-05-19.
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

**F6 reconciliation (2026-06-02) — fixtures updated.** The F6 runtime/integration reconciliation (`wizard/shape_detection.md` § 9) deliberately changed the classifier: scheduled execution + outbound integration are markdown-fine (the markdown-agents execution model), so the non-markdown triggers are now `probe_9_always_on` / `probe_10_inbound_serve` / `probe_2` (multi-user), and `probe_1_continuous_runtime` was renamed `probe_1_scheduled_cadence` (handoff `schema_major` 0→1). Effect on this pack: **re-derived** s01 (rationale → branch (c)), s02 (now non-markdown via always-on+inbound, not scheduled+outbound), s03 (now step-02 via the markdown-vs-skills branch-(c) guard), s04 (node-ui via multi-user+inbound), s06 (hosted-cloud via always-on+multi-user+datastore), s07 (mixed via a genuinely always-on responder), fo01 (**now markdown-agents** — a scheduled+outbound newsletter is markdown under F6; the canonical drift-fix fixture); **NEW** s09 (the estate-executor scheduled+outbound→markdown case). Oracle-UNCHANGED under F6 (each carries an in-file "F6 reconciliation note"): s05, s08, sc01-04, ms01.

| ID | Class | Target | Confidence | Emit step | Halt? |
|---|---|---|---|---|---|
| `s01-markdown-agents-clean` | shape | markdown-agents | high | 01 | no |
| `s02-python-service-clean` | shape | python-service-operator-facing (always-on + inbound) | high | 01 | no |
| `s03-claude-skills-clean` | shape | claude-skills | medium → high | 02 | no |
| `s04-node-ui-clean` | shape | node-ui | high | 02 | no |
| `s05-multi-user-datastore-clean` | shape | multi-user-datastore | high | 01 | no |
| `s06-hosted-cloud-clean` | shape | hosted-cloud | high | 02 | no |
| `s07-mixed-shapes` | shape | mixed | medium | 02 | no |
| `s08-unknown-low-signal` | shape | unknown | low | 02 | no |
| `s09-scheduled-outbound-agent` | shape (F6) | markdown-agents (scheduled + outbound) | high | 01 | no |
| `sc01-hipaa-markdown-halt` | stop-condition | 1 (HIPAA+markdown) | high | 01 | yes (pre-step-05) |
| `sc02-gdpr-markdown-halt` | stop-condition | 2 (GDPR+markdown) | high | 01 | yes (pre-step-05) |
| `sc03-pci-markdown-halt` | stop-condition | 3 (PCI+markdown) | high | 01 | yes (pre-step-05) |
| `sc04-regulated-no-framework-halt` | stop-condition | 4 (regulated + no framework) | high | 01 | yes (pre-step-05) |
| `ms01-mixed-signal-resolved-by-fallback` | mixed-signal | markdown-agents | medium → high | 02 | no |
| `fo01-forward-offered-newsletter` | forward-offered | markdown-agents (scheduled+outbound; F6) | high | 02 | no |

## Replay protocol

Per `the relevant build-side spec` v0 § 5 validation evidence storage:

1. Walk the classifier logic manually for each fixture
2. Record actual emit + (if applicable) re-check outcome + (if applicable) halt outcome
3. Compare to expected per fixture frontmatter
4. File results at the relevant build-side validation evidence record location
5. Update validation evidence index at `the relevant build-side spec`

a prior slice initial replay: the relevant build-side validation evidence record.

## Coverage limits at v0

- Synthetic inputs only; not real-operator data
- 15 fixtures cover basic discrimination + each stop condition + 1 mixed-signal + 1 forward-offered + 1 F6 scheduled+outbound→markdown positive (s09)
- Multi-step re-check scenarios (where pre-step-05 confirms but pre-step-08 revises) NOT covered at v0 — bind to next operator-facing slice
- Late-emergence stop-condition scenarios (regulatory exposure discovered at step 05-07) NOT covered at v0 — bind to next operator-facing slice
- "Operator picks (b) foundation-only at unsupported-shape transition" path NOT exercised at v0 — bind to downstream slice that implements foundation-only-mode behavior across steps 05-15 (out of a prior slice scope per decision F)
- Stop-condition loop-back-to-step-02 NOT exercised at v0 — bind to downstream slice that implements the loop per decision G

## Cross-references

- `wizard/shape_detection.md` — canonical spec
- `wizard/handoff_contracts/shape_detection_v0.md` — handoff contract
- `the relevant build-side spec` v0 § 5 — validation evidence storage convention
- the relevant build-side validation evidence record — first replay evidence
