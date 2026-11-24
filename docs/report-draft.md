# StackWinnow — Assignment report DRAFT

**Status: DRAFT — not submitted to faculty. No roll numbers, faculty approval,
or final grades are recorded here. Public GitHub identities only.**

---

## Project description

StackWinnow is an open-source command-line tool for choosing and managing AI
development tools in a software project. The core workflow is:

1. **Inspect** — read the project's manifests, declared dependencies, and
   explicit user goals.
2. **Recommend** — apply deterministic eligibility rules over a 30-entry
   curated catalog to explain which tools match and why.
3. **Plan** — build a reviewable, JSON-serializable setup plan for the chosen
   tool(s), with preflight checks before any action.
4. **Apply** — execute the plan under a file lock, writing ownership receipts
   before each mutation so the state can be reversed.
5. **Verify** — check installation, configuration, connection, and functional
   results independently after setup.
6. **Remove** — reverse only manager-owned changes, preserving user edits.

The project targets macOS arm64 with the Codex CLI assistant. Linux CI covers
unit behavior and packaging; real tool integration is macOS-only.

---

## Repository

<https://github.com/OSS-Project-Agentreckon/StackWinnow>  
Branch history and commit authorship are in the repository. See
[docs/contribution-matrix.md](contribution-matrix.md) for the role-by-role summary.

---

## Implemented features

| Feature | Status |
| --- | --- |
| CLI entry point and help | Implemented |
| 30-entry tool catalog with eligibility | Implemented |
| Project manifest inspection | Implemented |
| Explainable recommendations with conflict detection | Implemented |
| Runtime environment inspection (OS/Python/Node) | Implemented |
| Owned JSON configuration editing | Implemented |
| Execution receipts and project lock | Implemented |
| Coordinated removal with owned-change reversal | Implemented |
| Managed Graphify install/index/Codex query | Implemented |
| Headroom managed library compression | Implemented |
| promptfoo managed evaluation | Implemented |
| Playwright MCP + Codex scripted browser fixture | Implemented |
| Shared verification framework (4 dimensions) | Implemented |
| Unified guarded workflow CLI | Implemented |
| Portable selection profiles | Implemented |
| Distribution packaging and release tooling | Implemented |
| User installation and troubleshooting guides | Implemented |

---

## Architecture summary

The package follows an **adapter + ownership** pattern. Each supported tool has:

- A `plan_<tool>()` function that returns a typed, JSON-serializable plan
- An `apply_<tool>()` function that executes the plan and writes receipts
- A `verify/<tool>.py` adapter that checks state across four dimensions

Configuration ownership uses pre-write digests so removal can distinguish
manager-written from user-edited content. The project file lock prevents
concurrent adapter runs from interleaving receipts.

See [docs/guide-architecture.md](guide-architecture.md) for the full layout.

---

## Testing and evidence

All behavior-changing commits include the tests needed to review that change.
The CI pipeline runs on Ubuntu Python 3.11 and 3.14 (unit + packaging).
Real integration evidence was captured on macOS arm64:

| Tool | Evidence | Acceptance scope |
| --- | --- | --- |
| Graphify | docs/evidence/graphify-codex.md | Actual Codex CLI 0.169.0 query on macOS arm64 |
| Headroom | docs/evidence/headroom-library.json | Managed lifecycle; protected 282-token control, zero saving |
| Headroom synthetic comparison | docs/evidence/headroom-synthetic/README.md | Separate historical direct-library experiment; compact baseline and zero controls |
| promptfoo | docs/evidence/foundation-cli.json | Foundation narrow lifecycle on macOS arm64 |
| Playwright MCP | docs/evidence/playwright-acceptance.json | Scripted local provider, macOS arm64 |
| Portable profiles | docs/evidence/portable-profiles.json | 4 profiles, 20 actual CLI round-trip commands |
| Unified workflow | docs/evidence/unified-workflow.md | 2 actual CLI workflow smokes on macOS arm64 |

See [docs/evidence/index.md](evidence/index.md) for the full index and
measurement conditions.

---

## Known limitations and deferred work

| Item | Status |
| --- | --- |
| Combined final lifecycle acceptance (all 4 tools together) | Deferred — user requested scope reduction |
| A05 exhaustive profile combination acceptance | Deferred explicitly |
| Benchmarks comparing managed vs. manual setup effort | Runner provided; new measurements and setup comparison deferred |
| Fresh transitive dependency inventory | Historical snapshot at 2026-11-23; not refreshed |
| Final combined release acceptance | Deferred before publication |
| PyPI publication, GitHub release, faculty submission | Not performed |
| Manager version tag | 0.1.0.dev0 — unreleased development |

---

## Supported platforms and tool versions

See [docs/support-matrix.md](support-matrix.md) for the complete pinned version table.
The supported integration target is **macOS arm64 with Codex CLI 0.169.0**.

---

## Third-party attribution

See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and
[licenses/reference-2026-11-23/](../licenses/reference-2026-11-23/README.md).
The manager itself is MIT licensed. Supported integrations download separate
upstream packages that retain their own licenses.

---

## Results and interpretation

The delivered value is explainable selection plus reviewed, owned setup and
recovery for four supported modes. Thirty catalog entries do not mean thirty
working integrations. Historical narrow lifecycle checks demonstrate those
specific versions and environments; final combined acceptance is still deferred.

The separate synthetic Headroom experiment recorded 5,105→1,980 tokens for
pretty JSON and 3,276→1,980 for equivalent compact JSON (61.21% and 39.56%).
Both protected controls saved zero tokens. Two trials per fixture used warm
tokenizer caches without model calls. These observations do not establish
arbitrary-project cost savings or human setup-time improvements. Original
inputs, outputs and the recorded summary are published in the evidence index.

## Submission preparation

Use the [release handoff](release-handoff.md) for source/artifact traceability,
demo material and remaining gates. Add confirmed student details and faculty
requirements before exporting the final submission format. No identifiers,
approval, new test results or submission outcomes are inferred. This Markdown
document remains a technical draft until those details and formatting are finalized.
