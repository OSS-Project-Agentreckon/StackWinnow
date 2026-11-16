# StackWinnow

StackWinnow is an open-source project for choosing suitable AI development tools
and managing their setup for a project. The intended workflow is project
inspection, explained recommendations, a reviewed setup plan, installation,
functional verification, and removal that preserves the user's settings.

## Current scope

This is the first bootstrap commit, version `0.1.0.dev0`. It provides an
installable Python package, CLI help/version, validated shared contracts, and
tests. Inspection, recommendations, installation, configuration, verification,
and removal are **planned and not implemented**.

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
```

If `python3` is older than 3.11, use an installed newer interpreter, for example
`python3.11 -m venv .venv`. Initial dependency installation needs access to a
package index. Help, version, and contract validation need no API key or running
coding assistant. Bare `stackwinnow` displays help; unavailable commands return
a nonzero exit status.

## Develop and check

Inside the virtual environment:

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

The tests exercise the installed CLI from temporary working directories. Tests
for shared contracts use small examples, without installing tools or changing
assistant settings. CI and the reusable integration fixture harness are planned
for subsequent commits.

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
Third-party tools retain their own licenses. This bootstrap does not bundle
Graphify, Headroom, promptfoo, or Playwright MCP.
