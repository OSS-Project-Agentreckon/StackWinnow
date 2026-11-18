# StackWinnow: chronological 36-work-commit plan

Recorded from the assignment conversation on 15 November 2026; added to this repository on **16 November 2026**. Actual completion and evidence are in [implementation-progress.md](implementation-progress.md).

The target is **12 substantive work commits per person, 36 total**: a 30-entry OSS catalog and a proposed first release with Graphify, Headroom, promptfoo, and Playwright MCP. Catalog membership does not imply installation support. The relative seven-day schedule is not restarted here.

| Role | Ownership | Work-commit numbers |
| --- | --- | --- |
| A | Catalog, detection, recommendations, CLI, Graphify | 1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34 |
| B | Runtime, execution, state, Headroom, packaging | 2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35 |
| C | Fixtures/CI, configuration, verification/removal, promptfoo, Playwright | 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36 |

As checked on **18 November 2026**, local main is `a7c7654`. Steps 1–4 and
step 6 are merged. PR #5 supplies part of step 8's executor work; step 5's
pinned-command runner and managed environments are still pending. Integration
has not followed every planned step in order, so use actual delivered behavior
and dependencies rather than PR numbers to select the next task. A's step 7 is
implemented and tested locally on `feat/project-detection`, pending PR review/merge;
see the progress log for validation and the next dependency gates.
Review-fix and merge commits are additional history for their work items, not
new completed steps. Preserve the required work and genuine authorship rather
than rewriting history to force a Git commit count. The progress log retains
the dated contribution counts and validation evidence.

Numbering below is the planned integration order, not a completion claim or an instruction to change authors or timestamps. Each change includes relevant tests and review. Dedicated test steps add scenario or reproduction evidence. Work can proceed concurrently where dependencies allow.

Paths describe the planned implementation. Existing contracts use `src/stackwinnow/contracts.py`; runtime inspection is currently `src/stackwinnow/runtime.py`. Adapt future paths to the actual structure instead of creating empty modules to match the plan. Python package support begins at 3.11. Select and validate exact client/platform/tool versions before advertising integrations; step 3 does not establish support for any real assistant.

## Daily milestones

| Day | Commit range | Commits per member that day | Exit condition |
| --- | --- | ---: | --- |
| 1 | 1–6 | 2 | Shared contracts, initial compatibility findings, catalog, runner, and scoped configuration primitives exist. |
| 2 | 7–12 | 2 | A real promptfoo onboarding workflow passes; project facts, recommendations, preflight, and accurate checks are available. |
| 3 | 13–18 | 2 | All four baseline adapters and the guided workflow work on declared fixtures; reruns/conflicts are handled. |
| 4 | 19–24 | 2 | Portable profiles, scoped cleanup, and real lifecycle acceptance pass; freeze feature scope. |
| 5 | 25–30 | 2 | Packaged installation and independent reproduction work; quality checks and practical guides are in place. |
| 6 | 31–33 | 1 | Setup comparison, license evidence, real reviews, and individual demo material are complete. |
| 7 | 34–36 | 1 | Support claims, release artifacts, report, and evidence are ready; validate and tag the final commit. |

A commit's **acceptance check** is part of the work, not a promise to test later. Behavior-changing commits should contain the tests needed to review that change. Dedicated test commits below add new scenario coverage or independent reproduction evidence; they should not merely duplicate the implementation. Record real upstream integration findings in the relevant adapter documentation.

Day 2 is the first decisive feasibility gate. If commit 9 cannot complete a real installed/configured/verified workflow, reassess the scope before continuing with the remaining adapters. A mocked executor or a protocol-only check is not a substitute for the advertised integration.

## Day 1: Foundation and safe primitives

### 01. A — chore(project): bootstrap CLI package and shared contracts

**Depends on:** Pre-start decisions; no earlier commit.

**Deliver:** Create the Python CLI package, development setup, basic help/version command, and minimal typed contracts for project facts, catalog entries, plans, receipts, owned changes, adapters, and verification results. Add the selected license and attribute imported planning/research accurately. Keep the contracts small and agree them with B and C.

**Likely files:** `pyproject.toml`, `src/stackwinnow/cli.py`, `src/stackwinnow/models.py`, `tests/test_contracts.py`, `README.md`, `LICENSE`, `.gitignore`.

**Acceptance check:** A clean development install succeeds; help runs; contract validation/round-trip tests pass. No nonfunctional setup command is advertised as ready.

**Individual value:** Makes the codebase independently usable and gives the three workstreams compatible interfaces.

### 02. B — feat(runtime): inspect supported environment and prerequisites

**Depends on:** 01.

**Deliver:** Detect OS/architecture, Python/Node/package-manager versions, executable locations, and the selected assistant. Return structured capability results. Record the initial feasibility findings and exact intended upstream versions for B’s integration work; A and C contribute their own findings in their owned changes.

**Likely files:** `src/stackwinnow/runtime/inspect.py`, `tests/test_environment.py`, `docs/compatibility.md`.

**Acceptance check:** Supported, missing-runtime, and incompatible-version fixtures yield actionable results. Inspection runs no project scripts and modifies no settings.

**Individual value:** Explains setup blockers before installation begins.

### 03. C — test(project): add fixture harness and initial CI checks

**Depends on:** 01.

**Deliver:** Create temporary project/configuration fixtures for the selected client, a small codebase with known relationships, and a local browser page with a known result. Configure initial lint/unit CI. Separate local fixture checks from real tool/client checks that require additional prerequisites.

**Likely files:** `tests/conftest.py`, `tests/fixtures/`, `tests/test_fixture_isolation.py`, `.github/workflows/ci.yml`, `docs/testing.md`.

**Acceptance check:** The fixture harness uses temporary paths and leaves the developer’s live assistant settings untouched. CI runs the currently implemented tests and reports unavailable external checks clearly.

**Individual value:** Provides reproducible, isolated evidence for every later integration.

### 04. A — feat(catalog): add 30 source-reviewed tool entries and eligibility

**Depends on:** 01, 02.

**Deliver:** Convert the existing 30-candidate research into validated catalog entries with purpose, repository, license scope, prerequisites, conflicts, and readiness. Add list/filter/detail output. Keep LiteLLM/Langfuse automation ineligible until an OSS-only artifact is established, and distinguish reviewed entries from implemented adapters.

**Likely files:** `catalog/tools/`, `src/stackwinnow/catalog.py`, `tests/test_catalog.py`, `docs/catalog-sources.md`.

**Acceptance check:** Exactly 30 unique entries load; invalid/duplicate entries fail clearly; license-boundary and unsupported-recipe cases cannot appear as install-ready.

**Individual value:** Turns the research into a useful catalog while making support and license limits visible.

### 05. B — feat(runtime): execute pinned commands in managed environments

**Depends on:** 01, 02.

**Deliver:** Implement an argument-list subprocess runner and isolated Python/Node tool locations for pinned packages. Add explicit working directories, bounded timeouts, return-code handling, and redacted diagnostics. Limit execution to declared adapter operations.

**Likely files:** `src/stackwinnow/runtime/runner.py`, `src/stackwinnow/runtime/environments.py`, `tests/test_runner.py`.

**Acceptance check:** Space-containing paths, failed commands, timeout cleanup, and sensitive environment values are handled correctly. A failed command cannot be reported as a successful install.

**Individual value:** Provides the shared installation primitive without replacing upstream package managers.

### 06. C — feat(config): plan and apply owned project configuration edits

**Depends on:** 01, 03.

**Deliver:** Implement targeted edits for the chosen client/config format. Produce a preview and ownership records containing original values and written values. Validate the expected file state before an atomic write. Return ownership data through the shared contract so B’s executor can persist it.

**Likely files:** `src/stackwinnow/configure/patches.py`, `tests/test_configuration_patches.py`.

**Acceptance check:** An edit preserves unrelated keys and required syntax/comments for the supported format; malformed or changed input produces a conflict; no full-file replacement erases unrelated settings.

**Individual value:** Connects tools to a project while preserving the developer’s configuration.

## Day 2: First complete onboarding workflow

### 07. A — feat(detect): inspect project manifests and accept user goals

**Depends on:** 01, 02, 04.

**Deliver:** Read the supported Python/Node manifests and selected existing tool configuration. Capture explicit goals, selected client, local/hosted preference, and manual tool choices. Return evidence and unknown values instead of guessing unsupported details.

**Likely files:** `src/stackwinnow/detect/`, `src/stackwinnow/cli.py`, `tests/test_detection.py`.

**Acceptance check:** Different fixture projects produce different facts; manual goals remain explicit; unreadable/missing manifests are handled without running scripts or reading secrets.

**Individual value:** Gives recommendations actual project context and supports users whose projects cannot be inferred.

### 08. B — feat(install): execute reviewed plans and persist step receipts

**Depends on:** 01, 02, 05, 06.

**Deliver:** Build and execute an explicitly selected adapter plan with dry-run support. Persist planned operations and configuration ownership before mutation, then atomically record completed/failed steps. Expose the initial explicit-tool plan/apply command path for C’s first real adapter.

**Likely files:** `src/stackwinnow/plan.py`, `src/stackwinnow/install.py`, `src/stackwinnow/state/receipts.py`, `tests/test_execution_state.py`.

**Acceptance check:** Dry-run leaves the environment unchanged; a failed step has accurate durable state; successful steps and owned configuration can be inspected. Test adapters here are labeled fixtures.

**Individual value:** Coordinates installation into an auditable project setup rather than disconnected commands.

### 09. C — feat(promptfoo): onboard and verify a project evaluation

**Depends on:** 03, 04, 06, 08.

**Deliver:** Implement the first real pinned adapter: install promptfoo, create an owned evaluation configuration in a fixture project, and run known-result cases with a documented local deterministic provider. Add an explicit optional real-model path; identify the checks that incur provider usage.

**Likely files:** `src/stackwinnow/adapters/promptfoo.py`, `tests/integration/test_promptfoo.py`, `examples/evaluation/`, `docs/integrations/promptfoo.md`.

**Acceptance check:** The manager completes install → configure → evaluation → recorded result on the declared environment. A deliberately failing case reports failure. Local provider results are not presented as evidence of LLM quality.

**Individual value:** Delivers the first complete working onboarding path by Day 2.

### 10. A — feat(recommend): explain tool matches and conflicting choices

**Depends on:** 04, 07, 09.

**Deliver:** Implement explainable rules connecting goals/project facts to tools. Respect existing framework choices, surface overlapping alternatives, honor explicit selections, and show readiness. Allow an unsupported tool to be discovered without offering it as an executable setup.

**Likely files:** `src/stackwinnow/recommend.py`, `tests/test_recommendations.py`, `docs/recommendation-rules.md`.

**Acceptance check:** A code-navigation project and an evaluation project get different justified results; explicit preferences and conflicts have predictable outcomes; unsupported recommendations remain visibly unavailable for installation.

**Individual value:** Makes choosing tools a core feature rather than asking every user to know the ecosystem.

### 11. B — feat(plan): validate eligibility and detect existing installations

**Depends on:** 02, 04, 08, 09.

**Deliver:** Validate exact recipe versions, environment compatibility, selected OSS artifacts, required endpoints, and existing installations before apply. Show configuration/download effects and detect stale plans. Reuse compatible external installations without silently taking ownership.

**Likely files:** `src/stackwinnow/plan.py`, `src/stackwinnow/runtime/existing.py`, `tests/test_plan_preflight.py`.

**Acceptance check:** A changed prerequisite or unsupported artifact blocks the plan with a reason; a pre-existing installation is distinguished from an app-managed one and will not become eligible for deletion.

**Individual value:** Prevents avoidable install failures and accidental takeover of existing tools.

### 12. C — feat(verify): report installed connected and functional states

**Depends on:** 01, 03, 08, 09, 11.

**Deliver:** Add structured, tool-appropriate checks and a check command. Distinguish package health, configuration, effective connection, known-result functionality, failures, and blocked checks. Adapt promptfoo’s check into this framework and emit human-readable and JSON results.

**Likely files:** `src/stackwinnow/verify/`, `src/stackwinnow/cli.py`, `tests/test_verification_states.py`.

**Acceptance check:** A missing credential is blocked rather than passed; package presence cannot automatically imply client connectivity; intentionally wrong fixture output fails the functional check.

**Individual value:** Makes readiness claims inspectable and accurate.

## Day 3: Four adapters and a unified CLI

### 13. A — feat(graphify): index a project and verify a known relationship

**Depends on:** 04, 06, 08, 11, 12.

**Deliver:** Implement a pinned Graphify recipe with explicit project/client scope and a project graph path. Build the known fixture index, query a known relationship, and verify the selected integration. Record the actual package identity and do not use a broad all-client uninstall operation.

**Likely files:** `src/stackwinnow/adapters/graphify.py`, `tests/integration/test_graphify.py`, `docs/integrations/graphify.md`.

**Acceptance check:** The intended project is indexed, the expected relationship is returned, and the chosen client integration is exercised. Record real commands/results and any remaining provider-dependent checks separately.

**Individual value:** Automates useful project knowledge, beyond installing the Graphify package.

### 14. B — feat(headroom): configure and verify one supported request path

**Depends on:** 04, 05, 06, 08, 11, 12.

**Deliver:** Implement one explicitly selected, pinned Headroom integration mode. Configure the project/client for that mode, avoid implicit installation of unrelated add-ons, and exercise controlled input through the actual configured path. Distinguish library, proxy, and client-wrapper evidence.

**Likely files:** `src/stackwinnow/adapters/headroom.py`, `tests/integration/test_headroom.py`, `docs/integrations/headroom.md`.

**Acceptance check:** The chosen mode demonstrably processes the fixture input; cleanup is scoped; any claim of assistant routing is supported by an actual assistant-path check. Do not infer savings or connectivity from a running process.

**Individual value:** Adds the original context-optimization use case with verifiable behavior.

### 15. C — feat(playwright): connect browser automation through MCP

**Depends on:** 03, 04, 06, 08, 11, 12.

**Deliver:** Install the pinned server/browser prerequisites, register the server only in the selected client/project scope, and use the local page fixture to verify browser interaction. Record client-side tool invocation separately from raw MCP protocol checks.

**Likely files:** `src/stackwinnow/adapters/playwright_mcp.py`, `tests/integration/test_playwright_mcp.py`, `docs/integrations/playwright-mcp.md`.

**Acceptance check:** The selected client invokes the tool and observes the expected fixture value. Missing browser/runtime/provider prerequisites remain actionable blocked results rather than successful integration.

**Individual value:** Provides a demonstrable agent automation task through the real client.

### 16. A — feat(cli): connect discovery planning onboarding and status

**Depends on:** 07, 10, 11, 12, 13, 14, 15.

**Deliver:** Connect the existing commands into a complete guided journey with explicit tool selection, plan preview, apply, check, and status. Preserve noninteractive options for reproducible scripts and include example profiles for the four implemented adapters.

**Likely files:** `src/stackwinnow/cli.py`, `tests/test_cli_journey.py`, `examples/profiles/`.

**Acceptance check:** A user can reach a verified fixture result from a project path without manually editing the manager’s internal state; cancelling a plan changes nothing; a 30-tool catalog is not mistaken for 30 executable adapters.

**Individual value:** Makes the individual modules usable as one product.

### 17. B — feat(state): resume incomplete setup and avoid duplicate work

**Depends on:** 08, 11, 13, 14, 15.

**Deliver:** Reconcile receipts with observed state before rerunning. Skip verified compatible steps, retry explicitly resumable failed steps, and serialize concurrent operations for the same managed project. Explain externally changed state instead of blindly overwriting it.

**Likely files:** `src/stackwinnow/state/`, `src/stackwinnow/install.py`, `tests/test_repeat_apply.py`.

**Acceptance check:** Apply twice creates no duplicate installs or configuration; a controlled interruption can resume; a stale receipt cannot mask a missing tool or changed configuration.

**Individual value:** Turns installation automation into repeatable setup.

### 18. C — feat(config): detect collisions and preserve later user changes

**Depends on:** 06, 11, 12, 17.

**Deliver:** Extend configuration reconciliation to pre-existing tool names, user-edited owned values, malformed files, and stale previews. Return precise conflict reports and retain the unchanged original file when the manager cannot safely reconcile it.

**Likely files:** `src/stackwinnow/configure/conflicts.py`, `tests/test_configuration_conflicts.py`.

**Acceptance check:** An unrelated key, a modified owned value, and an existing conflicting tool registration each survive the relevant failure case; retry instructions identify the exact conflict.

**Individual value:** Handles realistic configuration sharing between developers and tools.

## Day 4: Repeatability, removal, and feature freeze

### 19. A — feat(profiles): export and validate reproducible project selections

**Depends on:** 04, 10, 11, 16.

**Deliver:** Add profile export/import with schema version, selected tools, tested versions, relevant preferences, and compatibility information. Keep machine-specific state and secrets in local receipts/environment references, not in a portable profile.

**Likely files:** `src/stackwinnow/profiles.py`, `tests/test_profile_portability.py`, `examples/profiles/`.

**Acceptance check:** An exported profile can be inspected and replanned in a second fixture project; malformed or incompatible profiles fail clearly; credential values and private absolute paths are excluded.

**Individual value:** Lets another developer reproduce the selected setup.

### 20. B — feat(runtime): plan removal of exclusively managed resources

**Depends on:** 08, 11, 17.

**Deliver:** Implement the lower-level removal plan for exact runtime/package resources owned by this manager. Check references and shared use, retain external installations and project data, and expose a dry-run removal summary. Coordinate actual execution through C’s cleanup command in commit 21.

**Likely files:** `src/stackwinnow/runtime/remove.py`, `tests/test_owned_runtime_removal.py`.

**Acceptance check:** Only receipt-owned, unreferenced resources are candidates for deletion; external tools, graph data, caches designated for retention, and another project’s resources remain untouched.

**Individual value:** Makes uninstall scope explicit and preserves pre-existing installations.

### 21. C — feat(remove): clean owned configuration before managed runtimes

**Depends on:** 06, 12, 18, 20.

**Deliver:** Implement the coordinated remove command. Compare current values to recorded writes, restore/remove only unchanged manager-owned entries, preserve subsequent edits, and then release eligible managed resources. Keep a runtime if preserved configuration still references it.

**Likely files:** `src/stackwinnow/remove.py`, `src/stackwinnow/cli.py`, `tests/test_safe_remove.py`.

**Acceptance check:** Removing one tool preserves unrelated settings, user-edited entries, project data, and other tools. Repeating removal is harmless, and conflicts are reported instead of resolved destructively.

**Individual value:** Completes a lifecycle that developers can safely reverse.

### 22. A — test(recommend): cover ambiguous projects overrides and eligibility

**Depends on:** 04, 07, 10, 16, 19.

**Deliver:** Add missing outcome-based cases for mixed-language projects, existing frameworks, absent manifests, conflicting goals, unsupported hardware, and mixed-license candidates. Fix any rule defects demonstrated by those cases in the same commit.

**Likely files:** `tests/fixtures/projects/`, `tests/test_recommendation_scenarios.py`, `docs/recommendation-rules.md`.

**Acceptance check:** Recommendations and their reasons match the expected user outcome for each scenario; no unsupported or ineligible tool enters an executable plan.

**Individual value:** Tests recommendation judgment on realistic edge cases rather than merely mirroring rule implementation.

### 23. B — test(lifecycle): exercise timeout interruption and recovery failures

**Depends on:** 05, 08, 17, 20, 21.

**Deliver:** Add fault-injection coverage for failed package commands, interrupted state writes, timeouts, concurrent attempts, and changed installations. Address reproducible runner/state defects uncovered by the tests.

**Likely files:** `tests/test_execution_failures.py`, `tests/test_receipt_recovery.py`, `docs/testing.md`.

**Acceptance check:** Receipts stay parseable, cleanup does not target unowned data, repeated setup reaches a defined result, and failures retain useful diagnostics.

**Individual value:** Demonstrates installation reliability under failures rather than only a happy path.

### 24. C — test(integration): verify supported profiles through the full lifecycle

**Depends on:** 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23.

**Deliver:** Run declared supported profiles through plan/apply/check/reapply/remove using actual tools. Test plausible combinations and document known conflicts; do not assume all four tools belong in one project. Map every advertised supported mode to evidence.

**Likely files:** `tests/integration/test_profiles.py`, `tests/integration/test_lifecycle.py`, `docs/support-matrix.md`.

**Acceptance check:** All four baseline adapters meet their declared acceptance checks and lifecycle requirements; failed/blocked combinations are accurately marked. Freeze feature scope here.

**Individual value:** Establishes a complete first release with an honest compatibility boundary.

## Day 5: Independent acceptance and distribution checks

### 25. A — test(cli): cover user journeys and portable profile onboarding

**Depends on:** 16, 19, 24.

**Deliver:** Add acceptance scenarios from user goals through displayed recommendations, plan cancellation, explicit selection, exported profiles, and interpretable verification results. Include malformed input and unsupported-tool journeys.

**Likely files:** `tests/acceptance/test_cli_journeys.py`, `examples/profiles/`, `docs/acceptance-scenarios.md`.

**Acceptance check:** The CLI’s output and exit status match the user-visible outcome; exported profiles work in a fresh fixture; unsupported setup never reports success.

**Individual value:** Checks the complete user experience independently of internal unit tests.

### 26. B — build(package): verify installation from distribution artifacts

**Depends on:** 01, 04, 19, 24.

**Deliver:** Build source and wheel artifacts, install the wheel outside the source checkout, and check that catalogs, recipes, entry points, version metadata, and runtime requirements are included correctly. Fix actual packaging omissions.

**Likely files:** `pyproject.toml`, `tests/packaging/`, `scripts/check_distribution.py`.

**Acceptance check:** A clean environment can run the packaged CLI and its declared setup workflow using distributed files alone; it does not accidentally import the developer’s checkout.

**Individual value:** Makes the project consumable by other developers rather than runnable only by its authors.

### 27. C — test(reproduction): add clean-environment integration verification

**Depends on:** 24, 25, 26.

**Deliver:** Have a second team member reproduce the supported setup from the distribution in a clean workspace on the declared platform. Add a repeatable harness and record versions, environment, commands, outcomes, and any blockers. Integrate only real recorded evidence.

**Likely files:** `scripts/reproduce_supported_setup.py`, `tests/integration/`, `docs/evidence/reproduction.md`.

**Acceptance check:** The documented supported workflows reproduce independently of the original developer’s environment; unexplained dependencies or client setup omissions are fixed or explicitly limit support.

**Individual value:** Provides independent reproducibility evidence for the submission.

### 28. A — docs(user): explain discovery setup profiles and support limits

**Depends on:** 16, 19, 24, 25, 27.

**Deliver:** Write the quickstart, project/goal selection guide, examples, configuration preview explanation, and readiness descriptions against the working CLI. Attribute research and AI-assisted material and distinguish the 30-entry catalog from four integrated tools.

**Likely files:** `README.md`, `docs/user-guide.md`, `docs/catalog-guide.md`.

**Acceptance check:** A peer follows the guide successfully; commands match current behavior; unsupported features and required provider access are visible.

**Individual value:** Makes the project understandable and usable without a team walkthrough.

### 29. B — docs(operations): document installation recovery and ownership

**Depends on:** 11, 17, 20, 21, 23, 26, 27.

**Deliver:** Document managed environment locations, version pins, receipts, reuse of existing tools, known failure causes, resume behavior, and resource-removal rules. Explain key execution/state tradeoffs with concrete examples.

**Likely files:** `docs/installation.md`, `docs/troubleshooting.md`, `docs/architecture.md`.

**Acceptance check:** A teammate can diagnose a staged failure from the documented information; destructive or unsupported recovery commands are not suggested.

**Individual value:** Shows maintainability and B’s understanding of the installation design.

### 30. C — ci(quality): run fixture packaging and opt-in integration checks

**Depends on:** 03, 23, 24, 25, 26, 27.

**Deliver:** Extend CI with the implemented fixture, regression, and packaging checks. Provide an explicit workflow for real supported-environment checks where runners and credentials are available. Keep secrets out of logs and separate blocked/skipped provider checks from passed tests.

**Likely files:** `.github/workflows/ci.yml`, `.github/workflows/integration.yml`, `docs/testing.md`.

**Acceptance check:** Normal CI is reproducible without paid provider credentials; integration output identifies actual test coverage; CI does not claim an unsupported hosted runner proves the target client works.

**Individual value:** Turns local quality evidence into a repeatable contribution workflow.

## Day 6: Measured value and contribution evidence

### 31. A — docs(evidence): compare setup workflows and explain project value

**Depends on:** 25, 27, 28, 29, 30.

**Deliver:** Measure upstream manual setup and manager-assisted setup on equivalent supported fixtures, recording versions, cached downloads, manual steps, elapsed time, and errors. Include the second student’s actual observations with attribution and explain where the project adds value.

**Likely files:** `docs/evidence/setup-comparison.md`, `docs/evidence/measurements.json`, `docs/design-rationale.md`.

**Acceptance check:** Recorded measurements can be traced to real runs; cold/warm conditions and small sample size are explicit; no unsupported universal productivity or token-saving claim is made.

**Individual value:** Supplies evidence of usefulness and originality for the report.

### 32. B — docs(licensing): audit pinned dependencies and third-party notices

**Depends on:** 04, 11, 26, 27, 29, 30.

**Deliver:** Review the chosen project license and the exact distributed dependencies and supported tool artifacts. Record sources, versions, license scope, required notices, and unresolved exclusions. Keep runtime/model/infrastructure coverage separate from the manager’s dependency inventory.

**Likely files:** `THIRD_PARTY_NOTICES.md`, `docs/dependency-inventory.json`, `docs/license-rationale.md`.

**Acceptance check:** Included artifacts have a documented eligible license scope; required notices are retained; unresolved candidates are unavailable for automated setup. Do not label an incomplete inventory as a complete system-wide SBOM.

**Individual value:** Demonstrates responsible OSS reuse for the actual deliverable.

### 33. C — docs(contributing): document reviews demo and individual evidence

**Depends on:** 27, 28, 29, 30, 31, 32.

**Deliver:** Document the real contribution/review workflow and a repeatable demo script. Assemble a contribution matrix linking each member’s actual issues, PRs, commits, tests, review work, and personal explanation notes. Attribute contributed notes to their real authors.

**Likely files:** `CONTRIBUTING.md`, `docs/governance.md`, `docs/demo-script.md`, `docs/contributions.md`.

**Acceptance check:** Every claimed contribution/review has real evidence; each member can demonstrate their subsystem and explain a design choice and a failure case. Empty issue/review activity is not counted as work.

**Individual value:** Makes individual contributions and the OSS collaboration process reviewable.

## Day 7: Release and submission

### 34. A — docs(release): finalize changelog and validated support boundaries

**Depends on:** 24, 27, 28, 31, 32, 33.

**Deliver:** Write the first release changelog and reconcile the README/support table with observed results. Identify supported versions, client/platform, candidate-only entries, known limitations, and deferred features. Incorporate real documentation feedback received during rehearsal.

**Likely files:** `CHANGELOG.md`, `docs/support-matrix.md`, `README.md`.

**Acceptance check:** Every advertised supported feature has evidence; all 30 catalog entries have accurate readiness; release notes describe the delivered behavior.

**Individual value:** Defines a clear, honest public release.

### 35. B — build(release): prepare versioned artifacts and build verification

**Depends on:** 26, 30, 32, 34.

**Deliver:** Finalize the release version and dependency locks, document a repeatable build/install process, and generate checksummed artifacts in ignored output directories. Define artifact verification from the eventual release tag; do not create the final tag before commit 36.

**Likely files:** `pyproject.toml`, `dependency lockfile for the chosen tooling`, `scripts/build_release.py`, `docs/releasing.md`.

**Acceptance check:** Version metadata and locks agree; build and clean-install checks pass. Checksums identify the produced files; byte-for-byte reproducibility is not claimed unless separately tested.

**Individual value:** Makes the release installable and traceable to its source.

### 36. C — docs(submission): finalize report and evaluation evidence index

**Depends on:** 31, 32, 33, 34, 35.

**Deliver:** Assemble the final report in the required format from the team’s attributed sections, covering the problem, architecture, actual implementation, license decisions, tests, measured value, limitations, and each member’s contribution. Link the real repository/PR/demo evidence and intended release tag, then run final read-only validation after this commit.

**Likely files:** `docs/submission/report.md`, `docs/submission/evidence-index.md`.

**Acceptance check:** The report is consistent with the final code and real evidence. After commit 36, verify 12 actual authored commits per person and 36 total, run final checks, then create/publish the tag and release without an extra content commit.

**Individual value:** Completes the submission with clear project and individual evidence.

## Final verification and release

After work and reviews are complete, validate the submitted tree, check actual author identities and work counts, then create the release tag. A tag is not another work commit. Build artifacts from that tag; preserve existing merge commits, reviews, and submitted history.

```sh
git rev-list --no-merges --count v0.1.0
git shortlog -sne --no-merges v0.1.0
git log --reverse --format='%h %aN <%aE> %s' v0.1.0
```

The planned result is 36 substantive work commits, 12 per actual person. Raw history also contains existing merge commits. Count genuine email aliases consistently. Review comments and coauthor trailers are separate evidence, not duplicate primary-author commits. Update the remaining plan when necessary; do not skip required fixes or pad counts to force a forecast.
