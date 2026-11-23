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

A03 portable profiles are implemented on feat/a03-portable-profiles, based on
published A02 PR #37 at 436992c. Core 9539895 and CLI 73e06e8 are committed
and pushed. Versioned allowlist export/import, four example profiles, destination
replanning and shared host validation are complete. Final installed package:
1245 passed / 14 opt-in skips; Python 3.14 focused: 100 passed; actual installed
CLI: four pure profile round-trips / 20 successful commands with unchanged
project bytes and mtimes. See portable-profiles.md and evidence/portable-profiles.md.
Publication uses a stacked PR on A02; no merge/release/submission is implied.
Next: A04 recommendation/CLI acceptance, then A05 real profile combinations,
A06 packaging/licenses/CI, A07 guides/measurements/report and A08 final readiness.

### Previous A02 checkpoint

A02 is implemented on feat/a02-unified-workflow, based on the accepted PR #36
handoff. Guard commit fc39092 adds read-only composition checks inside adapter
locks. The unified registry/inspect/plan/apply/check/status commands compose the
four supported modes, preserve original Graphify recipes and predicted source/
Codex effects, reject stale/replayed plans, and retain partial ownership. Workflow commit e7959c0 is pushed; final rebuilt 1182/14 tests and both actual
CLI smokes passed (190.08s), with 40 focused Python 3.14 tests. Evidence is recorded
in evidence/unified-workflow.md; the documentation commit/stacked PR follows. Next implementation is A03 portable profiles, using
WorkflowRequest and the supported-mode registry; A04–A08 remain unfinished.
No PR merge or release is implied. Preserve unrelated docs/superpowers files.

Current accepted handoff: test/a01-foundation-handoff at engineering commit
2a4f3b8 (production fix 188e155), stacked on removal PR #35. All four real narrow
CLI lifecycles passed through install, fresh/negative check, removal and reinstall;
shared Codex/source-change cases passed. Final rebuilt default + wheel packaging:
1142 passed / 12 opt-in skips. Clean sdist/resource smoke and actual failure
controls passed separately. See foundation-handoff.md and evidence/foundation-cli.json
for exact evidence, assertion audit and support limits. This accepted narrow handoff is the base for A02; its updated checkpoint is above. No merge or published release is claimed.

Previous branch: feat/a01-coordinated-removal, stacked on Headroom PR #34.
Coordinated configuration/runtime cleanup and deliberate reinstall are implemented
through commits 7c56cfb, 1df0f9c and 1c22568. The rebuilt package passed 1137
tests with warnings as errors / 13 opt-in skips; Python 3.14 focused selection
passed 97. Real filesystem and adapter command-double cases cover all four modes,
partial failure, retained data/settings and repeat/reinstall. See
coordinated-removal.md and evidence/coordinated-removal.md. Next: real assembled
B08/A01 foundation acceptance and exact handoff before A02 product work.

Previous indexing slice: feat/a01-graphify-freshness, stacked on configuration PR #31.
Managed Graphify indexing/reindexing and shared local verification are now
implemented and validated: 151 focused tests, 1042 rebuilt-package tests passed
with warnings as errors / 12 opt-in skips, and 1 real managed Graphify lifecycle
test passed. Lint, formatting, dependency and diff checks passed.
See graphify-index-lifecycle.md. The next agent owns real Codex integration.

Previous configuration slice: feat/a01-config-lifecycle, stacked on PR #30. JSON/Codex TOML
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
| B04 — Graphify indexing and shared verification | Implemented: source/runtime validation under lock, staged extraction/query, deliberate reindex, failure ownership, index CLI and shared verifier; 1042 default tests and the real managed lifecycle passed |
| B05 — Graphify Codex integration | Implemented: manager-owned stdio bridge, owned Codex settings and actual Codex0.169.0 tool calls with positive/repeat/negative evidence; connection and functionality remain separate |
| B06 — Headroom CLI and shared verification | Implemented in c6b7e8a: current inventory/import health, fresh shared compression reports, strict token/preservation checks and retained mutable data; real full library lifecycle passed, with 282 before/after and 0 saved; 70 dependency versions/license candidates captured, release audit still pending |
| B07 — Coordinated safe removal | Implemented through 1c22568: reviewed cleanup, bounded runtime snapshots, durable release/retirement, preserved references/data and repeat/reinstall; 1137 default tests and 97 focused Python 3.14 tests passed; real assembled acceptance remains B08 |
| B08 — Foundation acceptance and handoff | Accepted at 2a4f3b8: actual four-tool CLI lifecycles, negative/shared-Codex/source-change cases, clean distributions and documented narrow handoff; see foundation-handoff.md |

Packaging/release work does not replace B07 or B08. Do not mark these complete
from merged PR titles, receipts, fixture doubles, or skipped integration tests.
Known B implementation gaps must be finished before accepting the handoff.

## A after the handoff

A01 reproduce and accept the foundations; A02 unified workflow; A03 portable
profiles; A04 recommendation/CLI acceptance; A05 full lifecycle and combinations;
A06 packaging/license closure and release CI; A07 guides/measurements/demo/report;
A08 final release and submission. A03 implementation is recorded above; A04 is next.

After each implementation slice, update this checkpoint and
implementation-progress.md with the actual tests, revision/publication state,
remaining limitations and next milestone. Preserve unrelated local files.
