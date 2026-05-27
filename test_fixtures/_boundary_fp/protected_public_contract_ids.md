# Boundary-scanner FP-protection fixture — wizard's own public-contract identifiers

**Purpose.** This fixture documents the wizard's OWN public-contract identifiers that the
public-distribution boundary scanner MUST NOT flag. It is a false-positive guard: it asserts (by
scanning clean) that there is **no `F-N` blocking rule and no `F-N` candidate-lint rule**, because the
`F-N` form in this project's public surface is dominated by the wizard's own legitimate public-contract
and test-case identifiers — not private build provenance.

This file carries NO replay frontmatter and lives outside every registered fixture pack, so the
fixture-replay harness ignores it; only the boundary scanner reads it (and returns zero unclassified
violations + zero candidate-lint findings).

## Protected public-contract identifiers (legitimate neutral public semantics)

These are part of the wizard's published contract surface. They are public by design and must survive
any boundary scrub:

- **F-1** — the shape-detection hard-stop contract (the mandatory pre-vision re-check point). Cited
  throughout the interview steps as the shape-resolution gate.
- **F-9** — the generator-version identity contract (worktree-clean emission of the generated-bundle
  manifest's version field). Cited throughout the generator library + its tests.

## Protected test-case + category identifiers

The foundation-bundle test-case template + the section schema use `F`-prefixed identifiers as
acceptance-criteria rows, markdown-agent validation-matrix rows, and universal test-category tags:

- Acceptance-criteria rows: AC-F-1 through AC-F-7 (cost-control acceptance criteria).
- Markdown-agent validation rows: MA-F-1 through MA-F-19 (phase-gate / budget / review rows).
- Universal test-category tags: the `F`-row family (cost-control concepts shared across all shapes).

## Why no F-N scanner rule

A blocking or candidate `F-N` rule would over-match every identifier above — the wizard's own
public-contract IDs + its test-case taxonomy — and corrupt the published artifacts (the
"semantic amputation" failure the distribution-boundary policy explicitly warns against). Genuinely
private build-side finding references appear only in PREFIXED forms (the Phase-C review family and the
slice-advisor finding family), which carry their own dedicated detective rules. Bare `F-N` is therefore
handled by manual review per the boundary policy's rule-addition protocol, not by a scanner rule — and
this fixture is the standing guard against a future over-eager `F-N` rule being added.
