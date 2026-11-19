# Promptfoo onboarding

The step-9 adapter plans a pinned project-local installation, publishes an owned
evaluation configuration, runs two known-result cases, and records the outcome.
The default provider is a small StackWinnow JavaScript fixture that converts text
to uppercase. It makes no model calls and requires no API key. Passing these
cases demonstrates installation and evaluation mechanics, not LLM quality.

**Integration gate:** this branch starts from main `fa3616e`, which has the
executor and configuration API but lacks the shared command runner.
[PR #6](https://github.com/OSS-Project-Agentreckon/StackWinnow/pull/6) supplies that
dependency and has outstanding review findings. Planning and dry runs work now;
normal apply returns `blocked` before writing if the runner is absent.
The adapter accepts an injected runner for testing. Acceptance with an unmerged
runner is recorded separately from readiness of the default CLI. The catalog
continues to report promptfoo as `catalog_only` until integration is complete.

## Release and environment

| Item | Initial scope |
| --- | --- |
| Tool | `promptfoo@0.125.1`, MIT |
| Upstream Node requirement | `>=22.22.0` |
| Adapter execution scope | macOS arm64, Node 24, npm on PATH |
| Actual upstream probe | Darwin 27.2.0 arm64, Node 24.13.1, npm 11.8.0 |
| Python package | Python 3.11+ |
| Coding assistant | None required; this is a standalone project evaluation |
| Model/provider | Local deterministic fixture by default; OpenAI explicitly optional |

The adapter deliberately checks the tested Node major/platform. Its unit tests
can run on macOS/Linux without Node, npm, or network. Ubuntu package CI does not
establish support for a Linux promptfoo installation. Select the intended Node
installation in PATH before applying a plan; no runtime is installed globally.

## Preview and apply

From an installed StackWinnow build, with an existing project directory:

```sh
stackwinnow promptfoo plan ./my-project
stackwinnow promptfoo plan ./my-project --json > promptfoo-plan.json
stackwinnow promptfoo apply promptfoo-plan.json --dry-run --json
stackwinnow promptfoo apply promptfoo-plan.json --json
```

The plan contains the canonical project path, fixed version/integrity, provider,
configuration preview, and three steps. Review it before apply. Planning and
dry-run perform no commands, network requests, or writes. Shell redirection in
the example creates the selected plan file. Apply checks the saved plan against
the current project and bundled provider; edited or stale plans are blocked.

The installation uses `npm install --prefix ... --save-exact --ignore-scripts
--no-audit --no-fund promptfoo@0.125.1` with the public npm registry. It creates
a separate manifest/lock under the managed prefix, preserving the project's
own package manifest and lockfile. Installation requires Internet access and
downloads promptfoo's dependencies; the deterministic evaluation needs no hosted
provider. StackWinnow checks package version/license and npm's integrity record
before invoking the installed CLI. npm verifies package bytes during download.

The two fixture cases are `hello` → `HELLO` and `world` → `WORLD`. The adapter
requires process success and a version-3 JSON report with two successful cases,
their expected indices/outputs, and zero failures/errors. An invalid report or
a nonzero/timed-out process cannot establish success.

Apply exit statuses are **0** for success/dry-run, **1** for failed or blocked
execution, and **2** for invalid inputs. JSON returns the plan, operation results,
receipts, and evaluation summary where available.

## Failure and repeat checks

```sh
stackwinnow promptfoo plan ./my-project --scenario fail --json > negative-plan.json
stackwinnow promptfoo apply negative-plan.json --json
```

This passes a runtime variable to the local provider so both outputs deliberately
mismatch. The installed promptfoo process should return **100**, while
StackWinnow returns **1**, records `failed`, and reports two assertion failures.
An unexpected pass is also rejected. The owned config itself is unchanged.

Create a new plan for each repeat evaluation. An already attempted plan is
blocked, so saved success receipts cannot masquerade as a fresh check. A new
plan reuses an owned installation/configuration and creates a new result file.
Installation reuse checks metadata/integrity records and the CLI version; it
does not rehash the entire installed dependency tree. Existing unowned
configurations/prefixes are blocked. Changes to
owned configuration bytes or permissions require inspection rather than an
automatic overwrite. Use a fresh project when recovery is unclear.

## Managed files and receipts

| Location in the selected project | Purpose |
| --- | --- |
| `.stackwinnow/envs/promptfoo/node/` | npm installation and its manifest/lock |
| `promptfooconfig.stackwinnow.json` | Owned local-provider evaluation configuration |
| `promptfooconfig.stackwinnow.openai.json` | Separate optional OpenAI configuration |
| `.stackwinnow/promptfoo/` | Private child home, npm configuration/cache, empty dotenv file, logs, temporary files, and working directory |
| `.stackwinnow/promptfoo/results/<run-id>.json` | Fresh upstream report for one evaluation |
| `.stackwinnow/receipts.json` | Executor results, configuration intent/ownership, and evidence references |
| `.stackwinnow/promptfoo.lock` | Exclusive adapter-operation lock, released on completion and handled failures |

New state directories use mode `0700`; receipts and controlled files use `0600`.
The provider is bundled with StackWinnow, and the generated configuration
references its absolute installed path. Moving the project or reinstalling
StackWinnow elsewhere requires a new plan and review of any existing config.
Keep `.stackwinnow/` out of version control; generated plans/configurations also
contain local paths. This adapter does not edit the target project's gitignore.

Before configuration mutation, the executor persists the complete `ConfigPatch`
intent. Afterwards it records actual ownership, including publication followed
by cleanup failure. Retrying the same step retains earlier ownership in both
the retry intent and the final receipt, including no-op outcomes. If
final receipt persistence fails after a write, the earlier intent remains for
manual recovery; it is not silently promoted to successful ownership. Partial
installs and stale locks require inspection. Automatic repair/removal is later
work. There is no whole-plan rollback.

After acquiring the operation lock, apply re-reads receipts and revalidates the
plan against the current configuration. An overlapping invocation whose plan
was already attempted is blocked before executing or rewriting any step.
Overall success requires a fresh successful evaluation in that invocation;
skipped steps alone cannot establish a pass. Lock cleanup covers failures
immediately after creation, including descriptor-close errors. An uncatchable
process termination can still leave a lock requiring inspection.

Configuration ownership checks read bounded bytes and permission metadata from
the same descriptor opened with `O_NOFOLLOW`. `O_NONBLOCK` is retained so a FIFO
substituted between the initial file check and open can be rejected without
hanging. Invalid evaluation reports retain their specific sanitized diagnostic
in the failed receipt. A missing catalog entry produces a typed error or blocked
apply result.

Promptfoo runs from an empty managed working directory, avoiding discovery of
unrelated project JS/TS configuration. `DOTENV_CONFIG_PATH` is set **before Node
starts**, as well as using `--env-file`, because this release loads dotenv during
startup. Telemetry, update checking, sharing, and evaluation caching are disabled.
`--no-write` still permits startup database migration, so config/cache/log paths
are redirected too. Commands receive a minimal environment through the shared
runner; the adapter does not include provider keys in install/version commands,
plans, receipts, or diagnostic messages.

Symlinks in the adapter's checked directory, metadata, configuration, receipt,
and result paths are rejected. These checks and the adapter lock protect ordinary local use; they do
not sandbox upstream code or defend against a hostile concurrent filesystem
writer. Concurrent execution by other adapters is not coordinated by this lock.
Use the same trusted project/account boundary as the configuration API.

## Optional hosted model evaluation

An OpenAI model ID and separate apply opt-in are required. Set `OPENAI_API_KEY`
in the invoking environment through your usual credential mechanism; never
place it in the plan or source tree. For example:

```sh
stackwinnow promptfoo plan ./my-project --provider openai --model gpt-4.1-mini --json > hosted-plan.json
stackwinnow promptfoo apply hosted-plan.json --dry-run --json
stackwinnow promptfoo apply hosted-plan.json --allow-provider-usage --json
```

The hosted path sends the two synthetic uppercase prompts to the selected model
and **may incur provider charges**. Only the evaluation command receives the
explicit API key. Provider access/model availability and outputs can vary;
these two checks are a connectivity/functionality example, not a model benchmark.
The hosted path is source-reviewed and covered by command-double tests; it has
**not been executed with real credentials** for this contribution.

## OSS artifact evidence

- [Source repository](https://github.com/promptfoo/promptfoo).
- [Pinned npm tarball](https://registry.npmjs.org/promptfoo/-/promptfoo-0.125.1.tgz).
- Verified tarball SHA-512 SRI:
  `sha512-nogBhixdp69icwkg1EI0syZ4zAmAjJyWeLcqxAkTldbHi0qirOslwHvkUQhQmg65lQLrIKyMOMLXlBlSc6LRrg==`.
- Its MIT LICENSE matches the [source license at `8569e72`](https://github.com/promptfoo/promptfoo/blob/8569e72ed6cf7737082a6042be8d925e40f9739d/LICENSE).
  Registry provenance supplied this source revision; its signature was not
  independently verified.
- The upstream probe inspected the license metadata of the actual 626-package
  tree and license text for entries lacking metadata. No non-OSS license was
  found in that tree. LGPL sharp/libvips components retain their own notices
  and redistribution obligations. This is not a complete transitive legal audit;
  dependency ranges can resolve differently on later installs. The local npm
  lock records each actual resolution.

StackWinnow installs the OSS CLI, requires no Promptfoo cloud account, and does
not vendor upstream source/binaries. Its fixture provider is original MIT
StackWinnow code. A hosted model/service has separate terms from this CLI license.

## Verification

See [testing](../testing.md) for default versus opt-in checks and
[implementation progress](../implementation-progress.md) for dated results.
The real test installs into a copied fixture with spaces in its path, preserves
unrelated settings/manifests/default tool configuration, and runs positive,
negative, and repeat evaluations. Skips are reported as skips, not passes.
