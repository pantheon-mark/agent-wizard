# Schema-version negative-test fixtures

**Purpose:** verify that `tools/replay_fixtures.py`'s fail-closed schema-version check (per a prior slice) actually FAILs on deliberately-broken fixtures. Without this exercise the fail-closed claim is theater per advisor an advisor finding.

**Per a prior slice** — narrow a tracked open question fold-in. ONLY schema-version negative tests are folded into a prior slice; the broader a tracked open question cross-slice-mutation negative fixtures (stale-documented / missing-resolved-during-loop / missing-active-fired / etc.) remain deferred per a tracked open question resolution path.

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

Per `a relevant lesson record` (a prior slice R2-F1): validator gates referencing per-key status registries must validate keys-match-vocabulary + values-in-closed-enum + fail-closed on missing/unknown. These negative-test fixtures exercise that discipline at first-use for the schema-version fail-closed surface.

## Out-of-scope (per a prior slice)

The following a tracked open question negative-test classes are NOT covered here; they remain deferred under a tracked open question:
- Cross-slice mutation invariant violations (stale-documented [4, 1] for condition-4 → foundation_only paths)
- Missing `resolved_during_loop` on condition-4 → foundation_only
- Missing active fired-conditions list
- Missing mutation block on `terminal_outcome: foundation_only`
- Wrong `halted` value
- Wrong `resolved_via` value
