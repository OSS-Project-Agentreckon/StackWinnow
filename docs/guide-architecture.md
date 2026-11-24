# Architecture overview

## Package layout

```
src/stackwinnow/
├── __init__.py          # Package version (__version__)
├── cli.py               # Top-level argument parsing and command dispatch
├── workflow_cli.py      # Unified workflow and profile CLI handlers
├── catalog.py           # Catalog model, loading, filtering, and eligibility
├── detect.py            # Project inspection (manifests, goals, selections)
├── recommend.py         # Explainable tool recommendations
├── plan.py              # Preflight checks, eligibility validation, plans
├── configure.py         # Owned JSON configuration editing with original digests
├── removal.py           # Coordinated removal plans and owned-change reversal
├── verify/              # Verification adapter framework
│   ├── __init__.py      # check_project() dispatcher
│   ├── graphify.py      # Graphify verification adapter
│   ├── headroom.py      # Headroom verification adapter
│   ├── playwright.py    # Playwright MCP verification adapter
│   └── promptfoo.py     # promptfoo verification adapter
├── adapters/            # Tool-specific setup: plan/apply/check for each tool
│   ├── graphify.py
│   ├── graphify_install.py
│   ├── graphify_plan.py
│   ├── headroom.py
│   ├── playwright_mcp.py
│   └── promptfoo.py
├── runtime/             # Host environment inspection (OS, Python, Node, paths)
├── supported.py         # Executable mode registry (supported_modes())
├── profiles.py          # Portable profile export/import
├── workflow.py          # Workflow state machine (guarded transitions)
└── data/
    ├── catalog.json     # 30-entry tool catalog
    └── ...              # Additional data assets
```

## Core modules

### `catalog.py`

Loads the 30-entry JSON catalog from `data/catalog.json`. Provides
`load_catalog()`, `filter_catalog()`, `evaluate_eligibility()`, and
`CatalogEntry` / `Eligibility` models. Eligibility is evaluated given a
platform, assistant, and the set of registered adapters; it does not perform
host detection.

### `detect.py`

Reads project files (pyproject.toml, package.json, assistant-settings.json) and
user-supplied intent flags (`--goal`, `--assistant`, `--tool`, `--model-preference`)
to produce an `InspectionResult`. No scripts are executed and no settings are
modified. Missing optional manifests are recorded as unknown rather than as errors.

### `recommend.py`

Applies deterministic rules over the inspection result and catalog to produce
`RecommendationResult`. Reasons and alternatives are always explicit. Conflicts
(e.g., two context-aware navigators) are reported, not silently resolved.

### `configure.py`

Provides `ConfigurationChange` with original/written digests, diff previews, and
ownership records. Adapter mutations run under a project-scoped lock; configuration
primitives require their caller to supply lifecycle coordination. A preview
(no write) and an apply path are both available; the apply only proceeds when
the current file matches the recorded original digest.

### `workflow.py` / `workflow_cli.py`

A guarded state machine for the managed tool lifecycle:
`inspect → recommend → select → plan → apply → verify → status`.
Apply requires a saved plan; verification can report missing or partially
installed state. Partial failures are reported individually.

### `profiles.py`

Exports and imports portable selection profiles — an allowlisted projection of a
saved workflow plan for a fresh setup on a different host. Secrets, ownership
state, and local path assumptions are excluded.

### `verify/`

Each adapter registers a `ToolVerification` with four dimensions:
*installed*, *configured*, *connected*, *functional*. The dispatcher in
`verify/__init__.py` runs the requested subset and returns a combined report.
The `--run-functional` flag is opt-in; the default check is read-only.

## Adapter pattern

Each adapter in `adapters/` provides:

- `plan_<tool>(project_root, ...)` → returns a typed plan model
- `apply_<tool>(plan, ...)` → executes the plan, writes receipts
- `load_<tool>_plan(path)` → deserializes a saved plan from JSON

Plans are JSON-serializable review artifacts. Apply never proceeds from an
unreviewed plan generated in the same invocation; the user saves the plan,
reviews it, and passes it back.

## Ownership model

Every managed installation and configuration change records:

1. **Intent before mutation** — what the adapter intends to do
2. **Original state digest** — hash of the existing file/path before the write
3. **Ownership receipt** — the written state and a list of owned paths

Removal reads the receipts and only reverts unchanged managed content.
Changed or unowned content is preserved; partial state blocks rather than
being silently adopted.

## Configuration ownership

`configure.py` applies JSON patches as explicit ownership records. The original
byte-level content hash is stored before the first write. On re-apply, the patch
is a no-op when the current content matches the previously written state;
it blocks when the current content differs from both original and written states
(the user has edited the file).

## Project lock

Concurrent tool operations within the same project root use a file lock
(inside `<project>/.stackwinnow`). The lock prevents interleaved receipt
writes across simultaneous adapter runs; it is not held across unrelated manager
invocations.

## CI and packaging

Linux Python 3.11/3.14 CI covers unit behavior and packaging in
`.github/workflows/ci.yml` and `.github/workflows/packaging.yml`. The opt-in
macOS integration workflow (`.github/workflows/integration-macos.yml`) requires
`workflow_dispatch` and is not triggered automatically. See
[releasing.md](releasing.md) for distribution build steps.
