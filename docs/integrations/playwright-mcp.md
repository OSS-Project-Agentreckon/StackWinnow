# Playwright MCP with Codex

Step 15 adds managed installation, a project-scoped Codex registration and a
fresh browser fixture check. The supported recipe is **macOS arm64, Node 24,
npm, and Codex CLI 0.169.0**. Other versions/platforms return an actionable
block; they are not advertised as tested. Python 3.11+ runs StackWinnow.

The recipe pins **@playwright/mcp@0.0.86** and its exact Playwright dependencies
**1.66.0-alpha-2026-11-18**. This upstream release uses alpha Playwright packages;
upgrades require renewed acceptance testing. Browser automation uses downloaded
Chromium **headless shell revision 1255 (159.0.8154.6)**, with an isolated profile.
The browser installer also downloads FFmpeg revision 1013.

## Preview, apply and check

Ensure the supported Node and Codex versions are on PATH, then run:

    stackwinnow playwright-mcp plan ./my-project --assistant codex --json > playwright-plan.json
    stackwinnow playwright-mcp apply playwright-plan.json --dry-run
    stackwinnow playwright-mcp apply playwright-plan.json --json
    stackwinnow check ./my-project --tool playwright-mcp --json
    stackwinnow check ./my-project --tool playwright-mcp --run-functional --json
    stackwinnow check ./my-project --tool playwright-mcp --run-functional --scenario fail --json

Planning and dry runs do not execute commands, create directories, download
packages or change settings. Plans include the selected Node path, launcher
digest, expected configuration bytes, owned table values and ordered steps.
Changed plans or inputs are rejected. Use a **new plan** for every real attempt.

Apply downloads npm packages with lifecycle scripts disabled, verifies all three
pinned package versions/license declarations and npm integrity records, and then
runs the pinned browser installer. npm enforces registry tarball integrity;
subsequent inspection checks metadata, not hashes of every installed file.
Downloads need registry/browser-CDN access. Missing runtimes, unsupported client
versions and incomplete setup remain blocked or failed.
Installation exceptions after creating the managed state directory retain its
ownership in a failed receipt. Exclusive creation prevents a competing existing
directory from being adopted; no ownership is recorded if creation fails.

The private installation, browser, caches, work directory, output and check
reports live under **.stackwinnow/envs/playwright-mcp/**. Receipts are in the shared
**.stackwinnow/receipts.json**. State is reused only with real ownership receipts.
Dry-run ownership and duplicate receipt IDs are rejected. Partially installed
state is preserved for manual inspection; this recipe does not silently delete
or reinstall it. The shared executor persists intent before each step.

## Selected project configuration

Only **[mcp_servers.stackwinnow_playwright]** is appended to the selected project's
**.codex/config.toml**. Existing comments, unrelated table bytes and permission
bits are preserved. The narrow TOML writer refuses conflicting server tables,
inline parent tables that cannot be extended, symlinks, hard links, special
files, invalid TOML, oversized files and stale previews. Matching unowned tables
are not adopted. Subsequent unrelated edits are allowed; changing the managed
table requires manual review. Creating .codex/ is recorded separately.

Registration uses an absolute Node path and the installed StackWinnow launcher;
keep both available. It exposes navigation, click, DOM evaluation, snapshot and
close tools. Browser sessions are isolated and headless, service workers are
blocked, and WebMCP is disabled. The launcher strips inherited credentials and
uses a private short socket directory so long project paths work. Browser
outputs stay in the managed output directory. Forced termination can leave a
small /tmp/stackwinnow-pw-* directory for manual cleanup.

For ordinary use, open the selected project in Codex and trust it through Codex's
normal workflow. Codex loads project MCP configuration only for trusted projects;
restart/reload the client after registration. StackWinnow does not change your
personal trust, authentication or user configuration. Normal model/provider
selection and tool permissions continue to be controlled by Codex. The browser
is not a security sandbox for untrusted websites.

## What the functional check proves

The check starts the **real Codex CLI, real MCP server and real Chromium**. It
loads the selected, ownership-validated server registration into a disposable
Codex fixture project. Only that registration is copied; unrelated servers,
project instructions and personal provider settings are excluded. Private
HOME/CODEX_HOME and local trust apply only to the disposable test project.
Plugin/app discovery, plugin refresh, shell tools/snapshots, host skill discovery
and daemon autostart are disabled in that private client configuration.
This exercises the installed server and registration, but does not establish
that your ordinary Codex session has trusted/reloaded the selected project.

A loopback Responses-compatible endpoint scripts three tool decisions:
browser_navigate, browser_click and browser_evaluate. The page is the bundled
local fixture, with a fresh random value for each run. Acceptance reads Codex's
completed MCP events and requires the expected URL, actual click, and returned
DOM value. A model's final success sentence is never evidence. No API key or paid
model call is used; this does not measure model reasoning or hosted-provider
connectivity. There is no separate raw-MCP-only success claim.

The default read-only check reports installation/configuration evidence and
leaves connection/functionality **not_run**, returning exit 1. A fresh successful
check reports all four dimensions succeeded, with **connection_scope=assistant**.
The negative scenario changes only the served fixture response: client connection
can succeed while functionality fails and the command returns exit 1. A failed
click, browser crash or timeout is a failure even when Codex exits 0.

Each executed check writes a unique JSON report under the managed checks/
directory, containing the selected registration's hash and actual client tool
results. Check commands reuse the installation and do not modify the registered
configuration or create additional installation receipts. Apply records its
verification step in the shared receipts. An operation lock serializes this
adapter; shared state is not a transaction against unrelated external writers.
Both apply and fresh checks revalidate installation ownership and the selected
registration after the isolated client returns, while holding the operation
lock. Changes to the managed setup block readiness and preserve user edits;
unrelated configuration comments remain allowed. The isolated client's evidence
alone cannot establish readiness for a registration that changed during the run.

## Open-source evidence and boundaries

The MCP server, Playwright and playwright-core packages declare **Apache-2.0**;
the downloaded license files were inspected and hashed in
[artifact evidence](../evidence/playwright-artifacts.json). The headless shell
includes Chromium's BSD-style terms and extensive third-party notices in
LICENSE.headless_shell. FFmpeg includes COPYING.LGPLv2.1. Those notices remain
in the managed downloads. StackWinnow does not vendor or redistribute these
binaries or claim their dependencies share its MIT license. A future bundled
release must review the corresponding redistribution/source obligations.

Catalog availability remains **catalog_only** for the generic onboarding path;
this implemented, narrow recipe is invoked through playwright-mcp. The catalog's
other client/platform listings describe upstream compatibility, not verified
StackWinnow recipes. Removal, broader client support and hosted-model acceptance
remain outside this contribution.

References: [upstream MCP](https://github.com/microsoft/playwright-mcp),
[exact npm release](https://registry.npmjs.org/@playwright/mcp/0.0.86),
[Codex MCP configuration](https://developers.openai.com/codex/mcp/),
[Codex configuration/trust](https://developers.openai.com/codex/config-basic/).

Recorded [client acceptance evidence](../evidence/playwright-acceptance.json) includes
positive, negative and repeat tool results from the installed wheel on Python 3.11.14.
The source-checkout integration also passed on Python 3.14.0.

## Reproduce acceptance

    python -m pytest tests/integration/test_playwright_mcp.py --run-integration -q -W error

This downloads the pinned server/browser in a disposable project, verifies actual
client interaction, runs a negative fixture, repeats without reinstalling, and
checks preservation of unrelated configuration and project files. The default
unit suite covers ownership, stale/tampered plans, directory links, malformed
configuration, missing browser, failed downloads, tool-result validation and CLI
behavior without network access. Implementation and research were AI-assisted.
