# Graphify Codex validation — 23 November 2026

Implementation revision:
[384b0b7dc9265de6d71189c012f4d6edc8e2a2d0](https://github.com/OSS-Project-Agentreckon/StackWinnow/commit/384b0b7dc9265de6d71189c012f4d6edc8e2a2d0).
The bridge protocol is the preceding e434c50 commit. This is local execution
evidence, not a merge or hosted macOS validation claim.

Environment: macOS 27.2.1 arm64, CPython 3.11.14, Node24.13.1 and
Codex CLI0.169.0. The manager wheel was built from a separate source snapshot,
installed into a temporary virtual environment, and imported without PYTHONPATH.
The [machine-readable record](graphify-codex.json) includes its SHA256 and
the actual terminal Codex MCP events.

| Check | Observed result |
| --- | --- |
| Full rebuilt-package suite, warnings as errors | 1065 passed, 13 opt-in skips |
| Bridge/configuration/client/index focused selection | 83 passed on Python3.11.14 and3.14.4 |
| Execution preparation/install compatibility selection | 83 passed on Python3.11.14 |
| Real managed Graphify and Codex integration | 1 passed in91.44 seconds |
| Final-package reuse of earlier saved install identity and fresh actual Codex query | Passed; no installation commands executed |
| Ruff lint/format, dependency compatibility, diff whitespace | Passed for task/repository files; unrelated untracked planning files excluded |

The full suite's skips are eight real/provider integrations and five packaging
opt-ins. The dedicated new Graphify client integration was executed separately.
The initial real positive call passed, but the negative case exposed Codex's
terminal failed-call event representation. The parser was corrected and the
entire real lifecycle rerun successfully. No initial failed attempt is counted
as acceptance.

## Reproduction

Install the project wheel with its development extras in a fresh CPython3.11
environment. Put Node24 and Codex CLI0.169.0 on PATH, then run:

    python -m pytest tests/integration/test_graphify_client.py --run-integration -q -W error

The test creates its own project, installs the pinned Graphify lock, extracts
the reviewed source graph and verifies greet() calling normalize_name(). It
adds a managed Codex table while preserving a pre-existing unrelated table.
Codex is launched in an isolated temporary project with only that registration.
A scripted loopback provider selects the relationship tool; no model API key
or paid provider is used.

The tested sequence is:

1. Positive query: connected=true, functional=true, exact expected graph nodes
   and current source/graph provenance returned by the managed bridge.
2. Nonexistent callee: Codex emits item.completed with status=failed, a returned
   text result and error=null. This proves routing (connected=true) while
   functionality fails. Codex omits the MCP isError field from this event shape.
3. Repeated positive query: fresh terminal event and a distinct receipt/report.
4. Installation and configuration reapply reuse the owned state; fixture source
   and unrelated user settings remain unchanged.

After the advisory wording compatibility change, the final rebuilt package
reused the existing real install plan without executing installation commands
and passed another actual Codex query. All four call reports are preserved in
the JSON evidence file; the final report follows the three integration reports.

## Limits

This is selected-registration client evidence, not a test of personal Codex
rules or general model reasoning. Scripted provider token fields satisfy the
protocol and are not measured model consumption or claimed cost savings.
Only Codex0.169.0 is accepted by this fixture. The local Python3.14 tests validate
manager behavior with controlled adapters; the pinned real Graphify environment
continues to require Python3.11. Coordinated removal, the full foundation
handoff, unified product workflow and release artifact acceptance remain later
milestones. Work and evidence preparation were AI-assisted.
