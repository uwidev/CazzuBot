# Baseline Governance

<!--
Machine-checked by aegis-workspace.py: the checker requires the literal
ATX headings `## 1. Baseline Roles` … `## 7. Hard Boundaries`. hongdown
rewrites ATX numbered headings to setext, which would fail the check —
do NOT run hongdown on this file.
-->

## 1. Baseline Roles
- Product / Requirement Baseline: problem, accepted behavior, success evidence,
  non-goals, workflow constraints, and approved requirement/spec intent.
- Architecture / Runtime Boundary Baseline: canonical owner, contract,
  source-of-truth boundary, dependency direction, compatibility, runtime-ready
  boundary, and retirement state.

## 2. Design Defect
A confirmed error, gap, contradiction, or wrong abstraction IN the relevant
requirement, design, or baseline.
- Fix the defective requirement/design/baseline first.
- Then align implementation to the corrected baseline.
- Do NOT patch implementation around a defective baseline.

## 3. Implementation Drift
Implementation, plan, review, or documentation has deviated from a confirmed,
correct, unchanged requirement or architecture baseline.
- Return to baseline via the simplest stable path.
- Do NOT "update baseline to match drift" without explicit review.

## 4. Compatibility Aliases
- Architecture Defect = architecture-scoped Design Defect.
- Architecture Drift = architecture-scoped Implementation Drift.
- New findings should report Design Defect / Implementation Drift plus
  `scope: requirements | architecture | both`.

## 5. Baseline Check Protocol
Before non-trivial changes:
1. Read the latest Product / Requirement Baseline candidate.
2. Read the latest Architecture / Runtime Boundary Baseline candidate.
3. Compare current work against requirement acceptance and architecture owner /
   contract boundaries.
4. Check for new anti-patterns not recorded in known list.
5. Report: aligned / Design Defect / Implementation Drift /
   missing-authority / needs-clarification, with
   `scope: requirements | architecture | both`.

## 6. Architecture Review - 7 Dimensions
After each non-trivial change:
1. **Ownership integrity** - every component has exactly one canonical owner
2. **Module boundaries** - no unauthorized cross-module coupling
3. **Contract changes** - all API/signature/behavior contract changes documented
4. **Cascade proliferation** - no new cascading dependency chains
5. **Dependency direction** - dependencies flow toward stability
6. **Retirement completeness** - old owners/fallbacks/paths removed or scheduled
7. **Entropy flow** - net complexity decreased or stayed; no unjustified new entities

## 7. Hard Boundaries
- BASELINE-GOVERNANCE.md is the constitution for THIS project's Aegis workspace
- Baseline snapshots in `baseline/` are evidence, not authority
- ADRs in `adr/` record decisions; they do not replace baseline governance
- This file is NEVER auto-updated - changes require explicit user review

## Project Authority

- Project authority: `AGENTS.md` (conventions, guild safety, architecture) and
  the design docs it indexes (`docs/ARCHITECTURE.md`, `docs/PLUGINS.md`,
  `docs/TESTING.md`, …).
- Baselines never override the code: when code and a baseline disagree, the
  code is current and the baseline is stale — update it.
- A plan cites the baseline entries it depends on; work that invalidates a
  cited entry updates the baseline in the same change.

## Format

One file per dated entry under `baseline/YYYY-MM-DD-<slug>.md`, kept short
and factual. Entries that stop being true are marked stale rather than
silently rewritten.

## Scope discipline

A baseline records *measured, durable* facts only — no plans, no TODOs,
no transient progress.