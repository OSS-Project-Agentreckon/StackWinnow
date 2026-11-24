# Demo instructions

This document describes a repeatable walkthrough of StackWinnow's main commands
using the manager's own checkout as the subject project. No external assistant
or internet access is required for the catalog, inspection, and recommendation
steps.

## Prerequisites

- Python 3.11 or newer
- A working StackWinnow install (see [guide-installation.md](guide-installation.md))

## 1. Version and help

```sh
stackwinnow --version
stackwinnow --help
```

Expected: version string (`stackwinnow 0.1.0.dev0` or the installed version),
then a command summary listing `catalog`, `inspect`, `recommend`, `workflow`,
`check`, and tool subcommands.

## 2. Catalog discovery

```sh
stackwinnow catalog list
```

Expected: 30 entries in a fixed-width table with ID, category, availability,
and description. No network access; the catalog ships with the package.

Filter by category:

```sh
stackwinnow catalog list --category evaluation
stackwinnow catalog list --category context
```

Inspect one entry with eligibility details:

```sh
stackwinnow catalog show graphify --platform macos --assistant codex
stackwinnow catalog show headroom --platform macos
stackwinnow catalog show promptfoo --platform macos
```

JSON output for scripting:

```sh
stackwinnow catalog list --json
stackwinnow catalog show graphify --platform macos --assistant codex --json
```

## 3. Project inspection

Point `inspect` at the StackWinnow checkout itself to demonstrate manifest parsing:

```sh
stackwinnow inspect . --json
```

Expected: a JSON object with detected language (Python), declared dependencies
from `pyproject.toml`, and no assistant or manual tool selections (no
`assistant-settings.json` exists in the manager checkout).

Add explicit goals and an assistant:

```sh
stackwinnow inspect . \
    --goal "Evaluate answers" \
    --assistant codex \
    --tool graphify \
    --json
```

## 4. Recommendations

```sh
stackwinnow recommend . --goal "Evaluate answers"
stackwinnow recommend . --goal "Understand code relationships" --assistant codex
stackwinnow recommend . --goal "Test prompt quality" --assistant codex --json
```

Expected: an ordered list of matching tools with match reasons, support status,
and any conflicts. Catalog-only tools are reported as not installation-ready.

## 5. Unified workflow preview

```sh
stackwinnow workflow inspect . --goal "Test prompt quality"
stackwinnow workflow modes
```

The `inspect` subcommand shows the detection + recommendations summary.
`modes` lists the supported executable modes (the tools that have an adapter
registered in the mode registry).

Planning a workflow (read-only, produces a reviewable JSON plan):

```sh
stackwinnow workflow plan . \
    --tool promptfoo \
    --goal "Test prompt quality" \
    --json > /tmp/sw-plan.json
cat /tmp/sw-plan.json
```

Dry-run apply (no changes written):

```sh
stackwinnow workflow apply /tmp/sw-plan.json --dry-run --json
```

## 6. Verification (read-only check)

If a supported tool is installed on the demo host, the check command reports its
state without running any tests or changing anything:

```sh
stackwinnow check . --tool promptfoo
stackwinnow check . --tool graphify --tool promptfoo --json
```

The default check is fully read-only. Functional verification is opt-in:

```sh
stackwinnow check . --tool promptfoo --run-functional
```

## 7. Portable profiles

Export the saved workflow plan as a portable profile (no secrets, no local paths):

```sh
stackwinnow profile export /tmp/sw-plan.json --json > /tmp/sw-profile.json
cat /tmp/sw-profile.json
```

Import on a fresh destination to plan from an existing selection:

```sh
mkdir -p /tmp/demo-dest
stackwinnow profile import /tmp/sw-profile.json /tmp/demo-dest --json > /tmp/sw-destination-plan.json
stackwinnow workflow apply /tmp/sw-destination-plan.json --dry-run --json
```

## Notes

- Profile export/import only produce documents; neither accepts `--dry-run`.
- Use unique temporary paths for each demo and keep plans outside the project.
- Plans are saved to a file and reviewed before `apply` is called.
- Exit status 0 = command success; 1 can indicate incomplete inspection or
  unavailable readiness; 2 = invalid input. Passive checks do not prove functionality.
- Real tool integration (apply, functional verification) requires the target
  machine's prerequisites; see [support-matrix.md](support-matrix.md).
