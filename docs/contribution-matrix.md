# Contribution matrix

This document records what each contributor delivered, using their public GitHub
identities. It does not contain student roll numbers, faculty-approved grades,
or private institutional identifiers.

**Repository:** <https://github.com/OSS-Project-Agentreckon/StackWinnow>  
**Assignment plan:** docs/chronological-commit-plan.md (36 work commits across 3 roles)

---

## Role summary

| GitHub identity | Role | Planned work-commit positions |
| --- | --- | --- |
| BASKARUNIBASKARRAJU | A — Catalog, detection, recommendations, CLI, Graphify | 1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34 |
| komalnandiniakam | B — Runtime, execution, state, Headroom, packaging | 2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35 |
| AbhignanSharma | C — Fixtures/CI, configuration, verification/removal, promptfoo, Playwright | 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36 |

---

## BASKARUNIBASKARRAJU (Person A)

**Completed steps (committed and pushed, PRs merged or open):**

| Step | Branch / PR | Deliverable |
| --- | --- | --- |
| A01 — Bootstrap | `1942a77` / merged | Python CLI package, shared typed contracts, MIT license, README |
| A04 — Catalog | PR #2, merged | 30-entry catalog with eligibility, list/filter/detail CLI |
| A07 — Inspection | PR #7, merged | Project manifest inspection, detect.py, goal/assistant/tool intent flags |
| A10 — Recommendations | PR #9, merged | explain matched tools, deterministic ranking, alternatives/conflicts |
| A13 — Graphify adapter | PR #12, merged; PR #33 | Pinned graphifyy recipe, managed install/index, Codex bridge, known-call verifier |
| A16 — Unified CLI | PR #37, merged | Explicit inspect/recommend/select/plan/apply/verify/status workflow with guarded transitions |
| A19 — Portable profiles | PR #38, merged | Strict portable export/import, fresh-destination replanning, 4 profile round-trips |
| A22 — Recommendation acceptance | PR #39, open | Browser/Headroom mode discovery, conservative generic preflight, mode gates |
| A25 — Release tooling | PR #40, open | Committed-source wheel/sdist builder, historical license inventory, packaging CI |
| A28 — User guides | This PR | Installation, troubleshooting, architecture guides, demo instructions, evidence index |

**Deferred:**

- A05 exhaustive combined lifecycle acceptance (user-requested deferral)
- Benchmarks comparing managed vs. manual setup effort (measurement infrastructure exists; comparison deferred)
- Final full-suite acceptance, fresh runtime inventory reconciliation

---

## komalnandiniakam (Person B)

**Completed steps (committed and pushed, all PRs merged):**

| Step | Branch / PR | Deliverable |
| --- | --- | --- |
| B02 — Runtime inspect | merged to main | OS/arch/Python/Node detection, structured capability results |
| B05 — Pinned commands | merged to main | Managed environments, pinned command runner |
| B08 — Execute plans | merged to main | Installer, execution receipts, ownership paths |
| B11 — Preflight | PR #10, merged | Eligibility validation, preflight checks, detect-installs |
| B14 — Headroom | PR #34, merged | Headroom managed library compression, verification adapter |
| B17 — State/resume | PR #14, merged | Durable release, resume incomplete setup, avoid duplicate work |
| B20 — Coordinated removal | PR #35, merged | Coordinated removal plans, reinstall contracts |
| B23 — Foundation handoff | PR #36, merged | Four narrow actual tool lifecycles accepted; shared verification |
| B26 — Package verify | PR #27, merged | Distribution packaging tests (--run-packaging), clean venv install checks |
| B29 — Release artifacts | PR #28, merged | Build release script, PEP 440 version gate, verify-only mode |

---

## AbhignanSharma (Person C)

**Completed steps:**

| Step | Branch / PR | Deliverable |
| --- | --- | --- |
| C03 — Fixtures/CI | PR #3, merged | Test fixture harness, temporary-project fixtures, GitHub Actions CI |
| C06 — Configuration | PR #4, merged | Strict JSON config ownership, preview/apply, original-state digests |
| C09 — promptfoo | PR #6, merged | Runner, macOS arm64 promptfoo adapter, plan/apply/check |
| C12 — Verification framework | PR #13, merged | Shared VerificationCheck/ToolVerification, check CLI dispatcher |
| C15 — Playwright MCP | PR #16, merged | Playwright MCP + Codex installation, owned config, scripted browser acceptance |
| C18 — Removal | PR #31, merged | A01 config lifecycle, owned restoration, runtime references |
| C21 — Graphify freshness | PR #32, merged | Graphify freshness/reindexing repair, managed index lifecycle |
| C24 — Graphify Codex bridge | PR #33, merged | Graphify Codex bridge/client, actual query evidence |

**Remaining C steps (deferred or in progress):**
Steps C27, C30, C33, C36 (further verification/CLI/release steps); see
[docs/implementation-progress.md](implementation-progress.md) for current status.

---

## Notes

- Contribution counts at the time of this document:
  BASKARUNIBASKARRAJU 70, komalnandiniakam 36, AbhignanSharma 21 commits to origin.
- Review-fix and merge commits are additional history for their respective work items,
  not newly completed plan steps.
- All implementation is AI-assisted; contributors are responsible for reviewing,
  understanding, and taking ownership of submitted code and documentation.
- For detailed evidence of each step's acceptance, see [docs/evidence/index.md](evidence/index.md).
