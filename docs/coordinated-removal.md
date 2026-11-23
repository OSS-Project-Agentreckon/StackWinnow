# Remove managed tools while preserving project data

Removal is explicit and scoped to selected tools. Save the JSON preview outside
the project, review it, then apply that same plan. Plans and journals can contain
original configuration values; keep them private.

```sh
stackwinnow remove plan /path/to/project --tool graphify --tool playwright-mcp --json > /tmp/removal.json
stackwinnow remove apply /tmp/removal.json --dry-run --json
stackwinnow remove apply /tmp/removal.json --json
```

Planning and dry runs do not write managed files or run upstream tools. Changed
receipts, settings, runtime contents or directory identities invalidate the
review. Generate and review a new plan after a change. Unknown or duplicate tool
IDs are errors. A completed removal can be previewed and applied again harmlessly.

## Supported deletion scopes

| Tool | Removable runtime under `.stackwinnow/` | Preserved data |
| --- | --- | --- |
| Graphify | `envs/graphify/` | `graphify/`, source snapshots, graphs and index history |
| Headroom | `envs/headroom/python/` | `headroom/`, reports, tokenizer and other private caches |
| promptfoo | `envs/promptfoo/node/` | `promptfoo/`, reports, work files and caches |
| Playwright MCP | `envs/playwright-mcp/node/` and `envs/playwright-mcp/browsers/` | Other contents of `envs/playwright-mcp/`, including output, checks and npm cache |

These fixed scopes require successful recorded ownership. A receipt claiming
the managed root does not authorize deletion of its children. Other tools,
failed/interrupted owners, retained descendants and aliases protect overlapping
resources. The receipt file, operation lock, removal journals and external
installations are never removal targets. Installed package symlinks are removed
as links without following their targets; explicitly retained aliases survive.

Unchanged manager-owned JSON keys are restored to their recorded original
values or removed if originally absent. Canonical owned Codex TOML tables are
removed while preserving unrelated bytes. User modifications, foreign entries,
comments and reformatted or unreadable owned tables survive. Empty files remain.
A modified or blocked owned setting retains its tool's runtime, including
indirect wrapper commands that cannot be understood by text matching.

Reference checks inspect current and historical known configuration locations,
ownership and intent records, plus the supported Codex and promptfoo files even
when no configuration ownership exists. Preview projects only the proposed
clean restoration in memory. Apply re-reads the actual files before deletion.
Foreign references and filesystem aliases protect runtimes; unreadable known
configuration is conservative. This does not discover dependencies in arbitrary
shell scripts, unregistered configuration files or unrelated processes.

## Durable state and recovery

Apply holds the shared project lock. A private, atomic journal in
`.stackwinnow/removals/remove-*.json` records the original receipts and reviewed
plan before any configuration or runtime mutation. It records each configuration
outcome, including publication and released keys, and each completed deletion.
Released configuration evidence preserves the exact bytes' digest and mode;
later user changes cannot be adopted as a manager-restored file.

A deletion that finishes receives a release record bound to the original active
owners. If a later runtime fails, a fresh plan can recognize the previously
released runtime and finish the remaining cleanup. An accidentally missing
runtime has no such proof and is not silently treated as successful removal.
If a process is interrupted before a durable outcome, the `running` journal
blocks new removal plans for inspection. Do not delete or edit receipts merely
to bypass this guard. Back up the project and inspect the recorded original
state and completed outcomes before recovering an interrupted operation.

Once all selected tool runtimes have been intentionally released and owned
configuration is reconciled, original receipts are archived in `retirements`
instead of remaining active installation claims. Retained paths and original
evidence remain recorded. Fresh adapter plans can reinstall into those released
runtime locations while preserving the same retained data directory identity.
Changed or newly occupied runtime paths are rejected. A replaced retained
directory or a changed restored promptfoo configuration is not adopted.
Graphify reinstallation requires a fresh installation plan and deliberate fresh
indexing before its client can be considered functional again.

Runtime snapshots are limited to 100,000 entries, 80 directory levels and 2 GiB;
actual reads also fail if a file grows beyond its inspected size. Receipt, plan
and individual journal reads are limited to 4 MiB; at most 1,000 journal files
are inspected. Exceeding a bound blocks cleanup. Runtime deletion uses open
directory descriptors, content/identity checks and no symlink traversal. The
project lock coordinates StackWinnow operations; it cannot stop unrelated
programs from editing files after the final filesystem check.

## API and outcomes

`stackwinnow.removal` exports `plan_removal_lifecycle(project_root, tool_ids)`,
`load_removal_plan(path)` and `apply_removal(plan, dry_run=False)`. Keep the
general read-only classifier in `stackwinnow.runtime.remove` separate: its
candidate list alone never authorizes deletion.

Plans distinguish `remove`, `retain`, `absent` and a previously journaled
`released` runtime. Apply reports the actual removed paths, retained resources,
retired tools and journal path. A failure returns partial outcomes, preserving
the original evidence. CLI status is 0 for success/no-op/dry-run, 1 for an
operation that failed or remained blocked, and 2 for invalid/stale inputs.

The B07 tests exercise actual filesystem removal and four adapter lifecycles
using command doubles. They do not claim real upstream installation or client
acceptance. The next B08/A01 handoff must run the assembled narrow workflows
with the real pinned tools before A02 product work.
