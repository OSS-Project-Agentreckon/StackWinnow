# Contribution evidence

Audited against merged main `575a8e6` on 24 November 2026. The active schedule
is [B01–B08 then A01–A08](two-person-sequential-plan.md); the 36-step schedule
is historical. Milestone ownership does not establish commit authorship. C has
no future assigned work. Equal commit counts are not an assessment of effort.

| Contributor | Authored evidence | Scope |
| --- | --- | --- |
| BASKARUNIBASKARRAJU (BASKARRAJU) | `1942a77`, `2b0e5c5`, `2abbeae`, `9b6fb1c`, `0096d08`, `54c9119` | Bootstrap, catalog, inspection, recommendations, Graphify planning and locked installation |
| BASKARUNIBASKARRAJU | `8830dbf`, `8cc3972`, `9d554e8`, `e434c50`, `384b0b7`, `c6b7e8a`, `1df0f9c`, `2a4f3b8` (PRs #31–#36) | Later configuration repair, indexing, Codex bridge, Headroom checks, coordinated removal and foundation acceptance |
| BASKARUNIBASKARRAJU | `e7959c0`, `9539895`, `73e06e8`, `17e98be`, `9570581`, `a802747`, `e935929` (PRs #37–#40) | Unified workflow, profiles, discovery/preflight, source-bound builds and CI |
| komalnandiniakam | `6057fb5`, `0ce8c34`, `95df22f`, `9faa986`, `0ee0884`, `cb282e7` | Command runner, installer, preflight, initial Headroom adapter, resume/state and runtime removal |
| komalnandiniakam | `e5b44b0`, `976fc06`, `ca4d242`, `95a990f`, `31e29ab` | B foundation work and package verification; later repairs are attributed above |
| komalnandiniakam | `fcabdac`, `ac48b5c` (PRs #43–#44) | User guides, initial contribution/report draft, README/changelog handoff |
| AbhignanSharma (Kalwarala Abhignan) | `c30b667`, `484e3d3`, `5311f82`, `8f21b01`, `2d52f17` (PRs #3, #4, #8, #13, #16) | Fixtures/CI, configuration, promptfoo, shared verification and Playwright MCP |
| AbhignanSharma | `1abee56`, `a8fd603`, `983a6cd`, `76e377a`, `ce61b4c` | Configuration collision reporting and Playwright CLI repair |

These are representative authored commits, not an exhaustive effort measure.
Reviews are separate from authorship; consult PR discussions for review evidence.
PR #6 implements the runner; promptfoo was PR #8. Later PRs #31–#36 were
authored by A, not assigned retroactively to B or C.

Reproduce the authorship audit:

```sh
git log --no-merges --format="%h %an <%ae> %s" 575a8e6
git show --stat COMMIT
```

Implementation and review preparation were AI-assisted. Each student must
understand and accurately describe their contribution. Student identifiers,
faculty approval and assessment outcomes have not been supplied.
