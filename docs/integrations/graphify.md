# Graphify recipe preview and local relationship evidence

Step 13 has a read-only recipe preview and tested command builders for local
indexing/querying. Managed apply, client configuration, and the complete
verification lifecycle are not implemented. The catalog remains `catalog_only`.

## Preview a project

```sh
stackwinnow graphify plan ./my-project --platform macos --assistant codex
stackwinnow graphify plan ./my-project --platform macos --assistant codex --json
```

Both commands are read-only. They read existing receipts for preflight but do
not download packages, create environments, scan source code, edit settings,
or run Graphify. The declared target is required; this preview does not infer
it from the host. Other platform/client combinations are not yet implemented.

JSON contains one envelope `schema_version`, the exact artifact identity,
installation intentions, command argument arrays, child environment overrides,
preflight observations, notes, and blockers. `phase` is `preview-only` and
`ready_to_apply` is always false. Exit 0 means the preview was produced, including
blocked plans; exit 2 means invalid input, unsupported target, or unreadable or
invalid project state. There is no `graphify apply` command or saved-plan executor.
The preview is a developer review artifact; do not treat its command arrays as
an installation approval or run an arbitrary edited JSON document.

## Pinned artifact and indexing mode

| Property | Selected value |
| --- | --- |
| Upstream | [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) |
| Python distribution | `graphifyy==0.9.114`; the import/CLI name is `graphify` |
| Python requirement | `>=3.11.5,<3.15` from the wheel metadata |
| Wheel | `graphifyy-0.9.114-py3-none-any.whl` |
| SHA-256 | `cf3cb57e87840a0c6ef7399578a95ad7ff6a83539dc71dcef0465b1b7f3a3453` |
| License | Apache-2.0 in the wheel's LICENSE |
| Candidate client/OS | Codex on macOS; actual client connectivity remains unverified |
| Verified probe environment | macOS arm64, Darwin 27.2.0, Python 3.11.14 |
| Extras | None; no MCP, provider, cloud, or visualization extras |
| Environment path | `.stackwinnow/envs/graphify/python` |
| Graph path | `.stackwinnow/graphify/index/graphify-out/graph.json` |

The preview pins the top-level wheel by URL and SHA-256. It uses binary wheels
only; dependency versions are still resolved at install time. The observed
versions are recorded in [probe evidence](../evidence/graphify-probe.json), which
is an inventory of that run, not a dependency lock or complete license audit.
No upstream source or wheel is redistributed in StackWinnow.

The source inspection used the pinned wheel and
[upstream README at b582ad4](https://github.com/Graphify-Labs/graphify/blob/b582ad401aaef4378935ec6620e3b165ae8e03c1/README.md).
The included license bytes have SHA-256
`cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`.

The index command selects `--code-only --no-cluster --max-workers 1`, supplies
the project and output paths explicitly, and excludes `.stackwinnow`. It uses
local AST extraction and does not require a model API key. Documentation/media
semantic processing, cloud upload, and model-based extraction are outside this
recipe. Package acquisition requires network access.

All previewed Python commands use `-I` so the selected project's Python modules
cannot shadow the installed tool. The command descriptors include an isolated
child HOME/cache, `GRAPHIFY_NO_AUTO_REFRESH=1`, and
`GRAPHIFY_QUERY_LOG_DISABLE=1`. Upstream normally refreshes installed skills and
logs queries under the user's home; those effects must stay disabled when an
executor is added. The shared runner supplies a restricted environment rather
than forwarding provider credentials. Child environment overrides do not change
the user's shell environment.

## Known relationship and test coverage

The [existing sample](../../tests/fixtures/project/sample_app/greetings.py)
calls `normalize_name()` in `sample_app/names.py` from `greet()`. The expected
file/label pairs are declared in
[graphify-relationship.json](../../tests/fixtures/graphify-relationship.json).
They are a test fixture, not an assumed relationship in every user's project.

`check_relationship(graph, expected)` requires unique endpoint IDs, exact source
files and labels, and a directed `calls` edge tagged `EXTRACTED`. It rejects
missing/ambiguous endpoints, reversed calls, imports in place of calls, inferred
edges, duplicate IDs, and dangling edges. Recursive calls are accepted only
when an explicit matching `calls`/`EXTRACTED` self-edge exists; matching a node
to itself without that edge cannot pass. It checks supplied graph data only:
loading limits, freshness, source provenance, and client connectivity remain the
responsibility of the future verification integration. Its `OperationResult`
evidence explicitly identifies the supplied graph rather than claiming a file
was read or a client was contacted.

`relationship_query` uses the exact IDs found by that check for upstream's
`graphify path ... --graph ... --directed` command for distinct endpoints.
For recursive calls it uses `graphify explain ID --all --graph ...` to display
the self-edge, because upstream's path command rejects identical endpoints.
The integration test covers both a cross-file call and a recursive `factorial()`.
It indexes
a copied fixture, validates the graph, executes that query, tests an absent
target, removes the calls edge as a negative control, and repeats indexing.
Neither process exit 0 nor package presence alone counts as relationship proof.

Run normal fixture tests:

```sh
.venv/bin/python -m pytest -q -W error tests/test_graphify_adapter.py tests/test_cli.py
```

For the real upstream test, prepare an isolated interpreter on macOS arm64.
These commands download packages; they do not configure Codex:

```sh
python3.11 -m venv /tmp/stackwinnow-graphify-probe
/tmp/stackwinnow-graphify-probe/bin/python -m pip --isolated install --only-binary=:all: \
  'https://files.pythonhosted.org/packages/ef/4f/44f9f4271c4de7c9b65777a01f3ce28dc6a1ca04360f812fa942371a4827/graphifyy-0.9.114-py3-none-any.whl#sha256=cf3cb57e87840a0c6ef7399578a95ad7ff6a83539dc71dcef0465b1b7f3a3453'
STACKWINNOW_GRAPHIFY_PYTHON=/tmp/stackwinnow-graphify-probe/bin/python \
  .venv/bin/python -m pytest -q -W error tests/integration/test_graphify.py --run-integration
```

The test skips unless explicitly enabled with a supplied interpreter and the
declared platform. A supplied interpreter with a missing/wrong Graphify version
fails rather than counting as a pass. It neither performs a managed install nor
connects an assistant. The Python interpreter path must retain its virtualenv
location; resolving its symlink to the base interpreter loses that environment.

On 21 November 2026 this real test passed. Both index/query runs succeeded; the
expected output was `greet() --calls [EXTRACTED]--> normalize_name()`. The missing
target returned exit 4, the graph without a calls edge failed the evidence
check, and input/output model tokens were zero. Fixture source/settings were
unchanged; no Codex settings or project-root `graphify-out` directory were created.
See the machine-readable evidence for environment and dependency versions.
Implementation, research, and validation were AI-assisted.

## Remaining work for complete step 13

### Managed execution preparation

The original `graphify plan` preview remains unchanged. A separate, read-only
contract prepares the first managed install/index slice:

```sh
stackwinnow graphify execution-plan ./my-project --expectation ./expected.json --json > plan.json
stackwinnow graphify validate-plan plan.json --json
```

The expectation file explicitly identifies a relationship in that project:

```json
{
  "caller_file": "sample_app/greetings.py",
  "caller_label": "greet()",
  "callee_file": "sample_app/names.py",
  "callee_label": "normalize_name()"
}
```

These are fixture names, not defaults for arbitrary projects. Recursive calls
can specify the same file/label for both endpoints. Planning hashes the exact
referenced source files; it does not establish that the call exists or snapshot
the entire project. The future executor must establish fresh index provenance.
Redirection writes the output file through the user's shell; the command itself
does not write anything. Keep saved plans outside managed output directories.

The preparation includes 31 exact wheel URLs, versions and SHA-256 hashes from
the bundled `data/graphify-lock.json`. It targets **CPython 3.11.5–3.11.x,
macOS 14+, arm64**. This narrower target reflects the selected dependency wheels
(including NumPy's macOS 14 wheel); it does not broaden the original support
claim. Dependency closure and wheel tags are validated independently of the host.
Other POSIX hosts can inspect a plan but receive explicit runtime blockers;
systems without no-follow file operations receive an unsupported-input error. The exact
dependency resolution and download evidence was collected on Python 3.11.14.

The lock binds Graphify's dependencies, not the interpreter, pip/ensurepip, or
operating system. It contains no optional extras. Artifact downloads and hashes
were validated; complete dependency-license acceptance and real managed
installation remain pending. Wheels are not redistributed with StackWinnow.

Plans record the current runtime identity, receipt-file digest, and hashes of
the selected relationship sources. `validate-plan` rebuilds the reviewed recipe
and compares these inputs; changed hashes, operations, artifacts, paths, runtime,
catalog identity/license or receipts require a new plan. Input JSON is bounded;
duplicate keys, unsafe source paths and symlink inputs are rejected. Sources and
receipts are limited to 4 MiB each, expectation JSON to 64 KiB, saved plans to
1 MiB. Existing Graphify paths or real receipts block this fresh-install slice
until shared reconciliation is integrated; no ownership is inferred or adopted.

**Neither command executes a plan.** Both return 0 for successfully prepared or
revalidated output, including its blockers, and 2 for invalid/stale input. The
phase is `execution-preparation` and `ready_to_apply` is always false. Validation
is not a signature, permission record, functional check or Codex connection.
No new `apply` command is exposed. Reviewed shared locking/reconciliation,
bounded execution and owned client configuration remain prerequisites.

To reproduce the lock download check on the declared target (network required):

```sh
python -c 'from stackwinnow.adapters.graphify_plan import graphify_requirements; print(graphify_requirements(), end="")' > /tmp/graphify-locked.txt
python -m pip --isolated download --require-hashes --only-binary=:all: \
  --dest /tmp/graphify-locked-wheels -r /tmp/graphify-locked.txt
```

This downloads wheels only. It neither installs Graphify nor configures a client.
See [lock evidence](../evidence/graphify-lock.json) for the recorded result.

### Execution and client integration still pending

1. Integrate with C's step 12 verification framework and distinguish package,
   configuration, client connectivity, and known-result functionality.
2. Add owned, recoverable client configuration. Upstream Codex installation can
   write `AGENTS.md`, `.codex/skills/graphify/` and `.codex/hooks.json`. Existing
   JSON patch ownership does not cover Markdown sections or copied skill trees.
   Do not invoke its installer or broad all-client uninstaller as a shortcut.
3. Implement apply using the shared runner/executor, revalidate prerequisites,
   dependency artifacts, reviewed plans, and path ownership at execution time;
   handle failed/repeated operations and concurrent changes. A preflight external
   or managed observation alone must never establish ownership or readiness.
4. Exercise the actual selected Codex integration and preserve unrelated user
   settings. Record provider-dependent checks separately if needed. Validate
   scoped removal through the team's lifecycle component before advertising it.

The adapter's small command/evidence API is ready for that handoff. The manager
does not yet offer a complete Graphify installation lifecycle.
