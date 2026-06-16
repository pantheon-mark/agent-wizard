# Build Progress Ledger

*One row per committed build phase. Updated after each phase is built and accepted.
Read this file at the start of any build session to know which phase is current and
what is already accepted.*

---

## Phase Progress

| Phase | Capability | State | Layer-A | Layer-B | Open fix items | Deferred core precondition | Date |
|-------|-----------|-------|---------|---------|----------------|---------------------------|------|
{{BUILD_PROGRESS_ROWS}}

---

## State vocabulary

Each phase moves forward through these states in order:

- **built** — the capability has been implemented and the agents are in place; not yet reviewed.
- **technically-reviewed** — Layer-A automated reviews have passed for this phase.
- **supervised** — the operator has watched the agents run on real work for this phase.
- **provisionally-accepted** — Layer-B acceptance is complete except for one or more core checks
  that could not be exercised yet (see the "Deferred core precondition" column). The phase is
  usable but the next phase must clear that precondition before it can be accepted.
- **accepted** — both Layer-A and Layer-B are fully satisfied; this phase is closed.

---

## Layer definitions

**Layer-A (automated technical acceptance)**
The emitted system's per-component and phase-gate model reviews. These run automatically.
Layer-A must pass before a phase can advance to supervised or accepted.

Recorded values: `pass` / `fail` / `pending`

**Layer-B (operator business acceptance)**
The human flip. Only a confirmed Layer-B verdict advances a phase to accepted or
provisionally-accepted.

Tri-state verdict:
- **confirmed** — exercised on real work; operator accepted the result.
- **fix-needed** — operator flagged an issue; fixed in-session, re-run, and re-confirmed.
- **deferred-pending-real-use** — the check cannot be exercised yet. If the deferred check
  is non-core it routes to future items; if it is a core check the phase becomes
  provisionally-accepted and the deferred check becomes a forced precondition for the
  next phase (recorded in the "Deferred core precondition" column).

---

## How to update this file

After completing a phase:
1. Set the **State** column to the current state for that phase.
2. Set the **Layer-A** column to `pass`, `fail`, or `pending`.
3. Set the **Layer-B** column to the verdict: `confirmed`, `fix-needed`, or
   `deferred-pending-real-use`.
4. Fill in **Open fix items** if any issues were flagged and not yet resolved.
5. Fill in **Deferred core precondition** if this phase is provisionally-accepted.
6. Set the **Date** column to today's date.

The next-phase skill reads this file and refuses to start phase N+1 until phase N
shows `accepted` or `provisionally-accepted` with its deferred core precondition cleared.
