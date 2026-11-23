# Project report

`stackwinnow report` composes a project's inspection, explainable recommendations,
catalog eligibility, and an optional passive verification into one read-only
document. The default output is Markdown — a shareable summary of what a project
needs and what is ready; `--json` emits a structured payload. Building a report
installs nothing, runs no project scripts, makes no model calls, and writes
nothing to the project. It is a snapshot, not an executable plan: use
[`workflow`](unified-workflow.md) to actually set tools up. Implementation and
tests were AI-assisted.

## CLI

```sh
stackwinnow report . --goal "Evaluate answers" --tool promptfoo --platform macos > report.md
stackwinnow report . --goal "Evaluate answers" --tool promptfoo --check --json
stackwinnow report ./my-project --assistant codex --model-preference local
```

`report` accepts the same intent and configuration flags as
[`inspect`](project-inspection.md)/[`recommend`](recommendation-rules.md)
(`--goal`, `--assistant`, `--tool`, `--model-preference`, `--config`), plus
`--platform` for eligibility context and `--check` to add a passive verification
section. Without `--json` it prints Markdown to stdout; redirect it to a file.
Long options must be written in full.

`--check` reads passive verification state (installed/configured/connected/
functional) for the selected tools without running commands or writing anything;
it requires at least one `--tool`. There is no `--out` flag — emit to stdout and
redirect, as with other StackWinnow artifacts.

| Exit | Meaning |
| --- | --- |
| 0 | The report was produced, inspection completed, and any requested checks are ready. |
| 1 | Inspection was incomplete, or a checked tool is not ready. The report is still emitted. |
| 2 | Invalid arguments, unreadable project/config, an unknown tool ID, or `--check` without `--tool`. |

## What the report contains

The Markdown document has these sections: **Project** (inspection completeness,
assistant, goals, model preference, target platform, a declared-facts table, and
diagnostics), **Recommended tools** (per tool: why it matched, setup readiness
with eligibility reasons, integration status, alternatives, conflicts,
limitations), optional **Relationships**/**Unmatched goals**/**Notes**,
an optional **Verification** section (only with `--check`), and a fixed
**Caveats** line.

The JSON payload carries exactly one envelope `schema_version` and derived flags:

| Field | Meaning |
| --- | --- |
| `schema_version` | Report envelope version (currently `1`); nested model versions are omitted. |
| `project_root` | The inspected project path (spaces preserved exactly). |
| `generated_at` | UTC ISO-8601 timestamp when the report was built. |
| `ready` | Derived: inspection complete and, if `--check` ran, every selected tool ready. |
| `recommendation` | The recommendation result, including the embedded inspection and a derived `complete` flag. |
| `verification` | The passive verification report, or `null` without `--check`. |

`ready`, `complete`, and verification `status`/`ready` are derived, never
caller-supplied. The integration line distinguishes an available adapter from a
catalog-only entry using the recommendation's eligibility reasons.

## Scope and limits

- Offline and read-only: the report reuses the bounded [`inspect`](project-inspection.md)
  reader (macOS/Linux) and makes no model or network calls. `--check` is passive
  (`run_functional=False`); it never installs, configures, or executes a tool.
- A recommendation is not an executable plan, and catalog membership is not
  installation readiness. A tool is not proven functional without a fresh check,
  which this command does not perform.
- Report readiness mirrors `recommend`/`check` exit semantics; an incomplete
  inspection still produces a usable report.

## Python API

```python
from stackwinnow.report import ProjectReport, build_report

report = build_report(
    "./my-project",
    goals=["Evaluate answers"],
    selected_tools=["promptfoo"],
    platform="macos",
    include_verification=False,
)
restored = ProjectReport.model_validate_json(report.model_dump_json())
assert restored == report
print(report.to_markdown())
print(report.to_payload()["ready"])
```

`build_report` accepts an optional validated `Catalog` and an injectable
`generated_at` (for deterministic output). `include_verification=True` requires a
non-empty `selected_tools` and raises `ReportError` otherwise; it propagates
`InspectionError`/`RecommendationError`/`CatalogError`/`VerificationError` for
invalid inputs. Neither the input catalog nor any project file is mutated.

## Verification

Tests live in `tests/test_report.py` (builder and renderers: round-trip,
deterministic Markdown, single `schema_version`, verification requires a tool)
and `tests/test_report_cli.py` (installed CLI: Markdown default, JSON structure,
`--check` passive section with no writes, incomplete-inspection exit 1, invalid
tool and `--check` without `--tool` exit 2, and a path with spaces). They run
offline with no installation or provider calls. See [testing](testing.md).
