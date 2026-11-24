# A04 implementation and deferred acceptance

23 November 2026; branch `feat/a04-recommendation-acceptance`, stacked on A03
PR #38 (`b1ef9be`). Changes and tests were AI-assisted.

- `17e98be`: Headroom normalized distribution alias, browser goals, actual mode
  registration in catalog/recommendations, and truthful catalog-gate descriptions.
- `9570581`: generic preflight rejects receipt/directory/PATH readiness shortcuts,
  reads bounded unambiguous receipts, guards environment ancestors, and enforces
  actual host, target and assistant constraints. Recovery preserves ownership.
- CLI acceptance cases cover mixed/ambiguous manifests, deterministic ordering,
  explicit conflicts, local/hosted unknowns, unsupported execution selections,
  pure plan cancellation and dry runs, public help, and installed discovery.
  `workflow inspect` now returns 1 on incomplete inspection while retaining findings.
- Headroom command-double tests use explicit host facts so portable logic does
  not silently skip on other hosts; unsupported-host cases still reject execution.

## Checks actually run

Before the user's testing deferral, source-focused recommendation/preflight/
Graphify/verification/Headroom checks passed: 284 tests. After the assistant-gate
fix, recommendation CLI/preflight cases passed: 102 tests, with 10 installed
command cases deselected. These runs overlap and are not a full-suite count.
The final assistant/target sanity selection passed 7 tests, 78 deselected.
Ruff lint/format and `git diff --check` passed. Tests use declared command/host
doubles, not new upstream integration evidence.

The attempted isolated build could not fetch build dependencies in the restricted
network environment. No new A04 distribution or installed-package result is claimed.

## Deferred by explicit user instruction

The user asked to implement now and test later. Final full default/packaging suite,
Python 3.14 rerun, the prepared installed CLI cases, A05 actual combined/profile
lifecycles, new benchmarks and A08 release acceptance are deferred. Existing CI
remains enabled. Reuse `docs/testing.md` and the existing integration harnesses
when resuming validation; do not infer final acceptance from earlier A01–A03 runs.

Next implementation: A06 packaging/license/CI work, A07 operating/demo/report
materials and A08 artifact preparation, with the deferred checks recorded.
No merge, tag, publication or faculty submission is implied.
