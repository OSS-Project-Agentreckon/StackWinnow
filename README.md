# StackWinnow

StackWinnow is an open-source project for choosing suitable AI development tools
and managing their setup for a project. The intended workflow is project
inspection, explained recommendations, a reviewed setup plan, installation,
functional verification, and removal that preserves the user's settings.

## Current scope

Version `0.1.0.dev0` provides an installable Python package, CLI help/version,
validated shared contracts, a read-only runtime inspection API, and local tests
with reusable isolated fixtures and initial CI. The inspection API is not yet a
CLI command. Recommendations, installation, configuration, functional tool
verification, and removal remain **planned and not implemented**.

The team's first-release target is 30 researched catalog entries and four
working integrations: Graphify, Headroom, promptfoo, and Playwright MCP. Catalog
membership will not imply installation support. The supported integration OS,
coding assistant, and tool versions must be agreed and tested before any
integration is advertised as supported. No adapter is currently implemented.

## Install and run

Python 3.11 or newer is required. From a checkout, create a virtual environment
and install the package (commands below use a POSIX shell):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
stackwinnow --help
stackwinnow --version
stackwinnow catalog list
stackwinnow catalog list --category evaluation
stackwinnow catalog show graphify --platform macos --assistant codex
stackwinnow catalog list --json
```

If `python3` is older than 3.11, use an installed newer interpreter, for example
`python3.11 -m venv .venv`. Initial dependency installation needs access to a
package index. Catalog discovery runs offline and needs no API key or running
coding assistant. Bare `stackwinnow` and `stackwinnow catalog` display help.
Invalid commands, tool IDs, flags, or catalog data return exit status 2. A valid
empty result returns 0.

## Browse the catalog

`catalog list` sorts entries by tool ID. Use `--category` to filter by context,
caching, model-gateway, evaluation, browser-automation, observability, coding,
orchestration, or prompt-optimization. `catalog show TOOL_ID` displays prerequisites,
compatibility, limitations, related alternatives, license scope, and sources.

Both commands accept `--json`, `--platform macos|linux|windows`, and
`--assistant ASSISTANT_ID`. These target flags supply context for explanations;
they do not inspect the machine or prove compatibility. IDs use lowercase
letters/digits and optional hyphen or underscore separators, for example `codex`.
The JSON list envelope contains `schema_version`, `count`, and `tools`; each item
contains `tool` and `eligibility`. The show envelope contains `schema_version`,
`tool`, and `eligibility`. Eligibility includes `installable` and reasons with
stable codes and explanatory messages.

`catalog list --installable` currently returns no entries: all 30 tools are
`catalog_only`, with no registered StackWinnow adapters. Empty documented
platform/client lists mean unknown compatibility. Empty conflict lists mean
no conflicts recorded, not proof that a combination works. Alternatives are
related options, not necessarily interchangeable tools. There are no measured
cost-saving claims or completed upstream integration tests in this catalog.

### Sources and license review

The bundled [catalog](src/stackwinnow/data/catalog.json) records an AI-assisted
review of upstream README, license, and selected requirement files on
2026-11-16. Each source has a URL and SHA-256 digest of the downloaded content.
URLs referencing `HEAD` can change; the digests record what was reviewed but do
not pin installable versions or replace immutable release references. This is
documentation review, not human peer review or functional verification.

License scope matters: AutoGen code uses MIT while its documentation uses
CC-BY-4.0; Serena's application uses GPL-3.0-or-later; LiteLLM and Langfuse have
separately licensed enterprise directories. Those exclusions are recorded in
the entries. Reviewing the listed code's license does not resolve licenses of
every dependency, model, hosted service, or future downloaded artifact.

Requirements must be checked per tool. The reviewed Graphify manifest requires
Python >=3.11,<3.15 despite its README quickstart saying 3.10+. The reviewed
promptfoo package requires Node >=22.22.0. A generic runtime Node >=18 check is
insufficient for promptfoo, and does not establish Graphify prerequisites.

### Add or update an entry

Edit `src/stackwinnow/data/catalog.json` with a unique ID, category, capability
tags, prerequisites, compatibility notes, limitations, relationships, license
scope, review date, and reviewed source URLs/digests. Read the actual upstream
license and requirement files, including exceptions. Leave undocumented support
lists empty and new tools `catalog_only`. A `reviewed` license requires an
identifier in the validator's supported OSS license set and a license source;
extend that set only after review when adding another license. Run the checks
below. Validation rejects missing fields, duplicate IDs, invalid categories,
and dangling or self-referencing relationships.

### Eligibility handoff

`stackwinnow.catalog.load_catalog()` loads and validates the packaged data.
`evaluate_eligibility(entry, context)` returns setup eligibility and reasons.
Person B supplies `EligibilityContext` with the target platform/client, actual
registered adapter IDs, and tool-specific prerequisite statuses. The helper
`EligibilityContext.from_profile(profile)` maps runtime OS facts and assistant
identity; it deliberately leaves adapter registration and prerequisite checks
empty. A successful generic environment check must not be treated as success
for every tool. Selected tool IDs allow recorded conflicts to block setup.

Setup eligibility requires a reviewed OSS license scope, an available and
registered adapter, documented platform/client support, successful prerequisites,
and no recorded selection conflict. It does not execute installation. Person C's
post-install functional checks remain a separate requirement.

## Develop and check

Inside the virtual environment:

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

The tests exercise the installed CLI from temporary working directories and use
copied project/configuration fixtures. They install no agent tools and leave
personal assistant settings unchanged. Runtime unit tests declare available
tools through mocks; a local browser fixture uses loopback HTTP only. Real
integration/provider checks require explicit pytest opt-ins and are not yet
implemented. See [testing](docs/testing.md) for fixtures, commands, and CI scope.

The [chronological work plan](docs/chronological-commit-plan.md) and
[implementation progress](docs/implementation-progress.md) track the 36 planned
work commits separately from actual completion and merge history.

## Shared contracts

`stackwinnow.contracts` contains data validation only. It does not inspect the
filesystem, fetch repositories, or execute plans. The top-level models use
`schema_version: 1` and reject unrecognized fields.

| Contract | Purpose |
| --- | --- |
| `ProjectProfile` | Keep explicit user goals separate from observed facts and evidence. Missing assistant/OS information remains `None`. |
| `ToolSpec` | Describe a catalog tool, its source and license, and whether an adapter exists. An unknown license remains `None`. |
| `InstallPlan` | Describe selected tools and ordered intended steps. Tool and step IDs are unique; steps must reference selected tools. |
| `OperationResult` | Report an explicit operation status, message, optional errors, and evidence. Status never defaults to success. |

`EvidenceRef` supplies a source and supporting detail. `PlanStep` is a description
of intended work, not a shell command or execution receipt. Paths and evidence
references are caller-supplied; validation does not establish that they exist.

The following example data illustrates the contracts; it is not a project scan,
catalog verification, or completed installation:

```python
from stackwinnow.contracts import (
    InstallPlan,
    OperationResult,
    ProjectProfile,
    ToolSpec,
)

profile = ProjectProfile(
    project_root="./example-project",
    goals=["Understand relationships across source files"],
    facts={"languages": ["python"]},
    evidence=[{"source": "pyproject.toml", "detail": "Python project metadata"}],
)

tool = ToolSpec(
    tool_id="graphify",
    name="Graphify",
    description="Build a queryable project knowledge graph.",
    repository="https://github.com/Graphify-Labs/graphify",
    license="Apache-2.0",
    capabilities=["code-relationships"],
)

plan = InstallPlan(
    project_root=profile.project_root,
    assistant=profile.assistant,
    tool_ids=[tool.tool_id],
    steps=[
        {
            "step_id": "check-graphify",
            "tool_id": tool.tool_id,
            "description": "Check adapter availability and prerequisites",
        }
    ],
)

result = OperationResult(
    status="blocked",
    tool_id=tool.tool_id,
    step_id="check-graphify",
    message="The Graphify adapter is not implemented yet.",
)

serialized = plan.model_dump_json(indent=2)
restored = InstallPlan.model_validate_json(serialized)
assert restored == plan
print(result.model_dump_json(indent=2))
```

Tool and step IDs use lowercase letters/digits with optional hyphen or underscore
separators. Empty tool selections are valid for a no-op plan. Unknown schema
versions, duplicate selections, and steps referencing unselected tools are
rejected. The runtime must separately check license eligibility, actual adapter
availability, versions, platform compatibility, and authorization before acting.

`catalog_only` is the default integration availability. `adapter_available` means
an adapter has been implemented; it does not establish compatibility, installation,
or successful functional verification for a particular project. Result statuses
are `succeeded`, `failed`, `blocked`, and `skipped`. They describe the reported
operation; a success value alone is not proof that an integration works.

## Team handoff and contributions

- **A:** catalog, project profiles, recommendations, CLI, and Graphify adapter.
- **B:** environment inspection, execution/version management, installation plans
  and receipts, Headroom adapter, and packaging.
- **C:** configuration ownership, verification/removal, promptfoo and Playwright
  MCP adapters, integration fixtures, and CI.

Discuss shared-contract changes in a focused issue or pull request with the
affected component owner. Keep each change tied to a working outcome, include
appropriate tests, and run the checks above. Each contributor uses their own Git
identity; commits and reviews should reflect the work actually performed.
Detailed contribution and governance documentation will follow in the planned
documentation commit.

## License

StackWinnow's original code is licensed under the [MIT License](LICENSE).
Third-party tools retain their own licenses. StackWinnow includes catalog
metadata and source references, not upstream tool code or binaries.
