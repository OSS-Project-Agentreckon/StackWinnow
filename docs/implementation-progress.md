# StackWinnow implementation progress

Last updated: **18 November 2026**. This records observed history and actual work status. The [36-work-commit plan](chronological-commit-plan.md) is the roadmap; a planned step is not completed work.

Repository: [OSS-Project-Agentreckon/StackWinnow](https://github.com/OSS-Project-Agentreckon/StackWinnow).

## Step 9 / person C's third planned contribution

The promptfoo work is on `feat/promptfoo-onboarding`, based on main
`fa3616e856cd2ecbf918bfb3e6c816c33cca610b` (the merge of PR #7). Step 7 and its
review fix are now merged. PR #6's step-5 runner remains open at `6057fb5`; its
reviewed defects must be addressed before normal adapter integration.

This change delivers C's step-9 implementation: the MIT `promptfoo@0.125.1`
adapter, reviewable plan/apply CLI, bundled deterministic provider, owned
configuration, durable intent/ownership/evidence handoff, and fresh evaluation
results. It includes a deliberate failing case, repeat-run behavior, an explicit
optional OpenAI path, and an [integration guide](integrations/promptfoo.md) with
artifact/license evidence and a [demo](../examples/evaluation/README.md).

Normal apply is **blocked before writes when the shared runner is absent**.
Planning and dry-run are usable. The catalog stays `catalog_only`; full default
CLI readiness is pending runner integration and acceptance against its fixed
revision. This adapter change does not copy or merge the other contributor's
unreviewed runner implementation.

Local verification on 18 November 2026:

| Check | Result |
| --- | --- |
| Baseline at main `fa3616e` | 320 existing tests |
| Full default suite, Python 3.11.14 | **395 passed, 2 explicitly skipped**, warnings treated as errors |
| Full default suite, Python 3.14.0 | **395 passed, 2 explicitly skipped**, warnings treated as errors |
| Ruff lint/format, dependency and diff checks | Passed |
| Wheel build and isolated installation | Passed; installed CLI plan/dry-run/block behavior and bundled CJS provider verified outside the checkout |
| Real manager acceptance with injected PR #6 runner `6057fb5` | **1 passed, 1 provider test skipped** on Darwin 27.2.0 arm64, Node 24.13.1, npm 11.8.0 |
| Positive evaluation | Two successes, zero failures/errors; upstream exit 0 |
| Deliberate negative evaluation | Zero successes, two assertion failures, zero errors; upstream exit 100 and manager failure |
| Repeat evaluation | Two successes with a fresh report; the owned install/configuration were reused |
| Real hosted model/paid provider | Not executed |
| Hosted CI for this contribution | Not run; this is a local contribution |

The real manager test uses the unmerged runner as an explicit test dependency,
not a shipped default. An initial uncached attempt encountered npm
`EIDLETIMEOUT`; the adapter recorded failure and did not configure/evaluate.
The successful attempt seeded its isolated npm cache with registry bytes from
the independent artifact probe, then ran the actual unmodified npm install
command and promptfoo CLI. The installed tree contains 626 packages; its locked
versions/integrities match the reviewed probe (691 lock entries include optional
platform packages). Nine step receipts and three distinct result files record
the positive, negative, and repeat operations, each with zero model tokens.
Unrelated project settings, manifests, npmrc, and default tool config survived.

The 75 new offline cases cover the adapter/executor handoff, stale plans,
ownership, modified files, directory links, interrupted persistence, locks,
exact paths, invalid reports, explicit provider opt-in, and credential routing
with synthetic values. Implementation and verification were AI-assisted; the
contributor should review and understand the code and evidence.

Commit accounting: C's earlier numbered contributions are 3 and 6, but the
step-6 review fix is a third actual non-merge Git commit. This step-9 change
adds **one** commit, making **four actual C work commits across three planned
contributions**. At base `fa3616e`, non-merge counts are A: 7, B: 5, C: 3; after
this contribution they are A: 7, B: 5, C: 4. The 36/12-each target still needs
honest reconciliation of future work boundaries; history and authorship are
preserved.

## Earlier main snapshot and Person A's step-7 work

On 18 November, the user's pulled main is `a7c7654`. PR #5's executor merged as
`45167a3`, followed by PR #4's configuration API and review fixes as `a7c7654`.
The catalog, initial fixtures/CI, runtime inspection, executor, and configuration
API are now in the local main history. The entries below retain earlier branch
snapshots; their old branch names, test totals, and counts are not current-main
claims. Historical references to "the current user" identify the contributor
who wrote that section, not the reader of this log.

Person A's **step 7: project manifest detection and explicit user goals** is now
implemented and locally validated on `feat/project-detection`, based on
`a7c7654`. It is prepared for PR review and is not merged. Its dependencies
(1, 2, 4) were already merged; the numbered scope remains in the shared plan.

The step-5 pinned-command runner and managed environments are still absent from
this tree. PR #5 corresponds to executor work in step 8, not step 5. A callback
executor is present, but full runner/configuration-ownership integration and real
adapter acceptance remain pending. Do not infer completion from PR numbering or
merge order. All catalog entries remain catalog-only.

## Step 7 local implementation / Person A

- Adds `inspect_project()` and `stackwinnow inspect` for root Python/Node
  manifests, declared dependency groups/runtime constraints, and names from an
  explicitly selected project-local JSON `mcpServers` object.
- Records goals, assistant choice, manual catalog selections, and model
  preference separately from observed facts/evidence. This does not install
  tools, execute scripts, inspect host tools, or establish compatibility.
- Preserves unknowns and partial findings; includes bounded reads, sanitized
  diagnostics, and explicit complete/incomplete/input-error exit statuses.
- Uses `packaging` as a declared dependency for PEP 508 names and Python
  constraints, including prerelease/development versions. Initial bounded
  inspection is supported on macOS/Linux.
- Local review fixes preserve exact `ProjectProfile.project_root` and
  `EvidenceRef.source` strings in the shared contracts while still rejecting
  whitespace-only values. Padded MCP registration names produce diagnostics
  without corrupting JSON reloads; valid names are retained. Catalog selection
  reuses indexed lookup, and dynamic metadata is validated once.
- Usage, schema, handoff, and limitations: [project inspection](project-inspection.md).
- Validation on Python 3.11: merged-main baseline **243 tests passed**; after
  implementation and review fixes **317 tests passed**, both with warnings treated as errors.
  Ruff lint/format, dependency compatibility, and diff checks passed. Built and
  reinstalled the package, exercised the installed CLI outside the checkout in
  tests, and ran inspection against this repository. These validation results
  are local; they do not include hosted CI.
- The next action is PR review and integration of this feature.
  Next A engineering milestone is step 10, explainable recommendations, with the
  shared plan's first-real-adapter integration dependency still outstanding.

PR #7 review follow-up: dependency declarations that exceed the parser's
recursion limit now produce a sanitized failed diagnostic while other
dependencies and manifests remain available. Regression coverage includes
regular/optional Python dependencies and the installed CLI's partial JSON
response. All **320 tests passed** locally on Python 3.11 with warnings treated
as errors; Ruff lint/format and package build/reinstallation passed. Hosted CI
passed on Python 3.11/3.14 for the original `2abbeae` commit; those results do
not cover this follow-up.

Implementation, documentation, and test preparation were AI-assisted. These are
local feature results, not a claim that main or any upstream integration is ready.

## Completed work recorded before starting step 3

| Step | Author / role | Actual work commit | Integration evidence | Delivered scope |
| --- | --- | --- | --- | --- |
| 1 | BASKARRAJU / A | [1942a77](https://github.com/OSS-Project-Agentreckon/StackWinnow/commit/1942a777e3eb5abea6f7a295a426fc8b532be0c7), 16 Nov 13:51 IST | Root commit on main; no bootstrap merge PR was found | Python package, CLI help/version, shared Pydantic contracts, MIT license, README, metadata, CLI/contract tests. |
| 2 | I578380 / B; PR author komalnandiniakam | [d96d356](https://github.com/OSS-Project-Agentreckon/StackWinnow/commit/d96d356fae531c4d7d6909b3f17611fc274023fd), 16 Nov 15:03 IST | [PR #1](https://github.com/OSS-Project-Agentreckon/StackWinnow/pull/1), merged 15:34 IST as [6616b86](https://github.com/OSS-Project-Agentreckon/StackWinnow/commit/6616b86435c2425a85581255ccc8e522e66faeab) | OS/architecture, Python/Node, package-manager and assistant inspection module, plus runtime tests. |

These two work commits were verified in Git history. Their correctness review was completed after implementing step 3; see [review of commits 1 and 2](reviews/commits-01-02.md). There are two completed work changes, but only one merged PR because the bootstrap was a root commit.

## Completed step 3 / person C's first contribution

- Owner: the current user; the existing local Git identity is **Kalwarala Abhignan**.
- Planned title: `test(project): add fixture harness and initial CI checks`.
- Status: merged through [PR #3](https://github.com/OSS-Project-Agentreckon/StackWinnow/pull/3) on 17 November as `eebe447`. The work commit is `c30b667b1fa1a3d79c5f788cb9739bf130540d38`, attributed to AbhignanSharma with `abhignansharma.k@gmail.com`.
- Scope: isolated project/config/browser/code fixtures, meaningful fixture checks, initial lint/unit CI, testing documentation, and progress records.
- The chronological plan and steps 1–2 were documented before implementation.
- This step does not install agent tools or modify personal assistant configuration.

Implemented fixtures cover independent project copies, an unrelated existing
configuration entry, a known Python call relationship/result, a loopback browser
page, isolated subprocess environments, and explicit integration/provider test
opt-ins. Initial CI checks Python 3.11 and 3.14 with read-only repository access.

Validation performed locally on macOS during step 3:

| Check | Result |
| --- | --- |
| Original main baseline, Python 3.14.0 | 52 tests passed |
| Step 3, Python 3.14, warnings treated as errors | 62 tests passed |
| Step 3, Python 3.11, warnings treated as errors | 62 tests passed |
| Ruff lint and formatting | Passed |
| Dependency compatibility, both environments | Passed |
| Workflow syntax, triggers, permissions, action pins, Python matrix | Checked locally |
| Chronological plan count and local documentation links | 36 steps; 12 per owner; links resolve |
| Hosted GitHub Actions / real agent integrations at step-3 implementation time | Not run then; newer main CI evidence is recorded below |

The existing runtime-test lint failure was corrected with a test-only import/spacing cleanup. Step 3 did not change production code under `src/stackwinnow/`. Implementation and review preparation were AI-assisted; the student should inspect and understand the fixtures, CI, and findings.

## Review outcome

- Bootstrap: no actionable defect found within its implemented scope.
- Runtime: two open P2 findings were reproduced locally: an unreadable extension
  directory aborts inspection; malformed Node version output is accepted as
  successful. Detailed triggers and suggested fixes are in the linked review.
- No production fix for those findings was mixed into step 3, and no public
  review or issue comment was posted.

## Other observed work

[PR #2](https://github.com/OSS-Project-Agentreckon/StackWinnow/pull/2), A's step 4
(catalog/eligibility), merged on 17 November as `fe55d36`. Its initial work
commit was `2b0e5c5`; follow-up commits were `069f707`, `d4c19a2`, and `b9533e4`.
It delivers 30 validated catalog entries, eligibility explanations, and
list/filter/detail CLI commands. All entries remain catalog-only.

Main at `fe55d36` passed 139 tests locally on Python 3.14 with warnings treated
as errors, plus lint/format/dependency checks. [Hosted CI run 44074282186](https://github.com/OSS-Project-Agentreckon/StackWinnow/actions/runs/44074282186)
passed on Ubuntu/Python 3.11 and 3.14. Both earlier runtime P2 findings were
reproduced again. Step 5's command runner and managed environments are absent
from this base; no corresponding remote PR was found during the review.

## Step 6 implementation and review history / person C's second contribution

- Owner: Kalwarala Abhignan / AbhignanSharma, `abhignansharma.k@gmail.com`.
- Title: `feat(config): plan and apply owned project configuration edits`.
- Status: [PR #4](https://github.com/OSS-Project-Agentreckon/StackWinnow/pull/4) merged as `a7c7654`. The original implementation is `484e3d3`, followed by review-fix commit `6a07797`. The validation narrative below records that contribution's history.
- Dependencies at implementation time: steps 1 and 3 were merged. Work proceeded
  independently of step 5. Actual integration occurred before the planned
  step-5 runner was delivered; that dependency gap is recorded above.
- Scope: strict JSON previews, targeted object-key edits, original/written
  ownership data, expected-state checks, atomic publication, and tests.
- Shared contracts and the executor handoff are documented in
  [configuration](configuration.md). No runtime production fixes are included.

Tests cover unrelated settings, existing-value replacement, missing versus null,
no-op ownership, new files/parents, malformed data, precision preservation,
stale previews, write failures, path redirection, and publication/cleanup
failures. This uses POSIX filesystem operations and copied fixture projects;
no upstream tools or live assistant settings are involved.

Initial step-6 validation performed locally on macOS on 17 November:

| Check | Result |
| --- | --- |
| Python 3.14.0, warnings treated as errors | **212 tests passed** |
| Python 3.11.14, warnings treated as errors | **212 tests passed** |
| New configuration scenarios | **73 cases**, included in both full-suite runs |
| Ruff lint and formatting | Passed |
| Dependency compatibility, both Python environments | Passed |
| Documented temporary-project example | Executed successfully |

The initial feature commit also passed both Ubuntu/Python 3.11 and 3.14 jobs in
[CI run 44145287862](https://github.com/OSS-Project-Agentreckon/StackWinnow/actions/runs/44145287862).
Receipt persistence, complete removal, and real assistant integration are
outside this configuration change. Step-6 design, implementation, tests, and
documentation were AI-assisted and require the contributor's review and
understanding.

On 18 November, BASKARUNIBASKARRAJU's [review](https://github.com/OSS-Project-Agentreckon/StackWinnow/pull/4#pullrequestreview-5950525150)
identified two reproducible correctness issues: sorted JSON serialization
invalidated preview digests, and symlink-loop exceptions escaped the expected
planning/apply outcomes. The follow-up renders object keys deterministically
and normalizes both Python 3.11's RuntimeError and newer OSError(ELOOP) into
configuration conflicts.

Three regression tests failed against `484e3d3` on both Python versions before
the fixes. The updated branch passed **215 tests** on each of Python 3.11.14
and 3.14.0 with warnings treated as errors, plus Ruff lint/format checks. There
are now **76 configuration scenarios**. The author requested a separate fix
commit on the existing branch, preserving the original implementation commit.
The earlier CI result above covers `484e3d3`; the review-fix commit has its own
checks on PR #4.

## Contribution-count baseline

The historical baseline `6616b86` had **A: 1, B: 1, C: 0** non-merge commits.
Branch base `fe55d36` has **A: 5, B: 1, C: 1**, plus four merge commits
(11 total Git commits). Step 6's original implementation and requested review
fix are two Git commits for one planned work item. This branch's non-merge
counts are therefore **A: 5, B: 1, C: 3**. The review fix does not complete
another numbered plan step.

The catalog follow-ups and this review fix consume additional commit slots.
Retaining the 36/12-each target requires revising future commit boundaries
while preserving required work and genuine authorship. Existing commits and
the branch history are preserved. These counts describe this branch from
`fe55d36`; other work merged into origin/main after that base is separate.

```sh
git shortlog -sne --no-merges HEAD
git log --reverse --format='%h %an <%ae> %s' HEAD
```

## Evidence and boundaries

- Git history was inspected locally and PR state read through the public GitHub API.
- The earlier HTTP 401 authentication problem was resolved on 17 November; the step-3 push was verified under AbhignanSharma. No review or comment was published as part of this local work.
- AI-assisted review notes must be labeled as such and are not a substitute for the student's own review and understanding.
- This log does not establish faculty approval, upstream integration success, or a final supported assistant/platform.
