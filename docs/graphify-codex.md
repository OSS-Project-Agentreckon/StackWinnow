# Graphify through Codex

StackWinnow supplies a small stdio MCP bridge for Graphify's real local
relationship commands. The pinned upstream graphifyy 0.9.114 package has no
MCP server subcommand. The bridge is StackWinnow code; it does not imply an
upstream MCP feature or invoke Graphify's broad assistant installer.

The supported fixture uses macOS arm64, CPython 3.11.5–3.11.x for the locked
Graphify environment, and Codex CLI **0.169.0**. Install StackWinnow as a package
in the Python environment that will remain available to the registration.
The manager interpreter runs the bridge; an explicit project-local Graphify
interpreter argument identifies the managed query runtime. Removing either
interpreter makes that registration unusable.

## Commands

First complete [locked installation and reviewed indexing](graphify-index-lifecycle.md).
Then save and review a configuration plan outside the indexed project:

    stackwinnow graphify configure-plan ./my-project --json > /tmp/graphify-configure.json
    stackwinnow graphify configure /tmp/graphify-configure.json --dry-run --json
    stackwinnow graphify configure /tmp/graphify-configure.json --json
    stackwinnow check ./my-project --tool graphify --json
    stackwinnow check ./my-project --tool graphify --run-functional --json

Planning and dry runs execute no commands and write no project files. Applying
configuration creates .codex when necessary and appends only the
mcp_servers.stackwinnow_graphify table. Existing comments and unrelated tables
remain byte-preserved. Configuration alone does not claim client connectivity.

The check command distinguishes four observations:

| Observation | Required evidence |
| --- | --- |
| Installed | Current owned runtime inventory and pinned execution recipe |
| Configured | Original ownership plus the unchanged current bridge registration |
| Connected | An actual terminal Codex MCP call event returning a result from the selected server |
| Functional | A successful Codex call containing the exact expected relationship, node IDs and current graph/provenance digests |

Without configuration, --run-functional retains the standalone upstream query
check, while configured/connected remain blocked. With an owned registration,
it runs actual Codex acceptance. Passive checks do not reuse old client success.
A returned tool error is connected but not functional. Missing Codex, changed
sources, broken runtimes, foreign settings or stale graph evidence cannot produce
a ready result. Exit 0 means every required observation passed; incomplete or
failed checks return 1; malformed CLI input returns 2.

For a deliberate negative relationship query:

    stackwinnow check ./my-project --tool graphify --run-functional --scenario fail --json

## Client fixture and its limits

Verification launches real Codex in a temporary project with a temporary HOME
and CODEX_HOME. It copies only the selected registration, disables other tool
sources and uses a scripted loopback Responses provider to request one Graphify
tool call. The expected code relationship comes from the reviewed project index.
The managed bridge invokes upstream path --directed (or explain --all for a
recursive edge). It never accepts an executable command from tool arguments.

This establishes client routing and tool functionality for the selected
registration. It does not test model reasoning, paid providers, personal Codex
rules, or all other client versions. Scripted provider usage fields are protocol
fixtures, not measured model-token savings. No paid model is called.

Each bridge query acquires the shared project lock and rechecks installed files,
the complete included source snapshot, graph, and provenance before and after
the upstream command. MCP input is newline-delimited JSON bounded to 64 KiB per
message; relationship strings are bounded and source paths cannot escape the
project. Protocol output is JSON only. The bridge exposes one tool,
query_relationship, and rejects arbitrary methods/commands.

The parent verifier journals intent under the shared lock, releases it while
Codex calls the bridge, then reacquires it and rechecks the exact intent,
configuration and index evidence. This avoids a cross-process nested lock while
preventing a concurrent change from establishing current success. Partial
checks retain a failed intent. Reports are retained under
.stackwinnow/graphify/checks and referenced by execution receipts.

## Ownership and recovery

Reapply validates the owned table and preserves its original restoration data.
Unrelated TOML edits or another tool's table do not invalidate ownership. Modified,
removed, malformed, or matching foreign Graphify tables are preserved and blocked
for inspection. Old unsupported upstream-MCP registrations are not silently
overwritten. Configuration publication failures retain the original intent and
any created parent directory. Use the configuration lifecycle primitives for
reviewed cleanup; coordinated removal is the subsequent implementation task.

Older execution plans containing the former client-not-implemented advisory
remain valid: only that known advisory wording is normalized for recipe
comparison. Artifact hashes, executable recipe fields, source snapshots and
original plan digests remain validated.

## Interfaces and validation

graphify_configure exports GraphifyConfigurePlan, plan_graphify_configure,
load_graphify_configure_plan, apply_graphify_configure and
owned_graphify_configuration. The shared check_project entry point handles
passive checks and fresh client verification. The low-level bridge query owns
its lock; do not call it while holding the project operation lock.

The opt-in test is tests/integration/test_graphify_client.py:

    python -m pytest tests/integration/test_graphify_client.py --run-integration -q -W error

It runs real installation, indexing, owned configuration, positive/negative/
repeat Codex calls, install/config reuse and user-file preservation. See
[recorded evidence](evidence/graphify-codex.md) for actual environment/results.
