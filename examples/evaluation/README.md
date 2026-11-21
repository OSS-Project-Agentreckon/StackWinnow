# Project evaluation example

Use a disposable project directory with the installed `stackwinnow` command.
Read the [promptfoo prerequisites and limits](../../docs/integrations/promptfoo.md)
first. The integrated runner supports this initial adapter on macOS arm64 with
Node 24 and npm. Planning and dry-run execute no commands.

```sh
mkdir "evaluation demo"
stackwinnow promptfoo plan "evaluation demo" --json > evaluation-plan.json
stackwinnow promptfoo apply evaluation-plan.json --dry-run --json
stackwinnow promptfoo apply evaluation-plan.json --json
```

On a supported build/environment, apply installs `promptfoo@0.125.1` in the
project's managed prefix, writes the owned configuration, and evaluates:

| Input | Expected output |
| --- | --- |
| `hello` | `HELLO` |
| `world` | `WORLD` |

The local JavaScript fixture makes no model calls. Expect `status: succeeded`,
two successes, zero failures/errors, and a result-file reference in the receipts.

```sh
stackwinnow promptfoo plan "evaluation demo" --scenario fail --json > negative-plan.json
stackwinnow promptfoo apply negative-plan.json --json
```

Expect CLI exit **1**, `status: failed`, and two assertion failures with upstream
process exit **100**. This verifies that the manager detects bad results. For a
fresh successful evaluation, create another default plan; the same owned install
and configuration are reused. Replaying an attempted plan is blocked.

To verify that existing setup without installation or configuration changes:

```sh
stackwinnow check "evaluation demo" --tool promptfoo --json
stackwinnow check "evaluation demo" --tool promptfoo --run-functional --json
```

The read-only command reports `functional: not_run` and exits **1**. The second
command checks both known results afresh and exits **0** when ready. Both
report `connected: not_applicable` for the standalone provider. Details are in
[verification](../../docs/verification.md).

The configuration references the provider bundled with your installed
StackWinnow package. Keep generated machine-specific plans and `.stackwinnow/`
local. The [optional OpenAI path](../../docs/integrations/promptfoo.md#optional-hosted-model-evaluation)
needs a separate opt-in and may incur charges. Local fixture success measures
the onboarding path, not LLM quality.
