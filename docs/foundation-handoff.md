# Foundation acceptance and the A02 handoff

This document records the narrow adapter/lifecycle handoff. The unified workflow,
portable profiles, final recommendations, release artifacts and assignment report
remain A02–A08 work. No PR merge, published release, faculty approval or submission
is inferred from these engineering checks.

**The narrow foundation handoff is accepted at engineering revision `2a4f3b8`.**
Production code is `188e155`, stacked on removal PR #35 (`0ca8410`). The later
documentation commit records these results without changing production code.
The branch is `test/a01-foundation-handoff`, targeting
`feat/a01-coordinated-removal`. This does not establish a merge.

## Reproduction environment

The independent test environment was created from a newly built wheel, with no
editable install or `PYTHONPATH` import from the checkout. A second clean virtual
environment installed the source distribution directly. CLI acceptance launches
the installed manager in a separate process for every command, with isolated
home/config/cache directories and fixture projects. Plans and captured command
outputs are saved outside the indexed project.

| Component | Observed version or scope |
| --- | --- |
| Host | macOS 27.2.1, arm64 |
| Python | CPython 3.11.14 |
| Manager | 0.1.0.dev0 |
| Node | 24.13.1 |
| Codex CLI | 0.169.0 |
| Graphify | graphifyy 0.9.114, checked-in wheel lock |
| Headroom | headroom-ai 0.44.0, local library mode |
| promptfoo | 0.125.1, deterministic provider |
| Playwright MCP | @playwright/mcp 0.0.86, pinned browser recipe |

Graphify's installation lock requires CPython 3.11.5–3.11.x on macOS 14+ arm64.
The current Codex verification protocol requires CLI 0.169.0. The general manager
Python requirement and Linux unit CI do not establish broader integration support.
No copied credentials or paid provider calls are required for these fixtures.

From a checkout of the handoff revision, put the documented Node/Codex versions
on `PATH`, then build and install into a separate environment:

```sh
python3.11 -m venv /tmp/stackwinnow-handoff-env
/tmp/stackwinnow-handoff-env/bin/python -m pip install build
/tmp/stackwinnow-handoff-env/bin/python -m build
/tmp/stackwinnow-handoff-env/bin/python -m pip install 'dist/stackwinnow-0.1.0.dev0-py3-none-any.whl[dev]'
/tmp/stackwinnow-handoff-env/bin/python -m pytest -q -W error --run-packaging
/tmp/stackwinnow-handoff-env/bin/python -m pytest tests/integration/test_foundation_cli.py --run-integration -vv -W error
/tmp/stackwinnow-handoff-env/bin/python -m pytest tests/integration/test_graphify_install.py --run-integration -q -W error
```

Use dedicated temporary fixtures; real integration tests download/install upstream
packages and can take several minutes. The CLI lifecycle test refuses an import
from the checkout's `src/` tree. The existing Graphify install test separately
uses a real venv/bootstrap followed by a deliberately injected download failure;
this is a controlled failure test, not a claim of an observed upstream outage.

## Completed distribution and failure controls

The final rebuilt-package default/packaging selection passed **1,142 tests** with
**12 explicit integration/provider skips** in 65.19 seconds, with warnings treated
as errors. This includes five tests that build and independently install a wheel.
A separate clean source-distribution installation passed its console/version and
five-resource smoke checks. The installed module entry point was initially absent;
production commit `188e155` adds `python -m stackwinnow` support and the rebuilt
distributions pass that invocation.

The actual Graphify managed install/reindex/controlled-download-failure test passed
separately (one case, 58.53 seconds). The installed CLI missing-prerequisite and
damaged-receipt control also passed (one case, 0.56 seconds): planning remains
available without Node/Codex, apply blocks before state creation, and malformed
receipts are rejected unchanged.

One repeat of the suite was accidentally run under a restrictive host sandbox: its
package downloads and two local loopback servers were denied. The correctly scoped
repeat produced the passing result above; those denials were not product failures.
Ruff lint and formatting passed for the product files; unrelated untracked local
planning files were preserved and excluded from the formatting result.

## Actual CLI lifecycle acceptance

Three real lifecycle cases passed in **1,943.03 seconds** (32 minutes), covering
84 installed-manager subprocess commands; the separate prerequisite/receipt
control adds three commands. The sanitized [command and evidence record](evidence/foundation-cli.json)
contains observed exit codes, phase statuses, durations, report hashes and
artifact-capture counts. Expected failure exits are part of the acceptance.

| Case | Observed behavior |
| --- | --- |
| Headroom | Install, passive/fresh/negative check, fresh-plan reapply, remove/repeat, reinstall/fresh check and final remove; reports/tokenizer cache and user files preserved |
| promptfoo | Same full lifecycle; deterministic evaluation succeeds/fails as intended, zero model tokens, user configuration and prior result preserved |
| Graphify + Playwright/Codex | Both install/configure and perform actual client calls; positive/negative/repeated checks; stale index rejected after source edit; fresh index succeeds; edited Graphify registration retains runtime; unchanged owned settings restore; both remove/repeat/reinstall and verify again |

The original running process loaded the harness before its final stronger
functional assertions were added. After completion, the final helper was
independently applied to **all ten saved fresh/negative check reports**, covering
**14 distinct functional evidence files**. Each report proves installation and
configuration still succeeded; actual Codex modes also prove connection and
exact query_relationship or browser navigate/click/evaluate calls. Negative
scenarios fail the functional phase. Library modes record connectivity as not
applicable. Evidence exists, remains available after removal, and has distinct
identities across fresh checks. The checked-in harness includes these assertions
for future runs; this audit is not represented as a rerun of the full lifecycle.

Every successful Headroom control measured **282 tokens before, 282 after, zero
saved**. Its default policy protects recent/user messages; this is an honest
control, not proof of reduced cost. More representative experiments remain A07.
Promptfoo runtime validation is slow on the measured tree: the final removal
preview took 120.89 seconds, dry-run 146.22 seconds and apply 240.68 seconds.
This observation is recorded without promising faster behavior on other hosts.

Before removal, capture retained 70 Headroom distributions / 144 license-text
references, 33 Graphify distributions / 114 references, 623 promptfoo installed
npm package records and three Playwright MCP npm records. Hashes identify those
capture inputs. Python counts include environment bootstrap packages. These
inventories do not license-clear browser binaries or all transitive components;
A06 must reconcile them with its reviewed inventory.

## Interfaces delivered

| Capability | CLI/API boundary |
| --- | --- |
| Headroom library | `headroom plan PROJECT --json`, then `headroom apply PLAN --json`; `plan_headroom` / `apply_headroom` |
| Deterministic promptfoo | `promptfoo plan PROJECT --json`, then `promptfoo apply PLAN --json`; `plan_promptfoo` / `apply_promptfoo` |
| Playwright/Codex | `playwright-mcp plan PROJECT --assistant codex --json`, then `playwright-mcp apply PLAN --json`; `plan_playwright` / `apply_playwright` |
| Graphify install | `graphify execution-plan PROJECT --expectation FILE --json`, then `graphify apply PLAN --install-only --json` |
| Graphify index/reindex | `graphify index-plan PROJECT --expectation FILE --json`, then `graphify index PLAN --json` |
| Graphify/Codex | `graphify configure-plan PROJECT --json`, then `graphify configure PLAN --json` |
| Shared observations | `check PROJECT --tool TOOL --json`; explicit `--run-functional` produces fresh evidence |
| Coordinated removal | `remove plan PROJECT --tool TOOL --json`, then `remove apply PLAN --json`; repeat `--tool` for multiple tools |

All apply commands accept `--dry-run`. Planning and dry runs remain separate from
execution. Replaying an attempted Headroom, promptfoo or Playwright plan is not
the reapply interface: create a fresh plan so the next attempt has its own step
identities. Graphify install reuse validates the original saved installation
recipe; a new index plan is required after source changes. After intentional
removal, use a new installation plan and regenerate the current index.

Installation, configuration, client connection and functionality remain separate
observations. Passive `check` does not convert an older success report into a
fresh success. For library/deterministic modes, a client connection is explicitly
not applicable. Actual Codex fixtures use the supported client and MCP path with
a scripted loopback provider; they do not measure model reasoning quality.

## Ownership, removal and recovery

The [coordinated removal guide](coordinated-removal.md) is the operational
contract. It describes fixed runtime scopes, preserved project outputs/caches,
configuration references, snapshot bounds, journal phases and supported reinstall.
The [configuration lifecycle guide](configuration-lifecycle.md) documents the
lower-level restoration API and the caller's lock/journal responsibilities.

Successful removal restores only unchanged owned settings. Foreign entries,
user edits and unrelated comments survive. A preserved reference or modified
owned registration retains the associated runtime. Current receipts, historical
ownership and configuration intents all contribute to reference checks.

Each completed configuration/runtime release is durably recorded. A later
failure can be re-previewed using that evidence. Interrupted operations with a
`running` journal require inspection; deleting receipts to bypass recovery is
unsupported. Once removal completes, active installation receipts become
historical retirements, while retained resources keep their ownership/identity.
An accidentally missing runtime is not equivalent to a completed removal.

Fresh reinstall preserves existing report and generation history. Graphify's
active `provenance.json` advances after deliberate indexing; it is not immutable
history. A replaced retained data directory, newly occupied runtime, or changed
restored promptfoo configuration is not silently adopted.

## Dependency and release boundary

The Graphify lock records artifact URLs and hashes. Headroom and npm integrations
pin direct tools but currently resolve transitive dependencies. Acceptance
captures the installed Python versions/license candidates and npm lock records
before removal. These are observed snapshots, not promises about future resolver
results or completed downstream redistribution review.

The later A06 work owns final dependency specifications, third-party notices,
packaging/CI closure and the manager-only release scope. The current build's
setuptools data-package discovery warning is recorded even though both archive
installations contain the five required resources.

## Next work

A02 composes these validated boundaries into inspection, recommendations,
explicit selection, review, apply, fresh verification and status. A03 adds
portable profiles. A04 checks public recommendation/CLI behavior. A05 repeats
real lifecycles through that unified surface and freezes scope. A06–A08 complete
distribution/license work, documentation, measurements, report and authorized
release/submission preparation. The narrow acceptance here does not replace
those later milestones.
