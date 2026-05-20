# Schema-version negative-test fixtures

**Purpose:** verify that `tools/replay_fixtures.py`'s fail-closed schema-version check (S2.7 Decision C § A.3 + Decision H § A.8) actually FAILs on deliberately-broken fixtures. Without this exercise the fail-closed claim is theater per advisor R1 C-004.

**Per S2.7 slice spec § A.8 Decision H** — narrow IDQ-059 fold-in. ONLY schema-version negative tests are folded into S2.7; the broader IDQ-059 cross-slice-mutation negative fixtures (stale-documented / missing-resolved-during-loop / missing-active-fired / etc.) remain deferred per IDQ-059 resolution path.

## Fixtures

| Fixture | Failure mode | Expected validator output |
|---|---|---|
| `missing-schema-version-fixture.md` | omits `schema_version` field | FAIL: "required field `schema_version` missing" |
| `wrong-schema-version-fixture.md` | declares `schema_version: fixture-replay-v99` | FAIL: "schema_version mismatch: ... v99 ≠ v1" |

## Usage

```bash
python3 tools/replay_fixtures.py --include-negative
```

**Pass condition:** ALL negative fixtures FAIL as expected (each declared failure mode triggers the corresponding validator error).
**Fail condition:** ANY negative fixture passes (indicates the fail-closed check is broken or has been silently disabled).

## Discipline

Per `feedback_coverage_map_fail_closed_pattern.md` (S2.6 R2-F1): validator gates referencing per-key status registries must validate keys-match-vocabulary + values-in-closed-enum + fail-closed on missing/unknown. These negative-test fixtures exercise that discipline at first-use for the schema-version fail-closed surface.

## Out-of-scope (per S2.7 Decision H § A.8)

The following IDQ-059 negative-test classes are NOT covered here; they remain deferred under IDQ-059:
- Cross-slice mutation invariant violations (stale-documented [4, 1] for condition-4 → foundation_only paths)
- Missing `resolved_during_loop` on condition-4 → foundation_only
- Missing active fired-conditions list
- Missing mutation block on `terminal_outcome: foundation_only`
- Wrong `halted` value
- Wrong `resolved_via` value
