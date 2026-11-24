# Remaining implementation: B foundations, then A product work

Current checkpoint: **24 November 2026**, audited against merged main `575a8e6`.
This is the active schedule; the chronological 36-step schedule is historical.
C has no future assigned work. Preserve genuine authorship regardless of milestone
labels. See [contribution evidence](contribution-matrix.md) and the dated
[progress history](implementation-progress.md).

| Milestone | Actual status |
| --- | --- |
| B01–B08 | Foundation implementation and narrow acceptance complete, including A-authored repairs in #30–#36; see foundation-handoff.md |
| A01 | Foundation handoff accepted; #36 merged |
| A02 | Unified workflow implemented; #37 merged |
| A03 | Portable profiles implemented; #38 merged |
| A04 | Recommendation/preflight/CLI improvements implemented; #39 merged |
| A05 | Extensive combined/profile lifecycle acceptance deferred at user request; not completed |
| A06 | Source-bound packaging, license references and CI implemented; #40 merged |
| A07 | Guides/report draft added in merged #43; this follow-up corrects CLI instructions, attribution and measurement provenance |
| A08 | README/changelog in merged #44; final development artifact preparation and handoff follow below; release acceptance/publication/submission not completed |

## Current follow-up

Branch `docs/final-plan-handoff` starts at merged main. Correct demo/profile
commands, guide behavior, contribution attribution and evidence units/sources.
Publish prior synthetic inputs/results without new measurements. Reconcile the
plan and prepare exact committed-source development distributions with manifests.
Artifacts remain local until an authorized publication. Version stays `0.1.0.dev0`.

PR #42 (project tooling report) remains open at this audit. It is an optional
product feature, separate from the faculty report, and not a dependency of A01–A08.

## Remaining work and sequence

1. Review/merge this follow-up when ready. Agents do not merge automatically.
2. When testing resumes: run A05 combined/profile lifecycles, final installed
   package acceptance, and refresh the resolved runtime/license inventory. Prior
   narrow acceptance and historical inventories are not final-release evidence.
3. If the setup comparison is required, use the public measurement
   runner and perform a fair manual/managed comparison. No human-effort or dollar
   savings have been measured. Prior synthetic token counts are separately labeled.
4. Supply student details and confirm faculty requirements/approval; finalize the
   report format and perform the demo. The technical Markdown draft is available.
5. Choose a release version only after acceptance. Commit it, rebuild that exact
   revision and retain its manifest/checksums. Tagging, publishing and submission
   are separate external actions, not completed by building artifacts.

The user deferred rigorous testing. Continue minimal sanity checks and leave
existing CI enabled; do not run new integration suites or benchmarks by default.
For artifact commands and remaining gates see [release handoff](release-handoff.md).

## Continuation rule

For “progress forward”, read this checkpoint, local person-a-progress-plan.md and
the progress log; inspect current Git/PR state before picking the next item.
Do not add broad features to fill a milestone whose remaining work is validation
or submission. Update implemented/tested/committed/pushed/merged states separately.
