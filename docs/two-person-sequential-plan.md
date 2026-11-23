# Remaining implementation: B foundations, then A product work

Updated 23 November 2026, from the user-supplied B01–B08 / A01–A08 plan.
Audited base: 8466c8c9fad0207a825fd5599df8e4d18c4e0859.

The current user has authorized completing the remaining B capabilities before
moving to A's work. These labels identify milestones, not the Git author:
retain the current contributor's identity and existing contributor history.
Do not switch accounts to attribute new work to an absent teammate.

## Current implementation checkpoint

The latest user instruction authorizes a continuous multi-agent implementation
sequence under the current contributor's identity. A01 now includes repairing
the incomplete B prerequisites; a complete B handoff is not assumed.

Active branch: feat/a01-config-lifecycle, stacked on PR #30. JSON/Codex TOML
reconciliation, conservative owned configuration restoration and live runtime
reference inspection are implemented. The later removal executor must hold
the project lock, validate receipt ownership and journal intent/outcomes.
See configuration-lifecycle.md for the public APIs and deliberately retained
unsupported cases. This closes the configuration primitive gap, not the entire
handoff. Full lifecycle wiring and real tool acceptance remain pending.

Validation for this A01 repair: 142 focused tests and 1015 rebuilt-package
tests passed with warnings treated as errors; 12 opt-in checks skipped.
Lint, formatting and diff checks passed. Publication is through the two
configuration commits on this branch; no hosted CI/merge claim.

Branch: fix/b-foundation-baseline-removal.
Current slice: B01 baseline fixes and B02 read-only removal classification.
Implemented locally: deterministic Headroom plan-file closure, baseline lint
and formatting corrections, traversal rejection, safe handling of unresolved
ownership, explicit retained-data locations and ancestor protection, and
runtime eligibility independent of installation evidence.

Validation: 86 focused tests passed; the full rebuilt-package suite passed
993 tests with 12 opt-in skips, with warnings treated as errors. Lint,
formatting, dependency and installed CLI smoke checks passed. Twelve added
cases reproduced failures before the fixes. See
[baseline evidence](evidence/b01-b02-baseline.md) for scope and environment.
Publication: baseline cleanup is commit 9c80b11. Removal classification and
this checkpoint are the next commit on the same branch. No PR, merge or
hosted validation result is claimed here.

## B completion order

| Milestone | State and next acceptance requirement |
| --- | --- |
| B01 — Stable baseline | Implemented and locally validated; commit 9c80b11; hosted CI pending |
| B02 — Runtime removal classification | Implemented and locally validated in the following branch commit; see runtime-removal.md; hosted CI pending |
| B03 — Configuration/lifecycle ownership | Primitives implemented in A01 repair; coordinated removal must wire the documented lock/journal/reference contract |
| B04 — Graphify indexing and shared verification | Pending: validate installed inventory and reviewed sources under lock; stage fresh indexing; support deliberate reindex; retain ownership on failure; expose shared checks/CLI |
| B05 — Graphify Codex integration | Pending: replace unsupported upstream MCP command with a supported integration; prove actual Codex invocation; keep connection and functionality separate |
| B06 — Headroom CLI and shared verification | CLI exists; shared verifier, current real lifecycle evidence and dependency inventory remain |
| B07 — Coordinated safe removal | Pending: preserve edits, clean owned configuration, revalidate/remove unreferenced runtimes under lock, journal partial progress, repeat harmlessly |
| B08 — Foundation acceptance and handoff | Pending: all four narrow lifecycles, negative/mixed-tool cases, clean distribution acceptance, operational/API documentation and exact handoff revision |

Packaging/release work does not replace B07 or B08. Do not mark these complete
from merged PR titles, receipts, fixture doubles, or skipped integration tests.
Known B implementation gaps must be finished before accepting the handoff.

## A after the handoff

A01 reproduce and accept the foundations; A02 unified workflow; A03 portable
profiles; A04 recommendation/CLI acceptance; A05 full lifecycle and combinations;
A06 packaging/license closure and release CI; A07 guides/measurements/demo/report;
A08 final release and submission. A's product implementation has not started.

After each implementation slice, update this checkpoint and
implementation-progress.md with the actual tests, revision/publication state,
remaining limitations and next milestone. Preserve unrelated local files.
