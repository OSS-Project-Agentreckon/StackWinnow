# Verify a project's tools

`stackwinnow check` reports installation, configuration, connection, and
functionality separately for explicitly selected catalog tools. Promptfoo is
the first verifier. Other known tools return `blocked: verifier-unavailable`;
unknown tool IDs are input errors. Catalog membership and preflight eligibility
do not establish a working integration.

## Read existing state

```sh
stackwinnow check ./my-project --tool promptfoo
stackwinnow check ./my-project --tool promptfoo --json
stackwinnow check ./my-project --tool promptfoo --tool graphify --json
```

The default check reads bounded project metadata and ownership receipts. It
runs no subprocesses, makes no network requests, and writes no files. A healthy
existing setup reports `installed: succeeded`, `configured: succeeded`,
`connected: not_applicable`, and `functional: not_run`. Its exit status is **1**:
there is no fresh functional evidence. Earlier successful reports are historical
observations and never make this check ready.

## Run a fresh functional check

First [onboard promptfoo](integrations/promptfoo.md#preview-and-apply) into a
disposable project. On the declared macOS arm64 / Node 24 environment:

```sh
stackwinnow check ./my-project --tool promptfoo --run-functional --json
stackwinnow check ./my-project --tool promptfoo --run-functional --scenario fail
stackwinnow check ./my-project --tool promptfoo --run-functional
```

These commands reuse the owned installation and supported configuration. They
never invoke npm, install dependencies, or rewrite the evaluation configuration.
They check Node and the installed CLI version, evaluate `hello` → `HELLO` and
`world` → `WORLD`, and validate a fresh two-case report. Each actual evaluation
adds one executor receipt and its own result under
`.stackwinnow/promptfoo/results/`. Runtime caches, logs, temporary files, and
private state may be written during execution. Failed version probes also
receive a failed evaluation-step receipt. npm is needed for onboarding, but
not for checking an existing setup.

Inspection, planning, and direct evaluation share the same bounded receipt
validation. Duplicate step IDs are rejected, and dry-run receipts cannot supply
installation, runtime-state, or configuration ownership. A functional check
revalidates all three resources after acquiring the operation lock, before the
tool CLI runs, and after its version probe before evaluation. Invalid ownership
observed at these boundaries blocks further execution, including hosted-provider
calls. Real ownership retained after a failed write remains usable; filtering
dry-run ownership does not delete receipt history.

The deliberate negative case changes a runtime variable, preserving config
bytes. Both assertions must fail, with upstream process exit **100** and
StackWinnow exit **1**. A subsequent normal check must generate new passing
evidence. These local fixture results establish the evaluation mechanism;
they do not measure an LLM's quality.

## States and evidence

| Dimension | What promptfoo checks | Limits |
| --- | --- | --- |
| `installed` | Owned prefix, pinned package name/version/MIT metadata, npm integrity record, and regular CLI entrypoint | Static metadata alone does not prove runtime health or rehash installed dependencies. |
| `configured` | Owned configuration's bytes and permissions, plus the exact supported two-case profile | Existing unowned or modified profiles are not executed or repaired. |
| `connected` | `not_applicable` for the standalone local provider; actual provider responses for explicitly requested OpenAI checks | No coding-assistant connection is claimed. |
| `functional` | Fresh expected outputs, report structure and counters, process outcome, and a report path belonging to this check | A historical report, skipped execution, or missing artifact cannot pass. |

| Status | Meaning |
| --- | --- |
| `succeeded` | The check passed with supporting evidence. |
| `failed` | An observable requirement failed, such as a missing package, changed configuration, bad output, or invalid report. |
| `blocked` | The check cannot proceed, for example due to missing credentials, unsafe paths, unowned files, a lock, or an unavailable verifier. |
| `not_run` | A possible check was not requested or executed in this invocation. |
| `not_applicable` | No connection is needed for this standalone mode; valid only for the connection dimension. |

The aggregate status follows `failed` → `blocked` → `not_run` → `succeeded`
in priority order. A selected tool is ready only when all applicable checks
succeed. The whole report is ready only when every selected tool is ready.
One passing tool cannot hide an unsupported or failing selection.

CLI exits are **0** for ready, **1** for any failed/blocked/not-run result, and
**2** for invalid input. Duplicate/empty tool selections and a negative scenario
without a functional local check are rejected. JSON includes `schema_version`,
`project_root`, `checked_at` (UTC), `run_functional`, derived `status`/`ready`,
and `tools`. Each tool supplies its connection scope, derived status/readiness,
and four checks with `kind`, `status`, diagnostic `code`, `message`, and
`evidence` references. Paths preserve spaces exactly.

## Optional hosted-provider verification

After explicitly onboarding the separate OpenAI profile, select it by name:

```sh
stackwinnow check ./my-project --tool promptfoo --provider openai --json
# This next command permits provider usage and possible charges.
stackwinnow check ./my-project --tool promptfoo --provider openai --run-functional --allow-provider-usage --json
```

A functional OpenAI check requires both the opt-in flag and an explicitly set
`OPENAI_API_KEY`. Missing either blocks connection and functionality before any
commands or writes. The verifier reads the model from the existing owned
configuration; it cannot change the model or create a new hosted profile.
Only the evaluation command receives the key. Version checks, reports, and
receipts do not include it.

`connection_scope: provider` means the configured provider returned both
responses. Incorrect answers can therefore yield `connected: succeeded` and
`functional: failed`. An authentication/transport error cannot establish
connectivity. Read-only hosted checks leave connectivity `not_run`. This path
has offline command-double coverage; no real hosted-provider acceptance is
claimed.

## Python API and component handoff

```python
from stackwinnow.verify import VerificationReport, check_project

report = check_project("./my-project", tool_ids=["promptfoo"])
assert not report.ready  # Read-only inspection cannot establish fresh success.
payload = report.as_payload()  # CLI JSON view, including derived status/readiness.
restored = VerificationReport.model_validate_json(report.model_dump_json())
assert restored == report
```

`check_project(..., run_functional=True)` executes the selected check.
`provider`, `scenario`, and `allow_provider_usage` mirror the CLI. Tests can
inject a `command_runner` using the existing adapter interface.
`VerificationError` reports invalid inputs; ordinary unavailable/failed checks
return structured results. Models reject incomplete dimensions, duplicate
tools, success without evidence, and read-only functional-success claims.
`status`/`ready` are derived properties, not accepted caller-supplied verdicts.
Use normal model JSON for round trips and `as_payload()` for presentation.

Step 11's `check_plan()` answers whether a setup plan is eligible or already
managed. Step 12's `check_project()` checks the selected installed setup; it
does not reuse preflight's `is_ready_to_apply` as proof of functionality.
An integration regression covers a managed installation whose configuration
has since changed: preflight can still identify it as managed, while
verification fails and refuses execution. The unified guided CLI remains
step 16 in the [work plan](chronological-commit-plan.md).

Checks reuse the adapter's ownership validation, operation lock, runtime
isolation, executor, and report parser. They reject unsafe checked paths, dry-run
ownership, duplicate/corrupt receipts, and state changes observed during
execution. These are observations at check time, not protection against a
hostile concurrent writer. The merged runner's outstanding timeout, generic
environment-confinement, and plural-secret-redaction findings remain documented
in [implementation progress](implementation-progress.md); this feature does not
change that runner. Catalog availability remains `catalog_only`.
