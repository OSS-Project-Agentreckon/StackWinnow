# Portable tool selections

A portable profile carries reviewed tool selections to another project. Import
creates a fresh [workflow plan](unified-workflow.md) using the destination's files,
configuration, executable identities and receipts. It does not install tools or
copy an installation claim from the source project.

## Export and import

Keep workflow plans and command output outside the projects they describe,
especially when Graphify indexes their source trees:

~~~sh
stackwinnow workflow plan ./source-project --tool promptfoo --json > source-plan.json
stackwinnow profile export source-plan.json --json > selections.json
stackwinnow profile import selections.json ./destination-project --json > destination-plan.json
stackwinnow workflow apply destination-plan.json --dry-run --json
stackwinnow workflow apply destination-plan.json --json
~~~

Export and import run no commands and create no managed state. Omitting the last
command leaves the destination unchanged. A successful import returns exit 0
because planning succeeded; it makes no functional-readiness claim. Invalid or
incompatible profiles return exit 2 with diagnostics on stderr. JSON output goes
only to stdout. Omit `--json` for a human-readable selection/review summary.

An exported selection can come from a previously applied plan or a source project
that has since moved or changed. Export validates the saved document's schema,
checksum and current recipe identity, then projects only the fields below. It
does not recheck the former source's live state. The checksum is not a signature
or proof of human approval. The imported plan must receive a new review and
explicit apply; editing a profile cannot supply executable commands.

## What the profile contains

- Required integer `schema_version: 1` and the `stackwinnow-profile` document kind.
- Explicit unique tool IDs, supported modes and pinned root releases.
- The Codex assistant selection and local/hosted/any explanation preference.
- Compatibility requirements from the current supported-mode registry.
- An explicit portable relationship only when Graphify is selected.

The format excludes project roots, executable paths, receipts, installed/ready
flags, workflow IDs, source hashes, configuration originals, environment values,
credentials, arbitrary commands and freeform goals/diagnostics. Unknown fields,
including nested fields, are rejected. Root release pins do not claim that all
transitive dependencies are locked; the integration guides describe each recipe.
The hosted preference is explanatory; every supported workflow still uses local
checks with no paid-provider execution.

Profiles use the same four supported modes as `workflow modes`. Requirements must
match that registry; incompatible modes, releases, assistants, declared conflicts
and unsupported host/Python targets fail. Import checks observed host information
without executing prerequisites. Node/npm/Codex versions are checked at explicit
apply time. A valid imported plan can therefore still need prerequisites before
it can run.

If the destination already has a healthy owned installation, its own live state
may be reused by the new plan. Graphify retains that destination's original
immutable installation recipe. Nothing is adopted from the source project's
receipts. Damaged or foreign destination state retains the normal workflow
inspection and recovery rules.

## Graphify relationships

`caller_file` and `callee_file` are normalized, printable project-relative paths.
Absolute POSIX/Windows paths, drive-relative paths, traversal, home shortcuts and
private state components such as `.stackwinnow`, `.codex`, `.git`, `.aws`, `.ssh`
and `.env` files are rejected. Graphify's excluded runtime/cache directories
(`.venv`, `venv`, `node_modules`, `__pycache__`) are also rejected. Reserved components are matched without case
sensitivity; valid source paths retain their exact spelling. Paths are limited to
512 characters.

The caller/callee labels support simple qualified symbol names such as `greet()`,
`Service.run()` or `Service`, up to 256 characters. They cannot contain file paths,
freeform prose or control characters. An existing workflow relationship outside
this portable subset requires a new explicit relationship review rather than
silent rewriting. The destination must contain the named source files; applying
the new plan verifies the relationship against the destination's actual index.

The [code-map example](../examples/profiles/code-map-codex.json) names the copied
`tests/fixtures/project` source fixture. Change its relationship explicitly for
another project. Profiles never copy source code or infer equivalent symbols.

## Examples and validation

The [example profiles](../examples/profiles/README.md) cover one explicit mode
each. They are selection examples, not claims that all tools suit every project.
Use the recommendations and project requirements to choose a combination.

The portability tests exercise production workflow planning and adapters with
declared command doubles: fresh destination state, later explicit apply, a moved
source, existing destination ownership, Graphify recipe reuse, strict invalid
input, compatibility, secret-field diagnostics and CLI review/dry-run behavior.
Actual final profile combinations and upstream lifecycle acceptance are the next
A05 validation milestone; earlier narrow/unified checks remain separately
documented in [foundation evidence](foundation-handoff.md) and
[workflow evidence](evidence/unified-workflow.md).
See [A03 evidence](evidence/portable-profiles.md) for the 1,245-test installed
suite and all four actual CLI profile round-trips.

Python APIs are `export_profile(workflow_plan)`, `load_profile(path)` and
`import_profile(profile, destination)`. The last returns a `WorkflowPlan`; callers
explicitly invoke `apply_workflow` only after reviewing it.
