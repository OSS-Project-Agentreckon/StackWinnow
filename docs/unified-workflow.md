# Reviewed setup workflow

The workflow composes the existing adapters into one explicit journey: inspect,
explain recommendations, select tools, review a plan, apply, perform fresh checks,
and inspect passive status. No recommendation is installed automatically.

## Supported selections

Use **stackwinnow workflow modes** for the authoritative executable registry.
Catalog entries remain researched options; they are not execution support.

| Tool | Mode | Release | Additional requirements |
| --- | --- | --- | --- |
| Headroom | library | 0.44.0 | Manager Python; fixed local compression fixture |
| promptfoo | deterministic | 0.125.1 | Working Node 24 and npm |
| Playwright MCP | codex | 0.0.86 | Node 24, npm, Codex CLI 0.169.0; pinned browser recipe |
| Graphify | codex | graphifyy 0.9.114 | CPython 3.11.5–3.11.x, macOS 14+, Codex CLI 0.169.0; explicit relationship |

Execution support is macOS arm64. Linux unit tests do not establish Linux
integration support. Node 24.13.1 is an observed test version, not an exact patch
requirement. No workflow mode uses a paid model provider or imports API keys.
Upstream packages, browsers and tokenizer data can require downloads. Root
release pins do not imply every transitive dependency is locked; see the narrow
integration guides and [foundation evidence](foundation-handoff.md).

## Inspect, select, review and apply

Run these from the directory containing my-project, so the saved plan remains
outside that project's source tree:

~~~sh
stackwinnow workflow inspect ./my-project --goal "Evaluate answers" --json
stackwinnow workflow modes
stackwinnow workflow plan ./my-project --tool promptfoo --json > workflow-plan.json
stackwinnow workflow apply workflow-plan.json --dry-run --json
stackwinnow workflow apply workflow-plan.json --json
stackwinnow workflow status ./my-project --tool promptfoo --json
stackwinnow workflow check ./my-project --tool promptfoo --json
~~~

Repeat --tool to select several tools. Review the exact versions, modes,
configuration patches, source/input bindings and leaf operations in the JSON plan.
Omitting apply cancels the journey; inspect, plan and dry-run do not run commands
or create managed state. Real apply explicitly authorizes the reviewed local
operations, downloads and verification. All external prerequisite versions are
checked before the first installation.

Workflow status is passive: successful installation/configuration observations
are separate from a functional check that has not run. It normally returns
ready: false with functional not_run. Workflow check runs fresh checks without
installing tools. Workflow apply reports both the fresh verification and final
passive observations. A final setup failure prevents overall readiness even when
the earlier fresh check succeeded.

Successful preview/apply returns exit 0; an attempted workflow or check that is
not ready returns 1; invalid requests, stale plans and pre-install prerequisite
failures return 2. A valid dry-run returns 0 with ready: false. JSON goes to
stdout; invalid-request diagnostics go to stderr. Narrow tool commands remain
available with their existing contracts.

## Include Graphify

Create an explicit relationship file such as expected.json outside the project:

~~~json
{
  "caller_file": "sample_app/greetings.py",
  "caller_label": "greet()",
  "callee_file": "sample_app/names.py",
  "callee_label": "normalize_name()"
}
~~~

Both paths must identify existing source files inside the project. Choose labels
that describe the relationship you intend to verify; the files above are example
fixture paths, not inferred choices for arbitrary projects.

~~~sh
stackwinnow workflow plan ./my-project --tool graphify --tool promptfoo --tool playwright-mcp --expectation expected.json --json > combined-plan.json
stackwinnow workflow apply combined-plan.json --dry-run
stackwinnow workflow apply combined-plan.json --json
~~~

Graphify snapshots all regular files outside its documented exclusions, including
root JSON files. Save plans, captured CLI output and review notes outside the
indexed project; adding one afterward correctly makes its source snapshot stale.
The existing Graphify limits of 2,000 files / 32 MiB apply.

The fixed phase order is Graphify runtime, Headroom, promptfoo, Playwright,
Graphify indexing, Graphify configuration, then shared fresh verification. Omitted
tools omit their phases. This lets indexing include the exact reviewed promptfoo
configuration file and lets both Codex tables coexist without invalidating a
precomputed whole-file patch. Unrelated source/configuration/receipt changes block
the next phase. Existing healthy Graphify installations retain their original
immutable installation recipe while a new review can request a new relationship
and current source index.

## Repeat, partial failure and removal

A workflow plan is valid for one attempt. Each started attempt has a private
journal under .stackwinnow/workflows/WORKFLOW_ID.json; leaf receipts remain the
authority for ownership. Replaying an attempted plan is rejected. To repeat setup,
inspect the current project and generate a new plan. Healthy installations can be
reused, unchanged owned configuration can be a no-op, and functional checks still
run afresh. Failed or interrupted ownership requires the adapter's documented
inspection/removal policy; the workflow never silently erases it.

If one phase fails, subsequent installations stop. The result identifies the
stopped phase, completed step IDs, earlier phase outcomes, fresh verification if
actually run, and final passive status. Completed runtimes, configuration ownership
and failure evidence are retained. Do not clear receipts or delete a runtime to
hide an interrupted attempt. Use the existing reviewed removal flow:

~~~sh
stackwinnow remove plan ./my-project --tool promptfoo --json > removal-plan.json
stackwinnow remove apply removal-plan.json --dry-run
stackwinnow remove apply removal-plan.json --json
~~~

See [coordinated removal](coordinated-removal.md) for modified/foreign settings,
retained data, partial cleanup and intentional reinstall. A fresh workflow plan
after completed removal uses those existing reinstall contracts.

## API handoff for portable profiles

stackwinnow.supported.supported_modes() provides the supported recipes and
requirements. ToolSelection validates an exact tool/mode/version tuple;
select_tool(id) resolves the one supported pinned mode for a CLI selection.
WorkflowRequest contains explicit selections, Codex assistant, goals,
local/hosted/any preference and an optional Graphify relationship. Preference is
preserved for explanations; execution stays within the local modes above.

plan_workflow(root, request), load_workflow_plan(path) and
apply_workflow(plan, dry_run=False) implement the reviewed local flow.
WorkflowResult.as_payload() includes derived readiness and partial completion.
The local plan contains machine paths, state hashes, configuration originals and
one-attempt IDs. It is **not a portable profile**. [Portable profile export](portable-profiles.md)
projects an allowlist from the request/registry; import creates a new
destination-specific plan.

The checksum detects accidental edits, not human approval. Fixed leaf recipes,
current state comparison and read-only guards inside adapter locks enforce the
execution boundary. Only declared successful receipt transitions and reviewed
configuration effects advance expected state; serialized commands or credentials
are not executable inputs. See [A02 evidence](evidence/unified-workflow.md) for the
checks actually run and the later full combination acceptance boundary.


Discovery remains useful for partial projects: `workflow inspect` returns 1 if a
supported manifest is malformed, while preserving valid findings and diagnostics.
It returns 0 for complete inspection, including an empty/no-match result, and 2
for an invalid request. This matches the standalone `recommend` command.
